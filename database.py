import sqlite3
from contextlib import contextmanager

_db_path = "./focusva.db"


def set_db_path(path: str) -> None:
    global _db_path
    _db_path = path


@contextmanager
def get_conn():
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gmail_message_id TEXT UNIQUE,
                thread_id TEXT DEFAULT '',
                sender TEXT DEFAULT '',
                subject TEXT DEFAULT '',
                body TEXT DEFAULT '',
                received_at TEXT DEFAULT '',
                classification TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                processed_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS job_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL REFERENCES emails(id),
                data TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL REFERENCES emails(id),
                body TEXT DEFAULT '',
                approved_by TEXT DEFAULT '',
                approved_at TEXT DEFAULT '',
                sent_at TEXT DEFAULT ''
            );
        """)
