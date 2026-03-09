import os
import sqlite3
import uuid
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    cursor = conn.cursor()
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    return any(row[1] == column_name for row in cursor.fetchall())


def _ensure_system_columns(conn: sqlite3.Connection, table_name: str):
    if not _table_has_column(conn, table_name, "uuid"):
        conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "uuid" TEXT')
    if not _table_has_column(conn, table_name, "创建时间"):
        conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "创建时间" TEXT')
    if not _table_has_column(conn, table_name, "更新时间"):
        conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "更新时间" TEXT')


def _backfill_timestamps(conn: sqlite3.Connection, table_name: str):
    conn.execute(
        f"UPDATE \"{table_name}\" SET \"创建时间\" = COALESCE(\"创建时间\", datetime('now', 'localtime'))"
    )
    conn.execute(
        f"UPDATE \"{table_name}\" SET \"更新时间\" = COALESCE(\"更新时间\", datetime('now', 'localtime'))"
    )
    conn.execute(
        f"UPDATE \"{table_name}\" SET \"更新时间\" = datetime('now', 'localtime') WHERE \"更新时间\" = ''"
    )
    conn.execute(
        f"UPDATE \"{table_name}\" SET \"创建时间\" = datetime('now', 'localtime') WHERE \"创建时间\" = ''"
    )


def _backfill_uuid(conn: sqlite3.Connection, table_name: str):
    cursor = conn.cursor()
    cursor.execute(f'SELECT "id" FROM "{table_name}" WHERE "uuid" IS NULL OR "uuid" = ""')
    rows = cursor.fetchall()
    for row in rows:
        cursor.execute(
            f'UPDATE "{table_name}" SET "uuid" = ? WHERE "id" = ?',
            (str(uuid.uuid4()), row[0]),
        )


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 待办事项表（默认业务表示例）
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "todos" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT,
            "uuid" TEXT,
            "title" TEXT NOT NULL,
            "status" TEXT DEFAULT 'pending',
            "priority" TEXT DEFAULT 'normal',
            "due_date" TEXT,
            "创建时间" TEXT DEFAULT (datetime('now', 'localtime')),
            "更新时间" TEXT DEFAULT (datetime('now', 'localtime'))
        )
        """
    )

    # 表元数据（描述 + 别名，供 LLM 语义匹配）
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "_table_metadata" (
            "table_name" TEXT PRIMARY KEY,
            "description" TEXT DEFAULT '',
            "aliases" TEXT DEFAULT '',
            "updated_at" TEXT DEFAULT (datetime('now', 'localtime'))
        )
        """
    )

    # 兼容旧表结构：补齐系统字段
    _ensure_system_columns(conn, "todos")
    _backfill_uuid(conn, "todos")
    _backfill_timestamps(conn, "todos")

    # 为 todos 表插入元数据（已存在则忽略）
    default_meta = [
        ("todos", "待办事项和任务清单", "任务,to-do,代办,清单,todo,待办"),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO _table_metadata (table_name, description, aliases) VALUES (?, ?, ?)",
        default_meta,
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
