# tests/test_gmail_client.py
import json
import os
import tempfile
from unittest.mock import patch, MagicMock
import gmail_client
import config
import auth


def test_mock_mode_loads_from_json(tmp_path, monkeypatch):
    """When GMAIL_CREDENTIALS_PATH is empty, reads mock_emails.json."""
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "")
    mock_data = [
        {
            "gmail_message_id": "test_001",
            "thread_id": "t1",
            "sender": "a@b.com",
            "subject": "Test",
            "body": "Hello",
            "received_at": "2026-03-25T10:00:00Z",
        }
    ]
    mock_file = tmp_path / "mock_emails.json"
    mock_file.write_text(json.dumps(mock_data))

    with patch("gmail_client.MOCK_EMAILS_PATH", str(mock_file)):
        result = gmail_client.fetch_new_emails()

    assert len(result) == 1
    assert result[0]["gmail_message_id"] == "test_001"
    assert result[0]["sender"] == "a@b.com"


def test_mock_mode_returns_empty_when_file_missing(monkeypatch):
    """When mock file doesn't exist, returns empty list without crashing."""
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "")
    with patch("gmail_client.MOCK_EMAILS_PATH", "/nonexistent/path.json"):
        result = gmail_client.fetch_new_emails()
    assert result == []


def test_send_reply_mock_mode_does_not_crash(monkeypatch, capsys):
    """In mock mode, send_reply prints a message and returns without error."""
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "")
    gmail_client.send_reply("thread1", "client@example.com", "Re: Test", "Hello!")
    captured = capsys.readouterr()
    assert "[MOCK]" in captured.out
