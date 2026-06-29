from __future__ import annotations

import ast
import copy
import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.intake_v2.errors import IntakeV2Error


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_MODULE = "app.intake_v2.pipeline"
SOURCE_TEXT = (
    "SOURCE_TEXT_SENTINEL papeles en regla, oficial de primera, licencia profesional, "
    "bloqueante, nice to have, required."
)
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
ALLOWED_LOG_KEYS = {
    "event",
    "status",
    "code",
    "category",
    "response_version",
    "request_id",
    "service_calls",
    "display_plan_calls",
    "response_calls",
}
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
    "app.extractors",
    "app.main",
    "app.mappers",
    "app.normalization",
    "app.routers",
    "app.routes",
    "app.intake_v2.contract",
    "app.intake_v2.integrity",
    "app.intake_v2.provider",
    "app.intake_v2.prompts",
    "app.intake_v2.shape_recovery",
    "dotenv",
    "fastapi",
    "openai",
    "os",
    "starlette",
}
PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"
SERVICE_SCHEMA_VERSION = "cvbrain_intake_v2_service"
DISPLAY_PLAN_SCHEMA_VERSION = "cvbrain_intake_v2_display_plan"


class FakeInjectedProvider:
    def __init__(self) -> None:
        self.direct_extract_calls = 0

    def extract(self, _request: Any) -> Any:
        self.direct_extract_calls += 1
        raise AssertionError("pipeline must not call provider directly; service owns provider orchestration")


class HostileDependencyError(Exception):
    message = "SOURCE_TEXT_SENTINEL PROMPT_BODY_SENTINEL RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL"
    body = "RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL"
    headers = {"authorization": "Bearer SECRET_TOKEN_SENTINEL"}

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return "HostileDependencyError(SOURCE_TEXT_SENTINEL SECRET_TOKEN_SENTINEL)"


class FakeServiceRequest:
    calls: list[dict[str, Any]] = []

    def __init__(
        self,
        *,
        source_text: Any,
        source_language: Any,
        locale: str = "",
        country_context: str | None = None,
        candidate_market: str | None = None,
        employer_market: str | None = None,
        model: str = "",
        timeout_seconds: float = 0.0,
    ) -> None:
        values = {
            "source_text": source_text,
            "source_language": source_language,
            "locale": locale,
            "country_context": country_context,
            "candidate_market": candidate_market,
            "employer_market": employer_market,
            "model": model,
            "timeout_seconds": timeout_seconds,
        }
        self.__dict__.update(values)
        self.calls.append(copy.deepcopy(values))


class FakeServiceBoundary:
    def __init__(self, result: Mapping[str, Any], call_order: list[str]) -> None:
        self.result = copy.deepcopy(dict(result))
        self.call_order = call_order
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: Any, *, provider: Any, **kwargs: Any) -> Mapping[str, Any]:
        self.call_order.append("service")
        self.calls.append({"request": request, "provider": provider, "kwargs": kwargs})
        return copy.deepcopy(self.result)


class FakeDisplayBoundary:
    def __init__(self, result: Mapping[str, Any] | None, call_order: list[str], error: BaseException | None = None) -> None:
        self.result = copy.deepcopy(dict(result or display_plan_result()))
        self.error = error
        self.call_order = call_order
        self.calls: list[Mapping[str, Any]] = []

    def __call__(self, service_result: Mapping[str, Any]) -> Mapping[str, Any]:
        self.call_order.append("display")
        self.calls.append(copy.deepcopy(dict(service_result)))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.result)


class FakeResponseBoundary:
    def __init__(self, result: Mapping[str, Any], call_order: list[str], error: BaseException | None = None) -> None:
        self.result = copy.deepcopy(dict(result))
        self.error = error
        self.call_order = call_order
        self.calls: list[dict[str, Any]] = []

    def __call__(self, service_result: Mapping[str, Any], **kwargs: Any) -> Mapping[str, Any]:
        self.call_order.append("response")
        self.calls.append({"service_result": copy.deepcopy(dict(service_result)), "kwargs": copy.deepcopy(kwargs)})
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.result)


def pipeline_module() -> Any:
    try:
        return importlib.import_module(PIPELINE_MODULE)
    except ModuleNotFoundError as error:
        if error.name == PIPELINE_MODULE:
            pytest.fail(f"Gate 7 pipeline module is not implemented: expected import {PIPELINE_MODULE} ({error})")
        raise


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for the Gate 7 public pipeline boundary")
    return getattr(module, name)


def run_public_pipeline(**kwargs: Any) -> Mapping[str, Any]:
    module = pipeline_module()
    runner = required_attr(module, "run_public_intake_v2")
    result = runner(**kwargs)
    assert isinstance(result, Mapping), "run_public_intake_v2 must return a public response mapping"
    return result


def pipeline_request_error_type() -> type[BaseException]:
    error_type = required_attr(pipeline_module(), "V2PipelineRequestError")
    assert issubclass(error_type, IntakeV2Error)
    return error_type


def pipeline_error_type() -> type[BaseException]:
    error_type = required_attr(pipeline_module(), "V2PipelineError")
    assert issubclass(error_type, IntakeV2Error)
    return error_type


def install_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    *,
    service_result: Mapping[str, Any] | None = None,
    display_result: Mapping[str, Any] | None = None,
    public_response: Mapping[str, Any] | None = None,
    display_error: BaseException | None = None,
    response_error: BaseException | None = None,
) -> tuple[Any, FakeServiceBoundary, FakeDisplayBoundary, FakeResponseBoundary, list[str]]:
    module = pipeline_module()
    call_order: list[str] = []

    class RecordingServiceRequest(FakeServiceRequest):
        calls: list[dict[str, Any]] = []

        def __init__(self, **kwargs: Any) -> None:
            call_order.append("request")
            super().__init__(**kwargs)

    service = FakeServiceBoundary(service_result or service_success_result(), call_order)
    display = FakeDisplayBoundary(display_result or display_plan_result(), call_order, error=display_error)
    response = FakeResponseBoundary(public_response or public_success_response(), call_order, error=response_error)

    monkeypatch.setattr(module, "IntakeServiceRequestV2", RecordingServiceRequest, raising=False)
    monkeypatch.setattr(module, "run_intake_v2", service, raising=False)
    monkeypatch.setattr(module, "build_display_plan_v2", display, raising=False)
    monkeypatch.setattr(module, "build_public_response_v2", response, raising=False)
    monkeypatch.setattr(
        module,
        "internalize_draft_v2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pipeline must not internalize drafts")),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "OpenAIProviderV2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pipeline must not construct providers")),
        raising=False,
    )

    return module, service, display, response, call_order


def service_success_result(*, phrase: str = "papeles en regla") -> dict[str, Any]:
    return {
        "ok": True,
        "status": "ok",
        "schema_version": SERVICE_SCHEMA_VERSION,
        "provider": {
            "provider_response_id": "resp_pipeline_safe",
            "provider_request_id": "req_pipeline_safe",
            "model": "gpt-test-v2-pipeline",
            "attempt_kind": "extraction",
            "provider_call_count": 2,
            "semantic_attempt_count": 1,
            "repair_count": 0,
            "transient_retry_count": 1,
            "elapsed_seconds": 0.123,
            "parse_path": "output_parsed",
        },
        "document": {
            "schema_version": "cvbrain_job_intelligence_v2",
            "job_profile": {"role_title": "Pipeline role", "summary": phrase},
            "criteria": [{"internal_id": "v2_pipeline_criterion_0", "text": phrase}],
            "company_questions": [],
            "candidate_screening_questions": [],
            "search_strategy": {"search_terms": [phrase, "oficial de primera", "licencia profesional"]},
            "search_readiness": {
                "status": "usable_with_warnings",
                "proceed_allowed": True,
                "recommended_action": "ask_company",
                "recruiter_decision_required": True,
                "continued_with_missing_information": True,
            },
            "quality_control": {"warnings": ["required and nice to have are copied text"], "confidence": 0.82},
        },
        "integrity": {
            "ok": True,
            "paths": [],
            "counts": {"criteria": 1, "company_questions": 0, "candidate_screening_questions": 0},
            "codes": [],
            "categories": ["internal_reference_integrity"],
        },
    }


def service_failure_result() -> dict[str, Any]:
    return {
        "ok": False,
        "status": "error",
        "schema_version": SERVICE_SCHEMA_VERSION,
        "error": {"code": "provider_failed", "category": "provider"},
        "provider": {
            "provider_response_id": "resp_pipeline_safe",
            "provider_request_id": "req_pipeline_safe",
            "model": "gpt-test-v2-pipeline",
            "attempt_kind": "extraction",
            "provider_call_count": 1,
            "semantic_attempt_count": 1,
            "repair_count": 0,
            "transient_retry_count": 0,
            "elapsed_seconds": 0.123,
            "parse_path": "output_parsed",
        },
        "source_text": "SOURCE_TEXT_SENTINEL papeles en regla",
        "raw_output": "RAW_OUTPUT_SENTINEL",
        "prompt_body": "PROMPT_BODY_SENTINEL",
        "provider_payload": "SECRET_TOKEN_SENTINEL",
    }


def display_plan_result(*, phrase: str = "papeles en regla") -> dict[str, Any]:
    return {
        "display_plan": {
            "schema_version": DISPLAY_PLAN_SCHEMA_VERSION,
            "sections": [
                {
                    "id": "dp_section_00_job_profile",
                    "code": "job_profile",
                    "label": "Job profile",
                    "order": 0,
                    "items": [
                        {
                            "id": "dp_item_00_000",
                            "code": "summary",
                            "kind": "field",
                            "label": "Summary",
                            "order": 0,
                            "value": f"{phrase}; oficial de primera; licencia profesional",
                        }
                    ],
                },
                {
                    "id": "dp_section_01_criteria",
                    "code": "criteria",
                    "label": "Criteria",
                    "order": 1,
                    "items": [
                        {
                            "id": "dp_item_01_000",
                            "code": "criterion_0",
                            "kind": "criterion",
                            "label": "Criterion 1",
                            "order": 0,
                            "text": f"{phrase}; bloqueante; nice to have; required",
                        }
                    ],
                },
                {
                    "id": "dp_section_02_search_readiness",
                    "code": "search_readiness",
                    "label": "Search readiness",
                    "order": 2,
                    "items": [
                        {
                            "id": "dp_item_02_000",
                            "code": "status",
                            "kind": "field",
                            "label": "Status",
                            "order": 0,
                            "value": "usable_with_warnings",
                        }
                    ],
                },
            ],
        }
    }


def public_success_response(*, phrase: str = "papeles en regla") -> dict[str, Any]:
    return {
        "ok": True,
        "status": "success",
        "schema_version": PUBLIC_RESPONSE_SCHEMA_VERSION,
        "display_plan": copy.deepcopy(display_plan_result(phrase=phrase)["display_plan"]),
        "metadata": {
            "service_schema_version": SERVICE_SCHEMA_VERSION,
            "display_plan_schema_version": DISPLAY_PLAN_SCHEMA_VERSION,
            "provider": {
                "provider_response_id": "resp_pipeline_safe",
                "provider_request_id": "req_pipeline_safe",
                "model": "gpt-test-v2-pipeline",
                "attempt_kind": "extraction",
                "provider_call_count": 2,
                "semantic_attempt_count": 1,
                "repair_count": 0,
                "transient_retry_count": 1,
                "elapsed_seconds": 0.123,
                "parse_path": "output_parsed",
            },
            "integrity": {
                "ok": True,
                "paths": [],
                "counts": {"criteria": 1, "company_questions": 0, "candidate_screening_questions": 0},
                "codes": [],
                "categories": ["internal_reference_integrity"],
            },
        },
    }


def public_failure_response() -> dict[str, Any]:
    return {
        "ok": False,
        "status": "error",
        "schema_version": PUBLIC_RESPONSE_SCHEMA_VERSION,
        "error": {"code": "provider_failed", "category": "provider"},
        "metadata": {
            "service_schema_version": SERVICE_SCHEMA_VERSION,
            "provider": {
                "provider_response_id": "resp_pipeline_safe",
                "provider_request_id": "req_pipeline_safe",
                "model": "gpt-test-v2-pipeline",
                "attempt_kind": "extraction",
                "provider_call_count": 1,
                "semantic_attempt_count": 1,
                "repair_count": 0,
                "transient_retry_count": 0,
                "elapsed_seconds": 0.123,
                "parse_path": "output_parsed",
            },
        },
    }


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


def assert_safe_pipeline_error(error: BaseException, expected_type: type[BaseException]) -> None:
    assert isinstance(error, expected_type)
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


def assert_public_success(value: Mapping[str, Any]) -> None:
    assert set(value) <= ALLOWED_SUCCESS_KEYS
    assert value.get("ok") is True
    assert value.get("status") == "success"
    assert value.get("schema_version") == PUBLIC_RESPONSE_SCHEMA_VERSION
    assert "display_plan" in value
    assert_sensitive_sentinels_absent(value)
    assert_no_forbidden_public_keys(value)


def assert_public_failure(value: Mapping[str, Any]) -> None:
    assert set(value) <= ALLOWED_FAILURE_KEYS
    assert value.get("ok") is False
    assert value.get("status") == "error"
    assert value.get("schema_version") == PUBLIC_RESPONSE_SCHEMA_VERSION
    assert "display_plan" not in value
    error = value.get("error")
    assert isinstance(error, Mapping)
    assert set(error) <= ALLOWED_ERROR_KEYS
    assert isinstance(error.get("code"), str)
    assert isinstance(error.get("category"), str)
    assert_sensitive_sentinels_absent(value)
    assert_semantic_sentinels_absent(value)
    assert_no_forbidden_public_keys(value)


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


def pipeline_log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    prefix = "cvbrain_intake_v2_pipeline "
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith(prefix):
            continue
        payload = json.loads(message[len(prefix) :])
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def test_public_pipeline_requires_explicit_source_text_and_source_language():
    Error = pipeline_request_error_type()
    invalid_cases = [
        {"source_language": "Declared-Spanish", "provider": FakeInjectedProvider()},
        {"source_text": "", "source_language": "Declared-Spanish", "provider": FakeInjectedProvider()},
        {"source_text": SOURCE_TEXT, "provider": FakeInjectedProvider()},
        {"source_text": SOURCE_TEXT, "source_language": "", "provider": FakeInjectedProvider()},
        {"source_text": SOURCE_TEXT, "source_language": "Declared-Spanish", "provider": None},
    ]

    for kwargs in invalid_cases:
        with pytest.raises(Error) as exc_info:
            run_public_pipeline(**kwargs)
        assert_safe_pipeline_error(exc_info.value, Error)


def test_public_pipeline_uses_injected_provider_without_env_or_config_access(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "SECRET_TOKEN_SENTINEL")
    monkeypatch.setattr(
        os,
        "getenv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pipeline must not read env vars")),
    )
    sys.modules.pop(PIPELINE_MODULE, None)
    provider = FakeInjectedProvider()
    _module, service, display, response, _order = install_boundaries(monkeypatch)

    result = run_public_pipeline(source_text=SOURCE_TEXT, source_language="Declared-Spanish", provider=provider)

    assert result == public_success_response()
    assert service.calls[0]["provider"] is provider
    assert provider.direct_extract_calls == 0
    assert len(service.calls) == 1
    assert len(display.calls) == 1
    assert len(response.calls) == 1
    assert_sensitive_sentinels_absent(result)


def test_public_pipeline_success_composes_service_display_and_response_once(monkeypatch: pytest.MonkeyPatch):
    provider = FakeInjectedProvider()
    module, service, display, response, call_order = install_boundaries(monkeypatch)

    result = run_public_pipeline(
        source_text=SOURCE_TEXT,
        source_language="Declared-Spanish",
        provider=provider,
        locale="es-UY",
        country_context="UY",
        candidate_market="UY",
        employer_market="UY",
        model="gpt-test-v2-pipeline",
        timeout_seconds=90.0,
    )

    assert result == public_success_response()
    assert_public_success(result)
    assert call_order == ["request", "service", "display", "response"]
    assert len(service.calls) == len(display.calls) == len(response.calls) == 1
    request = service.calls[0]["request"]
    assert isinstance(request, module.IntakeServiceRequestV2)
    assert request.source_text == SOURCE_TEXT
    assert request.source_language == "Declared-Spanish"
    assert request.locale == "es-UY"
    assert service.calls[0]["provider"] is provider
    assert display.calls[0] == service_success_result()
    assert response.calls[0]["service_result"] == service_success_result()
    assert response.calls[0]["kwargs"] == {"display_plan": display_plan_result()}
    assert provider.direct_extract_calls == 0


def test_public_pipeline_service_failure_skips_display_and_returns_public_failure(monkeypatch: pytest.MonkeyPatch):
    provider = FakeInjectedProvider()
    _module, service, display, response, call_order = install_boundaries(
        monkeypatch,
        service_result=service_failure_result(),
        public_response=public_failure_response(),
    )

    result = run_public_pipeline(source_text=SOURCE_TEXT, source_language="Declared-Spanish", provider=provider)

    assert result == public_failure_response()
    assert_public_failure(result)
    assert call_order == ["request", "service", "response"]
    assert len(service.calls) == 1
    assert display.calls == []
    assert len(response.calls) == 1
    assert response.calls[0]["service_result"] == service_failure_result()
    assert "display_plan" not in response.calls[0]["kwargs"]
    assert provider.direct_extract_calls == 0


def test_public_pipeline_preserves_public_response_without_rewrite(monkeypatch: pytest.MonkeyPatch):
    provider = FakeInjectedProvider()
    expected_response = public_success_response()
    expected_response["metadata"]["request_id"] = "req_pipeline_external_safe"
    _module, _service, _display, response, _order = install_boundaries(monkeypatch, public_response=expected_response)

    result = run_public_pipeline(source_text=SOURCE_TEXT, source_language="Declared-Spanish", provider=provider)

    assert result == expected_response
    assert result == response.result
    assert result["metadata"]["request_id"] == "req_pipeline_external_safe"


def test_phrase_changes_do_not_change_pipeline_or_response_metadata_except_copied_values(monkeypatch: pytest.MonkeyPatch):
    first_provider = FakeInjectedProvider()
    first = install_boundaries(
        monkeypatch,
        service_result=service_success_result(phrase="papeles en regla"),
        display_result=display_plan_result(phrase="papeles en regla"),
        public_response=public_success_response(phrase="papeles en regla"),
    )
    first_result = run_public_pipeline(
        source_text="papeles en regla oficial de primera licencia profesional bloqueante nice to have required",
        source_language="Declared-Spanish",
        provider=first_provider,
    )
    first_order = list(first[4])

    monkeypatch.undo()
    second_provider = FakeInjectedProvider()
    second = install_boundaries(
        monkeypatch,
        service_result=service_success_result(phrase="changed AI-owned phrase"),
        display_result=display_plan_result(phrase="changed AI-owned phrase"),
        public_response=public_success_response(phrase="changed AI-owned phrase"),
    )
    second_result = run_public_pipeline(
        source_text="changed AI-owned phrase with required and licencia profesional",
        source_language="Declared-Spanish",
        provider=second_provider,
    )
    second_order = list(second[4])

    assert first_order == second_order == ["request", "service", "display", "response"]
    assert response_shape_signature(first_result) == response_shape_signature(second_result)
    assert set(first_result.get("metadata", {})) == set(second_result.get("metadata", {}))
    assert first_result["status"] == second_result["status"] == "success"
    assert first_result["schema_version"] == second_result["schema_version"] == PUBLIC_RESPONSE_SCHEMA_VERSION
    assert "papeles en regla" in safe_json(first_result["display_plan"])
    assert "changed AI-owned phrase" in safe_json(second_result["display_plan"])


def test_public_pipeline_does_not_infer_readiness_or_semantic_status(monkeypatch: pytest.MonkeyPatch):
    provider = FakeInjectedProvider()
    response_value = public_success_response()
    response_value["display_plan"]["sections"][2]["items"][0]["value"] = "AI-owned-readiness-only"
    _module, _service, _display, _response, _order = install_boundaries(monkeypatch, public_response=response_value)

    result = run_public_pipeline(source_text=SOURCE_TEXT, source_language="Declared-Spanish", provider=provider)

    assert result == response_value
    assert result["status"] == "success"
    assert "readiness" not in result
    assert "readiness_status" not in result
    assert "semantic_status" not in result
    assert "classification" not in result
    metadata = result.get("metadata", {})
    assert isinstance(metadata, Mapping)
    assert "readiness" not in metadata
    assert "semantic_status" not in metadata
    assert "AI-owned-readiness-only" in safe_json(result["display_plan"])


def test_public_pipeline_failure_safety_has_no_raw_or_secret_content(monkeypatch: pytest.MonkeyPatch):
    Error = pipeline_error_type()
    provider = FakeInjectedProvider()
    install_boundaries(monkeypatch, display_error=HostileDependencyError())

    with pytest.raises(Error) as exc_info:
        run_public_pipeline(source_text=SOURCE_TEXT, source_language="Declared-Spanish", provider=provider)

    assert_safe_pipeline_error(exc_info.value, Error)


def test_public_pipeline_response_construction_failure_raises_safe_pipeline_error(monkeypatch: pytest.MonkeyPatch):
    Error = pipeline_error_type()
    provider = FakeInjectedProvider()
    _module, service, display, response, call_order = install_boundaries(
        monkeypatch,
        response_error=HostileDependencyError(),
    )

    with pytest.raises(Error) as exc_info:
        run_public_pipeline(source_text=SOURCE_TEXT, source_language="Declared-Spanish", provider=provider)

    assert call_order == ["request", "service", "display", "response"]
    assert len(service.calls) == 1
    assert len(display.calls) == 1
    assert len(response.calls) == 1
    assert response.calls[0]["service_result"] == service_success_result()
    assert response.calls[0]["kwargs"] == {"display_plan": display_plan_result()}
    assert_safe_pipeline_error(exc_info.value, Error)
    rendered_error = safe_json(exc_info.value)
    assert "HostileDependencyError" not in rendered_error
    assert "provider_payload" not in rendered_error
    assert "authorization" not in rendered_error


def test_pipeline_module_imports_no_endpoint_provider_config_ui_or_v1_runtime():
    module_path = ROOT / "app/intake_v2/pipeline.py"
    if not module_path.exists():
        pytest.fail("Gate 7 pipeline module is not implemented: expected app/intake_v2/pipeline.py")

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


def test_pipeline_logs_are_absent_or_metadata_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    provider = FakeInjectedProvider()
    install_boundaries(monkeypatch, service_result=service_failure_result(), public_response=public_failure_response())

    with caplog.at_level(logging.INFO, logger="cvbrain.intake_v2.pipeline"):
        result = run_public_pipeline(source_text=SOURCE_TEXT, source_language="Declared-Spanish", provider=provider)

    assert_public_failure(result)
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)
    for payload in pipeline_log_payloads(caplog):
        assert set(payload) <= ALLOWED_LOG_KEYS
