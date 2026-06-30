from __future__ import annotations

import ast
from contextlib import contextmanager
import importlib
import inspect
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping

from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_MAIN_MODULE = "app.main"
APP_MAIN_PATH = ROOT / "app" / "main.py"
PROVIDER_CONFIG_MODULE = "app.intake_v2.provider_config"
ENDPOINT_PATH = "/intake/v2/analyze"
V2_API_KEY_ENV = "CVBRAIN_INTAKE_V2_OPENAI_API_KEY"
V2_MODEL_ENV = "CVBRAIN_INTAKE_V2_OPENAI_MODEL"
FORBIDDEN_IMPORT_ENV_FRAGMENTS = ("CVBRAIN_INTAKE_V2", "OPENAI_API_KEY", "API_KEY", "SECRET", "TOKEN", "BEARER")
MODEL = "gpt-test-v2-app-provider-dependency"
API_KEY = "SECRET_TOKEN_SENTINEL_API_KEY_SENTINEL_BEARER_SENTINEL"
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
    "AUTH_HEADER_SENTINEL",
)
SEMANTIC_SENTINELS = (
    "papeles en regla",
    "oficial de primera",
    "licencia profesional",
    "bloqueante",
    "nice to have",
    "required",
)
FORBIDDEN_RESPONSE_KEYS = {
    "api_key",
    "auth_headers",
    "authorization",
    "bearer_token",
    "debug",
    "document",
    "flat_compatibility",
    "prompt",
    "prompt_body",
    "provider_body",
    "provider_payload",
    "raw_exception",
    "raw_output",
    "raw_provider_output",
    "source_text",
    "standalone",
    "ui_sections",
    "v1_compatibility",
    "wordpress",
}
FORBIDDEN_DEPENDENCY_PARAMETERS = {
    "headers",
    "http_request",
    "request",
    "source_language",
    "source_text",
}
FORBIDDEN_DEPENDENCY_BODY_TERMS = {
    "canonical",
    "detect_language",
    "fallback",
    "mapper",
    "normalizer",
    "normalize",
    "required",
    "source_language",
    "source_text",
}
ALLOWED_LOG_KEYS = {
    "event",
    "status",
    "code",
    "category",
    "model",
    "route",
    "response_status_code",
    "request_id",
}


class FakeProvider:
    def __init__(self) -> None:
        self.direct_extract_calls = 0

    def extract(self, _request: Any) -> Any:
        self.direct_extract_calls += 1
        raise AssertionError("app-level V2 provider dependency must not call provider.extract directly")


class RecordingPipeline:
    def __init__(self, result: Mapping[str, Any] | None = None) -> None:
        self.result = dict(result or public_success_response())
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(dict(kwargs))
        return json.loads(json.dumps(self.result))


@contextmanager
def fresh_app_main_import() -> Iterator[Any]:
    original_main = sys.modules.get(APP_MAIN_MODULE)
    had_main = APP_MAIN_MODULE in sys.modules
    app_package = sys.modules.get("app")
    had_app_main_attr = app_package is not None and hasattr(app_package, "main")
    original_app_main_attr = getattr(app_package, "main", None) if app_package is not None else None

    sys.modules.pop(APP_MAIN_MODULE, None)
    if app_package is not None and hasattr(app_package, "main"):
        delattr(app_package, "main")

    try:
        yield importlib.import_module(APP_MAIN_MODULE)
    finally:
        sys.modules.pop(APP_MAIN_MODULE, None)
        if had_main:
            sys.modules[APP_MAIN_MODULE] = original_main

        current_app_package = sys.modules.get("app")
        if current_app_package is not None:
            if had_app_main_attr:
                setattr(current_app_package, "main", original_app_main_attr)
            elif hasattr(current_app_package, "main"):
                delattr(current_app_package, "main")


@contextmanager
def provider_runtime_call_recorder(*, include_config_construction: bool = False) -> Iterator[list[str]]:
    calls: list[str] = []

    def profile(frame: Any, event: str, _arg: Any) -> None:
        if event != "call":
            return
        filename = Path(frame.f_code.co_filename).name
        function_name = frame.f_code.co_name
        if filename == "provider.py" and function_name in {"__init__", "_client"}:
            calls.append(f"{filename}:{function_name}")
        if include_config_construction and filename == "provider_config.py" and function_name in {
            "__post_init__",
            "build_openai_provider_v2",
        }:
            calls.append(f"{filename}:{function_name}")

    previous_profile = sys.getprofile()
    sys.setprofile(profile)
    try:
        yield calls
    finally:
        sys.setprofile(previous_profile)


def app_main_module() -> Any:
    return importlib.import_module(APP_MAIN_MODULE)


def provider_config_module() -> Any:
    return importlib.import_module(PROVIDER_CONFIG_MODULE)


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for Gate 12 app-level provider dependency wiring")
    return getattr(module, name)


def registered_intake_v2_endpoint(app: Any) -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == ENDPOINT_PATH and "POST" in getattr(route, "methods", set()):
            endpoint = getattr(route, "endpoint", None)
            if endpoint is not None:
                return endpoint
    pytest.fail(f"{APP_MAIN_MODULE}.app must register POST {ENDPOINT_PATH}")


def clear_dependency_overrides(app: Any) -> None:
    app.dependency_overrides.clear()


def public_success_response() -> dict[str, Any]:
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
                            "value": "papeles en regla; oficial de primera; licencia profesional",
                        }
                    ],
                }
            ],
        },
        "metadata": {
            "service_schema_version": "cvbrain_intake_v2_service",
            "display_plan_schema_version": "cvbrain_intake_v2_display_plan",
            "provider": {
                "provider_response_id": "resp_app_provider_dependency_safe",
                "provider_request_id": "req_app_provider_dependency_safe",
                "model": "fake-app-provider-dependency-model",
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


def assert_sensitive_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SENSITIVE_SENTINELS:
        assert sentinel not in rendered


def assert_semantic_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SEMANTIC_SENTINELS:
        assert sentinel not in rendered


def assert_public_failure(value: Mapping[str, Any]) -> None:
    assert value.get("ok") is False
    assert value.get("status") == "error"
    assert value.get("schema_version") == PUBLIC_RESPONSE_SCHEMA_VERSION
    assert "display_plan" not in value
    error = value.get("error")
    assert isinstance(error, Mapping)
    assert isinstance(error.get("code"), str)
    assert isinstance(error.get("category"), str)
    assert all_keys(value).isdisjoint(FORBIDDEN_RESPONSE_KEYS)
    assert_sensitive_sentinels_absent(value)


def assert_pipeline_called_once_with_exact_inputs(pipeline: RecordingPipeline, provider: FakeProvider) -> None:
    assert len(pipeline.calls) == 1
    call = pipeline.calls[0]
    assert call["source_text"] == SOURCE_TEXT
    assert call["source_language"] == SOURCE_LANGUAGE
    assert call["provider"] is provider
    assert "inferred_source_language" not in call
    assert "normalized_source_text" not in call
    assert provider.direct_extract_calls == 0


def app_log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith("cvbrain_intake_v2_app "):
            continue
        payload = json.loads(message.removeprefix("cvbrain_intake_v2_app "))
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def get_provider_function_source() -> str:
    tree = ast.parse(APP_MAIN_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_intake_v2_provider":
            segment = ast.get_source_segment(APP_MAIN_PATH.read_text(encoding="utf-8"), node)
            assert segment is not None
            return segment.lower()
    pytest.fail("app.main must define get_intake_v2_provider")


def test_app_main_import_does_not_read_v2_env_or_construct_provider(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_API_KEY_ENV, API_KEY)
    monkeypatch.setenv(V2_MODEL_ENV, MODEL)

    def forbidden_v2_getenv(name: str, default: Any = None) -> Any:
        if any(fragment in name.upper() for fragment in FORBIDDEN_IMPORT_ENV_FRAGMENTS):
            raise AssertionError(f"app.main import must not read provider secret env var {name}")
        return default

    monkeypatch.setattr(os, "getenv", forbidden_v2_getenv)

    caplog.set_level(logging.INFO)
    with provider_runtime_call_recorder(include_config_construction=True) as provider_calls:
        with fresh_app_main_import() as main:
            assert required_attr(main, "app") is not None
            assert callable(required_attr(main, "get_intake_v2_provider"))

    assert provider_calls == []
    assert_sensitive_sentinels_absent(caplog.text)


def test_missing_v2_provider_config_returns_safe_unavailable_response_without_live_provider(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.delenv(V2_API_KEY_ENV, raising=False)
    monkeypatch.delenv(V2_MODEL_ENV, raising=False)
    caplog.set_level(logging.INFO)

    main = app_main_module()
    clear_dependency_overrides(main.app)
    client = TestClient(main.app)

    with provider_runtime_call_recorder() as provider_calls:
        response = client.post(ENDPOINT_PATH, json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE})

    assert response.status_code in {500, 503}
    body = response.json()
    assert_public_failure(body)
    assert body["error"]["category"] in {"configuration", "pipeline", "provider"}
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(body)
    assert provider_calls == []


def test_explicit_v2_config_builds_provider_lazily_with_provider_config_boundary(
    monkeypatch: pytest.MonkeyPatch,
):
    main = app_main_module()
    provider_config = provider_config_module()
    Config = required_attr(provider_config, "OpenAIProviderConfigV2")
    built_provider = FakeProvider()
    builder_calls: list[dict[str, Any]] = []

    def fake_build_openai_provider_v2(config: Any, *, client: Any = None) -> FakeProvider:
        builder_calls.append({"config": config, "client": client})
        if not isinstance(config, Config):
            pytest.fail("builder must receive OpenAIProviderConfigV2")
        if config.api_key != API_KEY:
            pytest.fail("builder received unexpected API key value")
        if config.model != MODEL:
            pytest.fail("builder received unexpected model value")
        return built_provider

    monkeypatch.setenv(V2_API_KEY_ENV, API_KEY)
    monkeypatch.setenv(V2_MODEL_ENV, MODEL)
    monkeypatch.setattr(provider_config, "build_openai_provider_v2", fake_build_openai_provider_v2)
    if hasattr(main, "build_openai_provider_v2"):
        monkeypatch.setattr(main, "build_openai_provider_v2", fake_build_openai_provider_v2)

    with provider_runtime_call_recorder() as provider_calls:
        provider = main.get_intake_v2_provider()

    assert provider is built_provider
    assert len(builder_calls) == 1
    assert builder_calls[0]["client"] is None
    assert provider_calls == []


def test_dependency_override_bypasses_v2_config_and_still_uses_fake_provider(
    monkeypatch: pytest.MonkeyPatch,
):
    main = app_main_module()
    app = required_attr(main, "app")
    provider_dependency = required_attr(main, "get_intake_v2_provider")
    provider_config = provider_config_module()
    pipeline = RecordingPipeline()
    provider = FakeProvider()
    endpoint = registered_intake_v2_endpoint(app)

    def forbidden_getenv(name: str, *_args: Any, **_kwargs: Any) -> str:
        raise AssertionError(f"dependency override must bypass env var {name}")

    def forbidden_builder(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("dependency override must bypass provider_config construction")

    monkeypatch.setattr(os, "getenv", forbidden_getenv)
    monkeypatch.setattr(provider_config, "build_openai_provider_v2", forbidden_builder)
    monkeypatch.setitem(endpoint.__globals__, "run_public_intake_v2", pipeline)
    app.dependency_overrides[provider_dependency] = lambda: provider
    try:
        response = TestClient(app).post(
            ENDPOINT_PATH,
            json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
        )
    finally:
        clear_dependency_overrides(app)

    assert response.status_code == 200
    assert response.json() == public_success_response()
    assert_pipeline_called_once_with_exact_inputs(pipeline, provider)


def test_provider_dependency_has_no_source_text_or_source_language_contract():
    main = app_main_module()
    dependency = required_attr(main, "get_intake_v2_provider")
    parameter_names = set(inspect.signature(dependency).parameters)
    function_source = get_provider_function_source()

    assert parameter_names.isdisjoint(FORBIDDEN_DEPENDENCY_PARAMETERS)
    for term in FORBIDDEN_DEPENDENCY_BODY_TERMS:
        assert term not in function_source


def test_invalid_v2_config_failure_does_not_leak_secret_sentinels(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_API_KEY_ENV, API_KEY)
    monkeypatch.setenv(V2_MODEL_ENV, "   ")
    caplog.set_level(logging.INFO)

    main = app_main_module()
    clear_dependency_overrides(main.app)
    response = TestClient(main.app).post(
        ENDPOINT_PATH,
        json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
    )

    assert response.status_code in {500, 503}
    assert_public_failure(response.json())
    assert_sensitive_sentinels_absent(response.json())
    assert_sensitive_sentinels_absent(caplog.text)


def test_app_provider_dependency_logs_are_absent_or_metadata_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.delenv(V2_API_KEY_ENV, raising=False)
    monkeypatch.delenv(V2_MODEL_ENV, raising=False)
    caplog.set_level(logging.INFO, logger="cvbrain.intake_v2.app")

    main = app_main_module()
    clear_dependency_overrides(main.app)
    response = TestClient(main.app).post(
        ENDPOINT_PATH,
        json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE},
    )

    assert response.status_code in {500, 503}
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)
    for payload in app_log_payloads(caplog):
        assert set(payload) <= ALLOWED_LOG_KEYS
