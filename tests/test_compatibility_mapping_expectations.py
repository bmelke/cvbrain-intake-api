import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPAT_DIR = ROOT / "tests" / "fixtures" / "compatibility_mapping"


def load(name):
    return json.loads((COMPAT_DIR / name).read_text(encoding="utf-8"))


def test_flat_contract_required_keys_are_documented():
    payload = load("flat_contract_required_keys.json")
    required = set(payload["required_top_level_keys"])
    assert {
        "ok",
        "version",
        "role_title",
        "must_have",
        "should_have",
        "nice_to_have",
        "credentials",
        "experience",
        "location",
        "search_terms",
        "semantic_terms",
        "warnings",
        "confidence",
    }.issubset(required)
    assert set(payload["required_nested_keys"]["location"]) == {"raw", "normalized", "remote_allowed", "hybrid_allowed"}


def test_wordpress_rich_draft_required_keys_are_documented():
    payload = load("wordpress_rich_draft_required_keys.json")
    assert set(payload["required_top_level_keys"]) == {
        "job_profile",
        "requirements",
        "soft_competencies",
        "education_preferences",
        "responsibilities",
        "screening_questions",
        "search_hints",
        "missing_information",
    }
    assert "hard_filter_candidate" in payload["future_metadata_not_required_now"]
    assert "source_span" in payload["future_metadata_not_required_now"]


def test_preview_mapping_is_preview_only_and_not_executed():
    payload = load("preview_mapping_expected_keys.json")
    assert payload["expected_mode"] == "preview_only"
    assert payload["not_executed"] is True
    assert "ignored_filters" in payload["required_keys"]
    assert "location" in payload["unsupported_filters_today"]
    assert "minimum_years" in payload["unsupported_filters_today"]


def test_mapping_expectations_preserve_product_boundaries_and_privacy():
    payload = load("mapping_expectations.json")
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "candidate ranking remains Super CV-owned" in payload["boundaries"]
    assert "hard_filter_candidate is not hard_filter_approved" in payload["boundaries"]
    assert payload["privacy"]["contains_candidate_pii"] is False
    assert payload["privacy"]["candidate_ids_allowed_by_default"] is False
    assert payload["privacy"]["persisted"] is False
    assert not re.search(r"sk-proj|sk-[A-Za-z0-9]|mailto:|tel:|@[A-Za-z0-9._%+-]+\.[A-Za-z]{2,}", serialized, re.I)
