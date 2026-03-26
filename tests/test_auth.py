# tests/test_auth.py
import json
import time
from unittest.mock import MagicMock, patch
import pytest
import config
import auth


def test_is_authenticated_false_when_no_credentials_path(monkeypatch):
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "")
    assert auth.is_authenticated() is False


def test_is_authenticated_false_when_token_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "fake_credentials.json")
    monkeypatch.setattr(config, "GMAIL_TOKEN_PATH", str(tmp_path / "no_token.json"))
    assert auth.is_authenticated() is False


def test_is_authenticated_true_when_valid_token_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "fake_credentials.json")
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({
        "token": "tok", "refresh_token": "ref",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid", "client_secret": "csec",
        "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
    }))
    monkeypatch.setattr(config, "GMAIL_TOKEN_PATH", str(token_path))
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False
    with patch("auth._load_credentials", return_value=mock_creds):
        assert auth.is_authenticated() is True


def test_get_auth_url_returns_url_and_stores_state(monkeypatch):
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "fake.json")
    monkeypatch.setattr(config, "GMAIL_REDIRECT_URI", "http://localhost:8000/auth/callback")
    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?state=abc", "abc")
    auth._pending_states.clear()
    with patch("auth.get_oauth_flow", return_value=mock_flow):
        url = auth.get_auth_url()
    assert url.startswith("https://accounts.google.com")
    assert len(auth._pending_states) == 1


def test_exchange_code_raises_for_unknown_state():
    auth._pending_states.clear()
    with pytest.raises(ValueError, match="Invalid or expired"):
        auth.exchange_code("some_code", "unknown_state")


def test_exchange_code_raises_for_expired_state():
    auth._pending_states["old_state"] = time.time() - 400  # 6+ min ago
    with pytest.raises(ValueError, match="Invalid or expired"):
        auth.exchange_code("some_code", "old_state")
    auth._pending_states.pop("old_state", None)


def test_exchange_code_removes_state_on_success(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "fake.json")
    monkeypatch.setattr(config, "GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setattr(config, "GMAIL_REDIRECT_URI", "http://localhost:8000/auth/callback")
    auth._pending_states.clear()
    auth._pending_states["valid_state"] = time.time()
    mock_flow = MagicMock()
    mock_flow.credentials.token = "tok"
    mock_flow.credentials.refresh_token = "ref"
    mock_flow.credentials.token_uri = "https://oauth2.googleapis.com/token"
    mock_flow.credentials.client_id = "cid"
    mock_flow.credentials.client_secret = "csec"
    mock_flow.credentials.scopes = ["https://www.googleapis.com/auth/gmail.modify"]
    with patch("auth.get_oauth_flow", return_value=mock_flow):
        auth.exchange_code("code123", "valid_state")
    assert "valid_state" not in auth._pending_states
    assert (tmp_path / "token.json").exists()
