from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "intake_v2_staging_config.md"
REQUIRED_V2_ENV_VARS = {
    "CVBRAIN_INTAKE_V2_API_KEY",
    "CVBRAIN_INTAKE_V2_OPENAI_API_KEY",
    "CVBRAIN_INTAKE_V2_OPENAI_MODEL",
}
LIVE_SMOKE_FLAG = "CVBRAIN_INTAKE_V2_ALLOW_LIVE_SMOKE"
V2_AUTH_HEADER = "X-CVBrain-V2-API-Key"
LEGACY_ENV_NAMES = {
    "CVBRAIN_INTAKE_API_KEY",
    "OPENAI_API_KEY",
    "CVBRAIN_OPENAI_MODEL",
}
LEGACY_ENV_TOKEN_PATTERNS = {
    name: re.compile(rf"(?<![A-Z0-9_]){re.escape(name)}(?![A-Z0-9_])") for name in LEGACY_ENV_NAMES
}
SAFE_PLACEHOLDERS = {
    "<configured-v2-model>",
    "<secret-from-secret-manager>",
}
FORBIDDEN_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bBearer\s+\S+"),
    re.compile(r"=\s*[A-Za-z0-9_./+=-]{64,}\b"),
)
LEAKAGE_SENTINELS = (
    "SOURCE_TEXT_SENTINEL",
    "PROMPT_BODY_SENTINEL",
    "PROVIDER_PAYLOAD_SENTINEL",
    "RAW_OUTPUT_SENTINEL",
    "RAW_EXCEPTION_SENTINEL",
    "SECRET_TOKEN_SENTINEL",
    "AUTH_HEADER_SENTINEL",
)


def doc_text() -> str:
    if not DOC_PATH.exists():
        pytest.fail(f"Gate 17 staging config doc is not implemented: expected {DOC_PATH}")
    return DOC_PATH.read_text(encoding="utf-8")


def folded(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower())


def assert_contains_near(text: str, anchor: str, *terms: str) -> None:
    index = text.find(anchor)
    assert index >= 0, f"{anchor} must be documented"
    window = folded(text[max(0, index - 300) : index + 500])
    for term in terms:
        assert term.lower() in window


def test_canonical_v2_staging_config_doc_exists():
    assert DOC_PATH.exists()
    assert DOC_PATH.name == "intake_v2_staging_config.md"


def test_required_v2_env_vars_and_auth_header_are_documented():
    text = doc_text()
    found_v2_names = set(re.findall(r"\bCVBRAIN_INTAKE_V2[A-Z0-9_]*\b", text))
    assert REQUIRED_V2_ENV_VARS <= found_v2_names
    assert found_v2_names <= REQUIRED_V2_ENV_VARS | {LIVE_SMOKE_FLAG}

    assert_contains_near(text, "CVBRAIN_INTAKE_V2_API_KEY", "server-side", "v2", "endpoint", "access key")
    assert V2_AUTH_HEADER in text
    assert_contains_near(text, "CVBRAIN_INTAKE_V2_OPENAI_API_KEY", "secret manager", "secure", "runtime")
    assert_contains_near(text, "CVBRAIN_INTAKE_V2_OPENAI_MODEL", "explicit", "v2", "provider")


def test_live_smoke_flag_is_documented_as_manual_and_disabled_by_default():
    text = doc_text()
    lower = folded(text)

    assert LIVE_SMOKE_FLAG in text
    assert f"{LIVE_SMOKE_FLAG}=1" in text
    assert "manual" in lower
    assert "off by default" in lower or "disabled by default" in lower
    for forbidden_default_surface in (
        "normal tests",
        "build",
        "deploy",
        "/health",
        "/intake/v2/status",
        "/intake/v2/analyze",
        "wordpress",
        "default ci",
    ):
        assert forbidden_default_surface in lower


def test_legacy_env_names_are_only_marked_do_not_use_for_v2():
    text = doc_text()
    lines = text.splitlines()

    for line_number, line in enumerate(lines):
        for legacy_name, legacy_pattern in LEGACY_ENV_TOKEN_PATTERNS.items():
            if not legacy_pattern.search(line):
                continue
            context = folded("\n".join(lines[max(0, line_number - 4) : line_number + 2]))
            assert "legacy" in context
            assert "v1" in context
            assert "do not use" in context
            assert "for v2" in context

    for legacy_name, legacy_pattern in LEGACY_ENV_TOKEN_PATTERNS.items():
        assert not re.search(
            rf"(?:--set-env-vars|--set-secrets)[^\n]*{legacy_pattern.pattern}\s*=",
            text,
        )


def test_doc_contains_no_literal_secrets_or_secret_like_values():
    text = doc_text()
    scrubbed = text
    for placeholder in SAFE_PLACEHOLDERS:
        scrubbed = scrubbed.replace(placeholder, "")

    for pattern in FORBIDDEN_SECRET_PATTERNS:
        assert not pattern.search(scrubbed)


def test_safe_staging_checklist_is_complete():
    text = doc_text()
    lower = folded(text)
    assert "checklist" in lower
    checklist_items = (
        ("v2 server api key", "secret"),
        ("v2 openai api key", "secret"),
        ("v2 openai model", "value"),
        ("/health", "generic"),
        ("get /intake/v2/status", "requires v2 auth"),
        ("post /intake/v2/analyze", "requires v2 auth"),
        ("missing provider config", "503", "unavailable"),
        ("request", "body", "source", "limits"),
        ("do not run live smoke", "explicitly gated"),
        ("do not deploy wordpress adapter",),
    )
    for item in checklist_items:
        for term in item:
            assert term in lower


def test_doc_separates_staging_config_from_push_build_deploy_authorization():
    text = doc_text()
    lower = folded(text)
    assert "does not authorize" in lower or "does not approve" in lower
    for out_of_scope in ("push", "build", "deploy", "live openai smoke", "wordpress adapter", "staging ui"):
        assert out_of_scope in lower


def test_later_deployment_config_awareness_is_documented_without_requiring_config_edits():
    text = doc_text()
    lower = folded(text)
    assert "later deployment checks" in lower
    for term in (
        "v2 env vars",
        "staging runtime",
        "secrets",
        "securely",
        "build/deploy",
        "separate approval",
        "branch",
        "upstream",
        "push plan",
    ):
        assert term in lower


def test_doc_does_not_leak_sources_prompts_provider_outputs_or_exceptions():
    text = doc_text()
    for sentinel in LEAKAGE_SENTINELS:
        assert sentinel not in text
    assert "provider raw output:" not in folded(text)
    assert "raw exception:" not in folded(text)


def test_doc_scope_is_operational_config_not_semantic_interpretation():
    text = doc_text()
    lower = folded(text)
    assert "operational" in lower
    assert "configuration" in lower
    assert "semantic interpretation" in lower
    assert "job description example" not in lower
    assert "expected role" not in lower
    assert "expected license" not in lower
