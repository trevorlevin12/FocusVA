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
[GET /auth/login] → Google OAuth consent screen (Web Application flow)
        ↓ callback
[GET /auth/callback] → exchanges code for token, saves token.json → HTTP 302 to /
        ↓
[Dashboard unlocks Settings tab with history import form]
        ↓ staff enters cutoff date (YYYY-MM-DD) + clicks "Import History"
[POST /admin/crawl-history] → async def endpoint, asyncio.create_task(crawl_sent_emails(...))
        ↓
[crawl.crawl_sent_emails(since_date, status_key)] → queries Gmail Sent, builds inquiry/response pairs
        ↓
[rag.index_pair(inquiry, response)] → embed via OpenAI (in executor), upsert into ChromaDB
        ↓
[GET /admin/crawl-status?key=<uuid>] → polls progress (total, indexed, errors, done)

── existing approve flow ──
[POST /emails/{id}/approve] → saves edited draft (via prior PUT), then sends reply via Gmail
        ↓ NEW: rag.index_pair(email.body, draft.body from DB)
        ↓ (synchronous call; ~1s latency acceptable for single-tenant use)
```

---

## 4. New Components

### 4.1 `auth.py` (new file)

Owns all OAuth2 logic. Uses **`google_auth_oauthlib.flow.Flow`** (Web Application client type — not `InstalledAppFlow`). No other module should import `google.oauth2` directly.

| Function | Purpose |
|---|---|
| `get_oauth_flow()` | Returns `Flow.from_client_secrets_file(GMAIL_CREDENTIALS_PATH, scopes=SCOPES, redirect_uri=GMAIL_REDIRECT_URI)` |
| `is_authenticated()` | Returns `True` if `GMAIL_TOKEN_PATH` exists and the loaded credentials are valid or refreshable |
| `get_credentials()` | Loads `GMAIL_TOKEN_PATH`, refreshes if expired, returns `google.oauth2.credentials.Credentials` |
| `get_auth_url()` | Generates a random hex `state`, calls `flow.authorization_url(state=state, access_type="offline", prompt="consent")`, stores `state → time.time()` in module-level `_pending_states: dict[str, float]`, removes entries older than 5 minutes, returns the URL string |
| `exchange_code(code, state)` | Validates `state` is in `_pending_states` and issued within 5 minutes (raises `ValueError` on failure); calls `flow.fetch_token(code=code)`; writes credentials to `GMAIL_TOKEN_PATH`; removes `state` from `_pending_states` |

**CSRF state storage:** `_pending_states` is a module-level dict. State is validated and deleted in `exchange_code`. Stale entries are pruned in `get_auth_url`. If the server restarts between `get_auth_url` and `exchange_code`, the state is lost and `exchange_code` raises `ValueError`, which triggers a 400 response — the user simply clicks "Connect Gmail" again to restart the flow. This is acceptable for single-tenant use.

**OAuth scopes:** `["https://www.googleapis.com/auth/gmail.modify"]`

**`GMAIL_TOKEN_PATH`** is read from `config.GMAIL_TOKEN_PATH` throughout `auth.py` — not hardcoded.

### 4.2 `crawl.py` (new file)

Historical import logic. Isolated from the main pipeline.

| Function | Purpose |
|---|---|
| `crawl_sent_emails(since_date: str, status_key: str) -> None` | Async coroutine — queries Sent, pairs with inquiries, indexes |
| `get_crawl_status(status_key: str) -> dict` | Returns `{"total": int, "indexed": int, "skipped": int, "errors": int, "done": bool}` |

**Pairing logic:**
1. Convert `since_date` from `YYYY-MM-DD` to `YYYY/MM/DD` (Gmail's `after:` operator requires slashes). Query: `in:sent after:YYYY/MM/DD`
2. For each sent message, fetch its full thread
3. Among all messages in the thread where `From` does NOT match `TARGET_EMAIL` AND `internalDate < sent_message.internalDate`, select the one with the maximum `internalDate` — i.e., the most recent qualifying customer message before the sent reply
4. If found → `await loop.run_in_executor(None, rag.index_pair, inquiry_body, sent_reply_body)` — runs blocking I/O off the event loop; increment `indexed`
5. If not found (cold outbound) → skip; increment `skipped` (not `indexed`, not `errors`)
6. On any exception for a single message → increment `errors`, continue

Between iterations, yield with `await asyncio.sleep(0)` to avoid starving the event loop.

**Progress tracking:** `_crawl_jobs: dict[str, dict]` — module-level, in-memory only. If the server restarts mid-crawl, the key disappears and the UI will see an empty/unknown status. The ChromaDB upsert is idempotent, so re-triggering the crawl is safe.

**Launch:** `POST /admin/crawl-history` is `async def`. It calls `asyncio.create_task(crawl_sent_emails(since_date, status_key))` — the correct form inside a running async context (do not use `asyncio.get_event_loop().create_task()`, which is deprecated in Python 3.10+).

### 4.3 `rag.py` (extended)

Add one function alongside the existing `retrieve_examples()`:

```python
def index_pair(inquiry: str, response: str) -> None:
    """Embed an inquiry/response pair and upsert into ChromaDB."""
```

- **Collection access:** uses `client.get_or_create_collection(COLLECTION_NAME)` — so it works before any crawl
- **Embedding:** OpenAI `text-embedding-3-small` on the `inquiry` text
- **Metadata stored:** `{"inquiry": inquiry[:2000], "response": response[:2000]}` — truncated to stay within ChromaDB metadata limits
- **Deterministic ID:** `hashlib.sha256(inquiry.encode()).hexdigest()[:16]` — deterministic across process restarts (avoids Python `hash()` randomization)
- **Write method:** `collection.upsert(ids=[doc_id], embeddings=[embedding], metadatas=[metadata])` — must use `upsert`, NOT `add`; `add` raises `chromadb.errors.DuplicateIDError` on re-crawl
- **No-op + log warning** on any exception or if `OPENAI_API_KEY` is unset

**Note on `retrieve_examples`:** The existing `_get_collection()` uses `get_collection()`. The `retrieve_examples` function guards with `if not Path(CHROMA_PATH).exists(): return None` (runs before try/except). Once `index_pair` creates the collection, `CHROMA_PATH` will exist, so this guard no longer returns early — `retrieve_examples` will proceed to call `_get_collection()`, which succeeds (collection exists), and query normally. If `index_pair` has been called at least once, there will be data; the try/except handles any query failures. **No changes needed to `retrieve_examples` or `_get_collection`.**

### 4.4 `gmail_client.py` (modified)

Replace `_get_gmail_service()`:

```python
def _get_gmail_service():
    from googleapiclient.discovery import build
    import auth
    creds = auth.get_credentials()
    return build("gmail", "v1", credentials=creds)
```

**Mock mode gate:** Both `fetch_new_emails()` and `send_reply()` check `auth.is_authenticated()`:
- If `not auth.is_authenticated()` → fall back to mock behavior (load `mock_emails.json` / print to stdout)
- If authenticated → use `_get_gmail_service()`

This replaces the old `config.GMAIL_SERVICE_ACCOUNT_PATH` check.

### 4.5 `main.py` (modified)

**New endpoints:**

```python
GET /auth/login
    → calls auth.get_auth_url()
    → returns HTTP 302 redirect to the Google consent URL

GET /auth/callback?code=...&state=...
    → calls auth.exchange_code(code, state)
    → on success: HTTP 302 redirect to /
    → on failure: HTTP 302 redirect to /?auth_error=<message> where <message> is
      urllib.parse.quote(str(e), safe='') applied to the ValueError message string
      (browser-facing endpoint; redirect on failure so dashboard can display the error;
       URL-encoding required because OAuth/ValueError messages may contain spaces and special chars)

GET /auth/status
    → returns {"connected": bool}  (calls auth.is_authenticated())

POST /admin/crawl-history         [async def]
    → body: CrawlRequest(since_date: str)  # "YYYY-MM-DD"
    → generates status_key = str(uuid.uuid4())
    → asyncio.create_task(crawl.crawl_sent_emails(since_date, status_key))
    → returns {"status_key": status_key}

GET /admin/crawl-status?key=<uuid>
    → returns crawl.get_crawl_status(key)
    → if key not found: {"total": 0, "indexed": 0, "errors": 0, "done": True}
      (done:True on missing key stops the frontend setInterval from polling forever
       if the server restarts and loses in-memory crawl state)
      Status dict shape: {"total": int, "indexed": int, "skipped": int, "errors": int, "done": bool}
      "indexed" = successfully upserted into ChromaDB; "skipped" = cold outbounds with no inquiry found
```

**Pydantic model:**
```python
class CrawlRequest(BaseModel):
    since_date: str  # "YYYY-MM-DD" ISO date string
```

**Modified endpoint:**
```
POST /emails/{id}/approve
    → (existing: load email + draft from DB, send via Gmail, update DB)
    → NEW after send: rag.index_pair(email["body"], draft["body"])
    → draft["body"] at this point is the staff-edited version (the preceding PUT /draft
      was called by the frontend before this approve request — see Section 6)
    → index_pair is called synchronously; ~1s latency is acceptable for single-tenant use.
      Note: approve_email remains a sync def; index_pair's OpenAI network call blocks a
      FastAPI thread pool worker (not the event loop). This is fine for single-tenant use.
      If ever converted to async, index_pair should be wrapped in run_in_executor.
    → return {"ok": True}
```

**Gated `/poll` endpoint:** The existing `POST /poll` manual trigger must also respect auth state:
```python
@app.post("/poll")
async def poll_now():
    if not auth.is_authenticated():
        raise HTTPException(status_code=400, detail="Gmail not connected")
    ...
```

**Poller skip when unauthenticated:**
```python
async def _poll_loop():
    while True:
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
        if not auth.is_authenticated():
            continue  # silently skip until authenticated
        try:
            ...
```

**Error format:** All new endpoints use FastAPI `HTTPException(status_code=..., detail="...")` to match the existing API's error shape `{"detail": "..."}`.

### 4.6 `static/` (modified)

**`app.js`:**
- On load, `GET /auth/status`. If `connected: false`, render a persistent top banner: `"Gmail not connected — [Connect Gmail]"`. Clicking navigates to `/auth/login`.
- On load, also check `window.location.search` for `?auth_error=...`. If present, show an error message in the auth banner (e.g., "Gmail connection failed: <message>") and clear the query param from the URL.
- Add a **Settings tab** following the same show/hide pattern as the existing admin tab. Specifically:
  - Add `settingsPanel` div
  - `showSettings()` hides `emailList`, `detailPanel`, and `adminPanel`, then shows `settingsPanel`
  - `showAdmin()` (existing) must also hide `settingsPanel` (mutual exclusion)
  - `hideSettings()` hides `settingsPanel`
  - All panel-switching functions are mutually exclusive — no two panels can be visible simultaneously
- Settings tab contents:
  - Connection status badge and account email (`TARGET_EMAIL` shown statically)
  - Date picker (`<input type="date">`) labeled "Import emails sent since:"
  - "Import History" button → `POST /admin/crawl-history` with `{"since_date": "YYYY-MM-DD"}`, stores returned `status_key`
  - Progress section: `"X of Y indexed, S skipped, Z errors"` — polls `GET /admin/crawl-status?key=<status_key>` every 2s via `setInterval`, clears interval when `done: true`

**`index.html`:** Add Settings tab nav item alongside existing tabs. Add `settingsPanel` div.

**`style.css`:** Add styles for the auth banner (fixed top bar, distinct background color), Settings tab panel, and crawl progress display.

---

## 5. Configuration Changes

### `.env.example` / `config.py`

**Remove:**
```
GMAIL_SERVICE_ACCOUNT_PATH
```

**Add:**
```
GMAIL_CREDENTIALS_PATH=./credentials.json   # OAuth client secret JSON from Google Cloud Console
GMAIL_TOKEN_PATH=./token.json               # written automatically after first sign-in
GMAIL_REDIRECT_URI=http://localhost:8000/auth/callback
```

**Unchanged:**
```
ANTHROPIC_API_KEY
OPENAI_API_KEY
TARGET_EMAIL=info@focusgraphics.net
POLL_INTERVAL_SECONDS
DB_PATH
```

`config.py` must expose `GMAIL_CREDENTIALS_PATH`, `GMAIL_TOKEN_PATH`, and `GMAIL_REDIRECT_URI` as module-level vars, and remove `GMAIL_SERVICE_ACCOUNT_PATH`.

---

## 6. Data Flow — Learning Loop

The frontend always calls `PUT /emails/{id}/draft` (saving staff edits) before calling `POST /emails/{id}/approve`. By the time the approve handler runs, `draft["body"]` fetched from the database is already the staff-edited final version. The approve handler:

1. Fetches the email and draft from DB (draft body is the edited version)
2. Sends via Gmail (existing)
3. Calls `rag.index_pair(email["body"], draft["body"])` synchronously
4. Returns `{"ok": True}`

The staff-edited draft — not the original AI-generated text — is what gets indexed. This ensures the RAG learns from human-validated responses.

---

## 7. Google Cloud Setup (one-time, operator)

1. In Google Cloud Console: create an **OAuth 2.0 Client ID** — type: **Web Application**
2. Add **Authorized redirect URI**: `http://localhost:8000/auth/callback` — this must match `GMAIL_REDIRECT_URI` exactly or Google will return a `redirect_uri_mismatch` error
3. Download the JSON → save as `credentials.json` in project root
4. First run: visit dashboard → click "Connect Gmail" banner → complete Google consent → token auto-saved to `token.json`
5. Polling and approval flow now use the OAuth token automatically

No service account, no domain-wide delegation required.

---

## 8. Security Notes

- `token.json` and `credentials.json` are already in `.gitignore` — no changes needed
- OAuth `state` parameter is validated server-side (5-minute TTL in-memory dict) to prevent CSRF
- Single-tenant; no multi-user session management needed
- `credentials.json` is never exposed via any API endpoint

---

## 9. Out of Scope

- Multi-user / multi-account support
- Gmail label changes (labeling is internal to dashboard only)
- Email attachment handling
- Crawl persistence across server restarts (re-trigger is safe — ChromaDB upsert is idempotent)
- Production OAuth redirect URI / HTTPS setup

---

## 10. File Change Summary

| File | Change |
|---|---|
| `auth.py` | **New** — OAuth2 Web Application flow, state CSRF dict, token read/write |
| `crawl.py` | **New** — historical import, date format conversion, `run_in_executor` for index_pair, in-memory progress |
| `rag.py` | **Extend** — add `index_pair()` with `get_or_create_collection`, SHA-256 ID, 2000-char truncation |
| `gmail_client.py` | **Modify** — swap `_get_gmail_service()` to use `auth.get_credentials()`; update mock-mode gate to `auth.is_authenticated()` |
| `main.py` | **Modify** — add auth + crawl endpoints; gate `/poll`; poller skips if unauthenticated; approve calls `rag.index_pair()` |
| `config.py` | **Modify** — remove `GMAIL_SERVICE_ACCOUNT_PATH`, add `GMAIL_CREDENTIALS_PATH`, `GMAIL_TOKEN_PATH`, `GMAIL_REDIRECT_URI` |
| `static/app.js` | **Modify** — auth status banner, Settings tab with show/hide pattern, crawl progress polling |
| `static/index.html` | **Modify** — Settings tab nav item and `settingsPanel` div |
| `static/style.css` | **Modify** — auth banner, Settings tab, progress bar styles |
| `.env.example` | **Update** — reflect new/removed config vars |
