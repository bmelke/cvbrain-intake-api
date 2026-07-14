from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "intake_v2_consumer_contract.md"

STATUS_PATH = "GET /intake/v2/status"
ANALYZE_PATH = "POST /intake/v2/analyze"
V2_AUTH_HEADER = "X-CVBrain-V2-API-Key"
V2_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"
REQUEST_BODY_LIMIT_BYTES = "262144"
SOURCE_TEXT_LIMIT_CHARS = "50000"
SUCCESS_ENVELOPE_KEYS = {"ok", "status", "schema_version", "display_plan", "metadata"}
REQUIRED_BODY_FIELDS = {"source_text", "source_language"}
FORBIDDEN_V1_AUTH_HEADERS = {
    "X-CVBrain-API-Key",
    "X-TrabajoAca-API-Key",
    "Authorization: Bearer",
}
SAFE_PLACEHOLDERS = {
    "<server-side-v2-api-key>",
    "<source text from recruiter input>",
}
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bBearer[ \t]+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{64,}(?![A-Za-z0-9])"),
)
PII_OR_REAL_DATA_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\+?\d[\d\s().-]{7,}"),
)


def consumer_doc_text() -> str:
    if not DOC_PATH.exists():
        pytest.fail(f"Gate 21 consumer contract doc is not implemented: expected {DOC_PATH}")
    return DOC_PATH.read_text(encoding="utf-8")


def folded(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower())


def assert_terms_near(
    text: str,
    anchor: str,
    *terms: str,
    before: int = 300,
    after: int = 700,
) -> None:
    folded_text = folded(text)
    folded_anchor = folded(anchor)
    index = folded_text.find(folded_anchor)
    assert index >= 0, f"{anchor} must be documented"
    window = folded_text[max(0, index - before) : index + after]
    for term in terms:
        assert folded(term) in window, f"{term!r} must be documented near {anchor!r}"


def test_consumer_contract_doc_target_is_locked():
    assert DOC_PATH == ROOT / "docs" / "intake_v2_consumer_contract.md"
    assert DOC_PATH.exists()


def test_consumer_contract_documents_v2_endpoints_and_server_side_auth_only():
    text = consumer_doc_text()

    assert STATUS_PATH in text
    assert ANALYZE_PATH in text
    assert V2_AUTH_HEADER in text
    assert_terms_near(text, V2_AUTH_HEADER, "server-side", "never", "browser", "public html", "logs")
    assert_terms_near(text, V2_AUTH_HEADER, "analytics", "client-side", "config")

    for forbidden_header in FORBIDDEN_V1_AUTH_HEADERS:
        assert forbidden_header in text
        assert_terms_near(text, forbidden_header, "must not", "fallback", "v2")


def test_consumer_contract_documents_request_body_and_no_php_inference():
    text = consumer_doc_text()

    assert_terms_near(text, ANALYZE_PATH, "json", "source_text", "source_language")
    for field in REQUIRED_BODY_FIELDS:
        assert field in text
    assert_terms_near(text, "source_text", "non-empty")
    assert_terms_near(text, "source_language", "explicit", "auto", "must not infer", "php")
    assert_terms_near(text, "source_language", "auto", "cvbrain", "ai", "determine")
    assert_terms_near(text, ANALYZE_PATH, "must not", "classify", "normalize", "job", "domain", "before sending")
    assert_terms_near(text, "grammar", "must not", "correct", "php")


def test_consumer_contract_documents_request_limits_and_413_handling():
    text = consumer_doc_text()

    assert REQUEST_BODY_LIMIT_BYTES in text
    assert SOURCE_TEXT_LIMIT_CHARS in text
    assert_terms_near(text, REQUEST_BODY_LIMIT_BYTES, "request body", "bytes", "precheck")
    assert_terms_near(text, SOURCE_TEXT_LIMIT_CHARS, "source_text", "characters", "precheck")
    assert_terms_near(text, "413", "too large", "safe")


def test_consumer_contract_documents_public_response_envelope_without_reinterpretation():
    text = consumer_doc_text()

    for key in SUCCESS_ENVELOPE_KEYS:
        assert key in text
    assert V2_RESPONSE_SCHEMA_VERSION in text
    assert_terms_near(text, "display_plan", "render", "safe")
    assert_terms_near(text, "display_plan", "must not", "reinterpret", "semantic")
    assert_terms_near(text, "display_plan", "recruiter-facing", "Search Brief", "contract")
    for section in (
        "comparison_basis",
        "must_have_criteria",
        "nice_to_have_criteria",
        "questions_for_recruiter",
        "missing_information_or_blockers",
        "search_readiness",
        "recommended_next_steps",
    ):
        assert section in text
    assert_terms_near(text, "must_have_criteria", "explicit", "hard", "requirements")
    assert_terms_near(text, "nice_to_have_criteria", "preferred", "appreciated", "items")
    assert_terms_near(text, "questions_for_recruiter", "separate", "criteria")
    assert_terms_near(text, "questions_for_recruiter", "must not", "infer", "must-have", "nice-to-have")
    assert_terms_near(text, "questions_for_recruiter", "must not", "generate", "missing criteria")
    assert_terms_near(text, "search_readiness", "render", "search", "recommended")
    assert_terms_near(text, "recommended_next_steps", "render", "next", "steps")
    assert "recommendation_summary" in text
    assert_terms_near(text, "recommendation_summary", "AI-owned", "human-readable", "recruiter-facing", "render")
    assert_terms_near(text, "recommended_next_steps", "AI-owned", "human-readable", "recruiter-facing", "render")
    assert_terms_near(text, "search_readiness", "must not", "generate", "themselves")
    assert_terms_near(text, "recommended_next_steps", "must not", "generate", "themselves")


def test_consumer_contract_documents_safe_error_and_unavailable_handling():
    text = consumer_doc_text()

    for status_code, label in (
        ("400", "request validation"),
        ("401", "unauthorized"),
        ("413", "too large"),
        ("503", "unavailable"),
    ):
        assert_terms_near(text, status_code, label, "safe")
    assert_terms_near(text, "503", "retry", "degraded", "unavailable")

    for forbidden_public_detail in (
        "secrets",
        "raw source text",
        "prompt text",
        "provider payload",
        "provider output",
        "raw exception text",
    ):
        assert forbidden_public_detail in folded(text)


def test_consumer_contract_locks_semantic_ownership_boundary():
    text = consumer_doc_text()
    lower = folded(text)

    assert "cvbrain is the semantic brain" in lower
    assert "trabajoaca" in lower
    assert "wordpress" in lower
    assert "only consume and render" in lower

    forbidden_php_behaviors = (
        "role/title interpretation",
        "license interpretation",
        "credential interpretation",
        "blocker interpretation",
        "required/preferred/nice-to-have interpretation",
        "source_language inference",
        "grammar correction",
        "domain phrase mapping",
        "hardcoded title/role dictionaries",
        "fallback semantic logic",
        "direct openai calls",
        "provider execution logic",
    )
    for behavior in forbidden_php_behaviors:
        assert behavior in lower
        assert_terms_near(text, behavior, "no", "wordpress", "php")


def test_consumer_contract_documents_security_and_logging_boundaries():
    text = consumer_doc_text()
    lower = folded(text)

    forbidden_logged_values = (
        "v2 api key",
        "auth headers",
        "raw source_text",
        "prompts",
        "provider payloads",
        "provider raw output",
        "raw exceptions",
        "openai keys",
        "model/env values",
    )
    for value in forbidden_logged_values:
        assert value in lower
        assert_terms_near(text, value, "must not", "log", "store", "expose")


def test_consumer_contract_locks_wordpress_adapter_boundary():
    text = consumer_doc_text()
    lower = folded(text)

    assert "does not authorize wordpress implementation" in lower
    assert "later separate gate" in lower
    assert_terms_near(text, "WordPress", "server-side", "call", "cvbrain api")
    assert_terms_near(text, "WordPress", "render", "safely")
    assert_terms_near(text, "WordPress", "must not", "ai", "domain interpretation")
    assert_terms_near(text, "OpenAI", "WordPress", "must not", "directly")


def test_consumer_contract_separates_consumer_work_from_live_smoke():
    text = consumer_doc_text()
    lower = folded(text)

    assert "live smoke is separate" in lower
    assert "no default live smoke" in lower
    assert "no consumer-triggered live smoke" in lower
    assert "no wordpress-triggered live smoke" in lower
    assert "staging analyze smoke" in lower
    assert "does not authorize adapter work" in lower


def test_consumer_contract_contains_no_literal_secrets_tokens_or_real_data_examples():
    text = consumer_doc_text()
    scrubbed = text
    for placeholder in SAFE_PLACEHOLDERS:
        scrubbed = scrubbed.replace(placeholder, "")

    for pattern in SECRET_PATTERNS:
        assert not pattern.search(scrubbed), f"secret-like literal is forbidden: {pattern.pattern}"
    for pattern in PII_OR_REAL_DATA_PATTERNS:
        assert not pattern.search(scrubbed), f"PII-like example is forbidden: {pattern.pattern}"

    lower = folded(text)
    forbidden_semantic_fixture_terms = (
        "expected role_title",
        "expected license",
        "expected credential",
        "real cv data",
        "real recruiter data",
        "real company name",
        "wordpress production data",
    )
    for term in forbidden_semantic_fixture_terms:
        assert term not in lower

def test_consumer_contract_documents_global_experience_questions_without_consumer_inference():
    text = consumer_doc_text()

    assert_terms_near(
        text,
        "global vague-experience clarification",
        "duration/time",
        "similarity",
        "depth",
        "scale/volume",
        "recency",
        "evidence",
        "criticality",
    )
    assert_terms_near(text, "experience clarification", "most relevant", "missing", "not", "every")
    assert_terms_near(text, "questions_for_recruiter", "experience", "separate", "criteria")
    assert_terms_near(text, "soft-skill assessment boundary", "observable behaviors", "recruiter/team", "assessment technique")
    assert_terms_near(text, "protected traits", "age", "sex", "gender", "must not", "criteria")
    assert_terms_near(
        text,
        "contractual/business baseline",
        "mandatory intake coverage",
        "salary",
        "hiring mode",
        "contract type",
        "schedule",
        "availability",
        "location/work modality",
        "start date/urgency",
    )
    assert_terms_near(text, "contractual/business baseline", "one compact grouped question", "acceptable")
    assert_terms_near(text, "contractual/business baseline", "not", "candidate criteria")
    assert "when absent and relevant" not in folded(text)
    assert_terms_near(text, "experience clarification", "must not", "php", "classify")
