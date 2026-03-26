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
