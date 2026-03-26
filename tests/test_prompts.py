# tests/test_prompts.py
from prompts import classify_prompt, extract_prompt, draft_prompt


def test_classify_prompt_contains_all_labels():
    prompt = classify_prompt("Quote needed", "I need 100 business cards")
    assert "quote_request" in prompt
    assert "revision_request" in prompt
    assert "vendor_spam" in prompt
    assert "bid_invite" in prompt


def test_classify_prompt_contains_subject_and_body():
    prompt = classify_prompt("My subject", "My body text here")
    assert "My subject" in prompt
    assert "My body text here" in prompt


def test_classify_prompt_truncates_body_at_500_chars():
    long_body = "x" * 1000
    prompt = classify_prompt("Subject", long_body)
    # The body preview in the prompt should not exceed 500 chars of original body
    assert long_body not in prompt
    assert "x" * 500 in prompt


def test_extract_prompt_contains_body_and_classification():
    prompt = extract_prompt("I need 50 banners", "quote_request")
    assert "I need 50 banners" in prompt
    assert "quote_request" in prompt
    assert "job_type" in prompt
    assert "quantity" in prompt


def test_draft_prompt_contains_missing_fields():
    prompt = draft_prompt(
        "I need window decals",
        {"job_type": "window decals"},
        ["size", "material"]
    )
    assert "size" in prompt
    assert "material" in prompt
    assert "window decals" in prompt


def test_draft_prompt_with_no_missing_fields():
    prompt = draft_prompt(
        "I need 50 banners, 4x8 ft, vinyl",
        {"job_type": "banner", "quantity": 50, "size": "4x8", "material": "vinyl"},
        []
    )
    assert "none" in prompt.lower() or "no missing" in prompt.lower() or prompt.count("missing") >= 1


def test_draft_prompt_includes_thread_history():
    from prompts import draft_prompt
    thread = [
        {"sender": "Alice <alice@example.com>", "body": "I need 100 banners", "received_at": "2026-03-25T10:00:00+00:00"},
        {"sender": "Bob <bob@example.com>", "body": "Can you clarify size?", "received_at": "2026-03-25T11:00:00+00:00"},
    ]
    result = draft_prompt("I need 100 banners", {}, [], examples=None, thread=thread)
    assert "Thread history" in result
    assert "Alice" in result
    assert "Can you clarify size?" in result


def test_draft_prompt_no_thread_unchanged_structure():
    from prompts import draft_prompt
    result = draft_prompt("test body", {}, [], examples=None, thread=None)
    assert "Thread history" not in result
    # Still has the original email section
    assert "test body" in result


def test_intake_prompt_includes_thread_history():
    from prompts import intake_prompt
    thread = [
        {"sender": "Alice <alice@example.com>", "body": "I want a vehicle wrap", "received_at": "2026-03-25T10:00:00+00:00"},
        {"sender": "Bob <bob@example.com>", "body": "Sure, tell us more details", "received_at": "2026-03-25T11:00:00+00:00"},
    ]
    questions = [{"field_name": "vehicle_details", "question_text": "What vehicle?", "required": True}]
    result = intake_prompt("Sure, tell us more details", {}, questions, examples=None, thread=thread)
    assert "Thread history" in result
    assert "Alice" in result
    assert "vehicle wrap" in result
