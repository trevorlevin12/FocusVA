# tests/test_crawl.py
import base64
import pytest
import config
import crawl


def test_get_crawl_status_unknown_key_returns_done():
    """Unknown key returns done:True — stops frontend setInterval polling."""
    result = crawl.get_crawl_status("nonexistent-key-xyz")
    assert result == {"total": 0, "indexed": 0, "skipped": 0, "errors": 0, "done": True}


def test_get_crawl_status_known_key():
    """Known key returns current progress dict."""
    crawl._crawl_jobs["test-key"] = {
        "total": 10, "indexed": 3, "skipped": 1, "errors": 0, "done": False
    }
    try:
        result = crawl.get_crawl_status("test-key")
        assert result["total"] == 10
        assert result["indexed"] == 3
        assert result["done"] is False
    finally:
        del crawl._crawl_jobs["test-key"]


def test_find_inquiry_returns_none_for_cold_outbound():
    """All messages from TARGET_EMAIL — no customer inquiry found."""
    messages = [{
        "internalDate": "1000",
        "payload": {
            "headers": [{"name": "From", "value": config.TARGET_EMAIL}],
            "body": {"data": ""},
            "parts": [],
        },
    }]
    result = crawl._find_inquiry(messages, sent_internal_date=2000)
    assert result is None


def test_find_inquiry_returns_most_recent_customer_message():
    """Picks the customer message with the highest internalDate before sent."""
    def encode(text):
        return base64.urlsafe_b64encode(text.encode()).decode()

    messages = [
        {
            "internalDate": "500",
            "payload": {
                "headers": [{"name": "From", "value": "customer@example.com"}],
                "body": {"data": encode("Older inquiry")},
                "parts": [],
            },
        },
        {
            "internalDate": "800",
            "payload": {
                "headers": [{"name": "From", "value": "customer@example.com"}],
                "body": {"data": encode("Newer inquiry")},
                "parts": [],
            },
        },
        {
            "internalDate": "1500",
            "payload": {
                "headers": [{"name": "From", "value": config.TARGET_EMAIL}],
                "body": {"data": encode("Our reply")},
                "parts": [],
            },
        },
    ]
    result = crawl._find_inquiry(messages, sent_internal_date=1500)
    assert result == "Newer inquiry"


def test_find_inquiry_ignores_messages_at_or_after_sent():
    """Messages with internalDate >= sent_internal_date are excluded."""
    def encode(text):
        return base64.urlsafe_b64encode(text.encode()).decode()

    messages = [{
        "internalDate": "2000",  # after sent
        "payload": {
            "headers": [{"name": "From", "value": "customer@example.com"}],
            "body": {"data": encode("Follow-up")},
            "parts": [],
        },
    }]
    result = crawl._find_inquiry(messages, sent_internal_date=1000)
    assert result is None
