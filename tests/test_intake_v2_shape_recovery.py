from __future__ import annotations

import copy
import hashlib
import importlib
import json
from typing import Any, Mapping

import pytest


SHAPE_MODULE = "app.intake_v2.shape_recovery"


def shape_module() -> Any:
    try:
        return importlib.import_module(SHAPE_MODULE)
    except ModuleNotFoundError as error:
        pytest.fail(f"Gate 2 shape recovery module is not implemented: expected import {SHAPE_MODULE} ({error})")


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for the Gate 2 shape-recovery contract")
    return getattr(module, name)


def valid_payload() -> dict[str, Any]:
    contract = importlib.import_module("app.intake_v2.contract")
    return {
        "schema_version": contract.SCHEMA_VERSION_V2,
        "job_profile": {
            "role_title": "Mecanico de coches",
            "role_family": None,
            "professional_grade": None,
            "seniority": None,
            "summary": None,
            "industries": [],
        },
        "location_and_modality": {
            "raw_location": None,
            "normalized_location": None,
            "country_code": None,
            "city": None,
            "region": None,
            "work_modality": None,
            "remote_allowed": None,
            "hybrid_allowed": None,
            "onsite_required": None,
        },
        "criteria": [],
        "company_questions": [],
        "candidate_screening_questions": [],
        "search_strategy": {
            "target_titles": [],
            "search_terms": [],
            "semantic_terms": [],
            "negative_terms": [],
        },
        "search_readiness": {
            "status": "insufficient_for_precise_search",
            "proceed_allowed": True,
            "recommended_action": "ask_company",
            "recruiter_decision_required": True,
            "continued_with_missing_information": True,
        },
        "quality_control": {
            "warnings": [],
            "confidence": 0.4,
            "contains_candidate_data": False,
            "contains_candidate_pii": False,
        },
    }


def recover(payload: Mapping[str, Any]) -> dict[str, Any]:
    module = shape_module()
    recover_fn = required_attr(module, "recover_provider_shape_v2")
    recovered = recover_fn(copy.deepcopy(payload))
    assert isinstance(recovered, dict)
    return recovered


def shape_error_type() -> type[BaseException]:
    error_type = required_attr(shape_module(), "V2ShapeRecoveryError")
    assert issubclass(error_type, Exception)
    return error_type


def assert_repair_required(payload: Mapping[str, Any], expected_path: str) -> BaseException:
    with pytest.raises(shape_error_type()) as exc_info:
        recover(payload)
    error = exc_info.value
    assert expected_path in str(error)
    assert getattr(error, "repair_required", True) is True
    return error


def delete_path(payload: dict[str, Any], path: tuple[Any, ...]) -> dict[str, Any]:
    output = copy.deepcopy(payload)
    target: Any = output
    for part in path[:-1]:
        target = target[part]
    del target[path[-1]]
    return output


def set_path(payload: dict[str, Any], path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    output = copy.deepcopy(payload)
    target: Any = output
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    return output


def test_present_valid_empty_semantic_lists_remain_empty():
    payload = valid_payload()

    recovered = recover(payload)

    assert recovered["criteria"] == []
    assert recovered["company_questions"] == []
    assert recovered["candidate_screening_questions"] == []
    assert recovered["search_strategy"]["target_titles"] == []
    assert recovered["search_strategy"]["search_terms"] == []
    assert recovered["search_strategy"]["semantic_terms"] == []
    assert recovered["search_strategy"]["negative_terms"] == []


def test_missing_required_criteria_requires_repair():
    assert_repair_required(delete_path(valid_payload(), ("criteria",)), "criteria")


def test_null_required_criteria_requires_repair():
    assert_repair_required(set_path(valid_payload(), ("criteria",), None), "criteria")


def test_missing_null_required_company_questions_requires_repair():
    assert_repair_required(delete_path(valid_payload(), ("company_questions",)), "company_questions")
    assert_repair_required(set_path(valid_payload(), ("company_questions",), None), "company_questions")


def test_missing_null_required_candidate_screening_questions_requires_repair():
    assert_repair_required(delete_path(valid_payload(), ("candidate_screening_questions",)), "candidate_screening_questions")
    assert_repair_required(
        set_path(valid_payload(), ("candidate_screening_questions",), None),
        "candidate_screening_questions",
    )


def test_missing_null_required_search_strategy_lists_require_repair():
    for key in ("target_titles", "search_terms", "semantic_terms", "negative_terms"):
        assert_repair_required(delete_path(valid_payload(), ("search_strategy", key)), f"search_strategy.{key}")
        assert_repair_required(set_path(valid_payload(), ("search_strategy", key), None), f"search_strategy.{key}")


def test_present_nullable_scalars_set_to_null_are_accepted():
    payload = valid_payload()

    recovered = recover(payload)

    assert recovered["job_profile"]["role_family"] is None
    assert recovered["job_profile"]["professional_grade"] is None
    assert recovered["job_profile"]["seniority"] is None
    assert recovered["job_profile"]["summary"] is None
    assert recovered["location_and_modality"]["raw_location"] is None
    assert recovered["location_and_modality"]["normalized_location"] is None
    assert recovered["location_and_modality"]["country_code"] is None
    assert recovered["location_and_modality"]["city"] is None
    assert recovered["location_and_modality"]["region"] is None
    assert recovered["location_and_modality"]["work_modality"] is None
    assert recovered["location_and_modality"]["remote_allowed"] is None
    assert recovered["location_and_modality"]["hybrid_allowed"] is None
    assert recovered["location_and_modality"]["onsite_required"] is None


def test_missing_required_scalar_requires_repair():
    assert_repair_required(delete_path(valid_payload(), ("job_profile", "role_title")), "job_profile.role_title")


def test_wrong_semantic_type_content_requires_repair_without_discard():
    cases = [
        (("criteria",), "Experiencia demostrable como mecanico"),
        (("job_profile", "role_title"), ["Mecanico de coches"]),
        (("search_strategy", "search_terms"), {"term": "mecanico de coches"}),
    ]
    for path, malformed_value in cases:
        error = assert_repair_required(set_path(valid_payload(), path, malformed_value), ".".join(str(part) for part in path))
        retained = getattr(error, "malformed_value", None)
        raw_hash = getattr(error, "raw_value_sha256", None)
        expected_hash = hashlib.sha256(json.dumps(malformed_value, sort_keys=True).encode("utf-8")).hexdigest()
        assert retained == malformed_value or raw_hash == expected_hash


def test_shape_recovery_never_creates_semantic_content():
    payload = valid_payload()

    recovered = recover(payload)

    assert recovered["job_profile"]["role_title"] == "Mecanico de coches"
    assert recovered["criteria"] == []
    assert recovered["company_questions"] == []
    assert recovered["candidate_screening_questions"] == []
    assert recovered["search_strategy"] == {
        "target_titles": [],
        "search_terms": [],
        "semantic_terms": [],
        "negative_terms": [],
    }
    assert recovered["location_and_modality"]["raw_location"] is None
    assert recovered["location_and_modality"]["normalized_location"] is None
