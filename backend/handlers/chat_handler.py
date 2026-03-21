"""
新聊天处理器 - 基于DeepSeek函数调用的完整工作流

实现:
1. 用户输入 → DeepSeek分析（带工具）
2. 解析tool_calls → 确认检查 → 自动执行或等待确认
3. 工具执行 → 结果反馈 → 生成最终回复
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
from uuid import uuid4

from backend.config import extended_config_manager
from backend.services.deepseek_service import deepseek_service
from backend.state import (
    ChatSession, ChatRequest, ChatResponse, ToolCall, ToolCallStatus,
    Confirmation, ConfirmationStatus, Message, SessionStatus
)
from backend.tools.registry import tool_registry
from backend.tools.init_tools import get_tools_for_llm

logger = logging.getLogger(__name__)


class SessionManager:
    """会话管理器"""

    def __init__(self):
        self._sessions: Dict[str, ChatSession] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, session_id: str, user_id: Optional[str] = None) -> ChatSession:
        """获取或创建会话"""
        async with self._lock:
            if session_id not in self._sessions:
                # 从配置获取自动执行设置
                auto_config = extended_config_manager.get_auto_execute_config()
                auto_execute_enabled = auto_config.get("enabled", False)

                session = ChatSession(
                    session_id=session_id,
                    user_id=user_id,
                    auto_execute_enabled=auto_execute_enabled
                )
                self._sessions[session_id] = session
                logger.info(f"创建新会话: {session_id}")
            return self._sessions[session_id]

    async def update_session(self, session: ChatSession):
        """更新会话"""
        async with self._lock:
            self._sessions[session.session_id] = session

    async def cleanup_expired_sessions(self, max_age_seconds: int = 3600):
        """清理过期会话"""
        async with self._lock:
            current_time = time.time()
            expired = []
            for session_id, session in self._sessions.items():
                if current_time - session.last_activity_at > max_age_seconds:
                    expired.append(session_id)

            for session_id in expired:
                del self._sessions[session_id]
                logger.info(f"清理过期会话: {session_id}")

    def get_session_count(self) -> int:
        """获取会话数量"""
        return len(self._sessions)


# 全局会话管理器
session_manager = SessionManager()


class ChatHandler:
    """聊天处理器"""

    def __init__(self):
        self.session_manager = session_manager

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        """
        处理聊天请求

        完整工作流:
        1. 获取会话和消息历史
        2. 调用DeepSeek API（带工具）
        3. 解析工具调用
        4. 检查确认需求
        5. 执行工具或等待确认
        6. 生成最终回复
        """
        try:
            # 1. 获取会话
            session = await self.session_manager.get_session(request.session_id)

            # 更新会话活动时间
            session.last_activity_at = time.time()

            # 2. 添加用户消息
            session.add_user_message(request.message)

            # 3. 准备消息历史（供LLM使用）
            llm_messages = self._prepare_llm_messages(session)

            # 4. 获取工具定义
            tools = get_tools_for_llm()

            # 5. 调用DeepSeek API
            logger.info(f"调用DeepSeek API，消息数: {len(llm_messages)}，工具数: {len(tools)}")
            llm_response = await deepseek_service.chat_completion(
                messages=llm_messages,
                tools=tools,
                provider=None,
                stream=False
            )

            # 6. 解析工具调用
            tool_calls_data = await deepseek_service.parse_tool_calls(llm_response)

            if tool_calls_data:
                # 7. 处理工具调用
                return await self._handle_tool_calls(
                    session, request, llm_response, tool_calls_data
                )
            else:
                # 8. 没有工具调用，直接返回响应
                return await self._handle_direct_response(
                    session, request, llm_response
                )

        except Exception as e:
            logger.error(f"处理聊天请求失败: {str(e)}", exc_info=True)
            return ChatResponse(
                session_id=request.session_id,
                success=False,
                error=f"处理失败: {str(e)}"
            )

    async def _handle_tool_calls(
        self,
        session: ChatSession,
        request: ChatRequest,
        llm_response: Dict[str, Any],
        tool_calls_data: List[Dict[str, Any]]
    ) -> ChatResponse:
        """处理工具调用"""
        # 1. 创建ToolCall对象
        tool_calls = []
        for tc_data in tool_calls_data:
            tool_call = ToolCall(
                id=tc_data.get("id", f"tool_{uuid4().hex[:8]}"),
                name=tc_data.get("name", ""),
                arguments=tc_data.get("arguments", {})
            )
            tool_calls.append(tool_call)

        # 2. 添加助手消息到会话（包含工具调用）
        assistant_content = ""
        for choice in llm_response.get("choices", []):
            message = choice.get("message", {})
            if message.get("content"):
                assistant_content = message.get("content")
                break

        # 转换为LLM格式的工具调用
        llm_tool_calls = []
        for tc in tool_calls:
            llm_tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                }
            })

        session.add_assistant_message(assistant_content, llm_tool_calls)

        # 3. 检查是否需要确认
        needs_confirmation, auto_execute, reason = await self._check_confirmation_need(
            session, request, tool_calls
        )

        if not needs_confirmation or auto_execute:
            # 4. 自动执行工具
            executed_tool_calls = await self._execute_tool_calls(session, tool_calls)

            # 5. 生成工具结果消息并反馈给LLM
            final_response = await self._generate_final_response(
                session, request, executed_tool_calls
            )

            return ChatResponse(
                session_id=session.session_id,
                success=True,
                response_text=final_response,
                tool_calls=executed_tool_calls,
                auto_executed=auto_execute,
                metadata={"auto_execute_reason": reason if auto_execute else None}
            )
        else:
            # 6. 需要用户确认
            confirmation_message = tool_registry.generate_confirmation_message(
                tool_calls[0].name if tool_calls else "unknown",
                tool_calls[0].arguments if tool_calls else {}
            )

            # 设置待处理的确认
            session.set_pending_confirmation(tool_calls)

            # 更新会话
            await self.session_manager.update_session(session)

            return ChatResponse(
                session_id=session.session_id,
                success=True,
                response_text=assistant_content or "需要确认操作",
                tool_calls=tool_calls,
                needs_confirmation=True,
                confirmation_id=session.pending_confirmation.id if session.pending_confirmation else None,
                confirmation_message=confirmation_message
            )

    async def _handle_direct_response(
        self,
        session: ChatSession,
        request: ChatRequest,
        llm_response: Dict[str, Any]
    ) -> ChatResponse:
        """处理直接响应（无工具调用）"""
        # 提取助手响应
        assistant_content = ""
        for choice in llm_response.get("choices", []):
            message = choice.get("message", {})
            if message.get("content"):
                assistant_content = message.get("content")
                break

        # 添加到会话
        session.add_assistant_message(assistant_content)

        # 更新会话
        await self.session_manager.update_session(session)

        return ChatResponse(
            session_id=session.session_id,
            success=True,
            response_text=assistant_content
        )

    async def _check_confirmation_need(
        self,
        session: ChatSession,
        request: ChatRequest,
        tool_calls: List[ToolCall]
    ) -> Tuple[bool, bool, Optional[str]]:
        """
        检查是否需要确认

        返回: (needs_confirmation, auto_execute, reason)
        """
        if not tool_calls:
            return False, False, None

        # 检查是否启用自动执行
        auto_execute_enabled = session.auto_execute_enabled
        if request.auto_execute is not None:
            auto_execute_enabled = request.auto_execute

        # 检查每个工具
        for tool_call in tool_calls:
            tool_name = tool_call.name

            # 检查工具是否需要确认
            if not tool_registry.requires_confirmation(tool_name):
                continue  # 这个工具不需要确认

            # 检查是否可以自动执行
            if auto_execute_enabled:
                should_auto, reason = tool_registry.should_auto_execute(
                    tool_name, tool_call.arguments
                )
                if should_auto:
                    return False, True, reason

            # 需要确认
            return True, False, None

        # 所有工具都不需要确认
        return False, False, None

    async def _execute_tool_calls(
        self,
        session: ChatSession,
        tool_calls: List[ToolCall]
    ) -> List[ToolCall]:
        """执行工具调用"""
        executed_tool_calls = []

        for tool_call in tool_calls:
            try:
                # 开始执行
                tool_call.start()

                # 执行工具
                result = await tool_registry.execute(
                    tool_call.name, tool_call.arguments
                )

                if result.get("success", False):
                    # 执行成功
                    tool_call.complete(result)

                    # 添加工具消息到会话
                    tool_message = await deepseek_service.create_tool_result_message(
                        tool_call.id, tool_call.name, result
                    )
                    session.add_tool_message(tool_call.id, tool_message.get("content", ""))

                    logger.info(f"工具执行成功: {tool_call.name}")
                else:
                    # 执行失败
                    error = result.get("error", "未知错误")
                    tool_call.fail(error)

                    # 添加错误消息到会话
                    error_message = f"工具执行失败: {error}"
                    session.add_tool_message(tool_call.id, error_message)

                    logger.error(f"工具执行失败: {tool_call.name}, 错误: {error}")

            except Exception as e:
                # 执行异常
                error = f"工具执行异常: {str(e)}"
                tool_call.fail(error)

                # 添加错误消息到会话
                session.add_tool_message(tool_call.id, error)

                logger.error(f"工具执行异常: {tool_call.name}, 异常: {str(e)}", exc_info=True)

            # 添加到已完成列表
            session.add_completed_tool_call(tool_call)
            executed_tool_calls.append(tool_call)

        # 更新会话
        await self.session_manager.update_session(session)

        return executed_tool_calls

    async def _generate_final_response(
        self,
        session: ChatSession,
        request: ChatRequest,
        executed_tool_calls: List[ToolCall]
    ) -> str:
        """生成最终回复（将工具结果反馈给LLM）"""
        # 准备消息历史（包含工具结果）
        llm_messages = self._prepare_llm_messages(session)

        # 再次调用LLM生成最终回复
        tools = get_tools_for_llm()

        try:
            llm_response = await deepseek_service.chat_completion(
                messages=llm_messages,
                tools=tools,
                provider=None,
                stream=False
            )

            # 提取助手响应
            for choice in llm_response.get("choices", []):
                message = choice.get("message", {})
                if message.get("content"):
                    final_response = message.get("content")
                    # 添加到会话
                    session.add_assistant_message(final_response)
                    await self.session_manager.update_session(session)
                    return final_response

            return "操作完成，但未能生成最终回复。"

        except Exception as e:
            logger.error(f"生成最终回复失败: {str(e)}", exc_info=True)
            # 如果LLM调用失败，返回一个简单的总结
            if executed_tool_calls:
                success_count = sum(1 for tc in executed_tool_calls if tc.status == ToolCallStatus.COMPLETED)
                fail_count = sum(1 for tc in executed_tool_calls if tc.status == ToolCallStatus.FAILED)
                return f"操作完成。成功: {success_count}，失败: {fail_count}"
            return "操作完成。"

    def _prepare_llm_messages(self, session: ChatSession) -> List[Dict[str, Any]]:
        """准备供LLM使用的消息历史"""
        messages = []

        # 获取最近的消息（最多20条）
        recent_messages = session.get_recent_messages(max_messages=20)

        for msg in recent_messages:
            message_dict = msg.to_dict()

            # 移除timestamp字段（LLM不需要）
            if "timestamp" in message_dict:
                del message_dict["timestamp"]

            messages.append(message_dict)

        return messages

    async def handle_confirmation(self, session_id: str, confirmation_id: str, action: str) -> ChatResponse:
        """处理确认请求"""
        try:
            # 获取会话
            session = await self.session_manager.get_session(session_id)

            # 检查是否有待处理的确认
            if not session.pending_confirmation:
                return ChatResponse(
                    session_id=session_id,
                    success=False,
                    error="没有待处理的确认"
                )

            # 检查确认ID是否匹配
            if session.pending_confirmation.id != confirmation_id:
                return ChatResponse(
                    session_id=session_id,
                    success=False,
                    error="确认ID不匹配"
                )

            # 检查是否过期
            if session.pending_confirmation.is_expired():
                session.pending_confirmation.expire()
                await self.session_manager.update_session(session)
                return ChatResponse(
                    session_id=session_id,
                    success=False,
                    error="确认已过期"
                )

            # 处理确认
            if action == "approve":
                session.pending_confirmation.approve()
                tool_calls = session.pending_confirmation.tool_calls

                # 执行工具
                executed_tool_calls = await self._execute_tool_calls(session, tool_calls)

                # 生成最终回复
                request = ChatRequest(session_id=session_id, message="确认执行操作")
                final_response = await self._generate_final_response(
                    session, request, executed_tool_calls
                )

                # 清除待处理的确认
                session.clear_pending_confirmation()
                await self.session_manager.update_session(session)

                return ChatResponse(
                    session_id=session_id,
                    success=True,
                    response_text=final_response,
                    tool_calls=executed_tool_calls,
                    metadata={"action": "approved"}
                )

            elif action == "reject":
                session.pending_confirmation.reject()

                # 添加用户拒绝消息
                session.add_user_message("用户拒绝了操作")

                # 清除待处理的确认
                session.clear_pending_confirmation()
                await self.session_manager.update_session(session)

                return ChatResponse(
                    session_id=session_id,
                    success=True,
                    response_text="操作已取消",
                    metadata={"action": "rejected"}
                )

            else:
                return ChatResponse(
                    session_id=session_id,
                    success=False,
                    error="无效的确认操作"
                )

        except Exception as e:
            logger.error(f"处理确认请求失败: {str(e)}", exc_info=True)
            return ChatResponse(
                session_id=session_id,
                success=False,
                error=f"处理确认失败: {str(e)}"
            )

    async def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话信息"""
        try:
            session = await self.session_manager.get_session(session_id)
            return session.get_full_dict()
        except Exception as e:
            logger.error(f"获取会话信息失败: {str(e)}")
            return None

    async def update_auto_execute(self, session_id: str, enabled: bool) -> bool:
        """更新会话的自动执行设置"""
        try:
            session = await self.session_manager.get_session(session_id)
            session.auto_execute_enabled = enabled
            await self.session_manager.update_session(session)
            return True
        except Exception as e:
            logger.error(f"更新自动执行设置失败: {str(e)}")
            return False


# 全局聊天处理器实例
chat_handler = ChatHandler()