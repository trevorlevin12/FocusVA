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
