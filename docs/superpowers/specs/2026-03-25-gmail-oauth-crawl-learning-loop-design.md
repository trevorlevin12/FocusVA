# FocusVA — Gmail OAuth, History Crawl & Learning Loop Design Spec
**Date:** 2026-03-25
**Project:** Focus Graphics Email Assistant — Phase 2
**Stack:** Python / FastAPI / SQLite / Vanilla HTML+JS / Anthropic Claude API / Gmail API / ChromaDB / OpenAI Embeddings

---

## 1. Problem

The current system authenticates via a Google service account (domain-wide delegation) with a hardcoded `TARGET_EMAIL`. This requires a GCP admin setup and makes it hard for the business owner (Dylan, info@focusgraphics.net) to self-serve. Additionally, while a RAG system exists, it has no data — the ChromaDB index is empty because there is no mechanism to seed it from historical emails or to grow it over time from approved replies.

---

## 2. Goals

1. Replace service account auth with **OAuth2 user flow** so Dylan can sign in via browser with his Google account
2. Allow Dylan to **crawl his Sent folder** from a configurable cutoff date to seed the RAG with real past inquiry/response pairs
3. **Auto-learn on every approval**: when staff approves a draft, the original inquiry + final sent reply are indexed into ChromaDB so future drafts improve over time
4. All changes are additive — no changes to the existing classify/extract/draft pipeline or approval flow logic beyond the learning step

---

## 3. Architecture

```
[Dashboard "Connect Gmail" banner]
        ↓ click
[GET /auth/login] → Google OAuth consent screen
        ↓ callback
[GET /auth/callback] → exchanges code for token, saves token.json
        ↓
[Dashboard unlocks Settings tab with history import form]
        ↓ staff enters cutoff date + clicks "Import History"
[POST /admin/crawl-history] → spawns asyncio background task
        ↓
[crawl.crawl_sent_emails(since_date)] → queries Gmail Sent, builds inquiry/response pairs
        ↓
[rag.index_pair(inquiry, response)] → embed via OpenAI, upsert into ChromaDB
        ↓
[GET /admin/crawl-status] → polls progress (total, indexed, errors, done)

── existing approve flow ──
[POST /emails/{id}/approve] → sends reply via Gmail
        ↓ NEW: rag.index_pair(original_email_body, approved_draft_body)
        ↓ (synchronous, ~1s added latency)
```

---

## 4. New Components

### 4.1 `auth.py` (new file)

Owns all OAuth2 logic. No other module should import `google.oauth2` directly.

| Function | Purpose |
|---|---|
| `get_oauth_flow()` | Builds InstalledAppFlow from `GMAIL_CREDENTIALS_PATH` |
| `is_authenticated()` | Returns bool — checks if `token.json` exists and is valid |
| `get_credentials()` | Loads token.json, refreshes if expired, returns `google.oauth2.credentials.Credentials` |
| `get_auth_url(state)` | Returns the Google consent URL for redirecting the user |
| `exchange_code(code, state)` | Exchanges auth code for tokens, writes `token.json` |

OAuth scopes: `https://www.googleapis.com/auth/gmail.modify` (read, send, modify — same as before).

### 4.2 `crawl.py` (new file)

Historical import logic. Isolated from the main pipeline.

| Function | Purpose |
|---|---|
| `crawl_sent_emails(since_date, status_key)` | Main crawl coroutine — queries Sent, pairs with inquiries, indexes |
| `get_crawl_status(status_key)` | Returns `{total, indexed, errors, done: bool}` |

**Pairing logic:**
1. Query: `in:sent after:{since_date}` (Gmail search)
2. For each sent message, fetch its full thread
3. Find the most recent message in the thread that is NOT from `TARGET_EMAIL` and predates the sent reply
4. If found → `rag.index_pair(inquiry_body, sent_reply_body)`
5. If not found (cold outbound, no prior customer message) → skip, count as skipped (not an error)

Progress is stored in a module-level dict `_crawl_jobs: dict[str, dict]` keyed by `status_key` (a UUID generated at crawl start). This is in-memory only — if the server restarts mid-crawl, the user must re-trigger. The ChromaDB upsert is idempotent, so re-crawling is safe.

### 4.3 `rag.py` (extended)

Add one function alongside the existing `retrieve_examples()`:

```python
def index_pair(inquiry: str, response: str) -> None:
    """Embed an inquiry/response pair and upsert into ChromaDB."""
```

- Uses OpenAI `text-embedding-3-small` to embed the `inquiry`
- Upserts with a deterministic ID derived from `hash(inquiry[:200])` — prevents duplicates on re-crawl
- Silently no-ops if `OPENAI_API_KEY` is not set (graceful degradation)

### 4.4 `gmail_client.py` (modified)

Replace `_get_gmail_service()` body:
- **Before:** `service_account.Credentials.from_service_account_file(...).with_subject(...)`
- **After:** `auth.get_credentials()` — uses OAuth token

Mock mode remains unchanged: if `GMAIL_CREDENTIALS_PATH` is unset, falls back to `mock_emails.json`.

### 4.5 `main.py` (modified)

New endpoints:

```
GET  /auth/login              → redirects to Google OAuth consent URL
GET  /auth/callback           → exchanges code, saves token, redirects to dashboard
GET  /auth/status             → {"connected": bool}

POST /admin/crawl-history     → body: {"since_date": "2024-01-01"}
                                → starts background crawl, returns {"status_key": "<uuid>"}
GET  /admin/crawl-status      → ?key=<uuid> → {total, indexed, errors, done}
```

Modified endpoint:
```
POST /emails/{id}/approve     → (existing logic) + rag.index_pair(email.body, draft.body)
```

### 4.6 `static/` (modified)

**`app.js`:**
- On load, `GET /auth/status`. If `connected: false`, show a persistent banner: "Gmail not connected — [Connect Gmail]"
- Clicking the banner navigates to `/auth/login`
- Add a "Settings" tab (existing tabs: Pending, Approved/Sent, Rejected, Spam & Bids)
  - Shows connection status
  - Shows history import form: date picker + "Import History" button
  - Shows crawl progress bar (polls `/admin/crawl-status` every 2s while `done: false`)

**`index.html`:** Add Settings tab nav item. No other structural changes.

---

## 5. Configuration Changes

### `.env` / `config.py`

Remove:
```
GMAIL_SERVICE_ACCOUNT_PATH   # no longer used
```

Add:
```
GMAIL_CREDENTIALS_PATH=./credentials.json   # OAuth client secret JSON (from Google Cloud Console)
GMAIL_TOKEN_PATH=./token.json               # written automatically after first sign-in
GMAIL_REDIRECT_URI=http://localhost:8000/auth/callback
```

Unchanged:
```
ANTHROPIC_API_KEY
OPENAI_API_KEY
TARGET_EMAIL=info@focusgraphics.net
POLL_INTERVAL_SECONDS
DB_PATH
```

`config.py` must be updated to read the new vars and remove `GMAIL_SERVICE_ACCOUNT_PATH`.

---

## 6. Data Flow — Learning Loop

On every `POST /emails/{id}/approve`:
1. Load email body and draft body from DB (already done for sending)
2. Gmail sends the reply (existing)
3. `rag.index_pair(email["body"], draft["body"])` — synchronous, ~1s
4. Return `{"ok": True}` to dashboard

The approved draft body (possibly edited by staff) is what gets indexed — not the original AI-generated draft. This ensures the RAG learns from human-validated responses.

---

## 7. Google Cloud Setup (one-time, operator)

1. In Google Cloud Console: create an **OAuth 2.0 Client ID** (type: Web Application)
2. Authorized redirect URI: `http://localhost:8000/auth/callback` (add production URI later)
3. Download the JSON → save as `credentials.json` in project root
4. First run: visit dashboard → click "Connect Gmail" → complete consent → token auto-saved

No service account, no domain-wide delegation, no GCP admin required beyond creating the OAuth client.

---

## 8. Security Notes

- `token.json` and `credentials.json` must be in `.gitignore` (already present for `token.json`; add `credentials.json`)
- OAuth state parameter used to prevent CSRF on callback
- No multi-user session management — single-tenant, token is shared at the process level
- In-memory crawl status is not persisted — acceptable for single-tenant use

---

## 9. Out of Scope

- Multi-user / multi-account support
- Gmail label changes (labeling is internal to dashboard only)
- Email attachment handling
- Crawl persistence across server restarts
- Production OAuth redirect URI / HTTPS setup

---

## 10. File Change Summary

| File | Change |
|---|---|
| `auth.py` | New — OAuth2 flow |
| `crawl.py` | New — historical import |
| `rag.py` | Add `index_pair()` |
| `gmail_client.py` | Swap service account → OAuth via `auth.get_credentials()` |
| `main.py` | Add auth + crawl endpoints; modify approve to call `rag.index_pair()` |
| `config.py` | Remove `GMAIL_SERVICE_ACCOUNT_PATH`, add OAuth vars |
| `static/app.js` | Auth status banner, Settings tab, crawl progress UI |
| `static/index.html` | Settings tab nav item |
| `.env.example` | Update vars |
