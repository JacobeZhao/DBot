import sqlite3
import os
import re
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")

INTERNAL_TABLES = {"checkpoints", "writes", "checkpoint_blobs", "checkpoint_migrations", "_table_metadata", "_app_config"}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(name: str) -> str:
    if not name or not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"非法标识符: {name}")
    return f'"{name}"'


# ── 元数据读写 ─────────────────────────────────────────────────

def save_table_metadata(table_name: str, description: str, aliases: list):
    """保存/更新表的描述和别名"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO _table_metadata (table_name, description, aliases, updated_at)
               VALUES (?, ?, ?, datetime('now', 'localtime'))""",
            (table_name, description, ",".join(a.strip() for a in aliases if a.strip())),
        )
        conn.commit()
    finally:
        conn.close()


def get_table_metadata(table_name: str = None) -> dict:
    """获取表元数据 {table_name: {description, aliases}}"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        if table_name:
            cursor.execute(
                "SELECT table_name, description, aliases FROM _table_metadata WHERE table_name=?",
                (table_name,),
            )
        else:
            cursor.execute("SELECT table_name, description, aliases FROM _table_metadata")
        rows = cursor.fetchall()
        return {
            row[0]: {
                "description": row[1] or "",
                "aliases": [a for a in (row[2] or "").split(",") if a.strip()],
            }
            for row in rows
        }
    finally:
        conn.close()


def build_enriched_schema_str(schema_info: dict, metadata: dict) -> str:
    """生成带描述和别名的 Schema 字符串，供 LLM 语义匹配使用"""
    result = ""
    for table, columns in schema_info.items():
        if table in INTERNAL_TABLES:
            continue
        col_desc = ", ".join([f"{c['name']}({c['type']})" for c in columns])
        meta = metadata.get(table, {})
        desc = meta.get("description", "")
        aliases = meta.get("aliases", [])

        label = ""
        if desc:
            label = f"【{desc}"
            if aliases:
                label += f" | 别名: {', '.join(aliases)}"
            label += "】"

        result += f"表 {table}{label}: {col_desc}\n"
    return result


# ── Schema 查询工具 ───────────────────────────────────────────

class GetTableSchemaTool:
    """获取 SQLite 数据库所有表的 schema 信息"""

    name = "get_table_schema"
    description = "获取数据库中所有表的字段结构信息"

    def run(self, table_name: str = None) -> dict:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            if table_name:
                tables = [table_name]
            else:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [row[0] for row in cursor.fetchall()]

            schema = {}
            for tbl in tables:
                cursor.execute(f"PRAGMA table_info({_quote_identifier(tbl)})")
                columns = cursor.fetchall()
                schema[tbl] = [
                    {
                        "cid": col[0],
                        "name": col[1],
                        "type": col[2],
                        "notnull": bool(col[3]),
                        "default": col[4],
                        "pk": bool(col[5]),
                    }
                    for col in columns
                ]
            return schema
        finally:
            conn.close()
