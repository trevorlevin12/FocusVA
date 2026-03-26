# Gmail OAuth, History Crawl & Learning Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace service-account Gmail auth with per-user OAuth2, seed the RAG index from historical sent emails, and auto-learn from every approved reply.

**Architecture:** A new `auth.py` module owns OAuth2 token lifecycle; `crawl.py` handles historical import as an async background task; `rag.py` gains `index_pair()` for upserts; `gmail_client.py`, `main.py`, and the static dashboard are updated to wire everything together.

**Tech Stack:** Python 3.12 / FastAPI / google-auth-oauthlib 1.2.1 / ChromaDB / OpenAI embeddings / Vanilla JS

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config.py` | Modify | Swap GMAIL_SERVICE_ACCOUNT_PATH → 3 new OAuth vars |
| `.env.example` | Modify | Mirror config.py change |
| `auth.py` | **Create** | OAuth2 Flow, token lifecycle, CSRF state |
| `gmail_client.py` | Modify | Use auth.is_authenticated() / auth.get_credentials() |
| `rag.py` | Modify | Add index_pair() with get_or_create_collection + upsert |
| `crawl.py` | **Create** | Historical Sent crawl, async coroutine, progress tracking |
| `main.py` | Modify | Auth/crawl endpoints, poll gate, approve learning |
| `static/index.html` | Modify | Auth banner div, Settings nav + settingsPanel |
| `static/style.css` | Modify | Auth banner, Settings panel, crawl progress styles |
| `static/app.js` | Modify | checkAuthStatus(), showSettings(), startCrawl(), showAdmin() fix |
| `tests/test_auth.py` | **Create** | Auth module unit tests |
| `tests/test_rag.py` | **Create** | index_pair unit tests |
| `tests/test_crawl.py` | **Create** | crawl module unit tests |
| `tests/test_gmail_client.py` | Modify | Update to match new auth gate |
| `tests/test_api.py` | Modify | Tests for new endpoints + approve learning |

---

## Task 1: Update config.py and .env.example

**Files:**
- Modify: `config.py`
- Modify: `.env.example`

- [ ] **Step 1: Replace config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
GMAIL_CREDENTIALS_PATH: str = os.getenv("GMAIL_CREDENTIALS_PATH", "")
GMAIL_TOKEN_PATH: str = os.getenv("GMAIL_TOKEN_PATH", "./token.json")
GMAIL_REDIRECT_URI: str = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8000/auth/callback")
TARGET_EMAIL: str = os.getenv("TARGET_EMAIL", "inbox@focusgraphics.com")
POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
DB_PATH: str = os.getenv("DB_PATH", "./focusva.db")
```

- [ ] **Step 2: Replace .env.example**

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GMAIL_CREDENTIALS_PATH=./credentials.json
GMAIL_TOKEN_PATH=./token.json
GMAIL_REDIRECT_URI=http://localhost:8000/auth/callback
TARGET_EMAIL=inbox@focusgraphics.com
POLL_INTERVAL_SECONDS=120
DB_PATH=./focusva.db
```

- [ ] **Step 3: Run tests — note expected partial failure**

```
pytest tests/ -v
```

Expected: Most tests pass. `tests/test_gmail_client.py` will **FAIL** at this step because `gmail_client.py` still reads `config.GMAIL_SERVICE_ACCOUNT_PATH` which no longer exists in config. This is intentional — Task 3 fixes `gmail_client.py`. All other tests should pass.

- [ ] **Step 4: Commit**

```bash
git add config.py .env.example
git commit -m "feat: swap service-account config for OAuth vars"
```

---

## Task 2: Create auth.py

**Files:**
- Create: `auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing tests — create tests/test_auth.py**

```python
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
```

- [ ] **Step 2: Run — expect FAIL (ImportError: no module named auth)**

```
pytest tests/test_auth.py -v
```

Expected: All fail (ImportError or AttributeError)

- [ ] **Step 3: Create auth.py**

```python
"""OAuth2 authentication for Gmail (Web Application flow)."""

import json
import secrets
import time
from pathlib import Path

import config

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

_pending_states: dict[str, float] = {}


def get_oauth_flow():
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_secrets_file(
        config.GMAIL_CREDENTIALS_PATH,
        scopes=SCOPES,
        redirect_uri=config.GMAIL_REDIRECT_URI,
    )


def is_authenticated() -> bool:
    """True if a valid (or refreshable) token exists on disk."""
    if not config.GMAIL_CREDENTIALS_PATH:
        return False
    if not Path(config.GMAIL_TOKEN_PATH).exists():
        return False
    try:
        creds = _load_credentials()
        return creds.valid or (creds.expired and creds.refresh_token is not None)
    except Exception:
        return False


def get_credentials():
    """Load token, refresh if expired, return google.oauth2.credentials.Credentials."""
    from google.auth.transport.requests import Request
    creds = _load_credentials()
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds)
    return creds


def get_auth_url() -> str:
    """Generate Google consent URL. Stores CSRF state with 5-minute TTL."""
    global _pending_states
    now = time.time()
    _pending_states = {s: t for s, t in _pending_states.items() if now - t < 300}
    state = secrets.token_hex(16)
    _pending_states[state] = now
    flow = get_oauth_flow()
    url, _ = flow.authorization_url(
        state=state,
        access_type="offline",
        prompt="consent",
    )
    return url


def exchange_code(code: str, state: str) -> None:
    """Validate CSRF state, exchange auth code for tokens, save to disk."""
    now = time.time()
    if state not in _pending_states or now - _pending_states[state] > 300:
        raise ValueError("Invalid or expired OAuth state. Please try signing in again.")
    del _pending_states[state]
    flow = get_oauth_flow()
    flow.fetch_token(code=code)
    _save_credentials(flow.credentials)


def _load_credentials():
    from google.oauth2.credentials import Credentials
    with open(config.GMAIL_TOKEN_PATH) as f:
        data = json.load(f)
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )


def _save_credentials(creds) -> None:
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }
    with open(config.GMAIL_TOKEN_PATH, "w") as f:
        json.dump(data, f)
```

- [ ] **Step 4: Run — expect PASS**

```
pytest tests/test_auth.py -v
```

Expected: All 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add auth.py tests/test_auth.py
git commit -m "feat: add OAuth2 auth module with CSRF state management"
```

---

## Task 3: Update gmail_client.py for OAuth

**Files:**
- Modify: `gmail_client.py`
- Modify: `tests/test_gmail_client.py`

- [ ] **Step 1: Update tests/test_gmail_client.py**

The existing tests patch `config.GMAIL_CREDENTIALS_PATH = ""`. After the change, that causes `auth.is_authenticated()` to return `False`, which triggers mock mode. The tests already use the correct attribute name — just add an explicit import of `auth` and note the new behavior in comments.

Replace the file:

```python
# tests/test_gmail_client.py
import json
from unittest.mock import patch
import pytest
import gmail_client
import config
import auth


def test_mock_mode_loads_from_json(tmp_path, monkeypatch):
    """When not authenticated (GMAIL_CREDENTIALS_PATH empty), reads mock_emails.json."""
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "")
    mock_data = [{
        "gmail_message_id": "test_001",
        "thread_id": "t1",
        "sender": "a@b.com",
        "subject": "Test",
        "body": "Hello",
        "received_at": "2026-03-25T10:00:00Z",
    }]
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
```

- [ ] **Step 2: Run — expect FAIL**

```
pytest tests/test_gmail_client.py -v
```

Expected: All 3 fail (gmail_client still checks GMAIL_SERVICE_ACCOUNT_PATH which no longer exists in config).

- [ ] **Step 3: Replace gmail_client.py**

```python
import base64
import json
from email.mime.text import MIMEText
import config

MOCK_EMAILS_PATH = "mock_emails.json"


def fetch_new_emails() -> list[dict]:
    """Returns list of email dicts. Uses mock_emails.json if not authenticated."""
    import auth
    if not auth.is_authenticated():
        return _load_mock_emails()
    return _fetch_from_gmail()


def send_reply(thread_id: str, to: str, subject: str, body: str) -> None:
    """Send an in-thread reply. Prints to stdout in mock mode."""
    import auth
    if not auth.is_authenticated():
        print(f"[MOCK] Would send to {to} | thread={thread_id} | body={body[:80]}...")
        return
    _send_via_gmail(thread_id, to, subject, body)


# --- Private helpers ---

def _load_mock_emails() -> list[dict]:
    try:
        with open(MOCK_EMAILS_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _get_gmail_service():
    import auth
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=auth.get_credentials())


def _fetch_from_gmail() -> list[dict]:
    service = _get_gmail_service()
    results = service.users().messages().list(
        userId="me", q="is:unread in:inbox"
    ).execute()
    messages = results.get("messages", [])
    emails = []
    for msg in messages:
        msg_data = service.users().messages().get(
            userId="me", id=msg["id"], format="full"
        ).execute()
        headers = {h["name"]: h["value"] for h in msg_data["payload"]["headers"]}
        body = _extract_body(msg_data["payload"])
        emails.append({
            "gmail_message_id": msg_data["id"],
            "thread_id": msg_data["threadId"],
            "sender": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "body": body,
            "received_at": headers.get("Date", ""),
        })
        service.users().messages().modify(
            userId="me", id=msg["id"],
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
    return emails


def _extract_body(payload: dict) -> str:
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            part_data = part.get("body", {}).get("data", "")
            if part_data:
                return base64.urlsafe_b64decode(part_data).decode("utf-8", errors="replace")
    return ""


def _send_via_gmail(thread_id: str, to: str, subject: str, body: str) -> None:
    service = _get_gmail_service()
    msg = MIMEText(body)
    msg["To"] = to
    msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(
        userId="me",
        body={"raw": raw, "threadId": thread_id}
    ).execute()
```

- [ ] **Step 4: Run gmail_client tests — expect PASS**

```
pytest tests/test_gmail_client.py -v
```

- [ ] **Step 5: Run full suite — expect PASS**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add gmail_client.py tests/test_gmail_client.py
git commit -m "feat: swap gmail_client auth from service account to OAuth"
```

---

## Task 4: Add index_pair to rag.py

**Files:**
- Modify: `rag.py`
- Create: `tests/test_rag.py`

- [ ] **Step 1: Write failing tests — create tests/test_rag.py**

```python
# tests/test_rag.py
import hashlib
from unittest.mock import MagicMock, patch
import pytest
import config
import rag


def test_index_pair_noop_when_openai_key_missing(monkeypatch):
    """index_pair silently no-ops when OPENAI_API_KEY is not set."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    # Must not raise
    rag.index_pair("Some customer inquiry", "Our response")


def test_index_pair_calls_upsert_with_sha256_id(monkeypatch, tmp_path):
    """index_pair embeds and upserts with deterministic SHA-256 ID."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "fake-key")
    mock_embedding = [0.1] * 1536
    mock_openai = MagicMock()
    mock_openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=mock_embedding)]
    )
    mock_collection = MagicMock()
    mock_chroma = MagicMock()
    mock_chroma.get_or_create_collection.return_value = mock_collection
    with patch("rag.CHROMA_PATH", str(tmp_path / "chroma")), \
         patch("openai.OpenAI", return_value=mock_openai), \
         patch("chromadb.PersistentClient", return_value=mock_chroma):
        rag.index_pair("Hello inquiry", "Hello response")
    expected_id = hashlib.sha256("Hello inquiry".encode()).hexdigest()[:16]
    mock_collection.upsert.assert_called_once_with(
        ids=[expected_id],
        embeddings=[mock_embedding],
        metadatas=[{"inquiry": "Hello inquiry", "response": "Hello response"}],
    )


def test_index_pair_truncates_long_texts(monkeypatch, tmp_path):
    """index_pair truncates inquiry and response to 2000 chars in metadata."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "fake-key")
    long_inquiry = "A" * 3000
    long_response = "B" * 3000
    mock_openai = MagicMock()
    mock_openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.0] * 1536)]
    )
    mock_collection = MagicMock()
    mock_chroma = MagicMock()
    mock_chroma.get_or_create_collection.return_value = mock_collection
    with patch("rag.CHROMA_PATH", str(tmp_path / "chroma")), \
         patch("openai.OpenAI", return_value=mock_openai), \
         patch("chromadb.PersistentClient", return_value=mock_chroma):
        rag.index_pair(long_inquiry, long_response)
    metadata = mock_collection.upsert.call_args.kwargs["metadatas"][0]
    assert len(metadata["inquiry"]) == 2000
    assert len(metadata["response"]) == 2000


def test_index_pair_noop_on_exception(monkeypatch):
    """index_pair catches exceptions and does not propagate them."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "fake-key")
    mock_openai = MagicMock()
    mock_openai.embeddings.create.side_effect = RuntimeError("API error")
    with patch("openai.OpenAI", return_value=mock_openai):
        # Must not raise
        rag.index_pair("inquiry", "response")
```

- [ ] **Step 2: Run — expect FAIL (AttributeError: module 'rag' has no attribute 'index_pair')**

```
pytest tests/test_rag.py -v
```

- [ ] **Step 3: Add index_pair to rag.py**

Append after the existing `retrieve_examples` function (keep all existing code intact):

```python
import hashlib
import logging

_rag_logger = logging.getLogger(__name__)


def index_pair(inquiry: str, response: str) -> None:
    """Embed an inquiry/response pair and upsert into ChromaDB."""
    if not config.OPENAI_API_KEY:
        _rag_logger.warning("[rag] OPENAI_API_KEY not set — skipping index_pair")
        return
    try:
        from openai import OpenAI
        import chromadb

        openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        embedding_response = openai_client.embeddings.create(
            model=EMBED_MODEL, input=[inquiry]
        )
        embedding = embedding_response.data[0].embedding

        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_or_create_collection(COLLECTION_NAME)

        doc_id = hashlib.sha256(inquiry.encode()).hexdigest()[:16]
        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            metadatas=[{"inquiry": inquiry[:2000], "response": response[:2000]}],
        )
    except Exception as e:
        _rag_logger.warning(f"[rag] index_pair failed: {e}")
```

- [ ] **Step 4: Run — expect PASS**

```
pytest tests/test_rag.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 5: Run full suite — expect PASS**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add rag.py tests/test_rag.py
git commit -m "feat: add index_pair to rag.py for continuous learning"
```

---

## Task 5: Create crawl.py

**Files:**
- Create: `crawl.py`
- Create: `tests/test_crawl.py`

- [ ] **Step 1: Write failing tests — create tests/test_crawl.py**

```python
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
```

- [ ] **Step 2: Run — expect FAIL (ImportError: no module named crawl)**

```
pytest tests/test_crawl.py -v
```

- [ ] **Step 3: Create crawl.py**

```python
"""
Historical Gmail Sent folder crawler.

Queries Sent folder from a cutoff date, finds each reply's corresponding
customer inquiry in the thread, and indexes the pair via rag.index_pair.
"""

import asyncio
import base64
import logging
from typing import Optional

import config
import rag

logger = logging.getLogger(__name__)

_crawl_jobs: dict[str, dict] = {}


def get_crawl_status(status_key: str) -> dict:
    """Return crawl progress. done:True if key not found (stops frontend polling)."""
    if status_key not in _crawl_jobs:
        return {"total": 0, "indexed": 0, "skipped": 0, "errors": 0, "done": True}
    return dict(_crawl_jobs[status_key])


async def crawl_sent_emails(since_date: str, status_key: str) -> None:
    """
    Async coroutine. Queries Gmail Sent from since_date (YYYY-MM-DD).
    Pairs each sent reply with the prior customer inquiry in its thread.
    Indexes found pairs into ChromaDB via rag.index_pair (run in executor).
    """
    _crawl_jobs[status_key] = {
        "total": 0, "indexed": 0, "skipped": 0, "errors": 0, "done": False
    }
    job = _crawl_jobs[status_key]

    try:
        service = _get_gmail_service()
        gmail_date = since_date.replace("-", "/")
        messages = _list_all_messages(service, f"in:sent after:{gmail_date}")
        job["total"] = len(messages)
        loop = asyncio.get_running_loop()

        for msg in messages:
            await asyncio.sleep(0)  # yield to event loop between iterations
            try:
                sent_msg = service.users().messages().get(
                    userId="me", id=msg["id"], format="full"
                ).execute()
                sent_body = _extract_body(sent_msg["payload"])
                sent_date = int(sent_msg["internalDate"])

                thread = service.users().threads().get(
                    userId="me", id=sent_msg["threadId"], format="full"
                ).execute()

                inquiry_body = _find_inquiry(thread["messages"], sent_date)
                if inquiry_body is None:
                    job["skipped"] += 1
                    continue

                await loop.run_in_executor(None, rag.index_pair, inquiry_body, sent_body)
                job["indexed"] += 1

            except Exception as e:
                logger.warning(f"[crawl] Error on message {msg['id']}: {e}")
                job["errors"] += 1

    except Exception as e:
        logger.error(f"[crawl] Fatal error: {e}")
        job["errors"] += 1
    finally:
        job["done"] = True


def _list_all_messages(service, query: str) -> list[dict]:
    """Fetch all message stubs matching the query, handling pagination."""
    messages: list[dict] = []
    page_token = None
    while True:
        kwargs: dict = {"userId": "me", "q": query}
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.users().messages().list(**kwargs).execute()
        messages.extend(result.get("messages", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return messages


def _get_gmail_service():
    import auth
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=auth.get_credentials())


def _find_inquiry(messages: list, sent_internal_date: int) -> Optional[str]:
    """
    Find the most recent non-TARGET_EMAIL message before sent_internal_date.
    Uses internalDate (int ms) for comparison. Returns body text or None.
    """
    target = config.TARGET_EMAIL.lower()
    candidates = []
    for msg in messages:
        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        from_header = headers.get("from", "").lower()
        msg_date = int(msg["internalDate"])
        if target not in from_header and msg_date < sent_internal_date:
            candidates.append((msg_date, msg))
    if not candidates:
        return None
    _, best_msg = max(candidates, key=lambda x: x[0])
    return _extract_body(best_msg["payload"])


def _extract_body(payload: dict) -> str:
    """Extract text/plain body from a Gmail message payload."""
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            part_data = part.get("body", {}).get("data", "")
            if part_data:
                return base64.urlsafe_b64decode(part_data).decode("utf-8", errors="replace")
    return ""
```

- [ ] **Step 4: Run — expect PASS**

```
pytest tests/test_crawl.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 5: Run full suite — expect PASS**

```
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add crawl.py tests/test_crawl.py
git commit -m "feat: add crawl.py for historical Gmail Sent import"
```

---

## Task 6: Update main.py

**Files:**
- Modify: `main.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add new tests to tests/test_api.py**

Append these tests after the last existing test in the file:

```python
# ── Auth endpoints ───────────────────────────────────────────

def test_auth_status_not_connected(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "is_authenticated", lambda: False)
    res = client.get("/auth/status")
    assert res.status_code == 200
    assert res.json() == {"connected": False}


def test_auth_status_connected(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "is_authenticated", lambda: True)
    res = client.get("/auth/status")
    assert res.json() == {"connected": True}


def test_auth_login_redirects(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "get_auth_url",
                        lambda: "https://accounts.google.com/consent?state=abc")
    res = client.get("/auth/login", follow_redirects=False)
    assert res.status_code == 302
    assert "accounts.google.com" in res.headers["location"]


def test_auth_callback_success_redirects_to_root(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "exchange_code", lambda code, state: None)
    res = client.get("/auth/callback?code=mycode&state=mystate", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/"


def test_auth_callback_failure_redirects_with_error(client, monkeypatch):
    import auth
    def bad_exchange(code, state):
        raise ValueError("bad state")
    monkeypatch.setattr(auth, "exchange_code", bad_exchange)
    res = client.get("/auth/callback?code=x&state=bad", follow_redirects=False)
    assert res.status_code == 302
    assert "auth_error=" in res.headers["location"]


# ── Crawl endpoints ──────────────────────────────────────────

def test_crawl_status_unknown_key(client):
    res = client.get("/admin/crawl-status?key=unknown-key-xyz")
    assert res.status_code == 200
    data = res.json()
    assert data["done"] is True
    assert data["total"] == 0


def test_crawl_history_returns_status_key(client, monkeypatch):
    import crawl
    async def fake_crawl(since_date, status_key):
        pass
    monkeypatch.setattr(crawl, "crawl_sent_emails", fake_crawl)
    res = client.post("/admin/crawl-history", json={"since_date": "2024-01-01"})
    assert res.status_code == 200
    assert "status_key" in res.json()


# ── Poll gate ────────────────────────────────────────────────

def test_poll_returns_400_when_not_authenticated(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "is_authenticated", lambda: False)
    res = client.post("/poll")
    assert res.status_code == 400
    assert "not connected" in res.json()["detail"].lower()


# ── Approve with learning ────────────────────────────────────

def test_approve_calls_index_pair(client, temp_db, monkeypatch):
    import gmail_client
    import rag
    monkeypatch.setattr(gmail_client, "send_reply", lambda *a, **k: None)
    indexed = []
    monkeypatch.setattr(rag, "index_pair", lambda inquiry, response: indexed.append((inquiry, response)))

    with database.get_conn() as conn:
        eid = _seed_email(conn)
        conn.execute("INSERT INTO drafts (email_id, body) VALUES (?, ?)", (eid, "Approved draft"))

    res = client.post(f"/emails/{eid}/approve", json={"approved_by": "staff"})
    assert res.status_code == 200
    assert len(indexed) == 1
    assert indexed[0][0] == "I need 50 banners"  # seeded email body
    assert indexed[0][1] == "Approved draft"
```

Also update the existing `test_approve_email` to mock `rag.index_pair`. Find this function in `tests/test_api.py` and replace it in full:

```python
def test_approve_email(client, temp_db, monkeypatch):
    import gmail_client
    import rag
    sent = []
    monkeypatch.setattr(gmail_client, "send_reply",
                        lambda *args, **kwargs: sent.append(args))
    monkeypatch.setattr(rag, "index_pair", lambda *args: None)

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
```

- [ ] **Step 2: Run new tests — expect FAIL**

```
pytest tests/test_api.py -v -k "auth or crawl or poll or index_pair"
```

Expected: All new tests fail (endpoints not defined).

- [ ] **Step 3: Update main.py imports**

Add these imports at the top of `main.py` (after existing imports):

```python
import urllib.parse
import uuid
import auth
import crawl
import rag
```

- [ ] **Step 4: Update _poll_loop in main.py**

Replace the existing `_poll_loop` function:

```python
async def _poll_loop() -> None:
    """Background loop: sleep first, then poll, so tests complete before first cycle."""
    while True:
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
        if not auth.is_authenticated():
            continue
        try:
            emails = gmail_client.fetch_new_emails()
            for email in emails:
                with database.get_conn() as conn:
                    exists = conn.execute(
                        "SELECT id FROM emails WHERE gmail_message_id = ?",
                        (email["gmail_message_id"],),
                    ).fetchone()
                if not exists:
                    pipeline.process_email(email)
        except Exception as exc:
            print(f"[poller error] {exc}")
```

- [ ] **Step 5: Update poll_now in main.py**

Replace the existing `poll_now` endpoint:

```python
@app.post("/poll")
async def poll_now():
    """Trigger an immediate Gmail poll outside the background schedule."""
    if not auth.is_authenticated():
        raise HTTPException(status_code=400, detail="Gmail not connected")
    emails = gmail_client.fetch_new_emails()
    new_count = 0
    for email in emails:
        with database.get_conn() as conn:
            exists = conn.execute(
                "SELECT id FROM emails WHERE gmail_message_id = ?",
                (email["gmail_message_id"],),
            ).fetchone()
        if not exists:
            pipeline.process_email(email)
            new_count += 1
    return {"fetched": len(emails), "new": new_count}
```

- [ ] **Step 6: Update approve_email in main.py**

Add `rag.index_pair(email["body"], draft["body"])` after the DB update block, just before `return {"ok": True}`:

```python
    rag.index_pair(email["body"], draft["body"])
    return {"ok": True}
```

- [ ] **Step 7: Add new endpoints to main.py**

Add these before the final `app.mount(...)` line:

```python
# ── Auth ────────────────────────────────────────────────────

@app.get("/auth/status")
def auth_status():
    return {"connected": auth.is_authenticated()}


@app.get("/auth/login")
def auth_login():
    from fastapi.responses import RedirectResponse
    url = auth.get_auth_url()
    return RedirectResponse(url=url, status_code=302)


@app.get("/auth/callback")
def auth_callback(code: str = "", state: str = ""):
    from fastapi.responses import RedirectResponse
    try:
        auth.exchange_code(code, state)
        return RedirectResponse(url="/", status_code=302)
    except Exception as e:
        error_msg = urllib.parse.quote(str(e), safe="")
        return RedirectResponse(url=f"/?auth_error={error_msg}", status_code=302)


# ── Crawl ────────────────────────────────────────────────────

class CrawlRequest(BaseModel):
    since_date: str  # "YYYY-MM-DD"


@app.post("/admin/crawl-history")
async def start_crawl(req: CrawlRequest):
    status_key = str(uuid.uuid4())
    asyncio.create_task(crawl.crawl_sent_emails(req.since_date, status_key))
    return {"status_key": status_key}


@app.get("/admin/crawl-status")
def crawl_status(key: str = ""):
    return crawl.get_crawl_status(key)
```

- [ ] **Step 8: Run full test suite — expect PASS**

```
pytest tests/ -v
```

Expected: All tests pass including the new ones.

- [ ] **Step 9: Commit**

```bash
git add main.py tests/test_api.py
git commit -m "feat: add auth/crawl endpoints, poll gate, and approve learning"
```

---

## Task 7: Update static files

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`

No automated tests — visual verification in browser.

- [ ] **Step 1: Update static/index.html**

Add auth banner div immediately after `<body>` (before `<div class="layout">`):

```html
<div id="authBanner" style="display:none;" class="auth-banner">
  <span id="authBannerMsg">Gmail not connected</span>
  <a href="/auth/login" class="auth-banner-link">Connect Gmail</a>
</div>
```

Add Settings button to the sidebar footer section, after the Job Types button and before `btn-refresh`:

```html
<button class="tab tab-admin" data-tab="settings" onclick="showSettings()">
  <span class="tab-icon">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
  </span>
  <span>Settings</span>
</button>
```

Add settingsPanel div inside `.layout`, after the `adminPanel` div:

```html
<div class="settings-panel" id="settingsPanel" style="display:none;">
  <div class="settings-header">
    <h2>Settings</h2>
  </div>
  <div class="settings-section">
    <div class="settings-label">Gmail Account</div>
    <div id="gmailStatus" class="settings-status">Checking...</div>
  </div>
  <div class="settings-section">
    <div class="settings-label">Import Email History</div>
    <p class="settings-hint">Import past sent emails to seed the AI with your response style.</p>
    <div class="settings-row">
      <label for="crawlSince">Import emails sent since:</label>
      <input type="date" id="crawlSince" />
    </div>
    <button class="btn btn-approve" onclick="startCrawl()" id="crawlBtn">Import History</button>
    <div id="crawlProgress" style="display:none;" class="crawl-progress">
      <div id="crawlProgressText">Starting...</div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Append to static/style.css**

```css
/* ── Auth Banner ─────────────────────────────────────────── */
.auth-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  background: rgba(244,112,112,0.12);
  border-bottom: 1px solid rgba(244,112,112,0.25);
  padding: 10px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: var(--danger);
}
.auth-banner.error { background: rgba(244,112,112,0.20); }
.auth-banner-link {
  color: var(--danger);
  font-weight: 600;
  text-decoration: underline;
  cursor: pointer;
}

/* ── Settings Panel ──────────────────────────────────────── */
.settings-panel {
  grid-column: 2 / 4;
  background: var(--bg);
  overflow-y: auto;
  padding: 40px 48px;
}
.settings-header {
  margin-bottom: 32px;
}
.settings-header h2 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: -0.025em;
}
.settings-section {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 16px;
}
.settings-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 8px;
}
.settings-hint {
  font-size: 12.5px;
  color: var(--text-3);
  margin-bottom: 16px;
  line-height: 1.6;
}
.settings-status { font-size: 13px; color: var(--text-2); }
.settings-status.connected { color: var(--success); }
.settings-status.disconnected { color: var(--danger); }
.settings-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.settings-row label { font-size: 13px; color: var(--text-2); white-space: nowrap; }
.settings-row input[type="date"] {
  background: var(--surface-3);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  font-family: inherit;
  color: var(--text-1);
  outline: none;
  transition: border-color 0.15s;
}
.settings-row input[type="date"]:focus { border-color: var(--accent); }

/* ── Crawl Progress ──────────────────────────────────────── */
.crawl-progress {
  margin-top: 14px;
  background: var(--surface-3);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
}
#crawlProgressText { font-size: 13px; color: var(--text-2); }
```

- [ ] **Step 3: Update static/app.js**

Update `showAdmin()` — add one line to also hide settingsPanel:

```javascript
function showAdmin() {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[onclick="showAdmin()"]').classList.add('active');
  document.getElementById('emailList').style.display = 'none';
  document.getElementById('detailPanel').style.display = 'none';
  document.getElementById('settingsPanel').style.display = 'none';  // NEW
  document.getElementById('adminPanel').style.display = 'flex';
  loadJobTypes();
}
```

Add these new functions before the `// ── Boot` line at the bottom:

```javascript
// ── Auth ─────────────────────────────────────────────────────
async function checkAuthStatus() {
  const params = new URLSearchParams(window.location.search);
  const authError = params.get('auth_error');
  if (authError) {
    const banner = document.getElementById('authBanner');
    const msg = document.getElementById('authBannerMsg');
    banner.classList.add('error');
    banner.style.display = 'flex';
    msg.textContent = 'Gmail connection failed: ' + decodeURIComponent(authError);
    const url = new URL(window.location);
    url.searchParams.delete('auth_error');
    window.history.replaceState({}, '', url);
    return;
  }
  try {
    const status = await api('/auth/status');
    const banner = document.getElementById('authBanner');
    banner.style.display = status.connected ? 'none' : 'flex';
  } catch (_) { /* non-fatal */ }
}

// ── Settings ─────────────────────────────────────────────────
function showSettings() {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[onclick="showSettings()"]').classList.add('active');
  document.getElementById('emailList').style.display = 'none';
  document.getElementById('detailPanel').style.display = 'none';
  document.getElementById('adminPanel').style.display = 'none';
  document.getElementById('settingsPanel').style.display = 'block';
  loadSettingsStatus();
}

function hideSettings() {
  document.getElementById('settingsPanel').style.display = 'none';
}

async function loadSettingsStatus() {
  const statusEl = document.getElementById('gmailStatus');
  try {
    const res = await api('/auth/status');
    if (res.connected) {
      statusEl.textContent = 'Connected';
      statusEl.className = 'settings-status connected';
    } else {
      statusEl.innerHTML = 'Not connected — <a href="/auth/login">Connect Gmail</a>';
      statusEl.className = 'settings-status disconnected';
    }
  } catch (_) {
    statusEl.textContent = 'Unable to check status';
    statusEl.className = 'settings-status';
  }
}

let _crawlPollInterval = null;

async function startCrawl() {
  const since = document.getElementById('crawlSince').value;
  if (!since) { showToast('Please select a date first'); return; }
  const btn = document.getElementById('crawlBtn');
  btn.disabled = true;
  const progress = document.getElementById('crawlProgress');
  const progressText = document.getElementById('crawlProgressText');
  progress.style.display = 'block';
  progressText.textContent = 'Starting import...';
  try {
    const res = await api('/admin/crawl-history', {
      method: 'POST',
      body: JSON.stringify({ since_date: since }),
    });
    const key = res.status_key;
    if (_crawlPollInterval) clearInterval(_crawlPollInterval);
    _crawlPollInterval = setInterval(async () => {
      try {
        const status = await api(`/admin/crawl-status?key=${key}`);
        progressText.textContent =
          `${status.indexed} of ${status.total} indexed, ${status.skipped} skipped, ${status.errors} errors`;
        if (status.done) {
          clearInterval(_crawlPollInterval);
          _crawlPollInterval = null;
          btn.disabled = false;
          showToast('Import complete');
        }
      } catch (_) {
        clearInterval(_crawlPollInterval);
        btn.disabled = false;
      }
    }, 2000);
  } catch (err) {
    showToast('Error: ' + err.message);
    btn.disabled = false;
    progress.style.display = 'none';
  }
}
```

Update the boot section (replace the last line):

```javascript
// ── Boot ─────────────────────────────────────────────────────
checkAuthStatus();
loadEmails(currentFilter);
```

- [ ] **Step 4: Run full test suite — expect PASS**

```
pytest tests/ -v
```

Expected: All tests pass. (Static file changes have no automated tests.)

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat: add Settings tab, auth banner, and crawl progress UI"
```

---

## Final: Smoke test checklist

- [ ] Start server: `uvicorn main:app --reload`
- [ ] Visit `http://localhost:8000` — auth banner appears ("Gmail not connected")
- [ ] Click **Settings** tab — shows "Not connected" status and date picker
- [ ] Click **Connect Gmail** — redirects to Google consent screen (requires `credentials.json`)
- [ ] After OAuth completes — banner disappears, Settings shows "Connected"
- [ ] Pick a date and click **Import History** — progress bar appears and counts up
- [ ] Approve an email via dashboard — server logs should show index_pair call (no error if OPENAI_API_KEY set)
- [ ] Run full test suite: `pytest tests/ -v` — all pass
