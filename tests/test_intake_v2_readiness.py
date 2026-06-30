from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping

from fastapi.testclient import TestClient
import pytest


APP_MAIN_MODULE = "app.main"
ANALYZE_PATH = "/intake/v2/analyze"
READINESS_PATH = "/intake/v2/status"
V2_AUTH_ENV = "CVBRAIN_INTAKE_V2_API_KEY"
V2_AUTH_HEADER = "X-CVBrain-V2-API-Key"
V2_AUTH_SECRET = "SERVER_SECRET_SENTINEL"
WRONG_CLIENT_SECRET = "WRONG_CLIENT_SECRET_SENTINEL"
OPENAI_KEY_SENTINEL = "OPENAI_KEY_SENTINEL"
MODEL_NAME_SENTINEL = "MODEL_NAME_SENTINEL"
V1_KEY_SENTINEL = "V1_KEY_SENTINEL"
SOURCE_TEXT_SENTINEL = (
    "SOURCE_TEXT_SENTINEL papeles en regla, oficial de primera, licencia profesional, "
    "bloqueante, nice to have, required."
)
SOURCE_LANGUAGE = "Declared-Spanish"
PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"
SENSITIVE_SENTINELS = (
    V2_AUTH_SECRET,
    WRONG_CLIENT_SECRET,
    OPENAI_KEY_SENTINEL,
    MODEL_NAME_SENTINEL,
    V1_KEY_SENTINEL,
    "BEARER_TOKEN_SENTINEL",
    "AUTH_HEADER_SENTINEL",
    "ENV_VALUE_SENTINEL",
    "PROVIDER_PAYLOAD_SENTINEL",
    "PROMPT_SENTINEL",
    "RAW_EXCEPTION_SENTINEL",
    "SOURCE_TEXT_SENTINEL",
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
    "env",
    "headers",
    "model",
    "openai_api_key",
    "prompt",
    "prompt_body",
    "provider_body",
    "provider_details",
    "provider_payload",
    "raw_exception",
    "raw_output",
    "raw_provider_output",
    "request_body",
    "response_body",
    "source_language",
    "source_text",
}
V1_ONLY_AUTH_HEADERS = (
    {"X-CVBrain-API-Key": V2_AUTH_SECRET},
    {"X-TrabajoAca-API-Key": V2_AUTH_SECRET},
    {"Authorization": f"Bearer {V2_AUTH_SECRET}"},
)


class FakeProvider:
    api_key = OPENAI_KEY_SENTINEL
    model = MODEL_NAME_SENTINEL
    provider_payload = "PROVIDER_PAYLOAD_SENTINEL"

    def __init__(self) -> None:
        self.direct_extract_calls = 0

    def extract(self, _request: Any) -> Any:
        self.direct_extract_calls += 1
        raise AssertionError("V2 readiness must not call provider.extract")


class RecordingProviderDependency:
    def __init__(self, provider: FakeProvider | None) -> None:
        self.provider = provider
        self.calls = 0

    def __call__(self) -> FakeProvider | None:
        self.calls += 1
        return self.provider


class RecordingPipeline:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(dict(kwargs))
        return {
            "ok": True,
            "status": "success",
            "schema_version": PUBLIC_RESPONSE_SCHEMA_VERSION,
            "display_plan": {"schema_version": "cvbrain_intake_v2_display_plan", "sections": []},
            "metadata": {"provider": {"provider_response_id": "safe_ready_response"}},
        }


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


def app_main_module() -> Any:
    import app.main

    return app.main


def registered_endpoint(app: Any, path: str, method: str) -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            endpoint = getattr(route, "endpoint", None)
            if endpoint is not None:
                return endpoint
    pytest.fail(f"{APP_MAIN_MODULE}.app must register {method} {path}")


def install_fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: FakeProvider | None,
) -> tuple[Any, RecordingProviderDependency, RecordingPipeline]:
    main = app_main_module()
    app = main.app
    app.dependency_overrides.clear()
    provider_dependency = RecordingProviderDependency(provider)
    pipeline = RecordingPipeline()
    monkeypatch.setitem(registered_endpoint(app, ANALYZE_PATH, "POST").__globals__, "run_public_intake_v2", pipeline)
    app.dependency_overrides[main.get_intake_v2_provider] = provider_dependency
    return main, provider_dependency, pipeline


def clear_overrides(app: Any) -> None:
    app.dependency_overrides.clear()


def readiness_response(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: FakeProvider | None,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[Any, RecordingProviderDependency, RecordingPipeline, list[str]]:
    main, provider_dependency, pipeline = install_fake_runtime(monkeypatch, provider=provider)
    client = TestClient(main.app)
    try:
        with provider_runtime_call_recorder() as runtime_calls:
            response = client.request(
                "GET",
                READINESS_PATH,
                content=body,
                headers=dict(headers or {}),
            )
            captured_runtime_calls = list(runtime_calls)
    finally:
        clear_overrides(main.app)
    return response, provider_dependency, pipeline, captured_runtime_calls


def analyze_response_with_missing_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, RecordingProviderDependency, RecordingPipeline, list[str]]:
    main, provider_dependency, pipeline = install_fake_runtime(monkeypatch, provider=None)
    client = TestClient(main.app)
    try:
        with provider_runtime_call_recorder() as runtime_calls:
            response = client.post(
                ANALYZE_PATH,
                json={"source_text": SOURCE_TEXT_SENTINEL, "source_language": SOURCE_LANGUAGE},
                headers=valid_v2_auth_headers(),
            )
            captured_runtime_calls = list(runtime_calls)
    finally:
        clear_overrides(main.app)
    return response, provider_dependency, pipeline, captured_runtime_calls


def valid_v2_auth_headers() -> dict[str, str]:
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
    assert value.get("status") == "error"
    assert value.get("ok") is False
    error = value.get("error")
    assert isinstance(error, Mapping)
    assert isinstance(error.get("code"), str)
    assert isinstance(error.get("category"), str)
    assert all_keys(value).isdisjoint(FORBIDDEN_RESPONSE_KEYS)
    assert_sensitive_sentinels_absent(value)
    assert_semantic_sentinels_absent(value)


def assert_safe_readiness_body(value: Any, *, expected_status: str) -> None:
    assert isinstance(value, Mapping)
    assert value.get("status") == expected_status
    assert all_keys(value).isdisjoint(FORBIDDEN_RESPONSE_KEYS)
    assert_sensitive_sentinels_absent(value)
    assert_semantic_sentinels_absent(value)


def assert_no_pipeline_provider_or_runtime(
    *,
    provider: FakeProvider | None,
    pipeline: RecordingPipeline,
    runtime_calls: list[str],
) -> None:
    assert pipeline.calls == []
    if provider is not None:
        assert provider.direct_extract_calls == 0
    assert runtime_calls == []


def test_v2_readiness_route_is_registered_without_changing_generic_health():
    main = app_main_module()
    client = TestClient(main.app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "ok": True,
        "service": "cvbrain-intake-api",
        "product": "CVBrain",
        "version": "0.1.0",
    }

    registered_endpoint(main.app, READINESS_PATH, "GET")


def test_v2_readiness_missing_server_key_returns_503_before_provider_dependency(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.delenv(V2_AUTH_ENV, raising=False)
    caplog.set_level(logging.INFO)
    provider = FakeProvider()

    response, provider_dependency, pipeline, runtime_calls = readiness_response(
        monkeypatch,
        provider=provider,
        headers=valid_v2_auth_headers(),
        body=b'{"source_text":"SOURCE_TEXT_SENTINEL"}',
    )

    assert response.status_code == 503
    assert_safe_failure_body(response.json())
    assert provider_dependency.calls == 0
    assert_no_pipeline_provider_or_runtime(provider=provider, pipeline=pipeline, runtime_calls=runtime_calls)
    assert_sensitive_sentinels_absent(caplog.text)


@pytest.mark.parametrize(
    ("headers", "description"),
    [
        ({}, "missing V2 client header"),
        ({V2_AUTH_HEADER: WRONG_CLIENT_SECRET}, "wrong V2 client header"),
        ({"X-CVBrain-API-Key": V1_KEY_SENTINEL}, "legacy CVBrain header"),
        ({"X-TrabajoAca-API-Key": V1_KEY_SENTINEL}, "legacy TrabajoAca header"),
        ({"Authorization": "Bearer BEARER_TOKEN_SENTINEL"}, "bearer header"),
    ],
)
def test_v2_readiness_rejects_missing_invalid_and_v1_auth_before_provider_dependency(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    headers: Mapping[str, str],
    description: str,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)
    provider = FakeProvider()

    response, provider_dependency, pipeline, runtime_calls = readiness_response(
        monkeypatch,
        provider=provider,
        headers=headers,
        body=f'{{"description":"{description}","source_text":"SOURCE_TEXT_SENTINEL"}}'.encode("utf-8"),
    )

    assert response.status_code == 401
    assert_safe_failure_body(response.json())
    assert provider_dependency.calls == 0
    assert_no_pipeline_provider_or_runtime(provider=provider, pipeline=pipeline, runtime_calls=runtime_calls)
    assert_sensitive_sentinels_absent(caplog.text)


def test_v2_readiness_with_available_provider_returns_safe_ready_without_pipeline_or_extract(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)
    provider = FakeProvider()

    response, provider_dependency, pipeline, runtime_calls = readiness_response(
        monkeypatch,
        provider=provider,
        headers=valid_v2_auth_headers(),
    )

    assert response.status_code == 200
    assert_safe_readiness_body(response.json(), expected_status="ready")
    assert provider_dependency.calls == 1
    assert_no_pipeline_provider_or_runtime(provider=provider, pipeline=pipeline, runtime_calls=runtime_calls)
    assert_sensitive_sentinels_absent(caplog.text)


def test_v2_readiness_with_missing_provider_returns_safe_unavailable_without_pipeline_or_extract(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, provider_dependency, pipeline, runtime_calls = readiness_response(
        monkeypatch,
        provider=None,
        headers=valid_v2_auth_headers(),
    )

    assert response.status_code == 503
    assert_safe_readiness_body(response.json(), expected_status="unavailable")
    assert provider_dependency.calls == 1
    assert_no_pipeline_provider_or_runtime(provider=None, pipeline=pipeline, runtime_calls=runtime_calls)
    assert_sensitive_sentinels_absent(caplog.text)


def test_v2_readiness_does_not_require_or_parse_request_body_source_fields(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    provider = FakeProvider()

    response, provider_dependency, pipeline, runtime_calls = readiness_response(
        monkeypatch,
        provider=provider,
        headers={**valid_v2_auth_headers(), "content-type": "application/json"},
        body=b'{"source_text":"SOURCE_TEXT_SENTINEL","source_language":"Wrong-Language-Sentinel",',
    )

    assert response.status_code == 200
    assert_safe_readiness_body(response.json(), expected_status="ready")
    assert provider_dependency.calls == 1
    assert_no_pipeline_provider_or_runtime(provider=provider, pipeline=pipeline, runtime_calls=runtime_calls)


def test_v2_analyze_missing_provider_returns_503_before_pipeline_or_provider_execution(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, provider_dependency, pipeline, runtime_calls = analyze_response_with_missing_provider(monkeypatch)

    assert response.status_code == 503
    assert_safe_readiness_body(response.json(), expected_status="unavailable")
    assert provider_dependency.calls == 1
    assert_no_pipeline_provider_or_runtime(provider=None, pipeline=pipeline, runtime_calls=runtime_calls)
    assert_sensitive_sentinels_absent(caplog.text)


def test_v2_readiness_has_no_semantic_behavior_or_source_language_contract(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    provider = FakeProvider()

    first, _, _, _ = readiness_response(monkeypatch, provider=provider, headers=valid_v2_auth_headers())
    second, _, _, _ = readiness_response(
        monkeypatch,
        provider=provider,
        headers=valid_v2_auth_headers(),
        body=(
            b'{"source_text":"SOURCE_TEXT_SENTINEL bloqueante required nice to have",'
            b'"source_language":"Inferred-Language-Should-Not-Matter"}'
        ),
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert_safe_readiness_body(first.json(), expected_status="ready")
