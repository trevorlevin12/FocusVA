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
