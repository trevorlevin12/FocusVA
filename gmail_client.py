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
