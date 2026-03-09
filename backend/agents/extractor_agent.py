import json
import os
import re
from rich.console import Console
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import openai
from dotenv import load_dotenv

from backend.state import DataSpeakState
from backend.config import config_manager

load_dotenv()

console = Console()

SYSTEM_PROMPT_EXTRACTOR = """你是一个结构化数据提取专家，使用 ReAct 格式思考并提取数据。

你的任务：根据用户输入和提取计划，从自然语言中提取结构化数据。

工作流程：
Thought: 分析用户输入，理解需要提取哪些字段
Action: 从文本中识别并提取对应字段值
Observation: 检查提取的值是否合理
... (可重复多次)
Thought: 所有字段都已提取完毕
Final Answer: {"table": "<目标表名>", "data": {<字段:值的JSON>}}

注意：
- Final Answer 必须是合法的 JSON 格式
- 金额字段只保留数字（如 35.0，不要包含货币符号）
- 日期字段使用 YYYY-MM-DD 格式，如果用户说"昨天"请推断具体日期
- 【重要】绝对不要包含自动生成的系统字段：id、uuid、创建时间、更新时间（以及兼容历史字段 created_at、updated_at）。这些字段由数据库自动处理，不得出现在 data 中
- 只输出 Final Answer 后的 JSON，不要有额外文字
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    reraise=True,
)
def _call_llm(llm: ChatOpenAI, messages: list) -> str:
    response = llm.invoke(messages)
    return response.content


def _parse_final_answer(content: str) -> dict:
    """从 ReAct 输出中解析 Final Answer 后的 JSON"""
    # 尝试找 Final Answer: 后的内容
    match = re.search(r"Final Answer:\s*(\{.*\})", content, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
        return json.loads(json_str)

    # 尝试直接解析整个内容为 JSON
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass

    # 尝试找任何 JSON 块
    json_match = re.search(r"\{[^{}]*\"table\"[^{}]*\"data\"[^{}]*\{.*?\}[^{}]*\}", content, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))

    raise ValueError(f"无法从 LLM 输出中解析 Final Answer JSON: {content[:200]}")


def extractor_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold yellow][EXTRACTOR][/bold yellow] 开始提取结构化数据...")

    from datetime import date, timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)

    # 从配置管理器获取LLM参数
    llm_params = config_manager.get_llm_params()

    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=llm_params.get("temperature", 0.0),
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )

    critic_feedback = state.get("critic_result", "")
    feedback_section = ""
    if critic_feedback and not critic_feedback.upper().startswith("PASS"):
        feedback_section = f"\n\n上次提取被拒绝，Critic 的意见：\n{critic_feedback}\n请根据以上意见修正提取结果。"

    history = state.get("chat_history") or []
    history_str = ""
    if history:
        history_str = "\n对话历史（最近几轮，用于理解上下文）：\n"
        for msg in history[-6:]:
            role = "用户" if msg["role"] == "user" else "助手"
            history_str += f"{role}: {msg['content']}\n"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_EXTRACTOR},
        {
            "role": "user",
            "content": (
                f"今天日期: {today.isoformat()}\n"
                f"昨天日期: {yesterday.isoformat()}\n"
                f"{history_str}\n"
                f"提取计划:\n{state.get('extraction_plan', '')}\n\n"
                f"用户输入: {state['user_input']}"
                f"{feedback_section}"
            ),
        },
    ]

    try:
        content = _call_llm(llm, messages)
        console.print(f"[bold yellow][EXTRACTOR][/bold yellow] LLM 原始输出:\n{content}")
        extracted_data = _parse_final_answer(content)
        console.print(f"[bold yellow][EXTRACTOR][/bold yellow] 提取结果: {extracted_data}")
    except Exception as e:
        console.print(f"[bold yellow][EXTRACTOR][/bold yellow] 提取失败: {e}")
        return {**state, "error": f"数据提取失败: {e}"}

    return {**state, "extracted_data": extracted_data}
