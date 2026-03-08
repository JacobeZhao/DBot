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

SYSTEM_PROMPT = """你是一个数据删除操作解析器（SQLite）。
解析用户想删除的数据行，输出 JSON（不要有其他文字）：
{
  "table": "表名",
  "where_clause": "WHERE 子句（不含 WHERE 关键字，直接写条件，如 id = 3 或 status = 'done'）",
  "description": "简洁描述，说明要删除什么（如：删除 id=3 的记录）",
  "is_batch": false
}

注意：
- where_clause 必须是合法的 SQL 条件表达式
- 字符串值要加单引号，如 status = 'done'
- 如果是批量删除（影响多行），设 is_batch = true
- 如果无法确定条件，where_clause 设为空字符串
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    reraise=True,
)
def _call_llm(llm, messages):
    return llm.invoke(messages).content


def delete_data_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold red][DELETE_DATA][/bold red] 解析数据删除需求...")

    schema_tool = GetTableSchemaTool()
    schema_info = schema_tool.run()
    internal = {"checkpoints", "writes", "checkpoint_blobs", "checkpoint_migrations", "_app_config"}
    schema_str = ""
    for table, columns in schema_info.items():
        if table in internal:
            continue
        cols = ", ".join([f"{c['name']}({c['type']})" for c in columns])
        schema_str += f"表 {table}: {cols}\n"

    llm_params = config_manager.get_llm_params()
    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=0,
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"数据库 Schema:\n{schema_str}\n用户输入: {state['user_input']}"},
    ]

    try:
        content = _call_llm(llm, messages)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        result = json.loads(match.group(0)) if match else {}
    except Exception as e:
        return {**state, "final_response": f"无法解析删除需求：{e}"}

    where_clause = result.get("where_clause", "")
    if not where_clause:
        return {**state, "final_response": "无法确定删除条件，请说明要删除哪些数据（如：删除 id 为 3 的记录）"}

    console.print(f"[bold red][DELETE_DATA][/bold red] 表: {result.get('table')}, 条件: {where_clause}")
    return {
        **state,
        "extracted_data": {
            "operation": "delete_data",
            "table": result.get("table", ""),
            "where_clause": where_clause,
            "description": result.get("description", ""),
            "is_batch": result.get("is_batch", False),
        },
    }
