# tests/test_main.py
import pytest
from fastapi.testclient import TestClient
import database
import main


@pytest.fixture(autouse=True)
def _test_db(tmp_path):
    db = str(tmp_path / "test.db")
    database.set_db_path(db)
    database.init_db()
    yield


@pytest.fixture
def client():
    return TestClient(main.app)


def _insert_thread(conn, thread_id="thread-1"):
    """Insert two emails sharing a thread_id. Returns (older_id, newer_id)."""
    conn.execute(
        """INSERT INTO emails (gmail_message_id, thread_id, sender, subject, body,
           received_at, classification, status, processed_at)
           VALUES (?, ?, ?, ?, ?, ?, 'general_question', 'pending', '')""",
        ("msg-1", thread_id, "Alice <alice@example.com>", "Hello", "First message",
         "2026-03-25T10:00:00+00:00"),
    )
    older_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO emails (gmail_message_id, thread_id, sender, subject, body,
           received_at, classification, status, processed_at)
           VALUES (?, ?, ?, ?, ?, ?, 'general_question', 'pending', '')""",
        ("msg-2", thread_id, "Bob <bob@example.com>", "Re: Hello", "Second message",
         "2026-03-25T11:00:00+00:00"),
    )
    newer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return older_id, newer_id


def test_get_email_includes_thread(client):
    with database.get_conn() as conn:
        older_id, newer_id = _insert_thread(conn)

    resp = client.get(f"/emails/{newer_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "thread" in data
    assert len(data["thread"]) == 2
    # Thread is ordered oldest first
    assert data["thread"][0]["id"] == older_id
    assert data["thread"][1]["id"] == newer_id


def test_get_email_thread_single_message(client):
    with database.get_conn() as conn:
        conn.execute(
            """INSERT INTO emails (gmail_message_id, thread_id, sender, subject, body,
               received_at, classification, status, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, 'general_question', 'pending', '')""",
            ("solo-msg", "solo-thread", "Solo <solo@example.com>", "Solo", "Only message",
             "2026-03-25T12:00:00+00:00"),
        )
        solo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    resp = client.get(f"/emails/{solo_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["thread"]) == 1
