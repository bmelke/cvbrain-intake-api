from __future__ import annotations

import copy
import json
import re

import pytest
from pydantic import ValidationError

from app.intake_v2.contract import JobIntelligenceDraftV2
from app.intake_v2.integrity import internalize_draft_v2
from app.intake_v2.display_plan import build_display_plan_v2
from app.intake_v2.response import build_public_response_v2
from app.intake_v2.search_execution_contract import (
    CONTRACT_SCHEMA_VERSION,
    SearchExecutionContractV1,
    build_search_execution_contract_v1,
    canonicalize_search_execution_contract_v1,
    compute_search_execution_contract_digest,
)


FORBIDDEN_KEYS = {
    "source_text",
    "raw_source",
    "uploaded_file_contents",
    "prompt",
    "provider_payload",
    "raw_provider_output",
    "api_key",
    "authorization",
    "headers",
    "browser",
    "session",
    "cookie",
    "recruiter_identity",
    "candidate_ids",
    "candidate_cvs",
    "candidate_scores",
    "candidate_rankings",
    "selected_candidates",
    "wordpress_post_ids",
    "transient_keys",
}


def draft() -> dict:
    return {
        "schema_version": "cvbrain_job_intelligence_v2",
        "job_profile": {
            "role_title": "Account Manager",
            "role_family": "Commercial",
            "professional_grade": None,
            "seniority": "Semi Senior",
            "summary": "AI-owned profile summary",
            "industries": ["Medical devices"],
        },
        "location_and_modality": {
            "raw_location": "CABA",
            "normalized_location": "Buenos Aires",
            "country_code": "AR",
            "city": "CABA",
            "region": "Buenos Aires",
            "work_modality": "hybrid",
            "remote_allowed": True,
            "hybrid_allowed": True,
            "onsite_required": False,
            "countries": ["AR"],
            "regions": ["Buenos Aires"],
            "cities": ["CABA"],
            "travel_requirement": "unresolved",
            "relocation_requirement": "not_required",
        },
        "criteria": [
            {
                "local_ref": "criterion_experience",
                "criterion_kind": "experience",
                "text": "Tres anos en dispositivos medicos",
                "source_evidence": "3 anos en dispositivos medicos",
                "importance": "must_have",
                "explicit": True,
                "precision_status": "precise",
                "missing_dimensions": [],
                "clarification_question_ref": None,
                "criterion_id": "criterion_experience",
                "scope": "candidate_filter",
                "operator": "greater_than_or_equal",
                "operand": "3",
                "unit": "years",
                "evidence_requirement": "cv_evidence",
                "experience_domain": "Medical devices commercial work",
                "minimum_value": 3.0,
                "maximum_value": None,
                "recency_requirement": None,
                "scale_or_scope": "Large accounts",
                "credential_name": None,
                "credential_issuer": None,
                "license_name": None,
                "license_category": None,
                "license_jurisdictions": [],
            },
            {
                "local_ref": "criterion_license",
                "criterion_kind": "license",
                "text": "Licencia profesional vigente",
                "source_evidence": "licencia profesional vigente",
                "importance": "must_have",
                "explicit": True,
                "precision_status": "needs_clarification",
                "missing_dimensions": ["license_category"],
                "clarification_question_ref": "question_license",
                "criterion_id": "criterion_license",
                "scope": "candidate_filter",
                "operator": "equals",
                "operand": None,
                "unit": None,
                "evidence_requirement": "official_document",
                "experience_domain": None,
                "minimum_value": None,
                "maximum_value": None,
                "recency_requirement": None,
                "scale_or_scope": None,
                "credential_name": None,
                "credential_issuer": None,
                "license_name": "Licencia profesional",
                "license_category": None,
                "license_jurisdictions": ["AR"],
            },
            {
                "local_ref": "criterion_credential",
                "criterion_kind": "credential",
                "text": "Titulo habilitante",
                "source_evidence": "titulo habilitante",
                "importance": "should_have",
                "explicit": True,
                "precision_status": "precise",
                "missing_dimensions": [],
                "clarification_question_ref": None,
                "criterion_id": "criterion_credential",
                "scope": "ranking_signal",
                "operator": "equals",
                "operand": "Titulo habilitante",
                "unit": None,
                "evidence_requirement": "official_document",
                "experience_domain": None,
                "minimum_value": None,
                "maximum_value": None,
                "recency_requirement": None,
                "scale_or_scope": None,
                "credential_name": "Titulo habilitante",
                "credential_issuer": None,
                "license_name": None,
                "license_category": None,
                "license_jurisdictions": [],
            },
            {
                "local_ref": "criterion_exclusion",
                "criterion_kind": "blocker",
                "text": "No ejecutar hasta aclarar documentacion",
                "source_evidence": "no avanzar",
                "importance": "blocker",
                "explicit": True,
                "precision_status": "precise",
                "missing_dimensions": [],
                "clarification_question_ref": None,
                "criterion_id": "criterion_exclusion",
                "scope": "exclusion",
                "operator": "equals",
                "operand": "missing_documentation",
                "unit": None,
                "evidence_requirement": "official_document",
                "experience_domain": None,
                "minimum_value": None,
                "maximum_value": None,
                "recency_requirement": None,
                "scale_or_scope": None,
                "credential_name": None,
                "credential_issuer": None,
                "license_name": None,
                "license_category": None,
                "license_jurisdictions": [],
            },
        ],
        "company_questions": [
            {
                "local_ref": "question_license",
                "question": "Que categoria de licencia aplica?",
                "audience": "hiring_company",
                "category": "search_precision",
                "criterion_refs": ["criterion_license"],
                "missing_dimensions": ["license_category"],
                "blocking_level": "important",
            }
        ],
        "candidate_screening_questions": [],
        "search_strategy": {
            "target_titles": ["Account Manager", "Key Account Manager"],
            "search_terms": ["medical devices", "key accounts"],
            "semantic_terms": ["healthcare commercial"],
            "negative_terms": [],
            "resolved_source_language": "es",
            "must_have_criterion_refs": ["criterion_experience", "criterion_license"],
            "preferred_criterion_refs": ["criterion_credential"],
            "exclusion_criterion_refs": ["criterion_exclusion"],
            "unresolved_criterion_refs": ["criterion_license"],
            "protected_traits_excluded": True,
            "contract_state": "safe",
        },
        "search_readiness": {
            "status": "usable_with_warnings",
            "proceed_allowed": True,
            "recommended_action": "ask_company",
            "recruiter_decision_required": True,
            "continued_with_missing_information": True,
            "recommendation_summary": "Puede iniciarse con advertencias.",
            "recommended_next_steps": ["Aclarar la licencia."],
            "contractual_baseline_questions": [],
        },
        "quality_control": {
            "warnings": [],
            "confidence": 0.9,
            "contains_candidate_data": False,
            "contains_candidate_pii": False,
        },
    }


def service_result(payload: dict | None = None) -> dict:
    internalized = internalize_draft_v2(payload or draft())
    return {
        "ok": True,
        "status": "ok",
        "schema_version": "cvbrain_intake_v2_service",
        "document": internalized["document"],
        "integrity": internalized["integrity"],
    }


def built_contract(payload: dict | None = None, *, source_language: str = "auto") -> dict:
    return build_search_execution_contract_v1(service_result(payload), source_language=source_language)


def test_contract_is_strict_typed_and_contains_required_machine_areas():
    contract = built_contract()

    assert contract["schema_version"] == CONTRACT_SCHEMA_VERSION == "cvbrain_confirmed_search_contract_v1"
    assert SearchExecutionContractV1.model_config["extra"] == "forbid"
    assert contract["source_language"] == {
        "source_language_mode": "auto",
        "resolved_source_language": "es",
    }
    assert contract["readiness"]["unresolved_question_ids"]
    assert contract["role_profile"]["primary_title"] == "Account Manager"
    assert contract["role_profile"]["alternate_titles"] == ["Account Manager", "Key Account Manager"]
    assert contract["location_and_work_arrangement"]["countries"] == ["AR"]
    assert contract["criteria"][0]["operator"] == "greater_than_or_equal"
    assert contract["experience_requirements"][0]["minimum_value"] == 3.0
    assert contract["credentials"][0]["credential_name"] == "Titulo habilitante"
    assert contract["licenses"][0]["license_name"] == "Licencia profesional"
    assert contract["exclusions"][0]["criterion_id"] in contract["search_strategy"]["exclusion_criterion_ids"]
    assert contract["safety"] == {
        "protected_traits_excluded": True,
        "no_candidate_selection_performed": True,
        "no_candidate_data_included": True,
        "contract_state": "safe",
    }
    assert re.fullmatch(r"[0-9a-f]{64}", contract["contract_digest"])

    hostile = copy.deepcopy(contract)
    hostile["unexpected"] = True
    with pytest.raises(ValidationError):
        SearchExecutionContractV1.model_validate(hostile)


def test_digest_is_deterministic_excludes_itself_and_changes_with_approved_data():
    first = built_contract()
    second = built_contract()
    assert first == second
    assert compute_search_execution_contract_digest(first) == first["contract_digest"]

    changed_draft = draft()
    changed_draft["criteria"][0]["minimum_value"] = 4.0
    changed_draft["criteria"][0]["operand"] = "4"
    changed = built_contract(changed_draft)
    assert changed["contract_digest"] != first["contract_digest"]

    explicit = built_contract(source_language="es")
    assert explicit["source_language"]["source_language_mode"] == "explicit"
    assert explicit["source_language"]["resolved_source_language"] == "es"
    assert explicit["contract_digest"] != first["contract_digest"]

    tampered = copy.deepcopy(first)
    tampered["contract_digest"] = "0" * 64
    assert compute_search_execution_contract_digest(tampered) == first["contract_digest"]
    with pytest.raises(ValidationError):
        canonicalize_search_execution_contract_v1(tampered)
    assert canonicalize_search_execution_contract_v1(first) == first


@pytest.mark.parametrize("legacy_mode", ["ai_resolved", "consumer_declared", "unresolved"])
def test_legacy_source_language_modes_are_rejected(legacy_mode: str):
    contract = built_contract()
    contract["source_language"]["source_language_mode"] = legacy_mode
    contract["contract_digest"] = compute_search_execution_contract_digest(contract)
    with pytest.raises(ValidationError):
        SearchExecutionContractV1.model_validate(contract)


def test_ai_draft_cannot_supply_or_override_request_source_language_mode():
    payload = draft()
    payload["search_strategy"]["source_language_mode"] = "explicit"
    with pytest.raises(ValidationError):
        JobIntelligenceDraftV2.model_validate(payload)


def test_referential_integrity_rejects_duplicate_and_unknown_ids():
    contract = built_contract()

    duplicate = copy.deepcopy(contract)
    duplicate["criteria"][1]["criterion_id"] = duplicate["criteria"][0]["criterion_id"]
    duplicate["contract_digest"] = compute_search_execution_contract_digest(duplicate)
    with pytest.raises(ValidationError):
        SearchExecutionContractV1.model_validate(duplicate)

    reference_paths = [
        ("search_strategy", "must_have_criterion_ids"),
        ("experience_requirements", 0, "criterion_id"),
        ("credentials", 0, "criterion_id"),
        ("licenses", 0, "criterion_id"),
        ("criteria", 1, "clarification_question_ids"),
    ]
    for path in reference_paths:
        invalid = copy.deepcopy(contract)
        target = invalid
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = ["unknown"] if path[-1] != "criterion_id" else "unknown"
        invalid["contract_digest"] = compute_search_execution_contract_digest(invalid)
        with pytest.raises(ValidationError):
            SearchExecutionContractV1.model_validate(invalid)


def test_privacy_boundary_excludes_forbidden_data_and_candidate_logic():
    result = service_result()
    result.update(
        {
            "source_text": "private source",
            "provider_payload": {"raw_provider_output": "private"},
            "candidate_ids": [123],
            "candidate_scores": [99],
        }
    )
    contract = build_search_execution_contract_v1(result, source_language="auto")
    rendered = json.dumps(contract, sort_keys=True).lower()
    assert all(key not in rendered for key in FORBIDDEN_KEYS)


def test_display_plan_wording_is_not_an_input_to_contract_or_digest():
    result = service_result()
    result["display_plan"] = {"sections": [{"code": "must_have_criteria", "items": ["wording one"]}]}
    first = build_search_execution_contract_v1(result, source_language="auto")
    result["display_plan"]["sections"][0]["items"] = ["completely different wording"]
    second = build_search_execution_contract_v1(result, source_language="auto")
    assert first == second


def test_unresolved_typed_values_remain_unresolved_without_prose_parsing():
    payload = draft()
    payload["criteria"][1]["text"] = "Licencia categoria C"
    payload["criteria"][1]["operand"] = None
    payload["criteria"][1]["license_category"] = None
    contract = built_contract(payload)
    license_entry = contract["licenses"][0]
    assert license_entry["license_category"] is None
    assert license_entry["precision_status"] == "needs_clarification"


def test_protected_or_non_filterable_criteria_cannot_enter_strategy_lists():
    payload = draft()
    payload["criteria"][0]["scope"] = "prohibited"
    payload["search_strategy"]["must_have_criterion_refs"] = ["criterion_experience"]
    with pytest.raises((ValueError, ValidationError)):
        built_contract(payload)


def test_success_envelope_keeps_contract_separate_and_errors_exclude_it():
    result = service_result()
    display = build_display_plan_v2(result)
    response = build_public_response_v2(result, display_plan=display, source_language="auto")

    assert response["display_plan"] == display["display_plan"]
    assert response["search_execution_contract"] == built_contract()
    assert response["search_execution_contract"] is not response["display_plan"]

    error = build_public_response_v2(
        {
            "ok": False,
            "status": "error",
            "schema_version": "cvbrain_intake_v2_service",
            "error": {"code": "provider_failed", "category": "provider"},
        }
    )
    assert "search_execution_contract" not in error
