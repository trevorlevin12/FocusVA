# tests/test_database.py
import json
import pytest
import database


def test_tables_created(temp_db):
    with database.get_conn() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    names = {r["name"] for r in tables}
    assert "emails" in names
    assert "job_data" in names
    assert "drafts" in names


def test_insert_and_fetch_email(temp_db):
    with database.get_conn() as conn:
        conn.execute(
            """INSERT INTO emails
               (gmail_message_id, thread_id, sender, subject, body, received_at,
                classification, status, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("msg1", "thread1", "client@example.com", "Quote needed",
             "I need 100 business cards", "2026-03-25T10:00:00Z",
             "quote_request", "pending", "2026-03-25T10:01:00Z")
        )
    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM emails WHERE gmail_message_id = 'msg1'").fetchone()
    assert row is not None
    assert row["subject"] == "Quote needed"
    assert row["status"] == "pending"


def test_dedup_on_gmail_message_id(temp_db):
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO emails (gmail_message_id, sender, subject, body, received_at) VALUES (?, ?, ?, ?, ?)",
            ("msg1", "a@b.com", "Test", "Body", "2026-03-25T10:00:00Z")
        )
    with pytest.raises(Exception):
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO emails (gmail_message_id, sender, subject, body, received_at) VALUES (?, ?, ?, ?, ?)",
                ("msg1", "a@b.com", "Test2", "Body2", "2026-03-25T10:00:00Z")
            )


def test_insert_job_data_and_draft(temp_db):
    with database.get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO emails (gmail_message_id, sender, subject, body, received_at) VALUES (?, ?, ?, ?, ?)",
            ("msg2", "a@b.com", "Subject", "Body", "2026-03-25T10:00:00Z")
        )
        email_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO job_data (email_id, data) VALUES (?, ?)",
            (email_id, json.dumps({"job_type": "banner", "quantity": 5}))
        )
        conn.execute(
            "INSERT INTO drafts (email_id, body) VALUES (?, ?)",
            (email_id, "Thanks for reaching out!")
        )
    with database.get_conn() as conn:
        jd = conn.execute("SELECT data FROM job_data WHERE email_id = ?", (email_id,)).fetchone()
        draft = conn.execute("SELECT body FROM drafts WHERE email_id = ?", (email_id,)).fetchone()
    assert json.loads(jd["data"])["job_type"] == "banner"
    assert draft["body"] == "Thanks for reaching out!"
