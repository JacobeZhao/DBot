import os
import sqlite3
from datetime import date

from dotenv import load_dotenv
from rich.console import Console
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.tools.schema_tools import (
    column_exists,
    get_table_columns,
    is_valid_identifier,
    quote_identifier,
    table_exists,
)

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")
console = Console()
SYSTEM_COLUMNS = {"id", "uuid", "创建时间", "更新时间", "created_at", "updated_at"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _resolve_where_clause(where: dict | None) -> tuple[str, list]:
    where = where or {}
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


def _assert_table_and_columns(table: str, columns: list[str]):
    if not is_valid_identifier(table):
        raise ValueError(f"非法表名: {table}")
    if not table_exists(table):
        raise ValueError(f"表不存在: {table}")

    table_cols = {col["name"] for col in get_table_columns(table)}
    for col in columns:
        if col not in table_cols:
            raise ValueError(f"字段不存在: {col}")


class DBInsertTool:
    """向指定表插入一行数据"""

    name = "db_insert"
    description = "向数据库表中插入一条记录"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(sqlite3.OperationalError),
        reraise=True,
    )
    def run(self, table: str, data: dict) -> dict:
        conn = _connect()
        try:
            _assert_table_and_columns(table, list(data.keys()))

            filtered = {k: v for k, v in (data or {}).items() if v is not None and k not in SYSTEM_COLUMNS}
            if not filtered:
                raise ValueError("没有可插入的有效字段")

            if "date" in [col["name"] for col in get_table_columns(table)] and "date" not in filtered:
                filtered["date"] = str(date.today())

            columns = ", ".join(quote_identifier(k) for k in filtered.keys())
            placeholders = ", ".join("?" for _ in filtered)
            values = list(filtered.values())
            sql = f"INSERT INTO {quote_identifier(table)} ({columns}) VALUES ({placeholders})"

            cursor = conn.cursor()
            cursor.execute(sql, values)
            conn.commit()
            return {"success": True, "rowid": cursor.lastrowid, "table": table}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class DBUpdateTool:
    """更新指定表中满足条件的行"""

    name = "db_update"
    description = "更新数据库表中满足条件的记录"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(sqlite3.OperationalError),
        reraise=True,
    )
    def run(self, table: str, data: dict, where: dict) -> dict:
        conn = _connect()
        try:
            update_data = {k: v for k, v in (data or {}).items() if k not in SYSTEM_COLUMNS or k == "更新时间"}
            if not update_data:
                raise ValueError("没有可更新的字段")

            _assert_table_and_columns(table, list(update_data.keys()) + list((where or {}).keys()))

            if column_exists(table, "更新时间") and "更新时间" not in update_data:
                update_data["更新时间"] = "now"

            set_clause = ", ".join(f"{quote_identifier(k)} = ?" for k in update_data.keys())
            where_clause, where_values = _resolve_where_clause(where)
            values = list(update_data.values()) + where_values

            sql = f"UPDATE {quote_identifier(table)} SET {set_clause} WHERE {where_clause}"
            cursor = conn.cursor()
            cursor.execute(sql, values)
            conn.commit()
            return {"success": True, "rows_affected": cursor.rowcount, "table": table}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class DBRowInsertTool:
    name = "row_insert"
    description = "插入一行记录"

    def run(self, table: str, data: dict) -> dict:
        return DBInsertTool().run(table=table, data=data)


class DBRowUpdateTool:
    name = "row_update"
    description = "更新一行或多行记录"

    def run(self, table: str, where: dict, data: dict) -> dict:
        return DBUpdateTool().run(table=table, data=data, where=where)


class DBRowDeleteTool:
    name = "row_delete"
    description = "删除一行或多行记录"

    def run(self, table: str, where: dict) -> dict:
        _assert_table_and_columns(table, list((where or {}).keys()))
        where_clause, where_values = _resolve_where_clause(where)

        conn = _connect()
        try:
            sql = f"DELETE FROM {quote_identifier(table)} WHERE {where_clause}"
            cursor = conn.cursor()
            cursor.execute(sql, where_values)
            conn.commit()
            return {"success": True, "rows_affected": cursor.rowcount, "table": table}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class DBCellGetTool:
    name = "cell_get"
    description = "查询单元格值"

    def run(self, table: str, where: dict, column: str) -> dict:
        if not is_valid_identifier(column):
            raise ValueError(f"非法字段名: {column}")

        _assert_table_and_columns(table, list((where or {}).keys()) + [column])
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
                "value": row["cell_value"],
            }
        finally:
            conn.close()


class DBCellUpdateTool:
    name = "cell_update"
    description = "更新单元格值"

    def run(self, table: str, where: dict, column: str, value) -> dict:
        if not is_valid_identifier(column):
            raise ValueError(f"非法字段名: {column}")

        _assert_table_and_columns(table, list((where or {}).keys()) + [column])
        return DBUpdateTool().run(table=table, data={column: value}, where=where)
