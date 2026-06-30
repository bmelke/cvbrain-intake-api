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
ENDPOINT_PATH = "/intake/v2/analyze"
V2_AUTH_ENV = "CVBRAIN_INTAKE_V2_API_KEY"
V2_AUTH_HEADER = "X-CVBrain-V2-API-Key"
V2_AUTH_SECRET = "SERVER_SECRET_SENTINEL"
WRONG_CLIENT_SECRET = "WRONG_CLIENT_SECRET_SENTINEL"
MAX_V2_REQUEST_BODY_BYTES = 262_144
MAX_V2_SOURCE_TEXT_CHARS = 50_000
SOURCE_LANGUAGE = "Declared-Spanish"
PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"
OVERSIZED_SOURCE_MARKER = "OVERSIZED_SOURCE_TEXT_SENTINEL"
SENSITIVE_SENTINELS = (
    "SERVER_SECRET_SENTINEL",
    "WRONG_CLIENT_SECRET_SENTINEL",
    "BEARER_TOKEN_SENTINEL",
    "V1_KEY_SENTINEL",
    "OVERSIZED_SOURCE_TEXT_SENTINEL",
    "PROMPT_SENTINEL",
    "PROVIDER_PAYLOAD_SENTINEL",
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


class FakeProvider:
    def __init__(self) -> None:
        self.direct_extract_calls = 0

    def extract(self, _request: Any) -> Any:
        self.direct_extract_calls += 1
        raise AssertionError("request limits must run before provider.extract")


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


def app_main_module() -> Any:
    import app.main

    return app.main


def registered_intake_v2_endpoint(app: Any) -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == ENDPOINT_PATH and "POST" in getattr(route, "methods", set()):
            endpoint = getattr(route, "endpoint", None)
            if endpoint is not None:
                return endpoint
    pytest.fail(f"{APP_MAIN_MODULE}.app must register POST {ENDPOINT_PATH}")


def install_fake_runtime(main: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[RecordingPipeline, RecordingProviderDependency]:
    app = main.app
    app.dependency_overrides.clear()
    pipeline = RecordingPipeline()
    provider_dependency = RecordingProviderDependency()
    endpoint = registered_intake_v2_endpoint(app)
    monkeypatch.setitem(endpoint.__globals__, "run_public_intake_v2", pipeline)
    app.dependency_overrides[main.get_intake_v2_provider] = provider_dependency
    return pipeline, provider_dependency


def valid_auth_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    headers = {V2_AUTH_HEADER: V2_AUTH_SECRET}
    if extra:
        headers.update(extra)
    return headers


def json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def public_success_response() -> dict[str, Any]:
    return {
        "ok": True,
        "status": "success",
        "schema_version": PUBLIC_RESPONSE_SCHEMA_VERSION,
        "display_plan": {
            "schema_version": "cvbrain_intake_v2_display_plan",
            "sections": [],
        },
        "metadata": {
            "provider": {
                "provider_response_id": "resp_request_limits_safe",
                "provider_request_id": "req_request_limits_safe",
                "model": "fake-request-limits-model",
            },
        },
    }


def valid_payload(*, source_text: str = "short mechanical request") -> dict[str, str]:
    return {"source_text": source_text, "source_language": SOURCE_LANGUAGE}


def oversized_body_payload() -> dict[str, str]:
    payload = valid_payload(source_text="small source")
    overhead = len(json_bytes({**payload, "padding": ""}))
    payload["padding"] = "P" * (MAX_V2_REQUEST_BODY_BYTES - overhead + 1)
    assert len(json_bytes(payload)) > MAX_V2_REQUEST_BODY_BYTES
    return payload


def oversized_source_text() -> str:
    return (OVERSIZED_SOURCE_MARKER + " ") + ("x" * (MAX_V2_SOURCE_TEXT_CHARS + 1))


def exact_limit_source_text() -> str:
    return "x" * MAX_V2_SOURCE_TEXT_CHARS


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


def assert_safe_public_failure(value: Any) -> None:
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


def assert_no_provider_pipeline_or_runtime(
    *,
    pipeline: RecordingPipeline,
    provider_dependency: RecordingProviderDependency,
    provider_runtime_calls: list[str],
) -> None:
    assert pipeline.calls == []
    assert provider_dependency.calls == 0
    assert provider_dependency.provider.direct_extract_calls == 0
    assert provider_runtime_calls == []


def post_json_bytes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    body: bytes,
    headers: Mapping[str, str] | None = None,
) -> tuple[Any, RecordingPipeline, RecordingProviderDependency, list[str]]:
    main = app_main_module()
    pipeline, provider_dependency = install_fake_runtime(main, monkeypatch)
    client = TestClient(main.app)

    try:
        with provider_runtime_call_recorder() as provider_runtime_calls:
            response = client.post(
                ENDPOINT_PATH,
                content=body,
                headers={"content-type": "application/json", **dict(headers or {})},
            )
            captured_provider_runtime_calls = list(provider_runtime_calls)
    finally:
        main.app.dependency_overrides.clear()

    return response, pipeline, provider_dependency, captured_provider_runtime_calls


def post_json_payload(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: Mapping[str, Any],
    headers: Mapping[str, str] | None = None,
) -> tuple[Any, RecordingPipeline, RecordingProviderDependency, list[str]]:
    return post_json_bytes(monkeypatch, body=json_bytes(payload), headers=headers)


def test_missing_client_auth_wins_before_oversized_body_or_provider_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_json_payload(
        monkeypatch,
        payload=oversized_body_payload(),
    )

    assert response.status_code == 401
    assert_safe_public_failure(response.json())
    assert_no_provider_pipeline_or_runtime(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)


def test_missing_server_auth_wins_before_malformed_json_body_parsing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.delenv(V2_AUTH_ENV, raising=False)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_json_bytes(
        monkeypatch,
        body=b'{"source_text": "OVERSIZED_SOURCE_TEXT_SENTINEL", ',
        headers=valid_auth_headers(),
    )

    assert response.status_code == 503
    assert_safe_public_failure(response.json())
    assert_no_provider_pipeline_or_runtime(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)


def test_missing_client_auth_wins_before_malformed_json_body_parsing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_json_bytes(
        monkeypatch,
        body=b'{"source_text": "OVERSIZED_SOURCE_TEXT_SENTINEL", ',
    )

    assert response.status_code == 401
    assert_safe_public_failure(response.json())
    assert_no_provider_pipeline_or_runtime(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)


def test_invalid_client_auth_wins_before_oversized_source_text_inspection(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_json_payload(
        monkeypatch,
        payload=valid_payload(source_text=oversized_source_text()),
        headers={V2_AUTH_HEADER: WRONG_CLIENT_SECRET},
    )

    assert response.status_code == 401
    assert_safe_public_failure(response.json())
    assert_no_provider_pipeline_or_runtime(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)


def test_authenticated_request_body_above_byte_cap_rejected_before_provider_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_json_payload(
        monkeypatch,
        payload=oversized_body_payload(),
        headers=valid_auth_headers(),
    )

    assert response.status_code == 413
    assert_safe_public_failure(response.json())
    assert_no_provider_pipeline_or_runtime(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)


def test_authenticated_oversized_source_text_rejected_before_provider_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_json_payload(
        monkeypatch,
        payload=valid_payload(source_text=oversized_source_text()),
        headers=valid_auth_headers(),
    )

    assert response.status_code == 413
    assert_safe_public_failure(response.json())
    assert_no_provider_pipeline_or_runtime(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)


def test_source_text_at_exact_character_cap_reaches_existing_route_behavior(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)

    response, pipeline, provider_dependency, provider_runtime_calls = post_json_payload(
        monkeypatch,
        payload=valid_payload(source_text=exact_limit_source_text()),
        headers=valid_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == public_success_response()
    assert len(pipeline.calls) == 1
    assert pipeline.calls[0]["source_text"] == exact_limit_source_text()
    assert pipeline.calls[0]["source_language"] == SOURCE_LANGUAGE
    assert pipeline.calls[0]["provider"] is provider_dependency.provider
    assert provider_dependency.calls == 1
    assert provider_dependency.provider.direct_extract_calls == 0
    assert provider_runtime_calls == []


def test_normal_small_valid_request_preserves_existing_success_behavior(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)

    response, pipeline, provider_dependency, provider_runtime_calls = post_json_payload(
        monkeypatch,
        payload=valid_payload(),
        headers=valid_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == public_success_response()
    assert len(pipeline.calls) == 1
    assert pipeline.calls[0]["source_text"] == "short mechanical request"
    assert pipeline.calls[0]["source_language"] == SOURCE_LANGUAGE
    assert pipeline.calls[0]["provider"] is provider_dependency.provider
    assert provider_dependency.calls == 1
    assert provider_dependency.provider.direct_extract_calls == 0
    assert provider_runtime_calls == []


def test_source_text_one_character_over_cap_rejected_before_provider_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv(V2_AUTH_ENV, V2_AUTH_SECRET)
    caplog.set_level(logging.INFO)

    response, pipeline, provider_dependency, provider_runtime_calls = post_json_payload(
        monkeypatch,
        payload=valid_payload(source_text="x" * (MAX_V2_SOURCE_TEXT_CHARS + 1)),
        headers=valid_auth_headers(),
    )

    assert response.status_code == 413
    assert_safe_public_failure(response.json())
    assert_no_provider_pipeline_or_runtime(
        pipeline=pipeline,
        provider_dependency=provider_dependency,
        provider_runtime_calls=provider_runtime_calls,
    )
    assert_sensitive_sentinels_absent(caplog.text)
