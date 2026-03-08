import sqlite3
import os
import re
from datetime import date
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")
console = Console()

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(name: str) -> str:
    if not name or not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"非法标识符: {name}")
    return f'"{name}"'


def _is_sqlite_lock_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()


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
        conn = sqlite3.connect(DB_PATH)
        try:
            # 过滤 null 值以及数据库自动管理的字段
            auto_fields = {"id", "created_at"}
            data = {k: v for k, v in data.items() if v is not None and k not in auto_fields}

            # 自动填充 date 字段（如果缺失）
            if "date" in [col for col in self._get_columns(table)] and "date" not in data:
                data["date"] = str(date.today())

            columns = ", ".join([_quote_identifier(k) for k in data.keys()])
            placeholders = ", ".join(["?" for _ in data])
            values = list(data.values())

            quoted_table = _quote_identifier(table)
            sql = f"INSERT INTO {quoted_table} ({columns}) VALUES ({placeholders})"
            console.print(f"[bold red][EXECUTOR][/bold red] INSERT SQL: {sql} | values: {values}")

            cursor = conn.cursor()
            cursor.execute(sql, values)
            conn.commit()
            row_id = cursor.lastrowid
            console.print(f"[bold red][EXECUTOR][/bold red] 插入成功，rowid={row_id}")
            return {"success": True, "rowid": row_id, "table": table}
        except sqlite3.OperationalError as e:
            conn.rollback()
            console.print(f"[bold red][EXECUTOR][/bold red] 操作失败，已回滚: {e}")
            raise
        except Exception as e:
            conn.rollback()
            console.print(f"[bold red][EXECUTOR][/bold red] 未知错误，已回滚: {e}")
            raise
        finally:
            conn.close()

    def _get_columns(self, table: str) -> list:
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({_quote_identifier(table)})")
            return [row[1] for row in cursor.fetchall()]
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
        conn = sqlite3.connect(DB_PATH)
        try:
            quoted_table = _quote_identifier(table)
            set_clause = ", ".join([f"{_quote_identifier(k)} = ?" for k in data.keys()])
            where_clause = " AND ".join([f"{_quote_identifier(k)} = ?" for k in where.keys()])
            values = list(data.values()) + list(where.values())

            sql = f"UPDATE {quoted_table} SET {set_clause} WHERE {where_clause}"
            console.print(f"[bold red][EXECUTOR][/bold red] UPDATE SQL: {sql} | values: {values}")

            cursor = conn.cursor()
            cursor.execute(sql, values)
            conn.commit()
            rows_affected = cursor.rowcount
            console.print(f"[bold red][EXECUTOR][/bold red] 更新成功，影响行数={rows_affected}")
            return {"success": True, "rows_affected": rows_affected, "table": table}
        except sqlite3.OperationalError as e:
            conn.rollback()
            console.print(f"[bold red][EXECUTOR][/bold red] 操作失败，已回滚: {e}")
            raise
        except Exception as e:
            conn.rollback()
            console.print(f"[bold red][EXECUTOR][/bold red] 未知错误，已回滚: {e}")
            raise
        finally:
            conn.close()
