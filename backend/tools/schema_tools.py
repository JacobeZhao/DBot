import os
import re
import sqlite3
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")

INTERNAL_TABLES = {"checkpoints", "writes", "checkpoint_blobs", "checkpoint_migrations", "_table_metadata", "_app_config"}
PROTECTED_COLUMNS = {"id", "uuid", "创建时间", "更新时间"}
_IDENTIFIER_RE = re.compile(r"^(?!\d)[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*$")


def is_valid_identifier(name: str) -> bool:
    return bool(name and _IDENTIFIER_RE.fullmatch(name))


def quote_identifier(name: str) -> str:
    if not is_valid_identifier(name):
        raise ValueError(f"非法标识符: {name}")
    return f'"{name}"'


# 兼容旧调用
_quote_identifier = quote_identifier


def table_exists(table_name: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return bool(cursor.fetchone())
    finally:
        conn.close()


def get_table_columns(table_name: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
        return [
            {
                "cid": row[0],
                "name": row[1],
                "type": row[2],
                "notnull": bool(row[3]),
                "default": row[4],
                "pk": bool(row[5]),
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def column_exists(table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in get_table_columns(table_name))


def add_column(table_name: str, column_name: str, column_type: str = "TEXT", notnull: bool = False, default: str = "") -> str:
    col_type = (column_type or "TEXT").strip().upper()
    if col_type not in {"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"}:
        raise ValueError(f"不支持的字段类型: {col_type}")

    if not is_valid_identifier(table_name):
        raise ValueError(f"非法表名: {table_name}")
    if not is_valid_identifier(column_name):
        raise ValueError(f"非法字段名: {column_name}")
    if column_exists(table_name, column_name):
        raise ValueError(f"字段已存在: {column_name}")

    sql = f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {quote_identifier(column_name)} {col_type}"
    if notnull:
        sql += " NOT NULL"
    if default:
        escaped = str(default).replace("'", "''")
        sql += f" DEFAULT '{escaped}'"

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(sql)
        conn.commit()
        return sql
    finally:
        conn.close()


def rename_column(table_name: str, old_name: str, new_name: str) -> str:
    if old_name in PROTECTED_COLUMNS:
        raise ValueError(f"系统字段不允许重命名: {old_name}")
    if new_name in PROTECTED_COLUMNS:
        raise ValueError(f"不允许重命名为系统字段: {new_name}")

    if not column_exists(table_name, old_name):
        raise ValueError(f"字段不存在: {old_name}")
    if column_exists(table_name, new_name):
        raise ValueError(f"目标字段已存在: {new_name}")

    sql = (
        f"ALTER TABLE {quote_identifier(table_name)} "
        f"RENAME COLUMN {quote_identifier(old_name)} TO {quote_identifier(new_name)}"
    )
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(sql)
        conn.commit()
        return sql
    finally:
        conn.close()


def drop_column(table_name: str, column_name: str) -> str:
    if column_name in PROTECTED_COLUMNS:
        raise ValueError(f"系统字段不允许删除: {column_name}")
    if not column_exists(table_name, column_name):
        raise ValueError(f"字段不存在: {column_name}")

    sql = f"ALTER TABLE {quote_identifier(table_name)} DROP COLUMN {quote_identifier(column_name)}"
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(sql)
        conn.commit()
        return sql
    finally:
        conn.close()


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
                cursor.execute(f"PRAGMA table_info({quote_identifier(tbl)})")
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
