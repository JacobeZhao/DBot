"""
重构的数据库操作工具 - 为DeepSeek函数调用设计

将现有工具类转换为函数，并提供OpenAI兼容的schema定义。
"""

import sqlite3
import datetime
from typing import Any, Dict, List, Optional
import os

from backend.tools.schema_tools import (
    column_exists,
    get_table_columns,
    is_valid_identifier,
    quote_identifier,
    table_exists,
)

import os
DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")
SYSTEM_COLUMNS = {"id", "uuid", "创建时间", "更新时间", "created_at", "updated_at"}


def _connect() -> sqlite3.Connection:
    """创建数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_serializable(value: Any) -> Any:
    """
    确保数据库返回值可JSON序列化

    Args:
        value: 数据库返回的值

    Returns:
        可序列化的值
    """
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    elif isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    elif isinstance(value, bytes):
        return value.decode('utf-8', errors='ignore')
    else:
        return str(value)


def _row_to_serializable_dict(row) -> Dict[str, Any]:
    """
    将sqlite3.Row对象转换为可序列化的字典

    Args:
        row: sqlite3.Row对象或字典

    Returns:
        可序列化的字典
    """
    if isinstance(row, sqlite3.Row):
        # sqlite3.Row对象 — 使用 keys() 方法
        row_dict = {key: _ensure_serializable(row[key]) for key in row.keys()}
    elif isinstance(row, dict):
        row_dict = {key: _ensure_serializable(value) for key, value in row.items()}
    else:
        row_dict = {"value": _ensure_serializable(row)}

    return row_dict


def _resolve_where_clause(where: Dict[str, Any]) -> tuple[str, List[Any]]:
    """将where字典转换为SQL条件和参数列表"""
    if not where:
        raise ValueError("缺少行定位条件")

    clauses = []
    values = []
    for key, value in where.items():
        if not is_valid_identifier(key):
            raise ValueError(f"非法字段名: {key}")
        clauses.append(f"{quote_identifier(key)} = ?")
        values.append(value)
    return " AND ".join(clauses), values


def _assert_table_and_columns(table: str, columns: List[str]):
    """验证表名和字段名存在"""
    if not is_valid_identifier(table):
        raise ValueError(f"非法表名: {table}")
    if not table_exists(table):
        raise ValueError(f"表不存在: {table}")

    table_cols = {col["name"] for col in get_table_columns(table)}
    for col in columns:
        if col not in table_cols:
            raise ValueError(f"字段不存在: {col}")


# ================ 核心工具函数 ================

def insert_row(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    向指定表插入一行数据

    Args:
        table: 表名
        data: 要插入的数据字典

    Returns:
        {
            "success": True/False,
            "rowid": 插入行的ID,
            "table": 表名,
            "message": 描述信息
        }
    """
    conn = _connect()
    try:
        _assert_table_and_columns(table, list(data.keys()))

        # 过滤掉系统字段和None值
        filtered = {k: v for k, v in data.items() if v is not None and k not in SYSTEM_COLUMNS}
        if not filtered:
            raise ValueError("没有可插入的有效字段")

        # 如果表中有date字段且未提供，自动添加当前日期
        if "date" in [col["name"] for col in get_table_columns(table)] and "date" not in filtered:
            filtered["date"] = str(date.today())

        columns = ", ".join(quote_identifier(k) for k in filtered.keys())
        placeholders = ", ".join("?" for _ in filtered)
        values = list(filtered.values())
        sql = f"INSERT INTO {quote_identifier(table)} ({columns}) VALUES ({placeholders})"

        cursor = conn.cursor()
        cursor.execute(sql, values)
        conn.commit()

        return {
            "success": True,
            "rowid": cursor.lastrowid,
            "table": table,
            "message": f"成功插入数据到表 '{table}'，行ID: {cursor.lastrowid}"
        }
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_row(table: str, where: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """
    更新指定表中满足条件的行

    Args:
        table: 表名
        where: 条件字典，如 {"id": 1}
        data: 要更新的数据字典

    Returns:
        {
            "success": True/False,
            "rows_affected": 影响的行数,
            "table": 表名,
            "message": 描述信息
        }
    """
    conn = _connect()
    try:
        # 过滤系统字段（除了更新时间）
        update_data = {k: v for k, v in data.items() if k not in SYSTEM_COLUMNS or k == "更新时间"}
        if not update_data:
            raise ValueError("没有可更新的字段")

        _assert_table_and_columns(table, list(update_data.keys()) + list(where.keys()))

        # 如果表有更新时间字段，自动更新
        if column_exists(table, "更新时间") and "更新时间" not in update_data:
            update_data["更新时间"] = "now"

        set_clause = ", ".join(f"{quote_identifier(k)} = ?" for k in update_data.keys())
        where_clause, where_values = _resolve_where_clause(where)
        values = list(update_data.values()) + where_values

        sql = f"UPDATE {quote_identifier(table)} SET {set_clause} WHERE {where_clause}"
        cursor = conn.cursor()
        cursor.execute(sql, values)
        conn.commit()

        return {
            "success": True,
            "rows_affected": cursor.rowcount,
            "table": table,
            "message": f"成功更新表 '{table}'，影响 {cursor.rowcount} 行"
        }
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_row(table: str, where: Dict[str, Any]) -> Dict[str, Any]:
    """
    删除指定表中满足条件的行

    Args:
        table: 表名
        where: 条件字典

    Returns:
        {
            "success": True/False,
            "rows_affected": 删除的行数,
            "table": 表名,
            "message": 描述信息
        }
    """
    _assert_table_and_columns(table, list(where.keys()))
    where_clause, where_values = _resolve_where_clause(where)

    conn = _connect()
    try:
        sql = f"DELETE FROM {quote_identifier(table)} WHERE {where_clause}"
        cursor = conn.cursor()
        cursor.execute(sql, where_values)
        conn.commit()

        return {
            "success": True,
            "rows_affected": cursor.rowcount,
            "table": table,
            "message": f"从表 '{table}' 删除 {cursor.rowcount} 行"
        }
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_data(table: str, where: Optional[Dict[str, Any]] = None, limit: int = 100) -> Dict[str, Any]:
    """
    查询表中的数据

    Args:
        table: 表名
        where: 可选的条件字典
        limit: 返回的最大行数

    Returns:
        {
            "success": True/False,
            "table": 表名,
            "columns": 字段列表,
            "rows": 数据行列表,
            "count": 返回的行数
        }
    """
    if not table_exists(table):
        raise ValueError(f"表不存在: {table}")

    conn = _connect()
    try:
        # 获取表结构
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({quote_identifier(table)})")
        columns = [
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

        # 构建查询
        sql = f"SELECT * FROM {quote_identifier(table)}"
        params = []

        if where:
            where_clause, where_values = _resolve_where_clause(where)
            sql += f" WHERE {where_clause}"
            params = where_values

        sql += f" ORDER BY rowid DESC LIMIT {limit}"

        cursor.execute(sql, params)
        rows = [_row_to_serializable_dict(row) for row in cursor.fetchall()]

        return {
            "success": True,
            "table": table,
            "columns": columns,
            "rows": rows,
            "count": len(rows)
        }
    finally:
        conn.close()


def get_cell_value(table: str, where: Dict[str, Any], column: str) -> Dict[str, Any]:
    """
    获取单元格值

    Args:
        table: 表名
        where: 条件字典
        column: 字段名

    Returns:
        {
            "success": True/False,
            "table": 表名,
            "column": 字段名,
            "value": 单元格值
        }
    """
    if not is_valid_identifier(column):
        raise ValueError(f"非法字段名: {column}")

    _assert_table_and_columns(table, list(where.keys()) + [column])
    where_clause, where_values = _resolve_where_clause(where)

    conn = _connect()
    try:
        sql = (
            f"SELECT {quote_identifier(column)} AS cell_value "
            f"FROM {quote_identifier(table)} WHERE {where_clause} LIMIT 1"
        )
        row = conn.execute(sql, where_values).fetchone()
        if not row:
            raise ValueError("未找到匹配行")

        return {
            "success": True,
            "table": table,
            "column": column,
            "value": _ensure_serializable(row["cell_value"])
        }
    finally:
        conn.close()


def update_cell_value(table: str, where: Dict[str, Any], column: str, value: Any) -> Dict[str, Any]:
    """
    更新单元格值

    Args:
        table: 表名
        where: 条件字典
        column: 字段名
        value: 新值

    Returns:
        update_row的返回结果
    """
    return update_row(table=table, where=where, data={column: value})


# ================ Schema定义 ================

INSERT_ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {
            "type": "string",
            "description": "目标表名"
        },
        "data": {
            "type": "object",
            "description": "要插入的数据，字段名到值的映射",
            "additionalProperties": True
        }
    },
    "required": ["table", "data"]
}

UPDATE_ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {
            "type": "string",
            "description": "目标表名"
        },
        "where": {
            "type": "object",
            "description": "行选择条件，字段名到值的映射",
            "additionalProperties": True
        },
        "data": {
            "type": "object",
            "description": "要更新的数据，字段名到新值的映射",
            "additionalProperties": True
        }
    },
    "required": ["table", "where", "data"]
}

DELETE_ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {
            "type": "string",
            "description": "目标表名"
        },
        "where": {
            "type": "object",
            "description": "行选择条件，字段名到值的映射",
            "additionalProperties": True
        }
    },
    "required": ["table", "where"]
}

QUERY_DATA_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {
            "type": "string",
            "description": "目标表名"
        },
        "where": {
            "type": "object",
            "description": "可选的行选择条件",
            "additionalProperties": True
        },
        "limit": {
            "type": "integer",
            "description": "返回的最大行数",
            "minimum": 1,
            "maximum": 1000,
            "default": 100
        }
    },
    "required": ["table"]
}

GET_CELL_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {
            "type": "string",
            "description": "目标表名"
        },
        "where": {
            "type": "object",
            "description": "行选择条件",
            "additionalProperties": True
        },
        "column": {
            "type": "string",
            "description": "要获取的字段名"
        }
    },
    "required": ["table", "where", "column"]
}

UPDATE_CELL_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {
            "type": "string",
            "description": "目标表名"
        },
        "where": {
            "type": "object",
            "description": "行选择条件",
            "additionalProperties": True
        },
        "column": {
            "type": "string",
            "description": "要更新的字段名"
        },
        "value": {
            "type": "string",
            "description": "新值"
        }
    },
    "required": ["table", "where", "column", "value"]
}