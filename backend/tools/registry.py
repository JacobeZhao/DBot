"""
工具注册和管理系统

统一注册所有可用的工具函数，生成OpenAI兼容的JSON Schema，
并提供工具执行和确认机制。

设计目标：
1. 统一工具注册和管理
2. 生成DeepSeek/OpenAI兼容的函数调用Schema
3. 支持确认机制和自动执行模式
4. 增强参数验证和安全性
"""

import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union
from enum import Enum


class ToolConfidence(Enum):
    """工具执行确认级别"""
    SAFE = "safe"           # 安全操作，可自动执行
    RISKY = "risky"         # 有风险操作，需要确认
    DESTRUCTIVE = "destructive"  # 破坏性操作，必须确认


@dataclass
class ToolRegistration:
    """工具注册信息"""
    name: str
    func: Callable
    description: str
    schema: Dict[str, Any]
    requires_confirmation: bool = True
    confidence_level: ToolConfidence = ToolConfidence.RISKY
    allowed_in_auto_mode: bool = False  # 是否允许在自动执行模式下运行

    def to_openai_schema(self) -> Dict[str, Any]:
        """转换为OpenAI兼容的工具schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema
            }
        }


class ToolRegistry:
    """工具注册和管理器"""

    def __init__(self):
        self._registry: Dict[str, ToolRegistration] = {}
        self._auto_execute_config = {
            "enabled": False,
            "threshold": 0.8,  # 置信度阈值
            "allowed_operations": ["query_data", "get_schema", "list_tables"],
            "exclude_tables": ["users", "settings", "_app_config", "_table_metadata"]
        }

    def register(self,
                name: str,
                func: Callable,
                description: str,
                schema: Dict[str, Any],
                requires_confirmation: bool = True,
                confidence_level: ToolConfidence = ToolConfidence.RISKY,
                allowed_in_auto_mode: bool = False) -> None:
        """
        注册一个工具

        Args:
            name: 工具名称（在函数调用中使用）
            func: 工具函数
            description: 工具描述
            schema: OpenAI兼容的JSON Schema
            requires_confirmation: 是否需要用户确认
            confidence_level: 操作风险级别
            allowed_in_auto_mode: 是否允许在自动执行模式下运行
        """
        self._registry[name] = ToolRegistration(
            name=name,
            func=func,
            description=description,
            schema=schema,
            requires_confirmation=requires_confirmation,
            confidence_level=confidence_level,
            allowed_in_auto_mode=allowed_in_auto_mode
        )

    def get_tool(self, name: str) -> Optional[ToolRegistration]:
        """获取工具注册信息"""
        return self._registry.get(name)

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """获取所有工具的OpenAI兼容schema"""
        return [tool.to_openai_schema() for tool in self._registry.values()]

    def get_available_tools(self) -> List[str]:
        """获取所有可用的工具名称"""
        return list(self._registry.keys())

    def requires_confirmation(self, tool_name: str) -> bool:
        """检查工具是否需要确认"""
        tool = self.get_tool(tool_name)
        if not tool:
            return True  # 未知工具默认需要确认

        # 检查自动执行模式配置
        if self._auto_execute_config["enabled"]:
            # 检查是否在允许的操作列表中
            if tool_name in self._auto_execute_config["allowed_operations"]:
                return not tool.allowed_in_auto_mode

        return tool.requires_confirmation

    def get_confidence_level(self, tool_name: str) -> ToolConfidence:
        """获取工具的风险级别"""
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolConfidence.RISKY
        return tool.confidence_level

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            执行结果字典，包含success、result、error等信息
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return {
                "success": False,
                "error": f"未知工具: {tool_name}",
                "tool_name": tool_name
            }

        try:
            # 验证参数
            self._validate_arguments(tool.schema, arguments)

            # 执行工具
            result = tool.func(**arguments)

            # 如果结果是协程，等待完成
            if inspect.iscoroutine(result):
                result = await result

            return {
                "success": True,
                "result": self._make_result_serializable(result),
                "tool_name": tool_name
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "tool_name": tool_name,
                "arguments": self._make_result_serializable(arguments)
            }

    def _validate_arguments(self, schema: Dict[str, Any], arguments: Dict[str, Any]) -> None:
        """
        验证参数是否符合schema

        Args:
            schema: JSON Schema
            arguments: 提供的参数

        Raises:
            ValueError: 参数验证失败
        """
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # 检查必需参数
        for param in required:
            if param not in arguments:
                raise ValueError(f"缺少必需参数: {param}")

        # 检查未知参数
        for param in arguments:
            if param not in properties:
                raise ValueError(f"未知参数: {param}")

        # TODO: 实现更详细的类型检查
        # 目前只做基本验证，后续可以添加类型转换和验证

    def _make_result_serializable(self, result: Any) -> Any:
        """
        确保工具执行结果可序列化

        Args:
            result: 工具执行结果

        Returns:
            可序列化的结果
        """
        import json
        import datetime

        # 基本类型直接返回
        if result is None:
            return None
        elif isinstance(result, (str, int, float, bool)):
            return result

        # 字典和列表递归处理
        elif isinstance(result, dict):
            return {k: self._make_result_serializable(v) for k, v in result.items()}
        elif isinstance(result, (list, tuple, set)):
            return [self._make_result_serializable(item) for item in result]

        # 处理日期时间
        elif isinstance(result, datetime.datetime):
            return result.isoformat()
        elif isinstance(result, datetime.date):
            return result.isoformat()

        # 处理字节
        elif isinstance(result, bytes):
            return result.decode('utf-8', errors='ignore')

        # 处理切片对象
        elif isinstance(result, slice):
            return f"{result.start}:{result.stop}:{result.step}"

        # 尝试转换为字典（处理对象）
        elif hasattr(result, '__dict__'):
            return self._make_result_serializable(result.__dict__)

        # 尝试JSON序列化，如果失败则字符串化
        else:
            try:
                json.dumps(result, ensure_ascii=False)
                return result
            except (TypeError, ValueError):
                return str(result)

    def generate_confirmation_message(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        生成用户确认消息

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            人类可读的确认消息
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return f"执行未知工具 '{tool_name}' 带参数: {json.dumps(arguments, ensure_ascii=False)}"

        # 根据工具类型生成不同的确认消息
        if tool_name == "insert_row":
            table = arguments.get("table", "未知表")
            data = arguments.get("data", {})
            return f"确认向表 '{table}' 插入数据:\n{json.dumps(data, ensure_ascii=False, indent=2)}"

        elif tool_name == "update_row":
            table = arguments.get("table", "未知表")
            where = arguments.get("where", {})
            data = arguments.get("data", {})
            return f"确认更新表 '{table}' 中满足条件 {where} 的数据为:\n{json.dumps(data, ensure_ascii=False, indent=2)}"

        elif tool_name == "delete_row":
            table = arguments.get("table", "未知表")
            where = arguments.get("where", {})
            return f"确认删除表 '{table}' 中满足条件 {where} 的数据"

        elif tool_name == "create_table":
            table = arguments.get("table_name", "未知表")
            columns = arguments.get("columns", [])
            return f"确认创建表 '{table}'，包含 {len(columns)} 个字段"

        elif tool_name == "drop_table":
            table = arguments.get("table_name", "未知表")
            return f"确认删除表 '{table}'（此操作不可逆）"

        elif tool_name == "add_column":
            table = arguments.get("table", "未知表")
            column = arguments.get("column", "未知字段")
            column_type = arguments.get("type", "TEXT")
            return f"确认向表 '{table}' 添加字段 '{column}' ({column_type})"

        elif tool_name == "drop_column":
            table = arguments.get("table", "未知表")
            column = arguments.get("column", "未知字段")
            return f"确认从表 '{table}' 删除字段 '{column}'"

        elif tool_name == "rename_column":
            table = arguments.get("table", "未知表")
            old_name = arguments.get("old_name", "未知字段")
            new_name = arguments.get("new_name", "未知字段")
            return f"确认将表 '{table}' 的字段 '{old_name}' 重命名为 '{new_name}'"

        else:
            # 默认确认消息
            return f"确认执行 '{tool_name}' 操作，参数: {json.dumps(arguments, ensure_ascii=False)}"

    def set_auto_execute_config(self,
                               enabled: bool = False,
                               threshold: float = 0.8,
                               allowed_operations: List[str] = None,
                               exclude_tables: List[str] = None) -> None:
        """
        设置自动执行模式配置

        Args:
            enabled: 是否启用自动执行
            threshold: 置信度阈值 (0.0-1.0)
            allowed_operations: 允许自动执行的操作列表
            exclude_tables: 排除的表列表（这些表不允许自动执行）
        """
        self._auto_execute_config["enabled"] = enabled
        self._auto_execute_config["threshold"] = max(0.0, min(1.0, threshold))
        self._auto_execute_config["allowed_operations"] = allowed_operations or []
        self._auto_execute_config["exclude_tables"] = exclude_tables or []

    def should_auto_execute(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查是否应该自动执行

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            (是否自动执行, 原因说明)
        """
        if not self._auto_execute_config["enabled"]:
            return False, "自动执行模式已禁用"

        tool = self.get_tool(tool_name)
        if not tool:
            return False, f"未知工具: {tool_name}"

        # 检查操作是否在允许列表中
        if tool_name not in self._auto_execute_config["allowed_operations"]:
            return False, f"工具 '{tool_name}' 不在自动执行允许列表中"

        # 检查工具是否允许自动执行
        if not tool.allowed_in_auto_mode:
            return False, f"工具 '{tool_name}' 不允许自动执行"

        # 检查表是否在排除列表中
        table = arguments.get("table") or arguments.get("table_name")
        if table and table in self._auto_execute_config["exclude_tables"]:
            return False, f"表 '{table}' 在自动执行排除列表中"

        # 检查风险级别
        if tool.confidence_level == ToolConfidence.DESTRUCTIVE:
            return False, f"工具 '{tool_name}' 是破坏性操作，需要人工确认"

        return True, "满足自动执行条件"


# 全局工具注册器实例
tool_registry = ToolRegistry()