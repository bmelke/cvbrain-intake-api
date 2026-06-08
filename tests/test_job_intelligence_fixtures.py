import json
import re
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "job_intelligence"
PII_OR_SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]|sk-proj|AIza|BEGIN (?:RSA|OPENSSH|PRIVATE) KEY|"
    r"candidate_email|mailto:|tel:|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    re.I,
)

client = TestClient(app)


def normalize(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def load_fixtures():
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIXTURE_DIR.glob("*.json"))]


FIXTURES = load_fixtures()
CURRENT_RUNTIME_FIXTURES = [f for f in FIXTURES if f.get("assertion_scope") == "current_runtime_contract"]
FUTURE_SCHEMA_FIXTURES = [f for f in FIXTURES if f.get("assertion_scope") == "future_schema_expectation"]


def payload_for(fixture):
    return {
        "source_text": fixture["source_text"],
        "source_filename": "",
        "source_mime_type": "text/plain",
        "recruiter_notes": "",
        "locale": fixture.get("locale", "es-UY"),
    }


def assert_contains_all(haystack, expected_terms, label):
    normalized = normalize(haystack)
    for term in expected_terms:
        assert normalize(term) in normalized, f"{label}: expected {term!r} in {haystack!r}"


def assert_contains_none(haystack, blocked_terms, label):
    normalized = normalize(haystack)
    for term in blocked_terms:
        assert normalize(term) not in normalized, f"{label}: blocked term leaked: {term!r}"


def test_fixture_files_are_sanitized_and_structured():
    assert len(FIXTURES) >= 21
    ids = [fixture["id"] for fixture in FIXTURES]
    assert len(ids) == len(set(ids))

    scopes = {fixture.get("assertion_scope") for fixture in FIXTURES}
    assert "current_runtime_contract" in scopes
    assert "future_schema_expectation" in scopes

    for fixture in FIXTURES:
        assert fixture["locale"]
        assert fixture["country_context"]
        assert fixture["candidate_market"]
        assert fixture["employer_market"]
        assert fixture["source_text"].strip()
        assert "expected" in fixture
        assert not PII_OR_SECRET_PATTERN.search(json.dumps(fixture, ensure_ascii=False))

        expected = fixture["expected"]
        for key in [
            "job_title",
            "location",
            "must_have_contains",
            "should_have_contains",
            "search_terms_include",
            "must_not_include",
            "warnings_include",
            "missing_information_include",
        ]:
            assert key in expected, f"{fixture['id']} missing expected.{key}"


@pytest.mark.parametrize("fixture", CURRENT_RUNTIME_FIXTURES, ids=[f["id"] for f in CURRENT_RUNTIME_FIXTURES])
def test_current_runtime_contract_fixtures(monkeypatch, fixture):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)

    response = client.post("/api/job-intake/analyze", json=payload_for(fixture))

    assert response.status_code == 200, fixture["id"]
    data = response.json()
    assert data["ok"] is True, fixture["id"]

    expected = fixture["expected"]
    runtime_expected = dict(expected)
    runtime_expected.update(expected.get("current_runtime", {}))

    assert data["role_title"] == runtime_expected["job_title"]

    if runtime_expected.get("seniority"):
        assert normalize(data["experience"].get("seniority", "")) == normalize(runtime_expected["seniority"])

    location = runtime_expected.get("location", {})
    expected_base = location.get("base")
    if expected_base is not None:
        assert normalize(data["location"].get("normalized", "")) == normalize(expected_base)

    if "remote_allowed" in location:
        assert data["location"].get("remote_allowed") is location["remote_allowed"]
    if "hybrid_allowed" in location:
        assert data["location"].get("hybrid_allowed") is location["hybrid_allowed"]

    assert_contains_all(data.get("must_have", []), runtime_expected.get("must_have_contains", []), fixture["id"])
    assert_contains_all(data.get("should_have", []), runtime_expected.get("should_have_contains", []), fixture["id"])
    assert_contains_all(data.get("nice_to_have", []), runtime_expected.get("nice_to_have_contains", []), fixture["id"])
    assert_contains_all(data.get("search_terms", []), runtime_expected.get("search_terms_include", []), fixture["id"])

    credentials = data.get("credentials", {})
    assert_contains_all(credentials.get("required", []), runtime_expected.get("credentials_required_contains", []), fixture["id"])
    assert_contains_all(credentials.get("preferred", []), runtime_expected.get("credentials_preferred_contains", []), fixture["id"])

    assert_contains_none(data, runtime_expected.get("must_not_include", []), fixture["id"])

    for unexpected_key in ["job_intelligence", "candidate_results", "candidate_ids", "salary", "currency"]:
        assert unexpected_key not in data


def test_future_schema_expectation_fixtures_are_design_only():
    assert FUTURE_SCHEMA_FIXTURES
    for fixture in FUTURE_SCHEMA_FIXTURES:
        expected = fixture["expected"]
        assert expected.get("location", {}).get("base") is not None
        assert isinstance(expected.get("must_not_include", []), list)
        assert "hard_filter_approved" not in expected or expected["hard_filter_approved"] is False
        assert not PII_OR_SECRET_PATTERN.search(json.dumps(fixture, ensure_ascii=False))


def test_required_fixture_categories_are_present():
    required_ids = {
        "uy_account_manager_medical_devices_montevideo_hybrid",
        "uy_sales_executive_b2b_montevideo_canelones",
        "uy_administrative_assistant_presencial_montevideo",
        "uy_technical_support_remote_hybrid_uruguay",
        "uy_logistics_coordinator_montevideo_canelones",
        "ar_account_manager_medical_devices_buenos_aires_caba_gba",
        "ar_sales_executive_b2b_caba_hybrid",
        "ar_technical_sales_engineer_medical_equipment_amba",
        "conflict_uy_context_source_caba_gba",
        "conflict_ar_context_source_montevideo",
        "uy_missing_location_no_default_city",
        "ar_missing_location_no_default_city",
        "uy_remote_only_no_city",
        "ar_hybrid_only_no_city",
        "spanish_hard_indicators_must_have_candidates",
        "spanish_preferred_indicators_not_hard_filters",
        "uy_driving_license_libreta_jurisdiction",
        "ar_driving_license_registro_jurisdiction",
        "education_bioengineer_biomedical_preferred",
        "search_expansion_uy_account_manager_no_argentina_leakage",
        "search_expansion_ar_account_manager_no_uruguay_leakage",
    }
    assert required_ids.issubset({fixture["id"] for fixture in FIXTURES})
