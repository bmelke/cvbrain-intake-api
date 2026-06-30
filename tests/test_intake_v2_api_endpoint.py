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

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[1]
API_MODULE = "app.intake_v2.api"
API_PATH = ROOT / "app" / "intake_v2" / "api.py"
PACKAGE_INIT = ROOT / "app" / "intake_v2" / "__init__.py"
ENDPOINT_PATH = "/intake/v2/analyze"
V2_AUTH_ENV = "CVBRAIN_INTAKE_V2_API_KEY"
V2_AUTH_HEADER = "X-CVBrain-V2-API-Key"
V2_AUTH_SECRET = "SERVER_SECRET_SENTINEL"
SOURCE_TEXT = (
    "SOURCE_TEXT_SENTINEL papeles en regla, oficial de primera, licencia profesional, "
    "bloqueante, nice to have, required."
)
SOURCE_LANGUAGE = "Declared-Spanish"
PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"
SENSITIVE_SENTINELS = (
    "SOURCE_TEXT_SENTINEL",
    "PROMPT_BODY_SENTINEL",
    "RAW_OUTPUT_SENTINEL",
    "SECRET_TOKEN_SENTINEL",
    "API_KEY_SENTINEL",
    "BEARER_SENTINEL",
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
    "route",
    "response_status_code",
    "request_id",
}
FORBIDDEN_RESPONSE_KEYS = {
    "api_key",
    "auth_headers",
    "authorization",
    "bearer_token",
    "body",
    "debug",
    "document",
    "endpoint",
    "errors",
    "exception",
    "fastapi_response",
    "flat_compatibility",
    "headers",
    "http_status",
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
FORBIDDEN_API_IMPORTS = {
    "app.extractors",
    "app.main",
    "app.mappers",
    "app.normalization",
    "app.routers",
    "app.routes",
    "app.intake_v2.contract",
    "app.intake_v2.display_plan",
    "app.intake_v2.integrity",
    "app.intake_v2.provider",
    "app.intake_v2.provider_config",
    "app.intake_v2.provider_factory",
    "app.intake_v2.response",
    "app.intake_v2.service",
    "app.intake_v2.shape_recovery",
    "dotenv",
    "openai",
    "requests",
    "httpx",
}
FORBIDDEN_PACKAGE_EXPORTS = {
    "analyze_intake_v2",
    "api",
    "create_intake_v2_router",
    "endpoint",
    "router",
}


class FakeInjectedProvider:
    def __init__(self) -> None:
        self.direct_extract_calls = 0

    def extract(self, _request: Any) -> Any:
        self.direct_extract_calls += 1
        raise AssertionError("endpoint must not call provider.extract directly")


class HostilePipelineError(Exception):
    message = "SOURCE_TEXT_SENTINEL PROMPT_BODY_SENTINEL RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL"
    body = "provider_payload=SECRET_TOKEN_SENTINEL raw=RAW_OUTPUT_SENTINEL"
    headers = {"authorization": "Bearer SECRET_TOKEN_SENTINEL"}

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return "HostilePipelineError(SOURCE_TEXT_SENTINEL SECRET_TOKEN_SENTINEL)"


class RecordingPipeline:
    def __init__(self, result: Mapping[str, Any] | None = None, error: BaseException | None = None) -> None:
        self.result = copy.deepcopy(dict(result or public_success_response()))
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.result)


def api_module() -> Any:
    try:
        return importlib.import_module(API_MODULE)
    except ModuleNotFoundError as error:
        if error.name == API_MODULE:
            pytest.fail(f"Gate 10 endpoint module is not implemented: expected import {API_MODULE} ({error})")
        raise


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for the Gate 10 endpoint boundary")
    return getattr(module, name)


def create_test_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: FakeInjectedProvider | None = None,
    pipeline: RecordingPipeline | None = None,
) -> tuple[TestClient, RecordingPipeline, FakeInjectedProvider]:
    module = api_module()
    provider = provider or FakeInjectedProvider()
    pipeline = pipeline or RecordingPipeline()
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    monkeypatch.setattr(module, "run_public_intake_v2", pipeline, raising=False)

    create_router = required_attr(module, "create_intake_v2_router")
    app = FastAPI()
    app.include_router(create_router(provider_dependency=lambda: provider))
    return TestClient(app), pipeline, provider


def auth_headers() -> dict[str, str]:
    return {V2_AUTH_HEADER: V2_AUTH_SECRET}


def public_success_response(*, phrase: str = "papeles en regla") -> dict[str, Any]:
    return {
        "ok": True,
        "status": "success",
        "schema_version": PUBLIC_RESPONSE_SCHEMA_VERSION,
        "display_plan": {
            "schema_version": "cvbrain_intake_v2_display_plan",
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
                }
            ],
        },
        "metadata": {
            "service_schema_version": "cvbrain_intake_v2_service",
            "display_plan_schema_version": "cvbrain_intake_v2_display_plan",
            "provider": {
                "provider_response_id": "resp_endpoint_safe",
                "provider_request_id": "req_endpoint_safe",
                "model": "fake-endpoint-model",
                "attempt_kind": "extraction",
                "provider_call_count": 1,
                "semantic_attempt_count": 1,
                "repair_count": 0,
                "transient_retry_count": 0,
                "elapsed_seconds": 0.01,
                "parse_path": "json",
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
            "service_schema_version": "cvbrain_intake_v2_service",
            "provider": {
                "provider_response_id": "resp_endpoint_safe",
                "provider_request_id": "req_endpoint_safe",
                "model": "fake-endpoint-model",
                "attempt_kind": "extraction",
                "provider_call_count": 1,
                "semantic_attempt_count": 1,
                "repair_count": 0,
                "transient_retry_count": 0,
                "elapsed_seconds": 0.01,
                "parse_path": "json",
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

    walk(value)
    return keys


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


def assert_sensitive_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SENSITIVE_SENTINELS:
        assert sentinel not in rendered


def assert_semantic_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SEMANTIC_SENTINELS:
        assert sentinel not in rendered


def assert_no_forbidden_keys(value: Any) -> None:
    assert all_keys(value).isdisjoint(FORBIDDEN_RESPONSE_KEYS)


def assert_public_success(value: Mapping[str, Any]) -> None:
    assert set(value) <= ALLOWED_SUCCESS_KEYS
    assert value.get("ok") is True
    assert value.get("status") == "success"
    assert value.get("schema_version") == PUBLIC_RESPONSE_SCHEMA_VERSION
    assert "display_plan" in value
    assert_no_forbidden_keys(value)


def assert_public_failure(value: Mapping[str, Any]) -> None:
    assert set(value) <= ALLOWED_FAILURE_KEYS
    assert value.get("ok") is False
    assert value.get("status") == "error"
    assert value.get("schema_version") == PUBLIC_RESPONSE_SCHEMA_VERSION
    error = value.get("error")
    assert isinstance(error, Mapping)
    assert set(error) <= ALLOWED_ERROR_KEYS
    assert isinstance(error.get("code"), str)
    assert isinstance(error.get("category"), str)
    assert "display_plan" not in value
    assert_sensitive_sentinels_absent(value)
    assert_no_forbidden_keys(value)


def imports_for_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def is_forbidden_import(module: str) -> bool:
    return any(module == forbidden or module.startswith(forbidden + ".") for forbidden in FORBIDDEN_API_IMPORTS)


def endpoint_log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    prefix = "cvbrain_intake_v2_api "
    for record in caplog.records:
        if not record.name.startswith("cvbrain.intake_v2.api"):
            continue
        message = record.getMessage()
        assert message.startswith(prefix)
        payload = json.loads(message[len(prefix) :])
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def assert_pipeline_called_once_with_exact_inputs(
    pipeline: RecordingPipeline,
    provider: FakeInjectedProvider,
    *,
    source_text: str = SOURCE_TEXT,
    source_language: str = SOURCE_LANGUAGE,
) -> None:
    assert len(pipeline.calls) == 1
    call = pipeline.calls[0]
    assert call["source_text"] == source_text
    assert call["source_language"] == source_language
    assert call["provider"] is provider
    assert "inferred_source_language" not in call
    assert "normalized_source_text" not in call
    assert "semantic_status" not in call
    assert provider.direct_extract_calls == 0


def test_api_module_import_is_side_effect_safe_without_env_provider_or_app_main(monkeypatch: pytest.MonkeyPatch):
    import app.intake_v2  # noqa: F401

    monkeypatch.setenv("OPENAI_API_KEY", "SECRET_TOKEN_SENTINEL")
    monkeypatch.setattr(
        os,
        "getenv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("endpoint must not read env vars")),
    )
    before_modules = dict(sys.modules)
    sys.modules.pop(API_MODULE, None)
    provider_runtime_calls: list[str] = []

    def profile(frame: Any, event: str, _arg: Any) -> None:
        if event != "call":
            return
        filename = Path(frame.f_code.co_filename)
        if filename.name in {"provider.py", "provider_config.py"} and frame.f_code.co_name in {
            "__init__",
            "_client",
            "build_openai_provider_v2",
        }:
            provider_runtime_calls.append(f"{filename.name}:{frame.f_code.co_name}")

    sys.setprofile(profile)
    try:
        module = api_module()
        loaded_or_replaced = {name for name, module_value in sys.modules.items() if before_modules.get(name) is not module_value}
        forbidden_loaded = sorted(
            name
            for name in loaded_or_replaced
            if name != API_MODULE and is_forbidden_import(name) and not name.startswith("app.intake_v2.pipeline")
        )
    finally:
        sys.setprofile(None)

    assert module.__name__ == API_MODULE
    assert provider_runtime_calls == []
    assert forbidden_loaded == []
    if "app.main" not in before_modules:
        assert "app.main" not in sys.modules


def test_api_module_imports_no_provider_config_env_ui_wordpress_or_v1_runtime():
    if not API_PATH.exists():
        pytest.fail("Gate 10 endpoint module is not implemented: expected app/intake_v2/api.py")

    imports = imports_for_file(API_PATH)
    offenders = sorted(imported for imported in imports if is_forbidden_import(imported))
    source = API_PATH.read_text(encoding="utf-8").lower()
    source_offenders = sorted(
        token
        for token in (
            "authorization",
            "bearer",
            "dotenv",
            "environ",
            "provider_config",
            "secret",
            "source_language_inferred",
        )
        if token in source
    )

    assert offenders == []
    assert source_offenders == []


def test_create_router_exposes_endpoint_without_app_main_registration(monkeypatch: pytest.MonkeyPatch):
    before_main = sys.modules.get("app.main")
    client, pipeline, provider = create_test_client(monkeypatch)

    response = client.post(
        ENDPOINT_PATH,
        json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == public_success_response()
    assert_pipeline_called_once_with_exact_inputs(pipeline, provider)
    if before_main is None:
        assert "app.main" not in sys.modules
    else:
        assert sys.modules.get("app.main") is before_main


def test_endpoint_requires_source_text_and_source_language_safely(monkeypatch: pytest.MonkeyPatch):
    client, pipeline, _provider = create_test_client(monkeypatch)
    invalid_payloads = [
        {},
        {"source_language": SOURCE_LANGUAGE},
        {"source_text": ""},
        {"source_text": "   ", "source_language": SOURCE_LANGUAGE},
        {"source_text": SOURCE_TEXT},
        {"source_text": SOURCE_TEXT, "source_language": ""},
        {"source_text": SOURCE_TEXT, "source_language": "   "},
    ]

    for payload in invalid_payloads:
        response = client.post(ENDPOINT_PATH, json=payload, headers=auth_headers())
        assert response.status_code == 400
        body = response.json()
        assert_public_failure(body)
        assert body["error"] == {"code": "invalid_request", "category": "request_validation"}
        assert_sensitive_sentinels_absent(body)
        assert_semantic_sentinels_absent(body)

    assert pipeline.calls == []


def test_valid_request_calls_public_pipeline_once_with_exact_inputs_and_injected_provider(
    monkeypatch: pytest.MonkeyPatch,
):
    client, pipeline, provider = create_test_client(monkeypatch)

    response = client.post(
        ENDPOINT_PATH,
        json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == public_success_response()
    assert_pipeline_called_once_with_exact_inputs(pipeline, provider)


def test_endpoint_returns_public_success_envelope_unchanged(monkeypatch: pytest.MonkeyPatch):
    expected = public_success_response()
    expected["metadata"]["request_id"] = "req_endpoint_external_safe"
    pipeline = RecordingPipeline(result=expected)
    client, pipeline, _provider = create_test_client(monkeypatch, pipeline=pipeline)

    response = client.post(
        ENDPOINT_PATH,
        json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert_public_success(response.json())


def test_pipeline_public_failure_envelope_returns_unchanged_without_display_or_ui_additions(
    monkeypatch: pytest.MonkeyPatch,
):
    expected = public_failure_response()
    pipeline = RecordingPipeline(result=expected)
    client, pipeline, provider = create_test_client(monkeypatch, pipeline=pipeline)

    response = client.post(
        ENDPOINT_PATH,
        json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert_public_failure(response.json())
    assert_pipeline_called_once_with_exact_inputs(pipeline, provider)


def test_pipeline_exception_returns_safe_http_failure_without_sensitive_content(monkeypatch: pytest.MonkeyPatch):
    pipeline = RecordingPipeline(error=HostilePipelineError())
    client, pipeline, provider = create_test_client(monkeypatch, pipeline=pipeline)

    response = client.post(
        ENDPOINT_PATH,
        json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
        headers=auth_headers(),
    )

    assert response.status_code == 500
    body = response.json()
    assert_public_failure(body)
    assert body["error"] == {"code": "pipeline_failed", "category": "pipeline"}
    assert_sensitive_sentinels_absent(body)
    assert_semantic_sentinels_absent(body)
    assert "HostilePipelineError" not in safe_json(body)
    assert_pipeline_called_once_with_exact_inputs(pipeline, provider)


def test_domain_phrase_changes_do_not_change_endpoint_behavior_or_metadata_shape(monkeypatch: pytest.MonkeyPatch):
    first_pipeline = RecordingPipeline(result=public_success_response(phrase="papeles en regla"))
    first_client, first_pipeline, first_provider = create_test_client(monkeypatch, pipeline=first_pipeline)
    first = first_client.post(
        ENDPOINT_PATH,
        json={
            "source_text": "papeles en regla oficial de primera licencia profesional bloqueante nice to have required",
            "source_language": SOURCE_LANGUAGE,
        },
        headers=auth_headers(),
    )
    monkeypatch.undo()

    second_pipeline = RecordingPipeline(result=public_success_response(phrase="changed AI-owned phrase"))
    second_client, second_pipeline, second_provider = create_test_client(monkeypatch, pipeline=second_pipeline)
    second = second_client.post(
        ENDPOINT_PATH,
        json={"source_text": "changed AI-owned phrase with required", "source_language": SOURCE_LANGUAGE},
        headers=auth_headers(),
    )

    assert first.status_code == second.status_code == 200
    assert response_shape_signature(first.json()) == response_shape_signature(second.json())
    assert set(first.json().get("metadata", {})) == set(second.json().get("metadata", {}))
    assert_pipeline_called_once_with_exact_inputs(
        first_pipeline,
        first_provider,
        source_text="papeles en regla oficial de primera licencia profesional bloqueante nice to have required",
    )
    assert_pipeline_called_once_with_exact_inputs(
        second_pipeline,
        second_provider,
        source_text="changed AI-owned phrase with required",
    )


def test_endpoint_response_does_not_add_wordpress_ui_v1_or_legacy_fields(monkeypatch: pytest.MonkeyPatch):
    client, _pipeline, _provider = create_test_client(monkeypatch)

    response = client.post(
        ENDPOINT_PATH,
        json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
        headers=auth_headers(),
    )

    body = response.json()
    assert_no_forbidden_keys(body)
    assert "wordpress" not in body
    assert "standalone" not in body
    assert "ui_sections" not in body
    assert "v1_compatibility" not in body
    assert "flat_compatibility" not in body


def test_package_root_does_not_export_endpoint_symbols_in_this_gate():
    import app.intake_v2 as package

    for name in FORBIDDEN_PACKAGE_EXPORTS:
        assert name not in package.__all__

    assert not hasattr(package, "create_intake_v2_router")
    assert not hasattr(package, "router")

    imports = imports_for_file(PACKAGE_INIT)
    assert "app.intake_v2.api" not in imports
    assert "app.intake_v2.endpoint" not in imports


def test_endpoint_logs_are_absent_or_metadata_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    pipeline = RecordingPipeline(error=HostilePipelineError())
    client, _pipeline, _provider = create_test_client(monkeypatch, pipeline=pipeline)

    with caplog.at_level(logging.INFO, logger="cvbrain.intake_v2.api"):
        response = client.post(
            ENDPOINT_PATH,
            json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
            headers=auth_headers(),
        )

    assert response.status_code == 500
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)
    for payload in endpoint_log_payloads(caplog):
        assert set(payload) <= ALLOWED_LOG_KEYS
