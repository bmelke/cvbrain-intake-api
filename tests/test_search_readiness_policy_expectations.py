import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JOB_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "job_intelligence"
POLICY_PATH = ROOT / "tests" / "fixtures" / "compatibility_mapping" / "search_readiness_policy.json"


def load_fixture(fixture_id):
    return json.loads((JOB_FIXTURE_DIR / f"{fixture_id}.json").read_text(encoding="utf-8"))


def test_search_readiness_policy_statuses_and_decisions_are_documented():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert policy["statuses"] == [
        "ready",
        "usable_with_warnings",
        "exploratory",
        "insufficient_for_precise_search",
        "blocked_for_safety_or_technical_reason",
    ]
    assert "blocked_for_safety_or_technical_reason" not in policy["proceed_allowed_statuses"]
    assert "continue_anyway" in policy["decision_options"]
    assert "answer_clarifying_questions" in policy["decision_options"]
    assert "company_clarification_questions_unanswered" in policy["must_not_block_merely_because"]


def test_ambiguous_clerk_search_can_continue_and_does_not_invent_specifics():
    fixture = load_fixture("ambiguous_clerk_search_continue_anyway")
    expected = fixture["expected"]
    readiness = expected["search_readiness"]

    assert readiness["status"] in {"exploratory", "insufficient_for_precise_search"}
    assert readiness["proceed_allowed"] is True
    assert "continue_anyway" in readiness["decision_options"]
    assert expected["company_clarification_questions"]
    assert "location" in expected["missing_information_include"]
    assert "industry" in expected["missing_information_include"]
    assert expected["location"]["base"] == ""
    assert expected["industries"] == []
    assert expected["must_have_contains"] == []
    assert expected["hard_filter_approved"] is False
    assert "CRM" in expected["must_not_include"]
    assert "salary" in expected["must_not_include"]


def test_vague_sales_manager_can_continue_and_negotiation_is_interview_verifiable():
    fixture = load_fixture("vague_sales_manager_negotiation_continue_anyway")
    expected = fixture["expected"]
    readiness = expected["search_readiness"]

    assert readiness["status"] in {"exploratory", "usable_with_warnings"}
    assert readiness["proceed_allowed"] is True
    assert "continue_anyway" in readiness["decision_options"]
    assert expected["company_clarification_questions"]
    assert "negotiation" in expected["soft_competencies_contains"]
    assert expected["negotiation_hard_resume_filter"] is False
    assert expected["hard_filter_approved"] is False
    assert expected["industries"] == []
    assert expected["location"]["base"] == ""
    for invented in ["B2B", "B2C", "CRM", "team size", "compensation", "travel", "Montevideo"]:
        assert invented in expected["must_not_include"]


def test_blocked_status_is_reserved_for_safety_or_technical_cases():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    assert policy["blocked_status"] == "blocked_for_safety_or_technical_reason"
    assert set(policy["block_only_when"]) == {
        "empty_source_text",
        "unsafe_or_prohibited_request",
        "discriminatory_or_protected_filtering_request",
        "api_security_or_permission_failure",
        "technical_extraction_failure_without_fallback",
    }
    assert "location_missing" in policy["must_not_block_merely_because"]
    assert "requirements_vague" in policy["must_not_block_merely_because"]
