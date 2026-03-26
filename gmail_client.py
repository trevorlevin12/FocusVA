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
