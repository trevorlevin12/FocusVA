# tests/test_api.py
import json
import pytest
from fastapi.testclient import TestClient
import database


@pytest.fixture
def client(temp_db):
    # Import after temp_db fixture sets up the DB path
    from main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _seed_email(conn, **kwargs) -> int:
    defaults = {
        "gmail_message_id": "msg1",
        "thread_id": "thread1",
        "sender": "client@example.com",
        "subject": "Quote needed",
        "body": "I need 50 banners",
        "received_at": "2026-03-25T10:00:00Z",
        "classification": "quote_request",
        "status": "pending",
        "processed_at": "2026-03-25T10:01:00Z",
    }
    defaults.update(kwargs)
    cursor = conn.execute(
        """INSERT INTO emails (gmail_message_id, thread_id, sender, subject, body,
           received_at, classification, status, processed_at)
           VALUES (:gmail_message_id, :thread_id, :sender, :subject, :body,
           :received_at, :classification, :status, :processed_at)""",
        defaults,
    )
    return cursor.lastrowid


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_list_emails_empty(client):
    res = client.get("/emails")
    assert res.status_code == 200
    assert res.json() == []


def test_list_emails_returns_seeded_rows(client, temp_db):
    with database.get_conn() as conn:
        _seed_email(conn)
        _seed_email(conn, gmail_message_id="msg2", subject="Another one", status="sent")

    res = client.get("/emails")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_list_emails_filter_by_status(client, temp_db):
    with database.get_conn() as conn:
        _seed_email(conn, gmail_message_id="msg1", status="pending")
        _seed_email(conn, gmail_message_id="msg2", status="sent")

    res = client.get("/emails?status=pending")
    data = res.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"


def test_list_emails_filter_by_classification(client, temp_db):
    with database.get_conn() as conn:
        _seed_email(conn, gmail_message_id="msg1", classification="quote_request")
        _seed_email(conn, gmail_message_id="msg2", classification="vendor_spam")

    res = client.get("/emails?classification=quote_request")
    data = res.json()
    assert len(data) == 1
    assert data[0]["classification"] == "quote_request"


def test_get_email_detail(client, temp_db):
    with database.get_conn() as conn:
        eid = _seed_email(conn)
        conn.execute("INSERT INTO job_data (email_id, data) VALUES (?, ?)",
                     (eid, json.dumps({"job_type": "banner"})))
        conn.execute("INSERT INTO drafts (email_id, body) VALUES (?, ?)",
                     (eid, "Thanks! What size?"))

    res = client.get(f"/emails/{eid}")
    assert res.status_code == 200
    body = res.json()
    assert body["email"]["subject"] == "Quote needed"
    assert body["job_data"]["job_type"] == "banner"
    assert body["draft"]["body"] == "Thanks! What size?"


def test_get_email_detail_not_found(client):
    res = client.get("/emails/9999")
    assert res.status_code == 404


def test_update_draft(client, temp_db):
    with database.get_conn() as conn:
        eid = _seed_email(conn)
        conn.execute("INSERT INTO drafts (email_id, body) VALUES (?, ?)", (eid, "Original text"))

    res = client.put(f"/emails/{eid}/draft", json={"body": "Updated text"})
    assert res.status_code == 200

    with database.get_conn() as conn:
        draft = conn.execute("SELECT body FROM drafts WHERE email_id = ?", (eid,)).fetchone()
    assert draft["body"] == "Updated text"


def test_update_draft_not_found(client, temp_db):
    with database.get_conn() as conn:
        eid = _seed_email(conn)
    # No draft inserted
    res = client.put(f"/emails/{eid}/draft", json={"body": "text"})
    assert res.status_code == 404


def test_approve_email(client, temp_db, monkeypatch):
    import gmail_client
    sent = []
    monkeypatch.setattr(gmail_client, "send_reply",
                        lambda *args, **kwargs: sent.append(args))

    with database.get_conn() as conn:
        eid = _seed_email(conn)
        conn.execute("INSERT INTO drafts (email_id, body) VALUES (?, ?)",
                     (eid, "Draft body text"))

    res = client.post(f"/emails/{eid}/approve", json={"approved_by": "staff"})
    assert res.status_code == 200

    with database.get_conn() as conn:
        row = conn.execute("SELECT status FROM emails WHERE id = ?", (eid,)).fetchone()
        draft = conn.execute("SELECT approved_by, sent_at FROM drafts WHERE email_id = ?",
                             (eid,)).fetchone()
    assert row["status"] == "sent"
    assert draft["approved_by"] == "staff"
    assert draft["sent_at"] != ""
    assert len(sent) == 1


def test_approve_already_sent_email(client, temp_db):
    with database.get_conn() as conn:
        eid = _seed_email(conn, status="sent")
        conn.execute("INSERT INTO drafts (email_id, body) VALUES (?, ?)", (eid, "text"))

    res = client.post(f"/emails/{eid}/approve", json={"approved_by": "staff"})
    assert res.status_code == 400


def test_reject_email(client, temp_db):
    with database.get_conn() as conn:
        eid = _seed_email(conn)

    res = client.post(f"/emails/{eid}/reject", json={"note": "not relevant"})
    assert res.status_code == 200

    with database.get_conn() as conn:
        row = conn.execute("SELECT status FROM emails WHERE id = ?", (eid,)).fetchone()
    assert row["status"] == "rejected"


def test_reject_email_not_found(client):
    res = client.post("/emails/9999/reject", json={})
    assert res.status_code == 404
