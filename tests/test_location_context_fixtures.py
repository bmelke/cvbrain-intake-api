import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCATION_CASES = ROOT / "tests" / "fixtures" / "location_context" / "location_context_cases.json"
JOB_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "job_intelligence"


def test_location_context_case_index_is_complete_and_sanitized():
    payload = json.loads(LOCATION_CASES.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert len(cases) >= 9

    case_ids = {case["id"] for case in cases}
    assert {
        "uy_montevideo_hybrid",
        "ar_buenos_aires_caba_gba",
        "cross_uy_context_caba_gba",
        "cross_ar_context_montevideo",
        "uy_missing_location",
        "ar_missing_location",
        "uy_remote_only",
        "ar_hybrid_only",
    }.issubset(case_ids)

    serialized = json.dumps(payload, ensure_ascii=False)
    assert not re.search(r"sk-proj|sk-[A-Za-z0-9]|mailto:|tel:|@[A-Za-z0-9._%+-]+\.[A-Za-z]{2,}", serialized, re.I)


def test_location_context_cases_reference_existing_job_fixtures():
    fixtures = {path.stem for path in JOB_FIXTURE_DIR.glob("*.json")}
    payload = json.loads(LOCATION_CASES.read_text(encoding="utf-8"))

    for case in payload["cases"]:
        assert case["fixture_id"] in fixtures
        expected = case["expected"]
        assert any(key in expected for key in ["base", "base_contains", "preserve", "remote_allowed", "hybrid_allowed"])


def test_cross_country_cases_require_warning_and_preserve_source():
    payload = json.loads(LOCATION_CASES.read_text(encoding="utf-8"))
    cross_cases = [case for case in payload["cases"] if case["id"].startswith("cross_")]
    assert len(cross_cases) == 2

    for case in cross_cases:
        expected = case["expected"]
        assert expected["warning"] == "country_context_mismatch"
        assert expected["preserve"]
        assert expected["must_not_include"]
