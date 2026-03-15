"""
重构的表结构工具 - 为DeepSeek函数调用设计
"""

import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

# 数据库配置
DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")
INTERNAL_TABLES = {"checkpoints", "writes", "checkpoint_blobs", "checkpoint_migrations", "_table_metadata", "_app_config"}
PROTECTED_COLUMNS = {"id", "uuid", "创建时间", "更新时间", "created_at", "updated_at"}
_IDENTIFIER_RE = re.compile(r"^(?!\d)[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*$")


# ================ 基础函数 ================

def is_valid_identifier(name: str) -> bool:
    """检查标识符是否合法"""
    return bool(name and _IDENTIFIER_RE.fullmatch(name))


def quote_identifier(name: str) -> str:
    """引用标识符（防止SQL注入）"""
    if not is_valid_identifier(name):
        raise ValueError(f"非法标识符: {name}")
    return f'"{name}"'


def table_exists(table_name: str) -> bool:
    """检查表是否存在"""
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


def get_table_columns(table_name: str) -> Dict[str, Any]:
    """获取表的列信息"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
        columns = []
        for row in cursor.fetchall():
            columns.append({
                "cid": row[0],
                "name": row[1],
                "type": row[2],
                "notnull": bool(row[3]),
                "default": row[4],
                "pk": bool(row[5]),
            })
        return {"success": True, "columns": columns}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def get_table_metadata(table_name: str = None) -> Dict[str, Any]:
    """获取表元数据"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        if table_name:
            cursor.execute(
                "SELECT table_name, description, aliases FROM _table_metadata WHERE table_name=?",
                (table_name,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "success": True,
                    table_name: {
                        "description": row[1],
                        "aliases": row[2].split(",") if row[2] else []
                    }
                }
            return {"success": True, table_name: {}}
        else:
            cursor.execute("SELECT table_name, description, aliases FROM _table_metadata")
            metadata = {}
            for row in cursor.fetchall():
                metadata[row[0]] = {
                    "description": row[1],
                    "aliases": row[2].split(",") if row[2] else []
                }
            return {"success": True, "metadata": metadata}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


# ================ 核心工具函数 ================

def column_exists(table_name: str, column_name: str) -> bool:
    """检查表中是否存在指定列"""
    try:
        columns = get_table_columns(table_name)
        if not columns.get("success"):
            return False
        return any(col["name"] == column_name for col in columns.get("columns", []))
    except Exception:
        return False


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


# ================ 内部工具函数 ================

def _add_column(table_name: str, column_name: str, column_type: str = "TEXT", notnull: bool = False, default: str = "") -> str:
    """添加字段到表（内部函数）"""
    col_type = (column_type or "TEXT").strip().upper()
    if col_type not in {"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"}:
        raise ValueError(f"不支持的字段类型: {col_type}")

    if not is_valid_identifier(table_name):
        raise ValueError(f"非法表名: {table_name}")
    if not is_valid_identifier(column_name):
        raise ValueError(f"非法字段名: {column_name}")

    columns_result = get_table_columns(table_name)
    if not columns_result.get("success"):
        raise ValueError(f"获取表结构失败: {columns_result.get('error', '未知错误')}")

    existing_columns = columns_result.get("columns", [])
    if any(col["name"] == column_name for col in existing_columns):
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


def _drop_column(table_name: str, column_name: str) -> str:
    """从表删除字段（内部函数）"""
    if column_name in PROTECTED_COLUMNS:
        raise ValueError(f"系统字段不允许删除: {column_name}")

    columns_result = get_table_columns(table_name)
    if not columns_result.get("success"):
        raise ValueError(f"获取表结构失败: {columns_result.get('error', '未知错误')}")

    existing_columns = columns_result.get("columns", [])
    if not any(col["name"] == column_name for col in existing_columns):
        raise ValueError(f"字段不存在: {column_name}")

    sql = f"ALTER TABLE {quote_identifier(table_name)} DROP COLUMN {quote_identifier(column_name)}"
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(sql)
        conn.commit()
        return sql
    finally:
        conn.close()


def _rename_column(table_name: str, old_name: str, new_name: str) -> str:
    """重命名字段（内部函数）"""
    if old_name in PROTECTED_COLUMNS:
        raise ValueError(f"系统字段不允许重命名: {old_name}")
    if new_name in PROTECTED_COLUMNS:
        raise ValueError(f"不允许重命名为系统字段: {new_name}")

    if not is_valid_identifier(new_name):
        raise ValueError(f"非法字段名: {new_name}")

    columns_result = get_table_columns(table_name)
    if not columns_result.get("success"):
        raise ValueError(f"获取表结构失败: {columns_result.get('error', '未知错误')}")

    existing_columns = columns_result.get("columns", [])
    if not any(col["name"] == old_name for col in existing_columns):
        raise ValueError(f"字段不存在: {old_name}")
    if any(col["name"] == new_name for col in existing_columns):
        raise ValueError(f"目标字段已存在: {new_name}")

    sql = f"ALTER TABLE {quote_identifier(table_name)} RENAME COLUMN {quote_identifier(old_name)} TO {quote_identifier(new_name)}"
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(sql)
        conn.commit()
        return sql
    finally:
        conn.close()


def _save_table_metadata(table_name: str, description: str, aliases: list) -> None:
    """保存/更新表的描述和别名（内部函数）"""
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


# ================ 核心工具函数 ================

def get_schema(table_name: Optional[str] = None) -> Dict[str, Any]:
    """
    获取数据库表结构

    Args:
        table_name: 可选表名，如果为None则获取所有表

    Returns:
        {
            "success": True/False,
            "schema": 表结构字典,
            "metadata": 表元数据,
            "tables": 表名列表
        }
    """
    try:
        tool = GetTableSchemaTool()
        schema = tool.run(table_name)

        # 获取元数据
        metadata = get_table_metadata()

        # 构建响应
        result = {
            "success": True,
            "schema": schema,
            "metadata": metadata
        }

        if table_name:
            result["table"] = table_name
        else:
            result["tables"] = list(schema.keys())

        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def list_tables() -> Dict[str, Any]:
    """
    列出所有用户表 - 修复版本

    Returns:
        {
            "success": True/False,
            "tables": 表信息列表
        }
    """
    try:
        # 实际查询数据库
        from backend.tools.db_tools import _connect
        conn = _connect()
        cursor = conn.cursor()

        # 获取所有用户表
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        all_tables = [row[0] for row in cursor.fetchall()]

        # 过滤掉内部表
        internal_tables = {"checkpoints", "writes", "checkpoint_blobs",
                          "checkpoint_migrations", "_table_metadata", "_app_config"}
        user_tables = [t for t in all_tables if t not in internal_tables]

        # 构建表信息
        tables = []
        for table_name in user_tables:
            # 获取列信息
            columns = []
            try:
                cursor.execute(f"PRAGMA table_info({table_name})")
                for row in cursor.fetchall():
                    columns.append({
                        "cid": row[0],
                        "name": row[1],
                        "type": row[2],
                        "notnull": bool(row[3]),
                        "default": row[4],
                        "pk": bool(row[5]),
                    })
            except Exception:
                columns = []

            tables.append({
                "name": table_name,
                "description": "",
                "aliases": [],
                "column_count": len(columns),
                "columns": columns
            })

        conn.close()

        return {
            "success": True,
            "tables": tables,
            "count": len(tables)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def add_column(table: str, column: str, type: str = "TEXT",
               notnull: bool = False, default: str = "") -> Dict[str, Any]:
    """
    向表添加字段

    Args:
        table: 表名
        column: 字段名
        type: 字段类型 (TEXT, INTEGER, REAL, BLOB, NUMERIC)
        notnull: 是否不允许NULL
        default: 默认值

    Returns:
        {
            "success": True/False,
            "sql": 执行的SQL语句,
            "table": 表名,
            "column": 字段名,
            "message": 描述信息
        }
    """
    try:
        sql = _add_column(table, column, type, notnull, default)
        return {
            "success": True,
            "sql": sql,
            "table": table,
            "column": column,
            "message": f"成功向表 '{table}' 添加字段 '{column}' ({type})"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "table": table,
            "column": column
        }


def drop_column(table: str, column: str) -> Dict[str, Any]:
    """
    从表删除字段

    Args:
        table: 表名
        column: 字段名

    Returns:
        {
            "success": True/False,
            "sql": 执行的SQL语句,
            "table": 表名,
            "column": 字段名,
            "message": 描述信息
        }
    """
    try:
        sql = _drop_column(table, column)
        return {
            "success": True,
            "sql": sql,
            "table": table,
            "column": column,
            "message": f"成功从表 '{table}' 删除字段 '{column}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "table": table,
            "column": column
        }


def rename_column(table: str, old_name: str, new_name: str) -> Dict[str, Any]:
    """
    重命名字段

    Args:
        table: 表名
        old_name: 原字段名
        new_name: 新字段名

    Returns:
        {
            "success": True/False,
            "sql": 执行的SQL语句,
            "table": 表名,
            "old_name": 原字段名,
            "new_name": 新字段名,
            "message": 描述信息
        }
    """
    try:
        sql = _rename_column(table, old_name, new_name)
        return {
            "success": True,
            "sql": sql,
            "table": table,
            "old_name": old_name,
            "new_name": new_name,
            "message": f"成功将表 '{table}' 的字段 '{old_name}' 重命名为 '{new_name}'"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "table": table,
            "old_name": old_name,
            "new_name": new_name
        }


def create_table(table_name: str, columns: List[Dict[str, Any]],
                 description: str = "", aliases: List[str] = []) -> Dict[str, Any]:
    """
    创建新表

    Args:
        table_name: 表名
        columns: 字段定义列表，每个字段包含: name, type, notnull, default
        description: 表描述
        aliases: 表别名列表

    Returns:
        {
            "success": True/False,
            "sql": 执行的SQL语句,
            "table": 表名,
            "message": 描述信息
        }
    """
    try:
        # 验证表名
        if not is_valid_identifier(table_name):
            raise ValueError(f"非法表名: {table_name}")

        # 检查是否为内部表名
        if table_name in {"checkpoints", "writes", "checkpoint_blobs",
                         "checkpoint_migrations", "_table_metadata", "_app_config"}:
            raise ValueError(f"表名与系统保留名冲突: {table_name}")

        # 系统字段定义
        all_defs = [
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            "uuid TEXT DEFAULT (lower(hex(randomblob(16))))",
            "创建时间 TEXT DEFAULT (datetime('now', 'localtime'))",
            "更新时间 TEXT DEFAULT (datetime('now', 'localtime'))",
        ]

        # 保护的系统字段
        PROTECTED_SYSTEM_COLUMNS = {"id", "uuid", "创建时间", "更新时间"}
        ALLOWED_COLUMN_TYPES = {"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"}

        # 添加用户定义的字段
        for col in columns:
            col_name = col.get("name", "").strip()
            if not col_name:
                raise ValueError("字段名不能为空")

            if not is_valid_identifier(col_name):
                raise ValueError(f"非法字段名: {col_name}")

            if col_name in PROTECTED_SYSTEM_COLUMNS:
                raise ValueError(f"字段名为系统保留字段: {col_name}")

            col_type = (col.get("type", "TEXT") or "TEXT").strip().upper()
            if col_type not in ALLOWED_COLUMN_TYPES:
                raise ValueError(f"不支持的字段类型: {col_type}")

            col_sql = f"{quote_identifier(col_name)} {col_type}"
            if col.get("notnull", False):
                col_sql += " NOT NULL"

            default_val = col.get("default", "")
            if default_val:
                escaped_default = str(default_val).replace("'", "''")
                col_sql += f" DEFAULT '{escaped_default}'"

            all_defs.append(col_sql)

        # 构建SQL
        sql = f"CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} ({', '.join(all_defs)})"

        # 执行创建
        import sqlite3
        import os
        DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(sql)
            conn.commit()
            _save_table_metadata(table_name, description, aliases)
        except sqlite3.OperationalError as e:
            raise ValueError(f"创建表失败: {str(e)}")
        finally:
            conn.close()

        return {
            "success": True,
            "sql": sql,
            "table": table_name,
            "message": f"表 '{table_name}' 创建成功"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "table": table_name
        }


def drop_table(table_name: str) -> Dict[str, Any]:
    """
    删除表

    Args:
        table_name: 表名

    Returns:
        {
            "success": True/False,
            "table": 表名,
            "message": 描述信息
        }
    """
    try:
        # 验证表名
        if not is_valid_identifier(table_name):
            raise ValueError(f"非法表名: {table_name}")

        # 检查是否为内部表
        if table_name in {"checkpoints", "writes", "checkpoint_blobs",
                         "checkpoint_migrations", "_table_metadata", "_app_config"}:
            raise ValueError("不允许删除系统内部表")

        # 检查表是否存在
        if not table_exists(table_name):
            raise ValueError(f"表不存在: {table_name}")

        # 执行删除
        import sqlite3
        import os
        DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(f"DROP TABLE {quote_identifier(table_name)}")
            conn.commit()
        finally:
            conn.close()

        return {
            "success": True,
            "table": table_name,
            "message": f"表 '{table_name}' 已删除"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "table": table_name
        }


def save_table_metadata(table_name: str, description: str = "", aliases: List[str] = []) -> Dict[str, Any]:
    """
    保存表元数据（描述和别名）

    Args:
        table_name: 表名
        description: 表描述
        aliases: 别名列表

    Returns:
        {
            "success": True/False,
            "table": 表名,
            "description": 描述,
            "aliases": 别名列表,
            "message": 描述信息
        }
    """
    try:
        if not table_exists(table_name):
            raise ValueError(f"表不存在: {table_name}")

        _save_table_metadata(table_name, description, aliases)

        return {
            "success": True,
            "table": table_name,
            "description": description,
            "aliases": aliases,
            "message": f"表 '{table_name}' 元数据已保存"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "table": table_name
        }


# ================ Schema定义 ================

GET_SCHEMA_SCHEMA = {
    "type": "object",
    "properties": {
        "table_name": {
            "type": "string",
            "description": "表名，如果省略则获取所有表结构"
        }
    },
    "required": []
}

LIST_TABLES_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": []
}

ADD_COLUMN_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {
            "type": "string",
            "description": "目标表名"
        },
        "column": {
            "type": "string",
            "description": "要添加的字段名"
        },
        "type": {
            "type": "string",
            "description": "字段类型 (TEXT, INTEGER, REAL, BLOB, NUMERIC)",
            "enum": ["TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"],
            "default": "TEXT"
        },
        "notnull": {
            "type": "boolean",
            "description": "是否不允许NULL值",
            "default": False
        },
        "default": {
            "type": "string",
            "description": "默认值",
            "default": ""
        }
    },
    "required": ["table", "column"]
}

DROP_COLUMN_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {
            "type": "string",
            "description": "目标表名"
        },
        "column": {
            "type": "string",
            "description": "要删除的字段名"
        }
    },
    "required": ["table", "column"]
}

RENAME_COLUMN_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {
            "type": "string",
            "description": "目标表名"
        },
        "old_name": {
            "type": "string",
            "description": "原字段名"
        },
        "new_name": {
            "type": "string",
            "description": "新字段名"
        }
    },
    "required": ["table", "old_name", "new_name"]
}

CREATE_TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "table_name": {
            "type": "string",
            "description": "新表名"
        },
        "columns": {
            "type": "array",
            "description": "字段定义列表",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "字段名"
                    },
                    "type": {
                        "type": "string",
                        "description": "字段类型",
                        "enum": ["TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"],
                        "default": "TEXT"
                    },
                    "notnull": {
                        "type": "boolean",
                        "description": "是否不允许NULL",
                        "default": False
                    },
                    "default": {
                        "type": "string",
                        "description": "默认值",
                        "default": ""
                    }
                },
                "required": ["name"]
            }
        },
        "description": {
            "type": "string",
            "description": "表描述",
            "default": ""
        },
        "aliases": {
            "type": "array",
            "description": "表别名列表",
            "items": {"type": "string"},
            "default": []
        }
    },
    "required": ["table_name", "columns"]
}

DROP_TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "table_name": {
            "type": "string",
            "description": "要删除的表名"
        }
    },
    "required": ["table_name"]
}

SAVE_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "table_name": {
            "type": "string",
            "description": "表名"
        },
        "description": {
            "type": "string",
            "description": "表描述",
            "default": ""
        },
        "aliases": {
            "type": "array",
            "description": "别名列表",
            "items": {"type": "string"},
            "default": []
        }
    },
    "required": ["table_name"]
}