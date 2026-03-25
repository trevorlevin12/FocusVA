# FocusVA — AI Virtual Email Assistant Design Spec
**Date:** 2026-03-25
**Project:** Focus Graphics Email Assistant
**Stack:** Python / FastAPI / SQLite / Vanilla HTML+JS / Anthropic Claude API / Gmail API

---

## 1. Problem

Focus Graphics (a print shop) spends significant time managing a shared Gmail inbox — reading incoming job requests, classifying them, extracting details, and writing replies. This tool automates that pipeline while keeping humans in control of every outbound message.

---

## 2. Goals

- Connect to a shared Google Workspace Gmail inbox
- Automatically classify, extract, and draft responses for incoming emails
- Hold all drafts for human approval — nothing is ever auto-sent
- Provide a simple web dashboard for staff to review, edit, approve, or reject drafts
- Structure extracted job data in a CRM-ready format for future integration

---

## 3. Architecture

```
Gmail (Google Workspace)
        ↓  OAuth2 / Gmail API
   [ Poller ]  ← background task, runs every 2 minutes
        ↓
   [ Ingest ]  → deduplicates via gmail_message_id, stores raw email
        ↓
   [ Classifier ]  → Claude API → one of 7 classification labels
        ↓
   [ Extractor ]  → Claude API → structured job data (JSON)
        ↓
   [ Drafter ]  → Claude API → short, human-toned draft response
        ↓
   [ SQLite DB ]  → persists all state
        ↓
   [ FastAPI REST API ]
        ↓
   [ Vanilla HTML/JS Dashboard ]
        → staff reviews draft → approves or rejects
        → on approve: Gmail API sends reply in-thread
```

**Key constraint:** All drafts have `status = pending` until a staff member explicitly approves via the dashboard. No auto-sending under any circumstance.

---

## 4. Classification Labels

| Label | Description |
|---|---|
| `quote_request` | Customer wants pricing for a print job |
| `revision_request` | Customer wants changes to an existing job |
| `proof_approval` | Customer approving or rejecting a proof |
| `scheduling` | Scheduling pickup, delivery, or a meeting |
| `general_question` | General inquiry not tied to a specific job |
| `vendor_spam` | Unsolicited vendor outreach |
| `bid_invite` | Invitation to bid on a contract |

`vendor_spam` and `bid_invite` are classified and stored but **no draft is generated**. They appear in a separate low-priority tab on the dashboard.

---

## 5. Data Model (SQLite)

### `emails`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `gmail_message_id` | TEXT UNIQUE | Deduplication key |
| `thread_id` | TEXT | For in-thread replies |
| `sender` | TEXT | |
| `subject` | TEXT | |
| `body` | TEXT | Raw email body |
| `received_at` | DATETIME | |
| `classification` | TEXT | One of 7 labels |
| `status` | TEXT | `pending` / `approved` / `rejected` / `sent` |
| `processed_at` | DATETIME | When pipeline ran |

### `job_data`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `email_id` | INTEGER FK | → emails.id |
| `data` | TEXT (JSON) | Flexible blob — fields present in email only |

Expected JSON fields (only populated if found in email):
`job_type`, `quantity`, `size`, `material`, `deadline`, `contact_name`, `company`, `notes`

### `drafts`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `email_id` | INTEGER FK | → emails.id |
| `body` | TEXT | AI-generated draft (editable before approval) |
| `approved_by` | TEXT | Staff name/identifier |
| `approved_at` | DATETIME | |
| `sent_at` | DATETIME | |

---

## 6. API Endpoints

```
GET  /emails                  → list emails (filterable: ?status=pending&classification=quote_request)
GET  /emails/{id}             → single email with job_data + draft
PUT  /emails/{id}/draft       → edit draft body before approving
POST /emails/{id}/approve     → approve draft, triggers Gmail send
POST /emails/{id}/reject      → reject draft (optional body: {"note": "..."})
GET  /health                  → health check
```

Static files (dashboard HTML/CSS/JS) served by FastAPI at `/`.

---

## 7. Dashboard UI

Single HTML page, vanilla JS, no framework.

**Inbox view** (default)
- Table: received time | sender | subject | classification badge | status
- Click row → Detail view

**Detail view**
- Original email body
- Extracted job data fields
- AI draft (editable inline)
- `Approve & Send` button | `Reject` button
- Classification badge

**Sidebar/tabs**
- Pending (action required)
- Approved / Sent
- Rejected
- Spam & Bids (low priority)

No authentication — internal LAN tool. Auth can be added as a future layer.

---

## 8. Claude Prompt Strategy

Three sequential Claude API calls per email:

### Prompt 1 — Classify
- Input: subject + body (truncated to 500 chars)
- Output: single label string
- Rule: "If uncertain, pick the more actionable label."

### Prompt 2 — Extract Job Data
- Input: full email body + classification label
- Output: JSON object with only fields that are explicitly present in the email
- Rule: Never guess or fill defaults. If a field isn't mentioned, omit it.

### Prompt 3 — Draft Response
- Input: email body + extracted job data + list of missing required fields
- Output: short, plain-English reply
- Rules:
  - Acknowledge what was received
  - Confirm known details
  - Ask only for what's missing
  - Never assume or invent information
  - 2–4 sentences max
  - Skip for `vendor_spam` and `bid_invite`

**Example output:**
> "Thanks for reaching out! I see you're looking for window decals — happy to help get this quoted.
> Could you confirm the size and whether these should be removable or permanent?"

---

## 9. Gmail Integration

- **Auth:** OAuth2 with Google Cloud credentials JSON. Path set in `.env`. One-time browser consent on first run, token cached locally.
- **Polling:** Every 2 minutes (configurable). Fetches `UNREAD` + `INBOX` messages. Marks as read after processing. Deduplicates by `gmail_message_id`.
- **Sending:** On approval, replies in-thread using original `threadId` via Gmail API `messages.send`.
- **Mock mode:** If `GMAIL_CREDENTIALS_PATH` is unset, loads from `mock_emails.json` for local testing without Google setup.

---

## 10. Configuration (`.env`)

```
ANTHROPIC_API_KEY=
GMAIL_CREDENTIALS_PATH=./credentials.json
GMAIL_TOKEN_PATH=./token.json
TARGET_EMAIL=inbox@focusgraphics.com
POLL_INTERVAL_SECONDS=120
DB_PATH=./focusva.db
```

---

## 11. Project Structure

```
FocusVA/
├── main.py                  # FastAPI app entry point
├── config.py                # Settings from .env
├── database.py              # SQLite setup, models
├── gmail_client.py          # Gmail API auth + polling + send
├── pipeline.py              # classify → extract → draft orchestration
├── prompts.py               # All Claude prompt templates
├── mock_emails.json         # Sample emails for local dev
├── static/
│   ├── index.html           # Dashboard
│   ├── style.css
│   └── app.js
├── .env.example
├── requirements.txt
└── docs/
    └── superpowers/specs/
        └── 2026-03-25-email-assistant-design.md
```

---

## 12. Out of Scope (for now)

- User authentication / login
- Multi-user role permissions
- Outbound email composition (non-reply)
- CRM API integration (data is structured and ready)
- Cloud deployment
- Email attachments (images, PDFs)
