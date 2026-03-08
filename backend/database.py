import sqlite3
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./dataspeak.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 待办事项表（只保留这一张表）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'normal',
            due_date TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 表元数据（描述 + 别名，供 LLM 语义匹配）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS _table_metadata (
            table_name TEXT PRIMARY KEY,
            description TEXT DEFAULT '',
            aliases TEXT DEFAULT '',
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 为todos表插入元数据（已存在则忽略）
    default_meta = [
        ("todos", "待办事项和任务清单", "任务,to-do,代办,清单,todo"),
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
