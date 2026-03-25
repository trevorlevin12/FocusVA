# FocusVA Email Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first AI email assistant for Focus Graphics that ingests Gmail, classifies emails, extracts job data, drafts responses, and holds all drafts for human approval via a web dashboard.

**Architecture:** FastAPI app with SQLite for persistence. A background polling loop fetches new Gmail messages every 2 minutes and runs each through a 3-step Claude pipeline (classify → extract → draft). A vanilla JS dashboard lets staff review, edit, approve, and reject drafts. Nothing is ever auto-sent.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (stdlib), Anthropic Python SDK, Google API Python Client, python-dotenv, pytest, httpx

---

## File Map

| File | Responsibility |
|---|---|
| `requirements.txt` | All dependencies pinned |
| `.env.example` | Config template |
| `config.py` | Load settings from `.env` via os.getenv |
| `database.py` | SQLite schema, `init_db()`, `get_conn()`, `set_db_path()` |
| `mock_emails.json` | 5 sample emails for dev without Gmail credentials |
| `prompts.py` | Three prompt-builder functions: classify, extract, draft |
| `pipeline.py` | Orchestrate 3 Claude calls, write results to DB |
| `gmail_client.py` | OAuth2 auth, fetch unread emails, mark read, send reply |
| `main.py` | FastAPI app, 6 endpoints, background poll loop, serve static |
| `static/index.html` | Single-page dashboard shell |
| `static/style.css` | Styles — sidebar, email list, detail panel |
| `static/app.js` | Fetch, render, approve/reject logic |
| `tests/conftest.py` | Shared `temp_db` pytest fixture |
| `tests/test_database.py` | DB init, insert, dedup |
| `tests/test_prompts.py` | Prompt output contains expected keywords |
| `tests/test_pipeline.py` | Pipeline with mocked Anthropic client |
| `tests/test_gmail_client.py` | Mock mode reads mock_emails.json |
| `tests/test_api.py` | All 6 endpoints via FastAPI TestClient |

---

## Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `config.py`
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.5
uvicorn[standard]==0.32.1
anthropic==0.40.0
google-auth==2.36.0
google-auth-oauthlib==1.2.1
google-auth-httplib2==0.2.0
google-api-python-client==2.155.0
python-dotenv==1.0.1
pytest==8.3.3
httpx==0.28.1
```

- [ ] **Step 2: Create .env.example**

```
ANTHROPIC_API_KEY=
GMAIL_CREDENTIALS_PATH=
GMAIL_TOKEN_PATH=./token.json
TARGET_EMAIL=inbox@focusgraphics.com
POLL_INTERVAL_SECONDS=120
DB_PATH=./focusva.db
```

- [ ] **Step 3: Create config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
GMAIL_CREDENTIALS_PATH: str = os.getenv("GMAIL_CREDENTIALS_PATH", "")
GMAIL_TOKEN_PATH: str = os.getenv("GMAIL_TOKEN_PATH", "./token.json")
TARGET_EMAIL: str = os.getenv("TARGET_EMAIL", "inbox@focusgraphics.com")
POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
DB_PATH: str = os.getenv("DB_PATH", "./focusva.db")
```

- [ ] **Step 4: Create tests/__init__.py** (empty file)

- [ ] **Step 5: Create tests/conftest.py**

```python
import os
import tempfile
import pytest
import database


@pytest.fixture(autouse=True)
def temp_db():
    """Every test gets a fresh temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    database.set_db_path(path)
    database.init_db()
    yield path
    os.unlink(path)
```

- [ ] **Step 6: Install dependencies**

```bash
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
```

Expected: All packages install without errors. `pip show fastapi anthropic` shows versions.

- [ ] **Step 7: Verify config loads**

```bash
python -c "import config; print(config.POLL_INTERVAL_SECONDS)"
```

Expected: `120`

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .env.example config.py tests/__init__.py tests/conftest.py
git commit -m "feat: project scaffold — config, requirements, test fixtures"
```

---

## Task 2: Database Layer

**Files:**
- Create: `database.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_database.py -v
```

Expected: `ModuleNotFoundError: No module named 'database'`

- [ ] **Step 3: Create database.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_database.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: SQLite schema — emails, job_data, drafts tables"
```

---

## Task 3: Mock Email Data

**Files:**
- Create: `mock_emails.json`

- [ ] **Step 1: Create mock_emails.json**

```json
[
  {
    "gmail_message_id": "mock_001",
    "thread_id": "thread_001",
    "sender": "Sarah Chen <sarah@greenleafcafe.com>",
    "subject": "Quote for window decals",
    "body": "Hi there,\n\nI'm looking to get some window decals made for our cafe. We have three windows at the front. Could you give me a quote?\n\nThanks,\nSarah",
    "received_at": "2026-03-25T09:15:00Z"
  },
  {
    "gmail_message_id": "mock_002",
    "thread_id": "thread_002",
    "sender": "Mike Torres <mike@torresconstruction.com>",
    "subject": "Revision on the truck wrap design",
    "body": "Hey,\n\nThe proof looks great but I need to change the phone number. It should be 555-0192 not 555-0129. Also can we make the logo slightly bigger?\n\nThanks,\nMike",
    "received_at": "2026-03-25T09:30:00Z"
  },
  {
    "gmail_message_id": "mock_003",
    "thread_id": "thread_003",
    "sender": "Linda Park <linda@sunsetevents.com>",
    "subject": "Proof looks good — approved",
    "body": "Hi,\n\nJust reviewed the proof for the event banners and everything looks great. You're good to go ahead and print.\n\nThanks,\nLinda",
    "received_at": "2026-03-25T10:00:00Z"
  },
  {
    "gmail_message_id": "mock_004",
    "thread_id": "thread_004",
    "sender": "noreply@printsuppliesplus.com",
    "subject": "SPECIAL OFFER: 40% off vinyl rolls this week only!",
    "body": "Dear Print Shop Owner,\n\nDon't miss our biggest sale of the year! 40% off all vinyl rolls, laminates, and substrates. Limited time offer. Click here to shop now.\n\nPrintSuppliesPlus Team",
    "received_at": "2026-03-25T10:30:00Z"
  },
  {
    "gmail_message_id": "mock_005",
    "thread_id": "thread_005",
    "sender": "James Okafor <james@riseacademy.org>",
    "subject": "Banner for graduation — need 50 pieces, 4x8 ft, by April 10",
    "body": "Hello Focus Graphics,\n\nWe need 50 banners printed for our graduation ceremony. Each should be 4 feet by 8 feet. We need them by April 10th. They'll hang outdoors so need to be weather resistant.\n\nPlease let me know the cost.\n\nJames Okafor\nRise Academy",
    "received_at": "2026-03-25T11:00:00Z"
  }
]
```

- [ ] **Step 2: Verify JSON is valid**

```bash
python -c "import json; data = json.load(open('mock_emails.json')); print(f'{len(data)} mock emails loaded')"
```

Expected: `5 mock emails loaded`

- [ ] **Step 3: Commit**

```bash
git add mock_emails.json
git commit -m "feat: mock email data for local dev without Gmail credentials"
```

---

## Task 4: Prompt Templates

**Files:**
- Create: `prompts.py`
- Create: `tests/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompts.py
from prompts import classify_prompt, extract_prompt, draft_prompt


def test_classify_prompt_contains_all_labels():
    prompt = classify_prompt("Quote needed", "I need 100 business cards")
    assert "quote_request" in prompt
    assert "revision_request" in prompt
    assert "vendor_spam" in prompt
    assert "bid_invite" in prompt


def test_classify_prompt_contains_subject_and_body():
    prompt = classify_prompt("My subject", "My body text here")
    assert "My subject" in prompt
    assert "My body text here" in prompt


def test_classify_prompt_truncates_body_at_500_chars():
    long_body = "x" * 1000
    prompt = classify_prompt("Subject", long_body)
    # The body preview in the prompt should not exceed 500 chars of original body
    assert long_body not in prompt
    assert "x" * 500 in prompt


def test_extract_prompt_contains_body_and_classification():
    prompt = extract_prompt("I need 50 banners", "quote_request")
    assert "I need 50 banners" in prompt
    assert "quote_request" in prompt
    assert "job_type" in prompt
    assert "quantity" in prompt


def test_draft_prompt_contains_missing_fields():
    prompt = draft_prompt(
        "I need window decals",
        {"job_type": "window decals"},
        ["size", "material"]
    )
    assert "size" in prompt
    assert "material" in prompt
    assert "window decals" in prompt


def test_draft_prompt_with_no_missing_fields():
    prompt = draft_prompt(
        "I need 50 banners, 4x8 ft, vinyl",
        {"job_type": "banner", "quantity": 50, "size": "4x8", "material": "vinyl"},
        []
    )
    assert "none" in prompt.lower() or "no missing" in prompt.lower() or prompt.count("missing") >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_prompts.py -v
```

Expected: `ModuleNotFoundError: No module named 'prompts'`

- [ ] **Step 3: Create prompts.py**

```python
LABELS = (
    "quote_request",
    "revision_request",
    "proof_approval",
    "scheduling",
    "general_question",
    "vendor_spam",
    "bid_invite",
)


def classify_prompt(subject: str, body: str) -> str:
    preview = body[:500]
    labels_list = "\n".join(f"- {label}" for label in LABELS)
    return f"""You are classifying an email for Focus Graphics, a print shop.

Classify this email into exactly one of these categories:
{labels_list}

Definitions:
- quote_request: customer wants pricing for a print job
- revision_request: customer wants changes to an existing job
- proof_approval: customer is approving or rejecting a proof
- scheduling: scheduling pickup, delivery, or a meeting
- general_question: general inquiry not tied to a specific job
- vendor_spam: unsolicited vendor outreach or marketing
- bid_invite: invitation to bid on a contract

Subject: {subject}
Body preview: {preview}

If uncertain between two labels, pick the more actionable one.
Respond with ONLY the category label, nothing else."""


def extract_prompt(body: str, classification: str) -> str:
    return f"""You are extracting job details from a print shop email.

Email classification: {classification}
Email body:
{body}

Extract ONLY the fields that are explicitly stated in the email. Do NOT guess, infer, or fill in missing values.
Return a JSON object with any of these fields that are clearly present:
- job_type (e.g. "business cards", "window decals", "banners")
- quantity (number)
- size (dimensions or description)
- material (e.g. "vinyl", "paper", "canvas")
- deadline (date or description)
- contact_name
- company
- notes (any other relevant details)

If a field is not mentioned in the email, omit it entirely from the JSON.
Return ONLY the JSON object, no explanation, no markdown fences."""


def draft_prompt(body: str, job_data: dict, missing_fields: list[str]) -> str:
    known_lines = "\n".join(f"- {k}: {v}" for k, v in job_data.items()) if job_data else "None"
    missing_line = ", ".join(missing_fields) if missing_fields else "none — all required info present"

    return f"""You are writing a short, friendly reply for Focus Graphics, a print shop.

Original email:
{body}

Known details extracted from this email:
{known_lines}

Missing required information: {missing_line}

Write a reply that:
1. Acknowledges what was received in one sentence
2. Confirms the details you DO know
3. Asks ONLY for the information listed under "Missing required information"
4. Is 2-4 sentences total
5. Sounds human and friendly, not corporate or robotic
6. Does NOT invent, assume, or guess any information not in the original email

If missing information is "none", write a brief confirmation that you have everything needed and will follow up shortly.

Reply with only the email body text. No subject line, no greeting like "Dear Customer", no sign-off."""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_prompts.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add prompts.py tests/test_prompts.py
git commit -m "feat: Claude prompt templates for classify, extract, and draft"
```

---

## Task 5: AI Pipeline

**Files:**
- Create: `pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
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
    responses = ["quote_request", '{"job_type": "banner", "quantity": 50}', "Thanks! What material?"]

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline'`

- [ ] **Step 3: Create pipeline.py**

```python
import json
from datetime import datetime, timezone
from typing import Optional

import anthropic
import config
import database
from prompts import LABELS, classify_prompt, extract_prompt, draft_prompt

NO_DRAFT_LABELS = {"vendor_spam", "bid_invite"}

REQUIRED_FIELDS: dict[str, list[str]] = {
    "quote_request": ["job_type", "quantity", "size", "material"],
    "revision_request": ["job_type", "revision_details"],
    "proof_approval": ["job_type"],
    "scheduling": ["reason"],
    "general_question": [],
}


def _claude(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def classify_email(subject: str, body: str) -> str:
    prompt = classify_prompt(subject, body)
    result = _claude(prompt).lower()
    for label in LABELS:
        if label in result:
            return label
    return "general_question"


def extract_job_data(body: str, classification: str) -> dict:
    prompt = extract_prompt(body, classification)
    result = _claude(prompt)
    start = result.find("{")
    end = result.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(result[start:end])
        except json.JSONDecodeError:
            pass
    return {}


def draft_response(body: str, job_data: dict, classification: str) -> Optional[str]:
    if classification in NO_DRAFT_LABELS:
        return None
    required = REQUIRED_FIELDS.get(classification, [])
    missing = [f for f in required if f not in job_data]
    prompt = draft_prompt(body, job_data, missing)
    return _claude(prompt)


def process_email(email: dict) -> int:
    """Run the full pipeline for one email. Returns the new email row ID."""
    now = datetime.now(timezone.utc).isoformat()

    classification = classify_email(email["subject"], email["body"])
    job_data = extract_job_data(email["body"], classification)
    draft = draft_response(email["body"], job_data, classification)

    with database.get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO emails
               (gmail_message_id, thread_id, sender, subject, body,
                received_at, classification, status, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                email["gmail_message_id"],
                email.get("thread_id", ""),
                email["sender"],
                email["subject"],
                email["body"],
                email["received_at"],
                classification,
                now,
            ),
        )
        email_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO job_data (email_id, data) VALUES (?, ?)",
            (email_id, json.dumps(job_data)),
        )

        if draft is not None:
            conn.execute(
                "INSERT INTO drafts (email_id, body) VALUES (?, ?)",
                (email_id, draft),
            )

    return email_id
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat: AI pipeline — classify, extract, draft via Claude API"
```

---

## Task 6: Gmail Client

**Files:**
- Create: `gmail_client.py`
- Create: `tests/test_gmail_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gmail_client.py
import json
import os
import tempfile
from unittest.mock import patch, MagicMock
import gmail_client
import config


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_gmail_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'gmail_client'`

- [ ] **Step 3: Create gmail_client.py**

```python
import base64
import json
import os
from email.mime.text import MIMEText
from typing import Optional

import config

MOCK_EMAILS_PATH = "mock_emails.json"


def fetch_new_emails() -> list[dict]:
    """Returns list of email dicts. Uses mock_emails.json if Gmail not configured."""
    if not config.GMAIL_CREDENTIALS_PATH:
        return _load_mock_emails()
    return _fetch_from_gmail()


def send_reply(thread_id: str, to: str, subject: str, body: str) -> None:
    """Send an in-thread reply. Prints to stdout in mock mode."""
    if not config.GMAIL_CREDENTIALS_PATH:
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
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
    creds: Optional[Credentials] = None

    if os.path.exists(config.GMAIL_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(config.GMAIL_TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(config.GMAIL_CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(config.GMAIL_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


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

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_gmail_client.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add gmail_client.py tests/test_gmail_client.py
git commit -m "feat: Gmail client with mock mode and OAuth send"
```

---

## Task 7: FastAPI Application

**Files:**
- Create: `main.py`
- Create: `static/.gitkeep` (placeholder, real static files in Task 8)
- Create: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api.py -v
```

Expected: `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Create static/.gitkeep** (so StaticFiles doesn't crash before Task 8)

```bash
mkdir -p static && touch static/.gitkeep
```

- [ ] **Step 4: Create main.py**

```python
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import database
import gmail_client
import pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    task = asyncio.create_task(_poll_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="FocusVA", lifespan=lifespan)


async def _poll_loop() -> None:
    """Background loop: sleep first, then poll, so tests complete before first cycle."""
    while True:
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
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


# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/emails")
def list_emails(
    status: Optional[str] = None,
    classification: Optional[str] = None,
):
    query = """
        SELECT e.*, d.body AS draft_body
        FROM emails e
        LEFT JOIN drafts d ON d.email_id = e.id
        WHERE 1=1
    """
    params: list = []
    if status:
        query += " AND e.status = ?"
        params.append(status)
    if classification:
        query += " AND e.classification = ?"
        params.append(classification)
    query += " ORDER BY e.received_at DESC"

    with database.get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/emails/{email_id}")
def get_email(email_id: int):
    with database.get_conn() as conn:
        email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        jd = conn.execute("SELECT data FROM job_data WHERE email_id = ?", (email_id,)).fetchone()
        draft = conn.execute("SELECT * FROM drafts WHERE email_id = ?", (email_id,)).fetchone()

    return {
        "email": dict(email),
        "job_data": json.loads(jd["data"]) if jd else {},
        "draft": dict(draft) if draft else None,
    }


class DraftUpdate(BaseModel):
    body: str


@app.put("/emails/{email_id}/draft")
def update_draft(email_id: int, update: DraftUpdate):
    with database.get_conn() as conn:
        draft = conn.execute("SELECT id FROM drafts WHERE email_id = ?", (email_id,)).fetchone()
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        conn.execute("UPDATE drafts SET body = ? WHERE email_id = ?", (update.body, email_id))
    return {"ok": True}


class ApproveRequest(BaseModel):
    approved_by: str = "staff"


@app.post("/emails/{email_id}/approve")
def approve_email(email_id: int, req: ApproveRequest):
    with database.get_conn() as conn:
        email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        if email["status"] != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve email with status '{email['status']}'",
            )
        draft = conn.execute("SELECT * FROM drafts WHERE email_id = ?", (email_id,)).fetchone()
        if not draft:
            raise HTTPException(status_code=400, detail="No draft to approve")

    now = datetime.now(timezone.utc).isoformat()
    gmail_client.send_reply(email["thread_id"], email["sender"], email["subject"], draft["body"])

    with database.get_conn() as conn:
        conn.execute("UPDATE emails SET status = 'sent' WHERE id = ?", (email_id,))
        conn.execute(
            "UPDATE drafts SET approved_by = ?, approved_at = ?, sent_at = ? WHERE email_id = ?",
            (req.approved_by, now, now, email_id),
        )
    return {"ok": True}


class RejectRequest(BaseModel):
    note: Optional[str] = None


@app.post("/emails/{email_id}/reject")
def reject_email(email_id: int, req: RejectRequest = RejectRequest()):
    with database.get_conn() as conn:
        email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        conn.execute("UPDATE emails SET status = 'rejected' WHERE id = ?", (email_id,))
    return {"ok": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_api.py -v
```

Expected: `13 passed`

- [ ] **Step 6: Run all tests together**

```bash
pytest -v
```

Expected: All tests pass. Note any failures and fix before committing.

- [ ] **Step 7: Commit**

```bash
git add main.py static/.gitkeep tests/test_api.py
git commit -m "feat: FastAPI app — all endpoints, background poller, static mount"
```

---

## Task 8: Dashboard Frontend

**Files:**
- Create: `static/index.html`
- Create: `static/style.css`
- Create: `static/app.js`

No automated tests for frontend. Manual verification checklist provided at end.

- [ ] **Step 1: Create static/index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FocusVA — Focus Graphics</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <h1>FocusVA</h1>
        <p>Focus Graphics</p>
      </div>
      <nav>
        <button class="tab active" data-tab="pending" data-filter="status=pending">
          Pending
        </button>
        <button class="tab" data-tab="sent" data-filter="status=sent">
          Sent
        </button>
        <button class="tab" data-tab="rejected" data-filter="status=rejected">
          Rejected
        </button>
        <button class="tab" data-tab="spam" data-filter="spam">
          Spam &amp; Bids
        </button>
      </nav>
    </aside>

    <div class="email-list" id="emailList">
      <div class="loading">Loading...</div>
    </div>

    <div class="detail-panel" id="detailPanel">
      <div class="empty-state">
        <p>Select an email to review</p>
      </div>
    </div>
  </div>
  <div class="toast" id="toast"></div>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create static/style.css**

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f0f2f5;
  color: #1a1a2e;
  height: 100vh;
  overflow: hidden;
}

.layout {
  display: grid;
  grid-template-columns: 200px 360px 1fr;
  height: 100vh;
}

/* ── Sidebar ─────────────────────── */
.sidebar {
  background: #1a1a2e;
  color: white;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.brand h1 { font-size: 20px; font-weight: 700; color: #60a5fa; }
.brand p  { font-size: 12px; color: #94a3b8; margin-top: 4px; }

nav { display: flex; flex-direction: column; gap: 4px; }

.tab {
  background: none;
  border: none;
  color: #94a3b8;
  text-align: left;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.15s, color 0.15s;
}
.tab:hover  { background: rgba(255,255,255,0.08); color: white; }
.tab.active { background: rgba(96,165,250,0.2); color: #60a5fa; font-weight: 600; }

/* ── Email List ──────────────────── */
.email-list {
  background: white;
  border-right: 1px solid #e2e8f0;
  overflow-y: auto;
}

.email-row {
  padding: 14px 16px;
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: background 0.1s;
  border-left: 3px solid transparent;
}
.email-row:hover  { background: #f8fafc; }
.email-row.active { background: #eff6ff; border-left-color: #3b82f6; }

.email-row-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 3px;
}
.email-sender  { font-weight: 600; font-size: 13px; color: #1e293b; }
.email-time    { font-size: 11px; color: #94a3b8; white-space: nowrap; }
.email-subject {
  font-size: 13px;
  color: #334155;
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.email-meta { display: flex; gap: 6px; align-items: center; }

/* ── Badges ──────────────────────── */
.badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  white-space: nowrap;
}
.badge-quote_request    { background: #dbeafe; color: #1d4ed8; }
.badge-revision_request { background: #fed7aa; color: #c2410c; }
.badge-proof_approval   { background: #d1fae5; color: #065f46; }
.badge-scheduling       { background: #ede9fe; color: #6d28d9; }
.badge-general_question { background: #f1f5f9; color: #475569; }
.badge-vendor_spam      { background: #fee2e2; color: #991b1b; }
.badge-bid_invite       { background: #fef9c3; color: #854d0e; }

.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.status-pending  { background: #f59e0b; }
.status-sent     { background: #10b981; }
.status-rejected { background: #ef4444; }

/* ── Detail Panel ────────────────── */
.detail-panel {
  padding: 32px;
  overflow-y: auto;
  background: #f8fafc;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #94a3b8;
  font-size: 15px;
}

.loading {
  padding: 32px;
  text-align: center;
  color: #94a3b8;
  font-size: 14px;
}

.detail-header { margin-bottom: 24px; }
.detail-subject {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 8px;
  line-height: 1.3;
}
.detail-meta {
  font-size: 13px;
  color: #64748b;
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
}

.section {
  background: white;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
  border: 1px solid #e2e8f0;
}
.section-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #94a3b8;
  margin-bottom: 12px;
}

.email-body {
  font-size: 14px;
  line-height: 1.75;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-word;
}

.job-data-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.job-field label {
  display: block;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
  margin-bottom: 2px;
}
.job-field span {
  font-size: 14px;
  font-weight: 500;
  color: #0f172a;
}

.draft-textarea {
  width: 100%;
  min-height: 120px;
  font-size: 14px;
  line-height: 1.65;
  padding: 12px;
  border: 1.5px solid #e2e8f0;
  border-radius: 8px;
  resize: vertical;
  font-family: inherit;
  color: #1e293b;
  background: #f8fafc;
  transition: border-color 0.15s, background 0.15s;
}
.draft-textarea:focus {
  outline: none;
  border-color: #3b82f6;
  background: white;
}

.actions { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }

.btn {
  padding: 9px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.15s;
}
.btn-approve { background: #22c55e; color: white; }
.btn-approve:hover { background: #16a34a; }
.btn-reject { background: white; color: #ef4444; border: 1.5px solid #ef4444; }
.btn-reject:hover { background: #fee2e2; }
.btn-save { background: #f1f5f9; color: #475569; border: 1.5px solid #e2e8f0; }
.btn-save:hover { background: #e2e8f0; }

/* ── Toast ───────────────────────── */
.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: #1e293b;
  color: white;
  padding: 12px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  opacity: 0;
  transition: opacity 0.25s;
  pointer-events: none;
  z-index: 100;
}
.toast.show { opacity: 1; }
```

- [ ] **Step 3: Create static/app.js**

```javascript
let currentFilter = 'status=pending';
let currentEmailId = null;

// ── API helper ─────────────────────────────────────────────
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

// ── Toast ──────────────────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Helpers ────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(str) {
  if (!str) return '';
  const d = new Date(str);
  if (isNaN(d)) return str;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function senderName(sender) {
  const m = sender.match(/^"?([^"<]+)"?\s*</);
  return m ? m[1].trim() : sender;
}

function badgeHtml(classification) {
  const label = (classification || '').replace(/_/g, ' ');
  return `<span class="badge badge-${escapeHtml(classification)}">${escapeHtml(label)}</span>`;
}

// ── Email List ─────────────────────────────────────────────
async function loadEmails(filter) {
  currentFilter = filter;
  const list = document.getElementById('emailList');
  list.innerHTML = '<div class="loading">Loading...</div>';

  try {
    let emails;
    if (filter === 'spam') {
      // Fetch both spam labels, merge, sort
      const [spam, bids] = await Promise.all([
        api('/emails?classification=vendor_spam'),
        api('/emails?classification=bid_invite'),
      ]);
      emails = [...spam, ...bids].sort(
        (a, b) => new Date(b.received_at) - new Date(a.received_at)
      );
    } else {
      emails = await api('/emails?' + filter);
    }

    if (emails.length === 0) {
      list.innerHTML = '<div class="loading">No emails here</div>';
      return;
    }

    list.innerHTML = emails.map(e => `
      <div class="email-row${e.id === currentEmailId ? ' active' : ''}"
           data-id="${e.id}"
           onclick="loadDetail(${e.id})">
        <div class="email-row-header">
          <span class="email-sender">${escapeHtml(senderName(e.sender))}</span>
          <span class="email-time">${formatDate(e.received_at)}</span>
        </div>
        <div class="email-subject">${escapeHtml(e.subject || '(no subject)')}</div>
        <div class="email-meta">
          ${badgeHtml(e.classification)}
          <span class="status-dot status-${escapeHtml(e.status)}"></span>
        </div>
      </div>
    `).join('');
  } catch (err) {
    list.innerHTML = `<div class="loading">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ── Detail Panel ───────────────────────────────────────────
async function loadDetail(id) {
  currentEmailId = id;
  document.querySelectorAll('.email-row').forEach(r => {
    r.classList.toggle('active', +r.dataset.id === id);
  });

  const panel = document.getElementById('detailPanel');
  panel.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const { email, job_data, draft } = await api(`/emails/${id}`);

    const jobHtml = Object.keys(job_data).length > 0
      ? `<div class="section">
           <div class="section-title">Extracted Job Details</div>
           <div class="job-data-grid">
             ${Object.entries(job_data).map(([k, v]) => `
               <div class="job-field">
                 <label>${escapeHtml(k.replace(/_/g, ' '))}</label>
                 <span>${escapeHtml(String(v))}</span>
               </div>
             `).join('')}
           </div>
         </div>`
      : '';

    const draftHtml = draft
      ? `<div class="section">
           <div class="section-title">AI Draft Response</div>
           <textarea class="draft-textarea" id="draftBody">${escapeHtml(draft.body)}</textarea>
           <div class="actions">
             <button class="btn btn-approve" onclick="approveDraft(${id})">Approve &amp; Send</button>
             <button class="btn btn-reject"  onclick="rejectEmail(${id})">Reject</button>
             <button class="btn btn-save"    onclick="saveDraft(${id})">Save Edits</button>
           </div>
         </div>`
      : `<div class="section">
           <div class="section-title">Draft</div>
           <p style="color:#94a3b8;font-size:14px;">
             No draft generated for this email type.
           </p>
         </div>`;

    panel.innerHTML = `
      <div class="detail-header">
        <div class="detail-subject">${escapeHtml(email.subject || '(no subject)')}</div>
        <div class="detail-meta">
          <span>From: ${escapeHtml(email.sender)}</span>
          <span>${formatDate(email.received_at)}</span>
          ${badgeHtml(email.classification)}
          <span class="status-dot status-${escapeHtml(email.status)}"></span>
          <span>${escapeHtml(email.status)}</span>
        </div>
      </div>
      <div class="section">
        <div class="section-title">Original Email</div>
        <div class="email-body">${escapeHtml(email.body)}</div>
      </div>
      ${jobHtml}
      ${draftHtml}
    `;
  } catch (err) {
    panel.innerHTML = `<div class="loading">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ── Actions ────────────────────────────────────────────────
async function saveDraft(id) {
  const body = document.getElementById('draftBody').value;
  try {
    await api(`/emails/${id}/draft`, {
      method: 'PUT',
      body: JSON.stringify({ body }),
    });
    showToast('Draft saved');
  } catch (err) {
    showToast('Error: ' + err.message);
  }
}

async function approveDraft(id) {
  const body = document.getElementById('draftBody').value;
  try {
    await api(`/emails/${id}/draft`, { method: 'PUT', body: JSON.stringify({ body }) });
    await api(`/emails/${id}/approve`, { method: 'POST', body: JSON.stringify({ approved_by: 'staff' }) });
    showToast('Email sent!');
    await loadEmails(currentFilter);
    document.getElementById('detailPanel').innerHTML =
      '<div class="empty-state"><p>Email sent successfully.</p></div>';
    currentEmailId = null;
  } catch (err) {
    showToast('Error: ' + err.message);
  }
}

async function rejectEmail(id) {
  try {
    await api(`/emails/${id}/reject`, { method: 'POST', body: JSON.stringify({}) });
    showToast('Email rejected');
    await loadEmails(currentFilter);
    document.getElementById('detailPanel').innerHTML =
      '<div class="empty-state"><p>Email rejected.</p></div>';
    currentEmailId = null;
  } catch (err) {
    showToast('Error: ' + err.message);
  }
}

// ── Tab navigation ─────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    loadEmails(tab.dataset.filter);
    document.getElementById('detailPanel').innerHTML =
      '<div class="empty-state"><p>Select an email to review</p></div>';
    currentEmailId = null;
  });
});

// ── Boot ───────────────────────────────────────────────────
loadEmails(currentFilter);
```

- [ ] **Step 4: Remove .gitkeep and verify static dir**

```bash
rm static/.gitkeep && ls static/
```

Expected: `app.js  index.html  style.css`

- [ ] **Step 5: Start the server and manually verify**

```bash
cp .env.example .env
# Edit .env: add your ANTHROPIC_API_KEY (leave GMAIL_CREDENTIALS_PATH empty for mock mode)
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` and verify:
- [ ] Dashboard loads with sidebar showing 4 tabs
- [ ] "Pending" tab is active by default
- [ ] Email list is empty (no emails processed yet)
- [ ] Clicking "Spam & Bids" tab shows no emails

- [ ] **Step 6: Trigger mock pipeline via Python REPL**

```bash
python - <<'EOF'
import database, pipeline
database.init_db()
import json
emails = json.load(open("mock_emails.json"))
for e in emails:
    pid = pipeline.process_email(e)
    print(f"Processed email ID: {pid}")
EOF
```

Expected: 5 lines like `Processed email ID: N` (requires valid ANTHROPIC_API_KEY in .env)

- [ ] **Step 7: Verify dashboard shows processed emails**

Refresh `http://localhost:8000` and verify:
- [ ] Pending tab shows emails from mock data
- [ ] Each row shows sender, subject, classification badge
- [ ] Clicking a row shows detail panel with original email, job data, and AI draft
- [ ] Draft text is editable
- [ ] "Save Edits" saves changes (no page reload)
- [ ] "Reject" moves email to Rejected tab
- [ ] "Approve & Send" sends (prints `[MOCK]` to terminal in mock mode) and moves to Sent tab
- [ ] Spam & Bids tab shows vendor_spam email

- [ ] **Step 8: Run full test suite**

```bash
pytest -v
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat: dashboard — inbox, detail view, approve/reject/edit flow"
```

---

## Final Checklist

- [ ] `pytest -v` → all tests pass
- [ ] App starts with `uvicorn main:app --reload`
- [ ] Dashboard loads at `http://localhost:8000`
- [ ] Mock pipeline processes 5 emails end-to-end
- [ ] Approve & Send triggers `[MOCK]` log (or real Gmail send if configured)
- [ ] `.env.example` committed, `.env` in `.gitignore`

- [ ] **Add .gitignore**

```bash
cat > .gitignore << 'EOF'
.env
*.db
token.json
credentials.json
venv/
__pycache__/
*.pyc
.pytest_cache/
EOF
git add .gitignore
git commit -m "chore: add .gitignore"
```
