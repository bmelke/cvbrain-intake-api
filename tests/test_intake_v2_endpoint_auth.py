from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping

from fastapi.testclient import TestClient
import pytest


APP_MAIN_MODULE = "app.main"
API_MODULE = "app.intake_v2.api"
ENDPOINT_PATH = "/intake/v2/analyze"
V2_AUTH_ENV = "CVBRAIN_INTAKE_V2_API_KEY"
V2_AUTH_HEADER = "X-CVBrain-V2-API-Key"
V2_AUTH_SECRET = "SERVER_SECRET_SENTINEL"
WRONG_CLIENT_SECRET = "WRONG_CLIENT_SECRET_SENTINEL"
SOURCE_TEXT = (
    "SOURCE_TEXT_SENTINEL papeles en regla, oficial de primera, licencia profesional, "
    "bloqueante, nice to have, required. PROMPT_SENTINEL PROVIDER_PAYLOAD_SENTINEL BEARER_SENTINEL"
)
SOURCE_LANGUAGE = "Declared-Spanish"
PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"
SENSITIVE_SENTINELS = (
    "SERVER_SECRET_SENTINEL",
    "WRONG_CLIENT_SECRET_SENTINEL",
    "SOURCE_TEXT_SENTINEL",
    "PROMPT_SENTINEL",
    "PROVIDER_PAYLOAD_SENTINEL",
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
FORBIDDEN_RESPONSE_KEYS = {
    "api_key",
    "auth_headers",
    "authorization",
    "bearer_token",
    "debug",
    "headers",
    "prompt",
    "prompt_body",
    "provider_body",
    "provider_payload",
    "raw_exception",
    "raw_output",
    "raw_provider_output",
    "request_body",
    "response_body",
    "source_text",
}
V1_ONLY_AUTH_HEADERS = (
    {"X-CVBrain-API-Key": V2_AUTH_SECRET},
    {"X-TrabajoAca-API-Key": V2_AUTH_SECRET},
    {"Authorization": f"Bearer {V2_AUTH_SECRET}"},
)


class FakeProvider:
    def __init__(self) -> None:
        self.direct_extract_calls = 0

    def extract(self, _request: Any) -> Any:
        self.direct_extract_calls += 1
        raise AssertionError("V2 endpoint auth must run before provider.extract")


class RecordingPipeline:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(dict(kwargs))
        return public_success_response()


class RecordingProviderDependency:
    def __init__(self) -> None:
        self.calls = 0
        self.provider = FakeProvider()

    def __call__(self) -> FakeProvider:
        self.calls += 1
        return self.provider


@contextmanager
def provider_runtime_call_recorder() -> Iterator[list[str]]:
    calls: list[str] = []

    def profile(frame: Any, event: str, _arg: Any) -> None:
        if event != "call":
            return
        filename = Path(frame.f_code.co_filename).name
        function_name = frame.f_code.co_name
        if filename == "provider.py" and function_name in {"__init__", "_client"}:
            calls.append(f"{filename}:{function_name}")
        if filename == "provider_config.py" and function_name in {"__post_init__", "build_openai_provider_v2"}:
            calls.append(f"{filename}:{function_name}")

    previous_profile = sys.getprofile()
    sys.setprofile(profile)
    try:
        yield calls
    finally:
        sys.setprofile(previous_profile)


@contextmanager
def fresh_v2_imports() -> Iterator[Any]:
    module_names = (API_MODULE, APP_MAIN_MODULE)
    originals = {name: sys.modules.get(name) for name in module_names}
    existed = {name for name in module_names if name in sys.modules}
    app_package = sys.modules.get("app")
    original_main_attr = getattr(app_package, "main", None) if app_package is not None else None
    had_main_attr = app_package is not None and hasattr(app_package, "main")

    for name in module_names:
        sys.modules.pop(name, None)
    if app_package is not None and hasattr(app_package, "main"):
        delattr(app_package, "main")

    try:
        yield importlib.import_module(APP_MAIN_MODULE)
    finally:
        for name in module_names:
            sys.modules.pop(name, None)
            if name in existed:
                sys.modules[name] = originals[name]
        current_app_package = sys.modules.get("app")
        if current_app_package is not None:
            if had_main_attr:
                setattr(current_app_package, "main", original_main_attr)
            elif hasattr(current_app_package, "main"):
                delattr(current_app_package, "main")


def app_main_module() -> Any:
    return importlib.import_module(APP_MAIN_MODULE)


def registered_intake_v2_endpoint(app: Any) -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == ENDPOINT_PATH and "POST" in getattr(route, "methods", set()):
            endpoint = getattr(route, "endpoint", None)
            if endpoint is not None:
                return endpoint
    pytest.fail(f"{APP_MAIN_MODULE}.app must register POST {ENDPOINT_PATH}")


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
                            "value": "safe copied AI-owned text",
                        }
                    ],
                }
            ],
        },
        "metadata": {
            "provider": {
                "provider_response_id": "resp_endpoint_auth_safe",
                "provider_request_id": "req_endpoint_auth_safe",
                "model": "fake-auth-model",
            },
        },
    }


def request_payload() -> dict[str, str]:
    return {"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE}


def valid_auth_headers() -> dict[str, str]:
    return {V2_AUTH_HEADER: V2_AUTH_SECRET}


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


def assert_safe_failure_body(value: Any) -> None:
    assert isinstance(value, Mapping)
    assert value.get("ok") is False
    assert value.get("status") == "error"
    assert value.get("schema_version") == PUBLIC_RESPONSE_SCHEMA_VERSION
    error = value.get("error")
    assert isinstance(error, Mapping)
    assert isinstance(error.get("code"), str)
    assert isinstance(error.get("category"), str)
    assert "display_plan" not in value
    assert all_keys(value).isdisjoint(FORBIDDEN_RESPONSE_KEYS)
    assert_sensitive_sentinels_absent(value)
    assert_semantic_sentinels_absent(value)


def assert_auth_failure_stopped_before_provider_pipeline(
    *,
    pipeline: RecordingPipeline,
    provider_dependency: RecordingProviderDependency,
    provider_runtime_calls: list[str],
) -> None:
    assert pipeline.calls == []
    assert provider_dependency.calls == 0
    assert provider_dependency.provider.direct_extract_calls == 0
    assert provider_runtime_calls == []


def install_fake_runtime(main: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[RecordingPipeline, RecordingProviderDependency]:
    app = main.app
    app.dependency_overrides.clear()
    provider_dependency = RecordingProviderDependency()
    pipeline = RecordingPipeline()
    endpoint = registered_intake_v2_endpoint(app)
    monkeypatch.setitem(endpoint.__globals__, "run_public_intake_v2", pipeline)
    app.dependency_overrides[main.get_intake_v2_provider] = provider_dependency
    return pipeline, provider_dependency


def post_with_fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    headers: Mapping[str, str] | None = None,
) -> tuple[Any, RecordingPipeline, RecordingProviderDependency, list[str]]:
    main = app_main_module()
    pipeline, provider_dependency = install_fake_runtime(main, monkeypatch)
    client = TestClient(main.app)

    try:
        with provider_runtime_call_recorder() as provider_runtime_calls:
            response = client.post(ENDPOINT_PATH, json=request_payload(), headers=dict(headers or {}))
            captured_provider_runtime_calls = list(provider_runtime_calls)
    finally:
        main.app.dependency_overrides.clear()

    return response, pipeline, provider_dependency, captured_provider_runtime_calls


def test_missing_server_key_fails_closed_before_provider_pipeline_or_source_inspection(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.delenv(V2_AUTH_ENV, raising=False)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_with_fake_runtime(
        monkeypatch,
        headers=valid_auth_headers(),
    )

    assert response.status_code == 503
    assert_safe_failure_body(response.json())
    assert_auth_failure_stopped_before_provider_pipeline(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)


def test_blank_server_key_fails_closed_before_provider_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, "   ")
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_with_fake_runtime(
        monkeypatch,
        headers=valid_auth_headers(),
    )

    assert response.status_code == 503
    assert_safe_failure_body(response.json())
    assert_auth_failure_stopped_before_provider_pipeline(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)


def test_missing_client_header_rejected_before_provider_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_with_fake_runtime(monkeypatch)

    assert response.status_code == 401
    assert_safe_failure_body(response.json())
    assert_auth_failure_stopped_before_provider_pipeline(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)


def test_invalid_client_header_rejected_before_provider_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_with_fake_runtime(
        monkeypatch,
        headers={V2_AUTH_HEADER: WRONG_CLIENT_SECRET},
    )

    assert response.status_code == 401
    assert_safe_failure_body(response.json())
    assert_auth_failure_stopped_before_provider_pipeline(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)


def test_valid_v2_header_allows_existing_route_behavior_without_auth_interpretation(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)

    response, pipeline, provider_dependency, provider_runtime_calls = post_with_fake_runtime(
        monkeypatch,
        headers=valid_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == public_success_response()
    assert len(pipeline.calls) == 1
    call = pipeline.calls[0]
    assert call["source_text"] == SOURCE_TEXT
    assert call["source_language"] == SOURCE_LANGUAGE
    assert call["provider"] is provider_dependency.provider
    assert "inferred_source_language" not in call
    assert "normalized_source_text" not in call
    assert "auth_decision" not in call
    assert provider_dependency.calls == 1
    assert provider_dependency.provider.direct_extract_calls == 0
    assert provider_runtime_calls == []


@pytest.mark.parametrize("headers", V1_ONLY_AUTH_HEADERS)
def test_v1_headers_and_authorization_bearer_do_not_authorize_v2(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    headers: Mapping[str, str],
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_with_fake_runtime(
        monkeypatch,
        headers=headers,
    )

    assert response.status_code == 401
    assert_safe_failure_body(response.json())
    assert_auth_failure_stopped_before_provider_pipeline(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)


def test_v2_auth_env_read_is_lazy_and_request_scoped(monkeypatch: pytest.MonkeyPatch):
    real_getenv = os.getenv

    def forbidden_import_getenv(name: str, default: Any = None) -> Any:
        if name == V2_AUTH_ENV:
            raise AssertionError("V2 endpoint auth must not read access key env at import time")
        return real_getenv(name, default)

    monkeypatch.setattr(os, "getenv", forbidden_import_getenv)
    with provider_runtime_call_recorder() as import_provider_calls:
        with fresh_v2_imports() as main:
            assert main.app is not None
            assert import_provider_calls == []

            reads: list[str] = []

            def observed_request_getenv(name: str, default: Any = None) -> Any:
                if name == V2_AUTH_ENV:
                    reads.append(name)
                    return V2_AUTH_SECRET
                return real_getenv(name, default)

            monkeypatch.setattr(os, "getenv", observed_request_getenv)
            pipeline, provider_dependency = install_fake_runtime(main, monkeypatch)
            try:
                response = TestClient(main.app).post(
                    ENDPOINT_PATH,
                    json=request_payload(),
                    headers=valid_auth_headers(),
                )
            finally:
                main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert reads == [V2_AUTH_ENV]
    assert len(pipeline.calls) == 1
    assert provider_dependency.calls == 1


def test_auth_failure_body_logs_and_exception_rendering_are_safe(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_with_fake_runtime(
        monkeypatch,
        headers={V2_AUTH_HEADER: WRONG_CLIENT_SECRET},
    )

    assert response.status_code == 401
    body = response.json()
    assert_safe_failure_body(body)
    assert_sensitive_sentinels_absent(body)
    assert_sensitive_sentinels_absent(caplog.text)
    assert_sensitive_sentinels_absent({"response": body, "logs": caplog.text})
    assert "WRONG_CLIENT_SECRET_SENTINEL" not in response.text
    assert_auth_failure_stopped_before_provider_pipeline(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
