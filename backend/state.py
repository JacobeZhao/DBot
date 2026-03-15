"""
新状态模型 - 为DeepSeek函数调用设计

定义聊天会话状态、工具调用、确认和执行结果等数据结构。
"""

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4


class ToolCallStatus(Enum):
    """工具调用状态"""
    PENDING = "pending"          # 等待执行
    EXECUTING = "executing"      # 执行中
    COMPLETED = "completed"      # 执行成功
    FAILED = "failed"            # 执行失败
    CANCELLED = "cancelled"      # 已取消


class ConfirmationStatus(Enum):
    """确认状态"""
    PENDING = "pending"          # 等待用户确认
    APPROVED = "approved"        # 用户已批准
    REJECTED = "rejected"        # 用户已拒绝
    AUTO_APPROVED = "auto_approved"  # 自动批准
    EXPIRED = "expired"          # 已过期


class SessionStatus(Enum):
    """会话状态"""
    ACTIVE = "active"            # 活跃会话
    IDLE = "idle"                # 空闲会话
    COMPLETED = "completed"      # 已完成会话
    ERROR = "error"              # 错误状态


@dataclass
class ToolCall:
    """工具调用表示"""
    id: str                      # 工具调用ID（通常来自LLM）
    name: str                    # 工具名称
    arguments: Dict[str, Any]    # 工具参数
    status: ToolCallStatus = ToolCallStatus.PENDING
    result: Optional[Dict[str, Any]] = None  # 执行结果
    error: Optional[str] = None  # 错误信息
    started_at: Optional[float] = None  # 开始时间戳
    completed_at: Optional[float] = None  # 完成时间戳
    execution_time_ms: Optional[float] = None  # 执行时间（毫秒）

    def start(self):
        """开始执行"""
        self.status = ToolCallStatus.EXECUTING
        self.started_at = time.time()

    def complete(self, result: Dict[str, Any]):
        """完成执行（成功）"""
        self.status = ToolCallStatus.COMPLETED
        self.result = result
        self.completed_at = time.time()
        if self.started_at:
            self.execution_time_ms = (self.completed_at - self.started_at) * 1000

    def fail(self, error: str):
        """执行失败"""
        self.status = ToolCallStatus.FAILED
        self.error = error
        self.completed_at = time.time()
        if self.started_at:
            self.execution_time_ms = (self.completed_at - self.started_at) * 1000

    def cancel(self):
        """取消执行"""
        self.status = ToolCallStatus.CANCELLED
        self.completed_at = time.time()
        if self.started_at:
            self.execution_time_ms = (self.completed_at - self.started_at) * 1000

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        # 转换枚举值为字符串
        data["status"] = self.status.value
        return data


@dataclass
class Confirmation:
    """操作确认表示"""
    id: str                      # 确认ID
    tool_calls: List[ToolCall]   # 需要确认的工具调用
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None  # 解决时间
    user_decision: Optional[str] = None  # 用户决定（"approve", "reject"）
    auto_execute_reason: Optional[str] = None  # 自动执行原因
    expires_at: Optional[float] = None   # 过期时间

    def __post_init__(self):
        """初始化后设置过期时间（默认10分钟）"""
        if self.expires_at is None:
            self.expires_at = self.created_at + 600  # 10分钟

    def approve(self, user_decision: str = "approve"):
        """批准操作"""
        self.status = ConfirmationStatus.APPROVED
        self.user_decision = user_decision
        self.resolved_at = time.time()

    def reject(self):
        """拒绝操作"""
        self.status = ConfirmationStatus.REJECTED
        self.user_decision = "reject"
        self.resolved_at = time.time()

    def auto_approve(self, reason: str):
        """自动批准"""
        self.status = ConfirmationStatus.AUTO_APPROVED
        self.auto_execute_reason = reason
        self.resolved_at = time.time()

    def expire(self):
        """标记为过期"""
        self.status = ConfirmationStatus.EXPIRED
        self.resolved_at = time.time()

    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data["status"] = self.status.value
        data["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        data["created_at"] = self.created_at
        data["expires_at"] = self.expires_at
        data["resolved_at"] = self.resolved_at
        return data


@dataclass
class Message:
    """聊天消息表示"""
    role: str                    # "user", "assistant", "tool"
    content: str                 # 消息内容
    timestamp: float = field(default_factory=time.time)
    tool_calls: Optional[List[Dict[str, Any]]] = None  # 工具调用（仅assistant角色）
    tool_call_id: Optional[str] = None  # 工具调用ID（仅tool角色）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp
        }
        if self.tool_calls:
            data["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        return data


@dataclass
class ChatSession:
    """聊天会话状态"""
    session_id: str              # 会话ID
    user_id: Optional[str] = None  # 用户ID（可选）
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    active_table: Optional[str] = None  # 当前活跃的表
    messages: List[Message] = field(default_factory=list)  # 消息历史
    pending_confirmation: Optional[Confirmation] = None  # 待处理的确认
    completed_tool_calls: List[ToolCall] = field(default_factory=list)  # 已完成的工具调用
    auto_execute_enabled: bool = False  # 是否启用自动执行
    metadata: Dict[str, Any] = field(default_factory=dict)  # 会话元数据

    def add_message(self, message: Message):
        """添加消息"""
        self.messages.append(message)
        self.last_activity_at = time.time()

    def add_user_message(self, content: str):
        """添加用户消息"""
        self.add_message(Message(role="user", content=content))

    def add_assistant_message(self, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None):
        """添加助手消息"""
        self.add_message(Message(role="assistant", content=content, tool_calls=tool_calls))

    def add_tool_message(self, tool_call_id: str, content: str):
        """添加工具消息"""
        self.add_message(Message(role="tool", content=content, tool_call_id=tool_call_id))

    def set_pending_confirmation(self, tool_calls: List[ToolCall]):
        """设置待处理的确认"""
        confirmation_id = f"confirm_{uuid4().hex[:8]}"
        self.pending_confirmation = Confirmation(
            id=confirmation_id,
            tool_calls=tool_calls
        )

    def clear_pending_confirmation(self):
        """清除待处理的确认"""
        self.pending_confirmation = None

    def add_completed_tool_call(self, tool_call: ToolCall):
        """添加已完成的工具调用"""
        self.completed_tool_calls.append(tool_call)
        # 保持最近100个工具调用
        if len(self.completed_tool_calls) > 100:
            self.completed_tool_calls = self.completed_tool_calls[-100:]

    def get_recent_messages(self, max_messages: int = 20) -> List[Message]:
        """获取最近的消息"""
        return self.messages[-max_messages:] if self.messages else []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "active_table": self.active_table,
            "message_count": len(self.messages),
            "has_pending_confirmation": self.pending_confirmation is not None,
            "completed_tool_call_count": len(self.completed_tool_calls),
            "auto_execute_enabled": self.auto_execute_enabled,
            "metadata": self.metadata
        }

    def get_full_dict(self) -> Dict[str, Any]:
        """获取完整字典（包含所有消息和工具调用）"""
        data = self.to_dict()
        data["messages"] = [msg.to_dict() for msg in self.messages]
        data["completed_tool_calls"] = [tc.to_dict() for tc in self.completed_tool_calls]
        if self.pending_confirmation:
            data["pending_confirmation"] = self.pending_confirmation.to_dict()
        return data


@dataclass
class ChatRequest:
    """聊天请求"""
    session_id: str
    message: str
    auto_execute: Optional[bool] = None  # 覆盖会话的自动执行设置
    stream: bool = False  # 是否使用流式响应

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatRequest":
        """从字典创建"""
        return cls(
            session_id=data.get("session_id", "default"),
            message=data.get("message", ""),
            auto_execute=data.get("auto_execute"),
            stream=data.get("stream", False)
        )


@dataclass
class ChatResponse:
    """聊天响应"""
    session_id: str
    success: bool
    response_text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    needs_confirmation: bool = False
    confirmation_id: Optional[str] = None
    confirmation_message: Optional[str] = None
    auto_executed: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = {
            "session_id": self.session_id,
            "success": self.success,
            "response_text": self.response_text,
            "needs_confirmation": self.needs_confirmation,
            "auto_executed": self.auto_executed,
            "error": self.error,
            "metadata": self.metadata
        }

        if self.tool_calls:
            data["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]

        if self.confirmation_id:
            data["confirmation_id"] = self.confirmation_id

        if self.confirmation_message:
            data["confirmation_message"] = self.confirmation_message

        return data


@dataclass
class ConfirmationRequest:
    """确认请求"""
    session_id: str
    confirmation_id: str
    action: str  # "approve" 或 "reject"
    notes: Optional[str] = None  # 用户备注

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfirmationRequest":
        """从字典创建"""
        return cls(
            session_id=data.get("session_id", ""),
            confirmation_id=data.get("confirmation_id", ""),
            action=data.get("action", ""),
            notes=data.get("notes")
        )


@dataclass
class ConfirmationResponse:
    """确认响应"""
    success: bool
    message: str
    executed_tool_calls: List[ToolCall] = field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = {
            "success": self.success,
            "message": self.message,
            "executed_tool_calls": [tc.to_dict() for tc in self.executed_tool_calls],
            "error": self.error,
            "metadata": self.metadata
        }
        return data