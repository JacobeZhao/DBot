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
from backend.tools.schema_tools import INTERNAL_TABLES, is_valid_identifier, quote_identifier

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")
console = Console()

SYSTEM_PROMPT = """你是一个数据库设计专家。
用户想存入某些数据，但数据库中没有合适的表。
根据用户描述，设计一个合适的表结构，并给出字段提取计划。
输出 JSON（不要有其他文字）：
{
  "table_name": "表名（支持中文/英文/数字/下划线，首字非数字）",
  "description": "表的中文用途描述（一句话）",
  "aliases": ["别名1", "别名2", "别名3"],
  "columns": [
    {"name": "字段名", "type": "TEXT|INTEGER|REAL", "notnull": true|false}
  ],
  "extraction_plan": "目标表：table_name\\n字段提取计划：\\n- field: 提取说明\\n..."
}
【重要】不要在 columns 中包含系统字段 id、uuid、创建时间、更新时间，这些自动添加。
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

    if not table_name or not is_valid_identifier(table_name):
        return {**state, "final_response": f"生成的表名「{table_name}」不合法，请手动创建表后重试。"}
    if table_name in INTERNAL_TABLES:
        return {**state, "final_response": f"生成的表名「{table_name}」与系统保留名冲突，请重试。"}

    # 过滤自动字段与非法字段
    filtered_columns = []
    seen_names = set()
    for col in columns:
        if not isinstance(col, dict):
            continue
        col_name = (col.get("name") or "").strip()
        if not col_name or not is_valid_identifier(col_name):
            continue
        if col_name in {"id", "uuid", "创建时间", "更新时间"} or col_name.lower() in {"created_at", "updated_at"}:
            continue
        if col_name in seen_names:
            continue
        seen_names.add(col_name)
        filtered_columns.append(col)
    columns = filtered_columns

    if not columns:
        return {**state, "final_response": "未识别到可用字段，请补充至少一个合法字段。"}

    # 创建表
    col_defs = [
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT',
        '"uuid" TEXT DEFAULT (lower(hex(randomblob(16))))',
        '"创建时间" TEXT DEFAULT (datetime(\'now\', \'localtime\'))',
        '"更新时间" TEXT DEFAULT (datetime(\'now\', \'localtime\'))',
    ]
    for col in columns:
        col_name = (col.get("name") or "").strip()
        col_type = (col.get("type", "TEXT") or "TEXT").strip().upper()
        if col_type not in {"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"}:
            col_type = "TEXT"
        col_sql = f"{quote_identifier(col_name)} {col_type}"
        if col.get("notnull"):
            col_sql += " NOT NULL"
        col_defs.append(col_sql)

    sql = f"CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} ({', '.join(col_defs)})"
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
