import json
import os
import re
import sqlite3

import openai
from langchain_openai import ChatOpenAI
from rich.console import Console
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.config import config_manager
from backend.state import DataSpeakState

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")
console = Console()

SYSTEM_PROMPT = """你是一个数据库设计专家。
用户想存入某些数据，但数据库中没有合适的表。
根据用户描述，设计一个合适的表结构，并给出字段提取计划。
输出 JSON（不要有其他文字）：
{
  "table_name": "英文表名（snake_case）",
  "description": "表的中文用途描述（一句话）",
  "aliases": ["别名1", "别名2", "别名3"],
  "columns": [
    {"name": "字段名", "type": "TEXT|INTEGER|REAL", "notnull": true|false}
  ],
  "extraction_plan": "目标表：table_name\\n字段提取计划：\\n- field: 提取说明\\n..."
}
【重要】不要在 columns 中包含 id 和 created_at，这两个自动添加。
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)),
    reraise=True,
)
def _call_llm(llm, messages):
    return llm.invoke(messages).content


def no_table_handler_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold yellow][NO_TABLE_HANDLER][/bold yellow] 未找到合适的表，自动设计并创建...")

    llm_params = config_manager.get_llm_params()
    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=0,
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"用户想存入的数据描述：{state['user_input']}"},
    ]

    try:
        content = _call_llm(llm, messages)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        schema = json.loads(match.group(0)) if match else {}
    except Exception as e:
        return {**state, "final_response": f"无法设计表结构：{e}"}

    table_name = schema.get("table_name", "").strip()
    columns = schema.get("columns", [])
    extraction_plan = schema.get("extraction_plan", "")

    if not table_name or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
        return {**state, "final_response": f"生成的表名「{table_name}」不合法，请手动创建表后重试。"}

    # 过滤自动字段
    columns = [c for c in columns if c.get("name", "").lower() not in {"id", "created_at"}]

    # 创建表
    col_defs = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
    for col in columns:
        col_sql = f"{col['name']} {col.get('type', 'TEXT')}"
        if col.get("notnull"):
            col_sql += " NOT NULL"
        col_defs.append(col_sql)
    col_defs.append("created_at TEXT DEFAULT (datetime('now', 'localtime'))")

    sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(col_defs)})"
    console.print(f"[bold yellow][NO_TABLE_HANDLER][/bold yellow] 创建表 SQL: {sql}")

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(sql)
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        return {**state, "final_response": f"自动建表失败：{e}"}

    # 保存元数据
    from backend.tools.schema_tools import GetTableSchemaTool, save_table_metadata
    description = schema.get("description", "")
    aliases = schema.get("aliases", [])
    save_table_metadata(table_name, description, aliases)

    col_names = ", ".join([c["name"] for c in columns])
    console.print(
        f"[bold yellow][NO_TABLE_HANDLER][/bold yellow] "
        f"✅ 已创建表「{table_name}」，字段：{col_names}，描述：{description}"
    )

    # 刷新 schema_info 并更新 extraction_plan，继续走插入流程
    new_schema = GetTableSchemaTool().run()

    return {
        **state,
        "schema_info": new_schema,
        "extraction_plan": extraction_plan,
        "newly_created_table": table_name,
    }
