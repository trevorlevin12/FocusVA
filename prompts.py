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


def _thread_block(thread: list[dict] | None) -> str:
    """Format a list of thread message dicts into a readable conversation log block."""
    if not thread or len(thread) <= 1:
        return ""
    parts = []
    for msg in thread:
        sender = msg.get("sender", "Unknown")
        date = msg.get("received_at", "")[:10]  # just the date portion
        body = (msg.get("body") or "").strip()
        parts.append(f"From: {sender} ({date})\n{body}")
    return "\n\nThread history (oldest to newest):\n\n" + "\n\n---\n\n".join(parts) + "\n"


def intake_prompt(
    body: str,
    job_data: dict,
    questions: list[dict],
    examples: list[dict] | None = None,
    thread: list[dict] | None = None,
) -> str:
    """Comprehensive intake — ask ALL unanswered questions in one email."""
    already_known = set(job_data.keys())
    unanswered = [q for q in questions if q["field_name"] not in already_known]

    if not unanswered:
        return draft_prompt(body, job_data, [], examples=examples, thread=thread)

    required_qs = [q for q in unanswered if q["required"]]
    optional_qs = [q for q in unanswered if not q["required"]]

    questions_block = "\n".join(
        f"{i+1}. {q['question_text']}" for i, q in enumerate(required_qs)
    )
    if optional_qs:
        questions_block += "\n\nAlso helpful if you have it:\n" + "\n".join(
            f"- {q['question_text']}" for q in optional_qs
        )

    known_lines = "\n".join(f"- {k}: {v}" for k, v in job_data.items()) if job_data else "None yet"

    examples_block = ""
    if examples:
        parts = []
        for ex in examples:
            parts.append(
                f"Customer:\n{ex['inquiry']}\n\nFocus Graphics replied:\n{ex['response']}"
            )
        examples_block = "\n\nHere are similar past exchanges to guide your tone and style:\n\n" + \
            "\n\n---\n\n".join(parts) + "\n"

    thread_block = _thread_block(thread)

    return f"""You are writing a reply for Focus Graphics, a print shop.{examples_block}{thread_block}

A customer sent this email:
{body}

Details already captured:
{known_lines}

Write ONE friendly email that collects all the information below in a single message. \
Number each required question clearly so the customer can reply point by point. \
Keep it warm and professional — not a cold form. Briefly acknowledge their request first.

Required information needed:
{questions_block}

Rules:
- Do NOT ask for information already captured above
- Do NOT invent or assume any details
- Keep the tone friendly and human, like Dylan or Jake would write it
- End with a clear call to action
- Do NOT use markdown formatting — no bold, no asterisks, no bullet points with hyphens or asterisks, no headers. Plain text only.
- Take into account any prior messages in the thread history above when crafting your reply

Reply with only the email body. No subject line, no sign-off."""


def draft_prompt(
    body: str,
    job_data: dict,
    missing_fields: list[str],
    examples: list[dict] | None = None,
    thread: list[dict] | None = None,
) -> str:
    known_lines = "\n".join(f"- {k}: {v}" for k, v in job_data.items()) if job_data else "None"
    missing_line = ", ".join(missing_fields) if missing_fields else "none — all required info present"

    examples_block = ""
    if examples:
        parts = []
        for ex in examples:
            parts.append(
                f"Customer:\n{ex['inquiry']}\n\nFocus Graphics replied:\n{ex['response']}"
            )
        examples_block = "\n\nHere are similar past exchanges to guide your tone and style:\n\n" + \
            "\n\n---\n\n".join(parts) + "\n"

    thread_block = _thread_block(thread)

    return f"""You are writing a short, friendly reply for Focus Graphics, a print shop.{examples_block}{thread_block}

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
7. Uses plain text only — no markdown, no bold, no asterisks, no bullet points, no headers
8. Takes into account any prior messages in the thread history above

If missing information is "none", write a brief confirmation that you have everything needed and will follow up shortly.

Reply with only the email body text. No subject line, no greeting like "Dear Customer", no sign-off."""
