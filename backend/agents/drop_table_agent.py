import json
import re

import openai
from langchain_openai import ChatOpenAI
from rich.console import Console
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.config import config_manager
from backend.state import DataSpeakState
from backend.tools.schema_tools import GetTableSchemaTool

console = Console()

SYSTEM_PROMPT = """你是一个数据库操作解析器。用户想删除一张表，解析出表名。
输出 JSON（不要有其他文字）：{"table": "表名"}
如果无法确定表名，返回：{"table": ""}
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    reraise=True,
)
def _call_llm(llm, messages):
    return llm.invoke(messages).content


def drop_table_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold red][DROP_TABLE][/bold red] 解析删表需求...")

    schema_tool = GetTableSchemaTool()
    schema_info = schema_tool.run()
    internal = {"checkpoints", "writes", "checkpoint_blobs", "checkpoint_migrations", "_app_config"}
    table_list = [t for t in schema_info if t not in internal]

    llm_params = config_manager.get_llm_params()
    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=0,
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"可用的表: {table_list}\n用户输入: {state['user_input']}"},
    ]

    try:
        content = _call_llm(llm, messages)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        result = json.loads(match.group(0)) if match else {}
        table = result.get("table", "")
    except Exception as e:
        return {**state, "final_response": f"无法解析要删除的表名：{e}"}

    if not table or table not in table_list:
        return {
            **state,
            "final_response": f"未找到表「{table}」。当前可用的表：{', '.join(table_list)}",
        }

    console.print(f"[bold red][DROP_TABLE][/bold red] 目标表: {table}")
    return {
        **state,
        "extracted_data": {"operation": "drop_table", "table": table},
    }
