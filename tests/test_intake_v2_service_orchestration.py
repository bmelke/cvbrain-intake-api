from __future__ import annotations

import ast
import copy
import importlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from app.intake_v2.contract import SCHEMA_VERSION_V2, validate_job_intelligence_draft_v2
from app.intake_v2.errors import IntakeV2Error, V2InternalIntegrityError, V2ProviderTerminalError
from app.intake_v2.provider import ProviderRequestV2, ProviderResultV2


ROOT = Path(__file__).resolve().parents[1]
SERVICE_MODULE = "app.intake_v2.service"
SOURCE_TEXT = (
    "SOURCE_TEXT_SENTINEL Spanish papeles en regla, English required, "
    "oficial de primera, licencia profesional, bloqueante, nice to have."
)
MODEL = "gpt-test-v2-service"
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
ALLOWED_SUCCESS_ENVELOPE_KEYS = {
    "ok",
    "status",
    "version",
    "schema_version",
    "provider",
    "document",
    "integrity",
    "request_id",
}
ALLOWED_FAILURE_ENVELOPE_KEYS = {
    "ok",
    "status",
    "version",
    "schema_version",
    "provider",
    "integrity",
    "error",
    "request_id",
}
ALLOWED_FAILURE_ERROR_KEYS = {
    "code",
    "category",
    "error_code",
    "error_category",
    "status",
    "provider",
    "integrity",
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
ALLOWED_SERVICE_LOG_KEYS = {
    "event",
    "status",
    "code",
    "category",
    "provider_call_count",
    "provider_calls",
    "integrity_ok",
    "integrity_counts",
    "integrity_codes",
    "integrity_categories",
    "request_id",
}
FORBIDDEN_ENVELOPE_KEYS = {
    "api_key",
    "auth_headers",
    "authorization",
    "bearer_token",
    "body",
    "display_plan",
    "flat_compatibility",
    "headers",
    "prompt",
    "prompt_body",
    "provider_body",
    "provider_payload",
    "raw_output",
    "raw_output_text",
    "raw_provider_output",
    "response_body",
    "source_text",
    "standalone",
    "ui_sections",
    "v1_compatibility",
    "wordpress",
}
FORBIDDEN_IMPORTS = {
    "app.normalization.requirement_importance",
    "app.normalization.role_title",
    "app.normalization.canonical_job_intelligence",
    "app.normalization.precision_questions",
    "app.mappers.recruiter_display_plan",
    "app.mappers.job_intelligence_to_flat",
    "app.extractors.deterministic",
    "app.extractors.router",
    "app.main",
}
SAFE_INTEGRITY_OK = {
    "ok": True,
    "paths": [],
    "counts": {"criteria": 1, "company_questions": 1, "candidate_screening_questions": 1},
    "codes": [],
    "categories": ["internal_reference_integrity"],
}
SAFE_INTEGRITY_FAILURE = {
    "ok": False,
    "paths": ["company_questions.criterion_refs"],
    "counts": {"criteria": 1, "company_questions": 1, "candidate_screening_questions": 1},
    "codes": ["unresolved_reference"],
    "categories": ["internal_reference_integrity"],
}


class FakeProvider:
    def __init__(self, result: ProviderResultV2 | None = None, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[ProviderRequestV2] = []

    def extract(self, request: ProviderRequestV2) -> ProviderResultV2:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class FakeInternalizer:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, draft: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append(copy.deepcopy(dict(draft)))
        if self.error is not None:
            raise self.error
        return {"document": fake_internal_document(draft), "integrity": copy.deepcopy(SAFE_INTEGRITY_OK)}


class SensitiveProviderFailure(V2ProviderTerminalError):
    message = "SOURCE_TEXT_SENTINEL PROMPT_BODY_SENTINEL"
    body = "RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL"
    headers = {"authorization": "Bearer SECRET_TOKEN_SENTINEL"}

    def __init__(self) -> None:
        self.response = SimpleNamespace(
            text="RAW_OUTPUT_SENTINEL PROMPT_BODY_SENTINEL",
            headers={"authorization": "Bearer SECRET_TOKEN_SENTINEL"},
            json=lambda: {"leak": "SOURCE_TEXT_SENTINEL"},
        )
        super().__init__("SOURCE_TEXT_SENTINEL PROMPT_BODY_SENTINEL RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL")

    def __str__(self) -> str:
        return "SOURCE_TEXT_SENTINEL PROMPT_BODY_SENTINEL RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL"

    def __repr__(self) -> str:
        return "SensitiveProviderFailure(SECRET_TOKEN_SENTINEL RAW_OUTPUT_SENTINEL)"


def service_module() -> Any:
    try:
        return importlib.import_module(SERVICE_MODULE)
    except ModuleNotFoundError as error:
        if error.name == SERVICE_MODULE:
            pytest.fail(f"Gate 4 service module is not implemented: expected import {SERVICE_MODULE} ({error})")
        raise


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for the Gate 4 service boundary")
    return getattr(module, name)


def service_request_error_type() -> type[BaseException]:
    error_type = required_attr(service_module(), "V2ServiceRequestError")
    assert issubclass(error_type, IntakeV2Error)
    return error_type


def make_service_request(*, source_text: str = SOURCE_TEXT, source_language: str = "Declared-Spanish") -> Any:
    Request = required_attr(service_module(), "IntakeServiceRequestV2")
    return Request(
        source_text=source_text,
        source_language=source_language,
        locale="es-UY",
        country_context="UY",
        candidate_market="UY",
        employer_market="UY",
        model=MODEL,
        timeout_seconds=90.0,
    )


def run_service(request: Any, *, provider: FakeProvider, internalizer: FakeInternalizer) -> Any:
    module = service_module()
    run_intake_v2 = required_attr(module, "run_intake_v2")
    return run_intake_v2(request, provider=provider, internalize_draft_v2=internalizer)


def valid_draft(*, phrase: str = "papeles en regla") -> dict[str, Any]:
    return validate_job_intelligence_draft_v2(
        {
            "schema_version": SCHEMA_VERSION_V2,
            "job_profile": {
                "role_title": "Service boundary role title",
                "role_family": "AI-owned role family",
                "professional_grade": None,
                "seniority": None,
                "summary": f"{phrase}; oficial de primera; licencia profesional.",
                "industries": ["AI-owned industry"],
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
                    "local_ref": "crit_service_alpha",
                    "criterion_kind": "legal_documentation",
                    "text": f"{phrase}; bloqueante; nice to have; required",
                    "source_evidence": f"{phrase}; required",
                    "importance": "must_have",
                    "explicit": True,
                    "precision_status": "needs_clarification",
                    "missing_dimensions": ["legal_documentation"],
                    "clarification_question_ref": "company_q_service_alpha",
                }
            ],
            "company_questions": [
                {
                    "local_ref": "company_q_service_alpha",
                    "question": f"What does {phrase} mean?",
                    "audience": "hiring_company",
                    "category": "search_precision",
                    "criterion_refs": ["crit_service_alpha"],
                    "missing_dimensions": ["legal_documentation"],
                    "blocking_level": "blocking",
                }
            ],
            "candidate_screening_questions": [
                {
                    "local_ref": "candidate_q_service_alpha",
                    "question": f"Can you evidence {phrase}?",
                    "audience": "candidate",
                    "category": "screening",
                    "criterion_refs": ["crit_service_alpha"],
                    "missing_dimensions": [],
                    "blocking_level": "advisory",
                }
            ],
            "search_strategy": {
                "target_titles": ["Service boundary role title"],
                "search_terms": [phrase],
                "semantic_terms": ["oficial de primera", "licencia profesional"],
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
                "warnings": ["required and nice to have are AI-owned text"],
                "confidence": 0.81,
                "contains_candidate_data": False,
                "contains_candidate_pii": False,
            },
        }
    )


def provider_result(
    *,
    draft: Mapping[str, Any] | None = None,
    provider_calls: int = 1,
    semantic_attempts: int = 1,
    repairs: int = 0,
    transient_retries: int = 0,
) -> ProviderResultV2:
    return ProviderResultV2(
        validated_draft=copy.deepcopy(dict(draft or valid_draft())),
        provider_response_id="resp_service_safe",
        provider_request_id="req_service_safe",
        model=MODEL,
        attempt_kind="extraction" if repairs == 0 else "repair",
        provider_call_count=provider_calls,
        semantic_attempt_count=semantic_attempts,
        repair_count=repairs,
        transient_retry_count=transient_retries,
        elapsed_seconds=0.123,
        parse_path="output_parsed",
    )


def fake_internal_document(draft: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": draft["schema_version"],
        "job_profile": copy.deepcopy(draft["job_profile"]),
        "criteria": [
            {
                "internal_id": "v2_service_fake_criteria_0",
                "text": draft["criteria"][0]["text"],
                "source_evidence": draft["criteria"][0]["source_evidence"],
            }
        ],
        "company_questions": [
            {
                "internal_id": "v2_service_fake_company_question_0",
                "question": draft["company_questions"][0]["question"],
                "criterion_ids": ["v2_service_fake_criteria_0"],
            }
        ],
        "candidate_screening_questions": [
            {
                "internal_id": "v2_service_fake_candidate_question_0",
                "question": draft["candidate_screening_questions"][0]["question"],
                "criterion_ids": ["v2_service_fake_criteria_0"],
            }
        ],
        "search_strategy": copy.deepcopy(draft["search_strategy"]),
        "search_readiness": copy.deepcopy(draft["search_readiness"]),
        "quality_control": copy.deepcopy(draft["quality_control"]),
    }


def value_at(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def object_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return set(value)
    if hasattr(value, "__dict__"):
        return set(vars(value))
    return set()


def provider_metadata(result: Any) -> Mapping[str, Any]:
    metadata = value_at(result, "provider")
    assert isinstance(metadata, Mapping), "successful service result must expose safe provider metadata"
    return metadata


def service_succeeded(result: Any) -> bool:
    return value_at(result, "ok") is True or value_at(result, "status") in {"ok", "success", "completed"}


def service_failed(result: Any) -> bool:
    return value_at(result, "ok") is False or value_at(result, "status") in {"error", "failed"}


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


def assert_sensitive_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SENSITIVE_SENTINELS:
        assert sentinel not in rendered


def assert_semantic_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SEMANTIC_SENTINELS:
        assert sentinel not in rendered


def assert_no_display_or_v1_projection(value: Any) -> None:
    observed = all_keys(value)
    assert observed.isdisjoint(FORBIDDEN_ENVELOPE_KEYS)


def assert_safe_request_error(error: BaseException) -> None:
    assert isinstance(error, service_request_error_type())
    assert_sensitive_sentinels_absent(error)
    assert_semantic_sentinels_absent(error)
    assert_no_display_or_v1_projection(error)
    assert set(vars(error)) <= {"code", "category"}
    assert isinstance(getattr(error, "code", None), str)
    assert isinstance(getattr(error, "category", None), str)
    for child in vars(error).values():
        assert not isinstance(child, BaseException)


def assert_safe_failure_envelope(value: Any) -> None:
    assert not isinstance(value, BaseException), "pipeline failures must return safe envelopes, not raise"
    assert_sensitive_sentinels_absent(value)
    assert_semantic_sentinels_absent(value)
    assert_no_display_or_v1_projection(value)
    assert service_failed(value)
    assert object_keys(value) <= ALLOWED_FAILURE_ENVELOPE_KEYS
    error = value_at(value, "error")
    assert isinstance(error, Mapping), "service failure result must expose a safe error mapping"
    assert set(error) <= ALLOWED_FAILURE_ERROR_KEYS
    assert isinstance(error.get("code") or error.get("error_code"), str)
    assert isinstance(error.get("category") or error.get("error_category"), str)


def integrity_from_failure(value: Any) -> Any:
    direct = value_at(value, "integrity")
    if direct is not None:
        return direct
    error = value_at(value, "error")
    if isinstance(error, Mapping):
        return error.get("integrity")
    return None


def service_log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    prefix = "cvbrain_intake_v2_service "
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith(prefix):
            continue
        payload = json.loads(message[len(prefix) :])
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def test_service_request_validation_failures_raise_safe_request_error():
    Request = required_attr(service_module(), "IntakeServiceRequestV2")
    Error = service_request_error_type()

    base = {
        "source_text": SOURCE_TEXT,
        "source_language": "Declared-Spanish",
        "locale": "es-UY",
        "country_context": "UY",
        "candidate_market": "UY",
        "employer_market": "UY",
        "model": MODEL,
        "timeout_seconds": 90.0,
    }
    invalid_cases = [
        {key: value for key, value in base.items() if key != "source_text"},
        {**base, "source_text": ""},
        {key: value for key, value in base.items() if key != "source_language"},
        {**base, "source_language": ""},
    ]

    for kwargs in invalid_cases:
        with pytest.raises(Error) as exc_info:
            Request(**kwargs)
        assert_safe_request_error(exc_info.value)


def test_service_request_passes_explicit_source_language_without_inference():
    provider = FakeProvider(provider_result())
    internalizer = FakeInternalizer()
    request = make_service_request(source_text=SOURCE_TEXT, source_language="Declared-Spanish")

    run_service(request, provider=provider, internalizer=internalizer)

    assert provider.calls[0].source_language == "Declared-Spanish"


def test_service_does_not_default_or_infer_source_text():
    Request = required_attr(service_module(), "IntakeServiceRequestV2")
    Error = service_request_error_type()

    with pytest.raises(Error) as exc_info:
        Request(
            source_language="Declared-Spanish",
            locale="es-UY",
            country_context="UY",
            candidate_market="UY",
            employer_market="UY",
            model=MODEL,
            timeout_seconds=90.0,
        )
    assert_safe_request_error(exc_info.value)


def test_service_builds_one_provider_request_without_semantic_enrichment():
    provider = FakeProvider(provider_result())
    internalizer = FakeInternalizer()
    request = make_service_request(source_text=SOURCE_TEXT, source_language="Declared-Spanish")

    run_service(request, provider=provider, internalizer=internalizer)

    assert len(provider.calls) == 1
    provider_request = provider.calls[0]
    assert isinstance(provider_request, ProviderRequestV2)
    assert provider_request.source_text == SOURCE_TEXT
    assert provider_request.source_language == "Declared-Spanish"
    assert provider_request.model == MODEL
    assert provider_request.timeout_seconds == 90.0
    assert set(vars(provider_request)) == {
        "source_text",
        "source_language",
        "locale",
        "country_context",
        "candidate_market",
        "employer_market",
        "model",
        "timeout_seconds",
    }


def test_service_calls_provider_once_and_internalizer_once_without_retry_or_repair_duplication():
    result_from_provider = provider_result(provider_calls=3, semantic_attempts=2, repairs=1, transient_retries=1)
    provider = FakeProvider(result_from_provider)
    internalizer = FakeInternalizer()

    result = run_service(make_service_request(), provider=provider, internalizer=internalizer)

    assert len(provider.calls) == 1
    assert len(internalizer.calls) == 1
    assert internalizer.calls[0] == result_from_provider.validated_draft
    metadata = provider_metadata(result)
    assert set(metadata) <= ALLOWED_PROVIDER_METADATA_KEYS
    assert metadata["provider_call_count"] == 3
    assert metadata["semantic_attempt_count"] == 2
    assert metadata["repair_count"] == 1
    assert metadata["transient_retry_count"] == 1


def test_success_result_envelope_contains_safe_provider_and_integrity_metadata():
    provider = FakeProvider(provider_result())
    internalizer = FakeInternalizer()

    result = run_service(make_service_request(), provider=provider, internalizer=internalizer)

    assert service_succeeded(result)
    assert object_keys(result) <= ALLOWED_SUCCESS_ENVELOPE_KEYS
    assert value_at(result, "document") == fake_internal_document(provider.result.validated_draft)
    assert value_at(result, "integrity") == SAFE_INTEGRITY_OK
    metadata = provider_metadata(result)
    assert metadata["model"] == MODEL
    assert metadata["provider_response_id"] == "resp_service_safe"
    assert metadata["provider_request_id"] == "req_service_safe"
    assert metadata["parse_path"] == "output_parsed"


def test_success_result_excludes_sensitive_inputs_display_plan_and_v1_projection():
    provider = FakeProvider(provider_result())
    internalizer = FakeInternalizer()

    result = run_service(make_service_request(), provider=provider, internalizer=internalizer)

    assert_sensitive_sentinels_absent(result)
    assert_no_display_or_v1_projection(result)
    serialized = safe_json(result)
    for semantic_phrase in SEMANTIC_SENTINELS:
        assert semantic_phrase in serialized


def test_provider_failure_returns_safe_envelope_without_freeform_content():
    provider = FakeProvider(error=SensitiveProviderFailure())
    internalizer = FakeInternalizer()

    failure = run_service(make_service_request(), provider=provider, internalizer=internalizer)

    assert len(provider.calls) == 1
    assert internalizer.calls == []
    assert_safe_failure_envelope(failure)


def test_internal_integrity_failure_preserves_safe_metadata_without_semantic_content():
    provider = FakeProvider(provider_result())
    internal_error = V2InternalIntegrityError(
        "SOURCE_TEXT_SENTINEL RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL papeles en regla",
        integrity=copy.deepcopy(SAFE_INTEGRITY_FAILURE),
    )
    internalizer = FakeInternalizer(error=internal_error)

    failure = run_service(make_service_request(), provider=provider, internalizer=internalizer)

    assert len(provider.calls) == 1
    assert len(internalizer.calls) == 1
    assert integrity_from_failure(failure) == SAFE_INTEGRITY_FAILURE
    assert_safe_failure_envelope(failure)


def test_domain_phrase_changes_do_not_change_service_orchestration_or_envelope_metadata():
    request_a = make_service_request(
        source_text="papeles en regla oficial de primera licencia profesional bloqueante nice to have required",
        source_language="Declared-Spanish",
    )
    request_b = make_service_request(
        source_text="Changed phrase with English required and Spanish licencia profesional",
        source_language="Declared-Spanish",
    )
    provider_a = FakeProvider(provider_result(draft=valid_draft(phrase="papeles en regla")))
    provider_b = FakeProvider(provider_result(draft=valid_draft(phrase="changed AI-owned phrase")))
    internalizer_a = FakeInternalizer()
    internalizer_b = FakeInternalizer()

    result_a = run_service(request_a, provider=provider_a, internalizer=internalizer_a)
    result_b = run_service(request_b, provider=provider_b, internalizer=internalizer_b)

    assert len(provider_a.calls) == len(provider_b.calls) == 1
    assert len(internalizer_a.calls) == len(internalizer_b.calls) == 1
    assert provider_a.calls[0].source_language == provider_b.calls[0].source_language == "Declared-Spanish"
    assert service_succeeded(result_a) and service_succeeded(result_b)
    assert object_keys(result_a) == object_keys(result_b)
    assert provider_metadata(result_a) == provider_metadata(result_b)
    assert value_at(result_a, "integrity") == value_at(result_b, "integrity")


def test_service_module_imports_no_v1_semantic_runtime():
    module_path = ROOT / "app/intake_v2/service.py"
    if not module_path.exists():
        pytest.fail("Gate 4 service module is not implemented: expected app/intake_v2/service.py")

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
        if any(imported == forbidden or imported.startswith(forbidden + ".") for forbidden in FORBIDDEN_IMPORTS)
    ]
    assert offenders == []


def test_service_logs_are_metadata_only_if_logs_are_emitted(caplog: pytest.LogCaptureFixture):
    provider = FakeProvider(error=SensitiveProviderFailure())
    internalizer = FakeInternalizer()

    with caplog.at_level(logging.INFO, logger="cvbrain.intake_v2.service"):
        failure = run_service(make_service_request(), provider=provider, internalizer=internalizer)

    assert_safe_failure_envelope(failure)
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)
    for payload in service_log_payloads(caplog):
        assert set(payload) <= ALLOWED_SERVICE_LOG_KEYS
