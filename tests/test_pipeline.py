# tests/test_pipeline.py
import json
from unittest.mock import MagicMock, patch
import database
import pipeline


def _mock_claude(return_value: str):
    """Helper: patches pipeline._claude to return a fixed string."""
    mock = MagicMock(return_value=return_value)
    return patch("pipeline._claude", mock)


def test_classify_returns_known_label(temp_db):
    with _mock_claude("quote_request"):
        result = pipeline.classify_email("Quote needed", "I need 100 business cards")
    assert result == "quote_request"


def test_classify_falls_back_to_general_question_on_unknown(temp_db):
    with _mock_claude("something completely unknown"):
        result = pipeline.classify_email("Hi", "Random text")
    assert result == "general_question"


def test_extract_returns_dict(temp_db):
    mock_json = '{"job_type": "banner", "quantity": 50}'
    with _mock_claude(mock_json):
        result = pipeline.extract_job_data("I need 50 banners", "quote_request")
    assert result == {"job_type": "banner", "quantity": 50}


def test_extract_handles_invalid_json(temp_db):
    with _mock_claude("Sorry, I cannot extract that."):
        result = pipeline.extract_job_data("Vague email", "general_question")
    assert result == {}


def test_draft_returns_string_for_actionable_labels(temp_db):
    with _mock_claude("Thanks for reaching out! Could you confirm the size?"):
        result = pipeline.draft_response("I need decals", {"job_type": "decals"}, "quote_request")
    assert result == "Thanks for reaching out! Could you confirm the size?"


def test_draft_returns_none_for_vendor_spam(temp_db):
    result = pipeline.draft_response("Buy our vinyl!", {}, "vendor_spam")
    assert result is None


def test_draft_returns_none_for_bid_invite(temp_db):
    result = pipeline.draft_response("Please bid on this", {}, "bid_invite")
    assert result is None


def test_process_email_writes_to_db(temp_db):
    email = {
        "gmail_message_id": "test_001",
        "thread_id": "thread_001",
        "sender": "client@example.com",
        "subject": "Quote for banners",
        "body": "I need 50 banners, 4x8 ft",
        "received_at": "2026-03-25T10:00:00Z",
    }
    call_count = {"n": 0}
    responses = ["quote_request", '{"job_type": "banner", "quantity": 50}', "none", "Thanks! What material?"]

    def fake_claude(prompt):
        resp = responses[call_count["n"]]
        call_count["n"] += 1
        return resp

    with patch("pipeline._claude", side_effect=fake_claude):
        email_id = pipeline.process_email(email)

    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        jd = conn.execute("SELECT data FROM job_data WHERE email_id = ?", (email_id,)).fetchone()
        draft = conn.execute("SELECT body FROM drafts WHERE email_id = ?", (email_id,)).fetchone()

    assert row["classification"] == "quote_request"
    assert row["status"] == "pending"
    assert json.loads(jd["data"])["job_type"] == "banner"
    assert draft["body"] == "Thanks! What material?"


def test_draft_response_passes_thread_to_claude(monkeypatch, temp_db):
    """draft_response() should include thread messages in the prompt sent to Claude."""
    captured = {}

    def fake_claude(prompt):
        captured["prompt"] = prompt
        return "Thanks for reaching out!"

    monkeypatch.setattr("pipeline._claude", fake_claude)

    thread = [
        {"sender": "Alice <a@b.com>", "body": "I need banners", "received_at": "2026-03-25T10:00:00"},
        {"sender": "Bob <b@c.com>", "body": "Can you share more?", "received_at": "2026-03-25T11:00:00"},
    ]
    result = pipeline.draft_response("Can you share more?", {}, "general_question", thread=thread)
    assert result == "Thanks for reaching out!"
    assert "Thread history" in captured["prompt"]
    assert "I need banners" in captured["prompt"]


def test_process_email_no_draft_for_spam(temp_db):
    email = {
        "gmail_message_id": "spam_001",
        "thread_id": "thread_spam",
        "sender": "promo@vendor.com",
        "subject": "Special offer!",
        "body": "Buy our vinyl now at 50% off!",
        "received_at": "2026-03-25T10:00:00Z",
    }
    responses = ["vendor_spam", "{}"]
    call_count = {"n": 0}

    def fake_claude(prompt):
        resp = responses[call_count["n"]]
        call_count["n"] += 1
        return resp

    with patch("pipeline._claude", side_effect=fake_claude):
        email_id = pipeline.process_email(email)

    with database.get_conn() as conn:
        draft = conn.execute("SELECT * FROM drafts WHERE email_id = ?", (email_id,)).fetchone()

    assert draft is None
