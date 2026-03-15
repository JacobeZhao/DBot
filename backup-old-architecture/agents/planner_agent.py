import os
from rich.console import Console
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import openai
from dotenv import load_dotenv

from backend.state import DataSpeakState
from backend.tools.schema_tools import GetTableSchemaTool, get_table_metadata, build_enriched_schema_str
from backend.config import config_manager

load_dotenv()

console = Console()

SYSTEM_PROMPT_PLANNER = """你是一个数据提取计划制定专家。

用户会告诉你他想要插入或更新的数据，你需要：
1. 结合对话历史和数据库 schema，确定目标表（若用户未明说，从上下文推断）
2. 确定需要从用户输入中提取哪些字段
3. 说明每个字段的提取方式（直接提取、推断、默认值等）

【重要】如果数据库中没有任何合适的表来存储用户的数据，输出的第一行必须是：
NO_SUITABLE_TABLE
然后说明原因。

否则正常输出（纯文本）：
目标表：<表名>
字段提取计划：
- <字段名>: <提取方式和说明>
- ...

补充规则：
- 目标表名和字段名允许中文/英文/数字/下划线，首字符不能是数字。
- 不要在提取计划中包含系统字段：id、uuid、创建时间、更新时间（以及兼容历史字段 created_at、updated_at）。
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


def planner_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold blue][PLANNER][/bold blue] 获取 Schema 并制定提取计划...")

    schema_tool = GetTableSchemaTool()
    schema_info = schema_tool.run()

    metadata = get_table_metadata()
    schema_str = build_enriched_schema_str(schema_info, metadata)
    console.print(f"[bold blue][PLANNER][/bold blue] 获取到 Schema:\n{schema_str}")

    # 从配置管理器获取LLM参数
    llm_params = config_manager.get_llm_params()

    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=llm_params.get("temperature", 0.0),
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )

    # 构建携带历史的消息列表
    history = state.get("chat_history") or []
    history_str = ""
    if history:
        history_str = "\n\n对话历史（最近几轮）：\n"
        for msg in history[-6:]:  # 最近 3 轮
            role = "用户" if msg["role"] == "user" else "助手"
            history_str += f"{role}: {msg['content']}\n"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_PLANNER},
        {
            "role": "user",
            "content": (
                f"数据库 Schema:\n{schema_str}"
                f"{history_str}\n"
                f"当前用户输入: {state['user_input']}"
            ),
        },
    ]

    try:
        extraction_plan = _call_llm(llm, messages)
    except Exception as e:
        console.print(f"[bold blue][PLANNER][/bold blue] 制定计划失败: {e}")
        extraction_plan = f"错误: {e}"

    console.print(f"[bold blue][PLANNER][/bold blue] 提取计划:\n{extraction_plan}")
    return {**state, "schema_info": schema_info, "extraction_plan": extraction_plan}
