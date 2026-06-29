from __future__ import annotations

import ast
import copy
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.intake_v2.contract import SCHEMA_VERSION_V2, validate_job_intelligence_draft_v2
from app.intake_v2.display_plan import build_display_plan_v2
from app.intake_v2.errors import IntakeV2Error
from app.intake_v2.integrity import internalize_draft_v2


ROOT = Path(__file__).resolve().parents[1]
RESPONSE_MODULE = "app.intake_v2.response"
PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"
SENSITIVE_SENTINELS = (
    "SOURCE_TEXT_SENTINEL",
    "PROMPT_BODY_SENTINEL",
    "RAW_OUTPUT_SENTINEL",
    "SECRET_TOKEN_SENTINEL",
)
SEMANTIC_SENTINELS = (
    "papeles en regla",
    "oficial de primera",
    "licencia profesional",
    "bloqueante",
    "nice to have",
    "required",
)
ALLOWED_SUCCESS_KEYS = {
    "ok",
    "status",
    "schema_version",
    "response_version",
    "display_plan",
    "metadata",
    "request_id",
}
ALLOWED_FAILURE_KEYS = {
    "ok",
    "status",
    "schema_version",
    "response_version",
    "error",
    "metadata",
    "request_id",
}
ALLOWED_ERROR_KEYS = {"code", "category"}
ALLOWED_METADATA_KEYS = {
    "provider",
    "integrity",
    "service_schema_version",
    "display_plan_schema_version",
    "counts",
    "request_id",
}
ALLOWED_PROVIDER_METADATA_KEYS = {
    "provider_response_id",
    "provider_request_id",
    "model",
    "attempt_kind",
    "provider_call_count",
    "semantic_attempt_count",
    "repair_count",
    "transient_retry_count",
    "elapsed_seconds",
    "parse_path",
}
ALLOWED_INTEGRITY_METADATA_KEYS = {"ok", "paths", "counts", "codes", "categories"}
FORBIDDEN_PUBLIC_KEYS = {
    "api_key",
    "auth_headers",
    "authorization",
    "bearer_token",
    "body",
    "cookie",
    "cookies",
    "debug",
    "document",
    "endpoint",
    "errors",
    "exception",
    "fastapi_response",
    "flat_compatibility",
    "headers",
    "http_status",
    "local_ref",
    "prompt",
    "prompt_body",
    "provider_body",
    "provider_payload",
    "raw_exception",
    "raw_output",
    "raw_output_text",
    "raw_provider_output",
    "request_body",
    "response_body",
    "route",
    "source_text",
    "standalone",
    "starlette_response",
    "ui_sections",
    "v1_compatibility",
    "wordpress",
}
FORBIDDEN_RUNTIME_IMPORTS = {
    "app.extractors.deterministic",
    "app.extractors.router",
    "app.main",
    "app.mappers.job_intelligence_to_flat",
    "app.mappers.recruiter_display_plan",
    "app.normalization.canonical_job_intelligence",
    "app.normalization.precision_questions",
    "app.normalization.requirement_importance",
    "app.normalization.role_title",
    "fastapi",
    "starlette",
}
ALLOWED_LOG_KEYS = {
    "event",
    "status",
    "code",
    "category",
    "response_version",
    "section_count",
    "item_count",
    "request_id",
}
_OMITTED = object()


def response_module() -> Any:
    try:
        return importlib.import_module(RESPONSE_MODULE)
    except ModuleNotFoundError as error:
        if error.name == RESPONSE_MODULE:
            pytest.fail(f"Gate 6 response module is not implemented: expected import {RESPONSE_MODULE} ({error})")
        raise


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for the Gate 6 public response boundary")
    return getattr(module, name)


def build_public_response_v2(service_result: Mapping[str, Any], *, display_plan: Any = _OMITTED) -> Mapping[str, Any]:
    module = response_module()
    builder = required_attr(module, "build_public_response_v2")
    if display_plan is _OMITTED:
        result = builder(service_result)
    else:
        result = builder(service_result, display_plan=display_plan)
    assert isinstance(result, Mapping), "build_public_response_v2 must return a mapping"
    return result


def response_error_type() -> type[BaseException]:
    module = response_module()
    error_type = required_attr(module, "V2PublicResponseError")
    assert issubclass(error_type, IntakeV2Error)
    return error_type


def valid_draft(*, phrase: str = "papeles en regla") -> dict[str, Any]:
    return validate_job_intelligence_draft_v2(
        {
            "schema_version": SCHEMA_VERSION_V2,
            "job_profile": {
                "role_title": "Gate 6 role title",
                "role_family": "AI-owned role family",
                "professional_grade": None,
                "seniority": None,
                "summary": f"{phrase}; oficial de primera; licencia profesional.",
                "industries": ["AI-owned industry required"],
            },
            "location_and_modality": {
                "raw_location": "Montevideo",
                "normalized_location": None,
                "country_code": "UY",
                "city": None,
                "region": None,
                "work_modality": None,
                "remote_allowed": None,
                "hybrid_allowed": None,
                "onsite_required": None,
            },
            "criteria": [
                {
                    "local_ref": "crit_response_alpha",
                    "criterion_kind": "legal_documentation",
                    "text": phrase,
                    "source_evidence": phrase,
                    "importance": "must_have",
                    "explicit": True,
                    "precision_status": "needs_clarification",
                    "missing_dimensions": ["legal_documentation"],
                    "clarification_question_ref": "company_q_response_alpha",
                },
                {
                    "local_ref": "crit_response_beta",
                    "criterion_kind": "license",
                    "text": "oficial de primera con licencia profesional",
                    "source_evidence": "oficial de primera; licencia profesional",
                    "importance": "nice_to_have",
                    "explicit": True,
                    "precision_status": "needs_clarification",
                    "missing_dimensions": ["license_category", "equivalence"],
                    "clarification_question_ref": "company_q_response_beta",
                },
                {
                    "local_ref": "crit_response_gamma",
                    "criterion_kind": "general_requirement",
                    "text": "bloqueante nice to have required",
                    "source_evidence": "bloqueante nice to have required",
                    "importance": "should_have",
                    "explicit": True,
                    "precision_status": "precise",
                    "missing_dimensions": [],
                    "clarification_question_ref": None,
                },
            ],
            "company_questions": [
                {
                    "local_ref": "company_q_response_alpha",
                    "question": f"Que documentacion significa {phrase}?",
                    "audience": "hiring_company",
                    "category": "search_precision",
                    "criterion_refs": ["crit_response_alpha"],
                    "missing_dimensions": ["legal_documentation"],
                    "blocking_level": "blocking",
                },
                {
                    "local_ref": "company_q_response_beta",
                    "question": "Que categoria aplica a oficial de primera y licencia profesional?",
                    "audience": "hiring_company",
                    "category": "search_precision",
                    "criterion_refs": ["crit_response_beta", "crit_response_gamma"],
                    "missing_dimensions": ["license_category", "equivalence"],
                    "blocking_level": "important",
                },
            ],
            "candidate_screening_questions": [
                {
                    "local_ref": "candidate_q_response_alpha",
                    "question": "Podes explicar papeles en regla y licencia profesional?",
                    "audience": "candidate",
                    "category": "screening",
                    "criterion_refs": ["crit_response_alpha", "crit_response_beta"],
                    "missing_dimensions": [],
                    "blocking_level": "advisory",
                }
            ],
            "search_strategy": {
                "target_titles": ["Gate 6 role title"],
                "search_terms": [phrase, "licencia profesional"],
                "semantic_terms": ["oficial de primera"],
                "negative_terms": ["bloqueante"],
            },
            "search_readiness": {
                "status": "usable_with_warnings",
                "proceed_allowed": True,
                "recommended_action": "ask_company",
                "recruiter_decision_required": True,
                "continued_with_missing_information": True,
            },
            "quality_control": {
                "warnings": ["required and nice to have are copied AI-owned text"],
                "confidence": 0.73,
                "contains_candidate_data": False,
                "contains_candidate_pii": False,
            },
        }
    )


def service_success_result(*, phrase: str = "papeles en regla") -> dict[str, Any]:
    internalized = internalize_draft_v2(valid_draft(phrase=phrase))
    return {
        "ok": True,
        "status": "ok",
        "schema_version": "cvbrain_intake_v2_service",
        "provider": {
            "provider_response_id": "resp_response_safe",
            "provider_request_id": "req_response_safe",
            "model": "gpt-test-v2-response",
            "attempt_kind": "extraction",
            "provider_call_count": 1,
            "semantic_attempt_count": 1,
            "repair_count": 0,
            "transient_retry_count": 0,
            "elapsed_seconds": 0.123,
            "parse_path": "output_parsed",
        },
        "document": internalized["document"],
        "integrity": internalized["integrity"],
    }


def service_failure_result() -> dict[str, Any]:
    return {
        "ok": False,
        "status": "error",
        "schema_version": "cvbrain_intake_v2_service",
        "error": {"code": "provider_failed", "category": "provider"},
        "provider": {
            "provider_response_id": "resp_response_safe",
            "provider_request_id": "req_response_safe",
            "model": "gpt-test-v2-response",
            "attempt_kind": "extraction",
            "provider_call_count": 1,
            "semantic_attempt_count": 1,
            "repair_count": 0,
            "transient_retry_count": 0,
            "elapsed_seconds": 0.123,
            "parse_path": "output_parsed",
        },
        "integrity": {
            "ok": False,
            "paths": ["criteria.clarification_question_ref"],
            "counts": {"criteria": 3, "company_questions": 2, "candidate_screening_questions": 1},
            "codes": ["unresolved_reference"],
            "categories": ["internal_reference_integrity"],
        },
    }


def display_plan_result(service_result: Mapping[str, Any]) -> Mapping[str, Any]:
    result = build_display_plan_v2(service_result)
    assert isinstance(result, Mapping)
    return result


def display_plan_from_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    plan = result.get("display_plan")
    assert isinstance(plan, Mapping)
    return plan


def safe_json(value: Any) -> str:
    return json.dumps(to_jsonable(value), sort_keys=True, default=str)


def to_jsonable(value: Any, seen: set[int] | None = None) -> Any:
    if seen is None:
        seen = set()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    value_id = id(value)
    if value_id in seen:
        return "<cycle>"
    seen.add(value_id)
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(child, seen) for key, child in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(child, seen) for child in value]
    if isinstance(value, BaseException):
        return {
            "type": value.__class__.__name__,
            "message": str(value),
            "repr": repr(value),
            "attributes": to_jsonable(vars(value), seen),
            "cause": to_jsonable(value.__cause__, seen),
            "context": to_jsonable(value.__context__, seen),
        }
    if hasattr(value, "__dict__"):
        return {"type": value.__class__.__name__, "attributes": to_jsonable(vars(value), seen)}
    return repr(value)


def all_keys(value: Any) -> set[str]:
    keys: set[str] = set()

    def walk(child: Any) -> None:
        if isinstance(child, Mapping):
            keys.update(str(key) for key in child)
            for item in child.values():
                walk(item)
        elif isinstance(child, (list, tuple, set)):
            for item in child:
                walk(item)
        elif isinstance(child, BaseException):
            walk(vars(child))
        elif hasattr(child, "__dict__"):
            walk(vars(child))

    walk(value)
    return keys


def assert_public_response_version(value: Mapping[str, Any]) -> None:
    marker = value.get("schema_version") or value.get("response_version")
    assert marker == PUBLIC_RESPONSE_SCHEMA_VERSION


def assert_sensitive_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SENSITIVE_SENTINELS:
        assert sentinel not in rendered


def assert_semantic_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SEMANTIC_SENTINELS:
        assert sentinel not in rendered


def assert_no_forbidden_public_keys(value: Any) -> None:
    assert all_keys(value).isdisjoint(FORBIDDEN_PUBLIC_KEYS)


def assert_public_metadata(metadata: Any) -> None:
    assert isinstance(metadata, Mapping)
    assert set(metadata) <= ALLOWED_METADATA_KEYS
    provider = metadata.get("provider")
    if provider is not None:
        assert isinstance(provider, Mapping)
        assert set(provider) <= ALLOWED_PROVIDER_METADATA_KEYS
    integrity = metadata.get("integrity")
    if integrity is not None:
        assert isinstance(integrity, Mapping)
        assert set(integrity) <= ALLOWED_INTEGRITY_METADATA_KEYS


def assert_safe_response_error(error: BaseException) -> None:
    assert isinstance(error, response_error_type())
    assert_sensitive_sentinels_absent(error)
    assert_semantic_sentinels_absent(error)
    assert_no_forbidden_public_keys(error)
    assert set(vars(error)) <= {"code", "category", "paths", "counts"}
    assert isinstance(getattr(error, "code", None), str)
    assert isinstance(getattr(error, "category", None), str)
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__ is True
    for child in vars(error).values():
        assert not isinstance(child, BaseException)


def response_shape_signature(value: Any) -> Any:
    if isinstance(value, Mapping):
        stripped: dict[str, Any] = {}
        for key, child in value.items():
            if key in {"value", "values", "text"}:
                stripped[str(key)] = "<copied-value>"
            else:
                stripped[str(key)] = response_shape_signature(child)
        return stripped
    if isinstance(value, list):
        return [response_shape_signature(child) for child in value]
    return value


def response_log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    prefix = "cvbrain_intake_v2_response "
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith(prefix):
            continue
        payload = json.loads(message[len(prefix) :])
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def test_public_response_success_wraps_display_plan_with_stable_version():
    service_result = service_success_result()
    display_result = display_plan_result(service_result)

    response = build_public_response_v2(service_result, display_plan=display_result)

    assert set(response) <= ALLOWED_SUCCESS_KEYS
    assert response["ok"] is True
    assert response["status"] == "success"
    assert_public_response_version(response)
    assert response["display_plan"] == display_plan_from_result(display_result)
    assert_public_metadata(response.get("metadata"))


def test_public_response_success_excludes_internal_raw_debug_and_v1_fields():
    service_result = service_success_result()
    service_result.update(
        {
            "source_text": "SOURCE_TEXT_SENTINEL papeles en regla",
            "raw_output": "RAW_OUTPUT_SENTINEL",
            "prompt_body": "PROMPT_BODY_SENTINEL",
            "provider_payload": {"secret": "SECRET_TOKEN_SENTINEL"},
            "api_key": "SECRET_TOKEN_SENTINEL",
            "auth_headers": {"authorization": "Bearer SECRET_TOKEN_SENTINEL"},
            "flat_compatibility": ["must not become V1 output"],
            "wordpress": {"ui": "must not leak"},
            "endpoint": {"http_status": 200, "headers": {"authorization": "Bearer SECRET_TOKEN_SENTINEL"}},
        }
    )
    display_result = display_plan_result(service_result)

    response = build_public_response_v2(service_result, display_plan=display_result)

    assert_sensitive_sentinels_absent(response)
    assert_no_forbidden_public_keys(response)
    assert "document" not in response
    assert "error" not in response


def test_public_response_preserves_display_plan_exactly_without_semantic_rewrite():
    service_result = service_success_result()
    display_result = display_plan_result(service_result)

    response = build_public_response_v2(service_result, display_plan=display_result)

    assert response["display_plan"] == display_plan_from_result(display_result)
    rendered = safe_json(response["display_plan"])
    for phrase in SEMANTIC_SENTINELS:
        assert phrase in rendered
    assert "PAPELES EN REGLA" not in rendered
    assert "Papeles En Regla" not in rendered


def test_phrase_changes_do_not_change_response_envelope_metadata_or_shape_except_copied_values():
    first_service = service_success_result(phrase="papeles en regla")
    second_service = service_success_result(phrase="changed AI-owned phrase")
    first_display = display_plan_result(first_service)
    second_display = display_plan_result(second_service)

    first = build_public_response_v2(first_service, display_plan=first_display)
    second = build_public_response_v2(second_service, display_plan=second_display)

    assert response_shape_signature(first) == response_shape_signature(second)
    assert safe_json(first.get("metadata")) == safe_json(second.get("metadata"))
    assert "papeles en regla" in safe_json(first["display_plan"])
    assert "changed AI-owned phrase" in safe_json(second["display_plan"])


def test_public_response_failure_uses_safe_error_envelope_without_display_plan():
    failure = service_failure_result()
    failure.update(
        {
            "source_text": "SOURCE_TEXT_SENTINEL papeles en regla",
            "raw_output": "RAW_OUTPUT_SENTINEL",
            "prompt_body": "PROMPT_BODY_SENTINEL",
            "provider_payload": "SECRET_TOKEN_SENTINEL",
            "http_status": 500,
            "wordpress": {"message": "must not leak"},
            "flat_compatibility": ["must not leak"],
        }
    )

    response = build_public_response_v2(failure)

    assert set(response) <= ALLOWED_FAILURE_KEYS
    assert response["ok"] is False
    assert response["status"] == "error"
    assert_public_response_version(response)
    assert "display_plan" not in response
    assert_sensitive_sentinels_absent(response)
    assert_semantic_sentinels_absent(response)
    assert_no_forbidden_public_keys(response)
    error = response.get("error")
    assert isinstance(error, Mapping)
    assert set(error) <= ALLOWED_ERROR_KEYS
    assert isinstance(error.get("code"), str)
    assert isinstance(error.get("category"), str)
    if "metadata" in response:
        assert_public_metadata(response["metadata"])


def test_invalid_response_input_raises_safe_response_error():
    invalid = {
        "ok": True,
        "status": "ok",
        "schema_version": "cvbrain_intake_v2_service",
        "source_text": "SOURCE_TEXT_SENTINEL papeles en regla",
        "raw_output": "RAW_OUTPUT_SENTINEL",
        "prompt_body": "PROMPT_BODY_SENTINEL",
        "provider_payload": "SECRET_TOKEN_SENTINEL",
    }

    with pytest.raises(response_error_type()) as exc_info:
        build_public_response_v2(invalid, display_plan={"display_plan": {}})

    assert_safe_response_error(exc_info.value)


def test_response_error_has_no_exception_chaining_or_raw_content():
    invalid = {
        "ok": True,
        "status": "success",
        "schema_version": "cvbrain_intake_v2_service",
        "display_plan": {"source_text": "SOURCE_TEXT_SENTINEL"},
        "error": {"message": "RAW_OUTPUT_SENTINEL PROMPT_BODY_SENTINEL SECRET_TOKEN_SENTINEL"},
    }

    with pytest.raises(response_error_type()) as exc_info:
        build_public_response_v2(invalid, display_plan={"display_plan": "not a mapping"})

    assert_safe_response_error(exc_info.value)


def test_public_response_does_not_infer_readiness_or_semantic_status():
    service_result = service_success_result()
    display_result = display_plan_result(service_result)

    response = build_public_response_v2(service_result, display_plan=display_result)

    assert response["status"] == "success"
    assert "readiness" not in response
    assert "readiness_status" not in response
    assert "semantic_status" not in response
    assert "classification" not in response
    metadata = response.get("metadata", {})
    assert isinstance(metadata, Mapping)
    assert "readiness" not in metadata
    assert "readiness_status" not in metadata
    assert "semantic_status" not in metadata
    assert "classification" not in metadata
    rendered_display = safe_json(response["display_plan"])
    for phrase in SEMANTIC_SENTINELS:
        assert phrase in rendered_display


def test_response_module_imports_no_v1_endpoint_or_ui_runtime():
    module_path = ROOT / "app/intake_v2/response.py"
    if not module_path.exists():
        pytest.fail("Gate 6 response module is not implemented: expected app/intake_v2/response.py")

    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    offenders = [
        imported
        for imported in imports
        if any(imported == forbidden or imported.startswith(forbidden + ".") for forbidden in FORBIDDEN_RUNTIME_IMPORTS)
    ]
    assert offenders == []


def test_response_logs_are_absent_or_metadata_allowlisted(caplog: pytest.LogCaptureFixture):
    failure = service_failure_result()
    failure.update(
        {
            "source_text": "SOURCE_TEXT_SENTINEL papeles en regla",
            "raw_output": "RAW_OUTPUT_SENTINEL",
            "prompt_body": "PROMPT_BODY_SENTINEL",
            "provider_payload": "SECRET_TOKEN_SENTINEL",
        }
    )

    with caplog.at_level(logging.INFO, logger="cvbrain.intake_v2.response"):
        response = build_public_response_v2(failure)

    assert response["ok"] is False
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)
    for payload in response_log_payloads(caplog):
        assert set(payload) <= ALLOWED_LOG_KEYS
