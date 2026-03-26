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
