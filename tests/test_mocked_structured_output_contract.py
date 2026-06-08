import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

from app.mappers.job_intelligence_to_flat import derive_flat_compatibility
from app.schemas.job_intelligence_v1_contract import (
    JobIntelligenceValidationError,
    validate_job_intelligence_v1,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "mocked_ai_outputs"
REQUIREMENTS_PATH = ROOT / "requirements.txt"

PII_OR_SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]|sk-proj|AIza|BEGIN (?:RSA|OPENSSH|PRIVATE) KEY|"
    r"candidate_email|mailto:|tel:|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    re.I,
)


def normalize(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def load_fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def load_all_fixtures():
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIXTURE_DIR.glob("*.json"))]


FIXTURES = load_all_fixtures()


@pytest.mark.parametrize("fixture", FIXTURES, ids=[fixture["fixture_id"] for fixture in FIXTURES])
def test_mocked_ai_outputs_validate_and_derive_flat_contract(fixture):
    validate_job_intelligence_v1(fixture)

    flat = derive_flat_compatibility(fixture)
    expected = fixture["flat_compatibility"]

    assert flat["role_title"] == expected["role_title"]
    assert flat["must_have"] == expected["must_have"]
    assert flat["should_have"] == expected["should_have"]
    assert flat["nice_to_have"] == expected["nice_to_have"]
    assert flat["credentials"] == expected["credentials"]
    assert flat["experience"] == expected["experience"]
    assert flat["location"]["normalized"] == expected["location"]["normalized"]
    assert flat["location"]["hybrid_allowed"] == expected["location"]["hybrid_allowed"]
    assert flat["search_terms"] == expected["search_terms"]
    assert flat["semantic_terms"] == expected["semantic_terms"]
    assert flat["recruiter_questions"] == expected["recruiter_questions"]
    assert flat["warnings"] == expected["warnings"]
    assert flat["confidence"] == expected["confidence"]

    required_flat_keys = {
        "role_title",
        "must_have",
        "should_have",
        "nice_to_have",
        "credentials",
        "experience",
        "location",
        "search_terms",
        "semantic_terms",
        "recruiter_questions",
        "warnings",
        "confidence",
    }
    assert required_flat_keys.issubset(flat)
    assert "candidate_results" not in flat
    assert "candidate_ids" not in flat


def test_mocked_ai_fixture_set_is_complete_and_sanitized():
    expected_names = {
        "uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json",
        "ar_account_manager_medical_devices_caba_gba_ai_output.json",
        "uy_caba_context_mismatch_ai_output.json",
        "ambiguous_clerk_continue_anyway_ai_output.json",
        "vague_sales_manager_negotiation_ai_output.json",
    }
    actual_names = {path.name for path in FIXTURE_DIR.glob("*.json")}

    assert expected_names.issubset(actual_names)
    for fixture in FIXTURES:
        serialized = json.dumps(fixture, ensure_ascii=False)
        assert not PII_OR_SECRET_PATTERN.search(serialized)
        assert fixture["quality_control"]["contains_candidate_data"] is False
        assert fixture["quality_control"]["contains_candidate_pii"] is False


def test_uruguay_account_manager_fixture_has_no_argentina_leakage():
    fixture = load_fixture("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    flat = derive_flat_compatibility(fixture)
    serialized = normalize(fixture)

    assert fixture["job_profile"]["normalized_role_title"] == "Account Manager Semi Senior"
    assert "dispositivos medicos" in normalize(fixture["job_profile"]["primary_industries"])
    assert flat["location"]["normalized"] == "Montevideo"
    assert flat["location"]["hybrid_allowed"] is True
    assert flat["experience"]["minimum_years"] == 3
    assert "dispositivos medicos" in normalize(flat["search_terms"])
    for blocked in ["Argentina", "Buenos Aires", "CABA", "GBA"]:
        assert normalize(blocked) not in serialized


def test_argentina_account_manager_fixture_has_no_uruguay_leakage():
    fixture = load_fixture("ar_account_manager_medical_devices_caba_gba_ai_output.json")
    flat = derive_flat_compatibility(fixture)
    serialized = normalize(fixture)

    assert flat["location"]["normalized"] == "Buenos Aires / CABA / GBA"
    assert "CABA" in flat["search_terms"]
    assert "GBA" in flat["search_terms"]
    for blocked in ["Montevideo", "Canelones"]:
        assert normalize(blocked) not in serialized


def test_country_mismatch_preserves_source_location_and_warns():
    fixture = load_fixture("uy_caba_context_mismatch_ai_output.json")
    flat = derive_flat_compatibility(fixture)

    assert fixture["location_intelligence"]["normalized"] == "CABA / GBA"
    assert fixture["location_intelligence"]["country_context_mismatch"] is True
    assert "country_context_mismatch" in flat["warnings"]
    assert "search_readiness_usable_with_warnings" in flat["warnings"]
    assert "Montevideo" not in json.dumps(fixture, ensure_ascii=False)


def test_ambiguous_clerk_can_continue_without_invented_specifics():
    fixture = load_fixture("ambiguous_clerk_continue_anyway_ai_output.json")
    flat = derive_flat_compatibility(fixture)
    readiness = fixture["search_readiness"]

    assert readiness["status"] in {"exploratory", "insufficient_for_precise_search"}
    assert readiness["proceed_allowed"] is True
    assert "continue_anyway" in readiness["decision_options"]
    assert fixture["company_clarification_questions"]
    assert fixture["missing_information"]
    assert fixture["job_profile"]["primary_industries"] == []
    assert fixture["requirements"]["must_have"] == []
    assert flat["location"]["normalized"] == ""
    assert "search_readiness_exploratory" in flat["warnings"]

    serialized = normalize(fixture)
    for invented in ["CRM", "Excel", "SAP", "salary", "compensation", "Montevideo", "CABA"]:
        assert normalize(invented) not in serialized


def test_vague_sales_manager_keeps_negotiation_as_interview_verifiable():
    fixture = load_fixture("vague_sales_manager_negotiation_ai_output.json")
    flat = derive_flat_compatibility(fixture)

    soft_competencies = fixture["requirements"]["soft_competencies"]
    assert fixture["search_readiness"]["proceed_allowed"] is True
    assert fixture["company_clarification_questions"]
    assert fixture["candidate_screening_questions"]
    assert fixture["requirements"]["must_have"] == []
    assert soft_competencies[0]["text"] == "Negotiation"
    assert soft_competencies[0]["evidence_expected"] == "interview"
    assert soft_competencies[0]["hard_filter_candidate"] is False
    assert soft_competencies[0]["hard_filter_approved"] is False
    assert "Negotiation" not in flat["must_have"]

    serialized = normalize(fixture)
    for invented in ["B2B", "B2C", "CRM", "compensation", "travel", "Montevideo"]:
        assert normalize(invented) not in serialized


def test_preferred_items_do_not_become_hard_filter_approved():
    fixture = load_fixture("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    validate_job_intelligence_v1(fixture)

    assert any(item["hard_filter_candidate"] and not item["hard_filter_approved"] for item in fixture["requirements"]["must_have"])
    for group in ("should_have", "nice_to_have", "soft_competencies"):
        for item in fixture["requirements"][group]:
            assert item["hard_filter_approved"] is False


def test_validator_rejects_preferred_hard_filter_approval():
    fixture = load_fixture("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    fixture["requirements"]["should_have"][0]["hard_filter_approved"] = True
    fixture["requirements"]["should_have"][0]["hard_filter_candidate"] = True

    with pytest.raises(JobIntelligenceValidationError):
        validate_job_intelligence_v1(fixture)


def test_mocked_contract_layer_has_no_runtime_openai_import():
    requirements = REQUIREMENTS_PATH.read_text(encoding="utf-8")

    assert "openai" in requirements.lower()
    assert "openai" not in sys.modules
