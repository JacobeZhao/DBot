import json
import os
import re
import sqlite3
from rich.console import Console
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import openai
from dotenv import load_dotenv

from backend.state import DataSpeakState
from backend.config import config_manager
from backend.tools.schema_tools import INTERNAL_TABLES, is_valid_identifier, quote_identifier

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")
console = Console()

SYSTEM_PROMPT_CREATE_TABLE = """你是一个数据库表结构设计专家。

用户会用自然语言描述想创建的数据表，你需要解析出：
1. 表名（支持中文/英文/数字/下划线，首字符不能是数字，不超过 30 字符）
2. 表的中文描述（一句话说明用途）
3. 常用别名列表（用户可能用哪些词称呼这张表，如"花销"、"账单"等，3-5个）
4. 字段列表（不含系统字段：id、uuid、创建时间、更新时间，这些会自动添加）

输出合法 JSON，格式如下：
{
  "table_name": "表名",
  "description": "表的中文用途描述",
  "aliases": ["别名1", "别名2", "别名3"],
  "columns": [
    {"name": "字段名", "type": "TEXT|INTEGER|REAL", "notnull": true|false}
  ]
}

设计原则：
- 根据业务含义推断合适的字段和类型
- 文本用 TEXT，整数用 INTEGER，小数用 REAL
- 必填的核心字段设 notnull=true，可选信息设 notnull=false
- 【重要】不要包含系统字段 id、uuid、创建时间、更新时间，这些由系统自动添加
- 不要输出任何 JSON 以外的内容
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


def create_table_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold cyan][CREATE_TABLE][/bold cyan] 解析建表需求...")

    # 从配置管理器获取LLM参数
    llm_params = config_manager.get_llm_params()

    llm = ChatOpenAI(
        model=llm_params.get("model", "gpt-4o-mini"),
        temperature=llm_params.get("temperature", 0.0),
        api_key=llm_params.get("api_key"),
        base_url=llm_params.get("base_url"),
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_CREATE_TABLE},
        {"role": "user", "content": state["user_input"]},
    ]

    try:
        content = _call_llm(llm, messages)
        # 提取 JSON 块
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError("LLM 未返回有效 JSON")
        schema = json.loads(match.group(0))
    except Exception as e:
        console.print(f"[bold cyan][CREATE_TABLE][/bold cyan] 解析失败: {e}")
        return {**state, "error": str(e), "final_response": f"抱歉，无法解析建表需求：{e}"}

    table_name = schema.get("table_name", "").strip()
    columns = schema.get("columns", [])

    console.print(f"[bold cyan][CREATE_TABLE][/bold cyan] 目标表: {table_name}, 字段: {columns}")

    if not table_name or not is_valid_identifier(table_name):
        return {**state, "final_response": f"表名 '{table_name}' 不合法，请使用中文/字母/数字/下划线，且不能以数字开头。"}
    if table_name in INTERNAL_TABLES:
        return {**state, "final_response": f"表名「{table_name}」与系统保留名冲突，请更换表名。"}

    # 过滤掉 LLM 可能返回的自动管理字段（由代码统一添加）
    auto_fields = {"id", "uuid", "创建时间", "更新时间", "created_at", "updated_at"}
    filtered_columns = []
    seen_names = set()
    for col in columns:
        if not isinstance(col, dict):
            continue
        col_name = (col.get("name") or "").strip()
        if not col_name or not is_valid_identifier(col_name):
            continue
        if col_name in {"id", "uuid", "创建时间", "更新时间"} or col_name.lower() in auto_fields:
            continue
        if col_name in seen_names:
            continue
        seen_names.add(col_name)
        filtered_columns.append(col)
    columns = filtered_columns

    # 构建 CREATE TABLE SQL
    col_defs = [
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT',
        '"uuid" TEXT DEFAULT (lower(hex(randomblob(16))))',
        '"创建时间" TEXT DEFAULT (datetime(\'now\', \'localtime\'))',
        '"更新时间" TEXT DEFAULT (datetime(\'now\', \'localtime\'))',
    ]
    for col in columns:
        col_name = col.get("name", "").strip()
        col_type = (col.get("type", "TEXT") or "TEXT").strip().upper()
        if col_type not in {"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"}:
            col_type = "TEXT"
        col_sql = f"{quote_identifier(col_name)} {col_type}"
        if col.get("notnull"):
            col_sql += " NOT NULL"
        col_defs.append(col_sql)

    if not columns:
        return {**state, "final_response": "未识别到可用字段，请至少提供一个合法字段名。"}

    sql = f"CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} ({', '.join(col_defs)})"
    console.print(f"[bold cyan][CREATE_TABLE][/bold cyan] SQL: {sql}")

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(sql)
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        console.print(f"[bold cyan][CREATE_TABLE][/bold cyan] 建表失败: {e}")
        return {**state, "error": str(e), "final_response": f"建表失败：{e}"}

    # 保存表元数据
    from backend.tools.schema_tools import save_table_metadata
    description = schema.get("description", "")
    aliases = schema.get("aliases", [])
    save_table_metadata(table_name, description, aliases)

    col_summary = "、".join([c["name"] for c in columns]) if columns else "（无业务字段）"
    meta_line = f"描述：{description}" if description else ""
    alias_line = f"别名：{', '.join(aliases)}" if aliases else ""
    extra = "\n".join(filter(None, [meta_line, alias_line]))

    final_response = (
        f"✅ 已成功创建表「{table_name}」！\n\n"
        f"字段：id（自增主键）、uuid（唯一标识）、{col_summary}、创建时间、更新时间\n"
        + (f"{extra}\n" if extra else "")
        + "\n现在可以用自然语言向这张表插入数据了。"
    )
    console.print(f"[bold cyan][CREATE_TABLE][/bold cyan] 建表成功: {table_name}，描述: {description}")
    return {**state, "final_response": final_response}
