import json
from datetime import datetime, timezone
from typing import Optional

import anthropic
import config
import database
import rag
from prompts import LABELS, classify_prompt, extract_prompt, draft_prompt, intake_prompt

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


def _match_job_type(job_data: dict, body: str) -> Optional[list[dict]]:
    """Find the best matching configured job type and return its questions, or None."""
    with database.get_conn() as conn:
        job_types = conn.execute("SELECT * FROM job_types").fetchall()
        if not job_types:
            return None

        names = [jt["name"] for jt in job_types]
        names_list = "\n".join(f"- {n}" for n in names)
        job_type_hint = job_data.get("job_type", "")

        prompt = f"""You are matching a print shop email to a job type.

Available job types:
{names_list}

Email body (first 400 chars):
{body[:400]}

Extracted job type from email: {job_type_hint or "not specified"}

Reply with ONLY the exact name of the best matching job type from the list above, or "none" if no match."""

        match = _claude(prompt).strip()

        matched = next((jt for jt in job_types if jt["name"].lower() == match.lower()), None)
        if not matched:
            return None

        questions = conn.execute(
            "SELECT * FROM job_type_questions WHERE job_type_id = ? ORDER BY sort_order",
            (matched["id"],),
        ).fetchall()
        return [dict(q) for q in questions]


def draft_response(body: str, job_data: dict, classification: str, thread: Optional[list] = None) -> Optional[str]:
    if classification in NO_DRAFT_LABELS:
        return None

    examples = rag.retrieve_examples(body)

    # For quote requests, use comprehensive job-type intake
    if classification == "quote_request":
        questions = _match_job_type(job_data, body)
        if questions:
            prompt = intake_prompt(body, job_data, questions, examples, thread=thread)
            return _claude(prompt)

    # Fallback: standard draft for other classifications
    required = REQUIRED_FIELDS.get(classification, [])
    missing = [f for f in required if f not in job_data]
    prompt = draft_prompt(body, job_data, missing, examples, thread=thread)
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
