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

SYSTEM_PROMPT = """你是一个数据库结构修改专家（SQLite）。
解析用户想对表结构做的修改，输出 JSON（不要有其他文字）：
{
  "table": "表名",
  "sqls": ["ALTER TABLE ... (完整SQL语句)", ...],
  "description": "人类可读的操作描述"
}

支持的操作（SQLite 语法）：
- 加字段: ALTER TABLE t ADD COLUMN name TYPE [NOT NULL] [DEFAULT val]
- 删字段: ALTER TABLE t DROP COLUMN name
- 改字段名: ALTER TABLE t RENAME COLUMN old TO new
- 改表名: ALTER TABLE t RENAME TO new_name

注意：每条操作生成一条独立 SQL，sqls 是数组。
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    reraise=True,
)
def _call_llm(llm, messages):
    return llm.invoke(messages).content


def alter_table_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold cyan][ALTER_TABLE][/bold cyan] 解析表结构修改需求...")

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
        return {**state, "final_response": f"无法解析修改需求：{e}"}

    sqls = result.get("sqls", [])
    description = result.get("description", "修改表结构")

    if not sqls:
        return {**state, "final_response": "无法识别具体的修改操作，请描述得更清晰。"}

    console.print(f"[bold cyan][ALTER_TABLE][/bold cyan] 操作: {description}")
    console.print(f"[bold cyan][ALTER_TABLE][/bold cyan] SQLs: {sqls}")

    return {
        **state,
        "extracted_data": {
            "operation": "alter_table",
            "table": result.get("table", ""),
            "sqls": sqls,
            "description": description,
        },
    }
