"""
DeepSeek API服务层

封装DeepSeek API调用，支持函数调用和流式响应。
"""

import asyncio
import datetime
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
import openai
from openai import OpenAI

from backend.config import extended_config_manager, LLMProvider

logger = logging.getLogger(__name__)


class DeepSeekService:
    """DeepSeek API服务"""

    def __init__(self, config_manager=None):
        self.config_manager = config_manager or extended_config_manager
        self._client_cache = {}  # 客户端缓存，按提供商存储

    def _get_client(self, provider=None) -> OpenAI:
        """获取OpenAI客户端（支持缓存）"""
        cache_key = "default"
        if cache_key in self._client_cache:
            return self._client_cache[cache_key]

        # 获取LLM参数
        llm_params = self.config_manager.get_llm_params()
        api_key = llm_params.get("api_key")
        base_url = llm_params.get("base_url")

        if not api_key:
            raise ValueError("LLM API密钥未配置")

        # 创建客户端
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=30.0
        )

        self._client_cache[cache_key] = client
        return client

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        provider=None,
        stream: bool = False,
        **kwargs
    ) -> Union[Dict[str, Any], AsyncGenerator[Dict[str, Any], None]]:
        """
        聊天补全调用

        Args:
            messages: 消息列表
            tools: 工具定义列表（OpenAI格式）
            provider: LLM提供商
            stream: 是否使用流式响应
            **kwargs: 其他参数（temperature, max_tokens等）

        Returns:
            如果stream=False: 完整的响应字典
            如果stream=True: 响应生成器
        """
        client = self._get_client()
        llm_params = self.config_manager.get_llm_params()

        # 准备请求参数
        request_params = {
            "model": llm_params.get("model"),
            "messages": messages,
            "temperature": kwargs.get("temperature", llm_params.get("temperature", 0.0)),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }

        # 添加工具参数
        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = kwargs.get("tool_choice", "auto")

        # 其他可选参数
        optional_params = ["top_p", "frequency_penalty", "presence_penalty"]
        for param in optional_params:
            if param in kwargs:
                request_params[param] = kwargs[param]

        try:
            if stream:
                return self._stream_completion(client, request_params)
            else:
                return self._direct_completion(client, request_params)
        except Exception as e:
            logger.error(f"DeepSeek API调用失败: {str(e)}")
            raise

    def _direct_completion(self, client: OpenAI, params: Dict[str, Any]) -> Dict[str, Any]:
        """直接（非流式）补全调用"""
        response = client.chat.completions.create(**params)

        # 解析响应
        result = {
            "id": response.id,
            "model": response.model,
            "created": response.created,
            "choices": []
        }

        for choice in response.choices:
            choice_data = {
                "index": choice.index,
                "finish_reason": choice.finish_reason,
                "message": {
                    "role": choice.message.role,
                    "content": choice.message.content or ""
                }
            }

            # 处理工具调用
            if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                choice_data["message"]["tool_calls"] = []
                for tool_call in choice.message.tool_calls:
                    tool_call_data = {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    }
                    choice_data["message"]["tool_calls"].append(tool_call_data)

            result["choices"].append(choice_data)

        return result

    async def _stream_completion(self, client: OpenAI, params: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        """流式补全调用"""
        response = client.chat.completions.create(**params, stream=True)

        # 跟踪累积的tool_calls
        tool_calls_accumulator = {}

        async for chunk in response:
            chunk_data = {
                "id": chunk.id,
                "model": chunk.model,
                "created": chunk.created,
                "choices": []
            }

            for choice in chunk.choices:
                choice_data = {
                    "index": choice.index,
                    "finish_reason": choice.finish_reason,
                    "delta": {}
                }

                delta = choice.delta

                # 内容增量
                if delta.content:
                    choice_data["delta"]["content"] = delta.content

                # 工具调用增量
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    for tool_call_delta in delta.tool_calls:
                        idx = tool_call_delta.index

                        # 初始化该索引的tool_call
                        if idx not in tool_calls_accumulator:
                            tool_calls_accumulator[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {
                                    "name": "",
                                    "arguments": ""
                                }
                            }

                        # 更新ID
                        if tool_call_delta.id:
                            tool_calls_accumulator[idx]["id"] = tool_call_delta.id

                        # 更新函数名
                        if hasattr(tool_call_delta.function, 'name') and tool_call_delta.function.name:
                            tool_calls_accumulator[idx]["function"]["name"] = tool_call_delta.function.name

                        # 更新参数
                        if hasattr(tool_call_delta.function, 'arguments') and tool_call_delta.function.arguments:
                            tool_calls_accumulator[idx]["function"]["arguments"] += tool_call_delta.function.arguments

                        choice_data["delta"]["tool_calls"] = [
                            {
                                "index": idx,
                                "id": tool_call_delta.id or "",
                                "type": "function",
                                "function": {
                                    "name": tool_call_delta.function.name if hasattr(tool_call_delta.function, 'name') else "",
                                    "arguments": tool_call_delta.function.arguments if hasattr(tool_call_delta.function, 'arguments') else ""
                                }
                            }
                        ]

                chunk_data["choices"].append(choice_data)

            yield chunk_data

        # 如果流结束且有tool_calls，发送完整的tool_calls
        if tool_calls_accumulator:
            final_chunk = {
                "id": "final_tool_calls",
                "model": chunk_data["model"],
                "created": chunk_data["created"],
                "choices": [{
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "tool_calls": list(tool_calls_accumulator.values())
                    }
                }]
            }
            yield final_chunk

    async def parse_tool_calls(self, llm_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从LLM响应中解析工具调用

        Args:
            llm_response: LLM响应字典

        Returns:
            工具调用列表，每个元素包含name, arguments, id
        """
        tool_calls = []

        for choice in llm_response.get("choices", []):
            message = choice.get("message", {})
            if "tool_calls" in message:
                for tool_call in message["tool_calls"]:
                    if tool_call.get("type") == "function":
                        try:
                            # 解析参数JSON
                            arguments_str = tool_call["function"].get("arguments", "{}")
                            arguments = json.loads(arguments_str)
                        except json.JSONDecodeError:
                            logger.warning(f"无法解析工具参数: {arguments_str}")
                            arguments = {}

                        tool_calls.append({
                            "id": tool_call.get("id", ""),
                            "name": tool_call["function"].get("name", ""),
                            "arguments": arguments,
                            "raw_arguments": arguments_str
                        })

        return tool_calls

    def _make_serializable(self, obj: Any) -> Any:
        """
        递归地将对象转换为可JSON序列化的格式。
        处理类型: sqlite3.Row, datetime, date, Decimal, slice, bytes等
        """
        if obj is None:
            return None
        elif isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple, set)):
            return [self._make_serializable(item) for item in obj]
        elif isinstance(obj, datetime.datetime):
            return obj.isoformat()
        elif isinstance(obj, datetime.date):
            return obj.isoformat()
        elif isinstance(obj, slice):
            # 处理切片对象，返回字符串表示
            return f"{obj.start}:{obj.stop}:{obj.step}"
        elif hasattr(obj, '__dict__'):
            # 尝试转换为字典
            return self._make_serializable(obj.__dict__)
        else:
            # 最后尝试字符串化
            return str(obj)

    async def create_tool_result_message(
        self,
        tool_call_id: str,
        tool_name: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        创建工具执行结果消息，增强序列化处理

        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            工具结果消息
        """
        try:
            # 清理和序列化结果
            serializable_result = self._make_serializable(result)
            content = json.dumps(serializable_result, ensure_ascii=False)

            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": content
            }
        except Exception as e:
            logger.error(f"创建工具结果消息失败: {str(e)}")
            # 返回错误信息而不是崩溃
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": json.dumps({
                    "success": False,
                    "error": f"结果序列化失败: {str(e)}",
                    "original_result_type": str(type(result))
                }, ensure_ascii=False)
            }

    async def format_messages_for_history(
        self,
        user_input: str,
        llm_response: Dict[str, Any],
        tool_results: List[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        格式化消息以便存储到历史记录

        Args:
            user_input: 用户输入
            llm_response: LLM响应
            tool_results: 工具执行结果列表

        Returns:
            消息历史列表
        """
        messages = []

        # 用户消息
        messages.append({
            "role": "user",
            "content": user_input
        })

        # 助手消息（可能包含工具调用）
        for choice in llm_response.get("choices", []):
            message = choice.get("message", {})
            if message:
                assistant_msg = {
                    "role": "assistant",
                    "content": message.get("content", "")
                }

                if "tool_calls" in message:
                    assistant_msg["tool_calls"] = message["tool_calls"]

                messages.append(assistant_msg)
                break  # 只取第一个choice

        # 工具结果消息
        if tool_results:
            for result in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": result.get("tool_call_id", ""),
                    "name": result.get("tool_name", ""),
                    "content": result.get("content", "")
                })

        return messages

    async def test_connection(self, provider=None) -> Dict[str, Any]:
        """测试API连接"""
        try:
            result = self.config_manager.test_connection()
            return result
        except Exception as e:
            return {
                "success": False,
                "message": f"连接测试失败: {str(e)}",
                "provider": provider.value
            }


# 全局服务实例
deepseek_service = DeepSeekService()