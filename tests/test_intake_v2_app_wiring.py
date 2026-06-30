from __future__ import annotations

import ast
import copy
import importlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Mapping

from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_MAIN_MODULE = "app.main"
APP_MAIN_PATH = ROOT / "app" / "main.py"
ENDPOINT_PATH = "/intake/v2/analyze"
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
FORBIDDEN_MAIN_V2_IMPORTS = {
    "app.intake_v2.provider_factory",
    "app.intake_v2.provider",
    "openai",
    "dotenv",
}
ALLOWED_PROVIDER_CONFIG_IMPORTS = {
    "OpenAIProviderConfigV2",
    "build_openai_provider_v2",
}
ALLOWED_LOG_KEYS = {
    "event",
    "status",
    "code",
    "category",
    "route",
    "response_status_code",
    "request_id",
}


class FakeInjectedProvider:
    def __init__(self) -> None:
        self.direct_extract_calls = 0

    def extract(self, _request: Any) -> Any:
        self.direct_extract_calls += 1
        raise AssertionError("app-level V2 wiring must not call provider.extract directly")


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


def app_main_module() -> Any:
    return importlib.import_module(APP_MAIN_MODULE)


def registered_intake_v2_endpoint(app: Any) -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == ENDPOINT_PATH and "POST" in getattr(route, "methods", set()):
            endpoint = getattr(route, "endpoint", None)
            if endpoint is not None:
                return endpoint
    pytest.fail(f"{APP_MAIN_MODULE}.app must register POST {ENDPOINT_PATH}")


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for Gate 11 app-level V2 wiring")
    return getattr(module, name)


def client_with_fake_v2_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: FakeInjectedProvider | None = None,
    pipeline: RecordingPipeline | None = None,
) -> tuple[TestClient, RecordingPipeline, FakeInjectedProvider, Any]:
    main = app_main_module()
    app = required_attr(main, "app")
    provider_dependency = required_attr(main, "get_intake_v2_provider")
    provider = provider or FakeInjectedProvider()
    pipeline = pipeline or RecordingPipeline()
    endpoint = registered_intake_v2_endpoint(app)
    if "run_public_intake_v2" not in endpoint.__globals__:
        pytest.fail("registered V2 app route must call run_public_intake_v2")
    monkeypatch.setitem(endpoint.__globals__, "run_public_intake_v2", pipeline)
    app.dependency_overrides[provider_dependency] = lambda: provider
    return TestClient(app), pipeline, provider, app


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
                "provider_response_id": "resp_app_wiring_safe",
                "provider_request_id": "req_app_wiring_safe",
                "model": "fake-app-wiring-model",
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
                "provider_response_id": "resp_app_wiring_safe",
                "provider_request_id": "req_app_wiring_safe",
                "model": "fake-app-wiring-model",
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


def imports_for_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


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
    assert value.get("ok") is True
    assert value.get("status") == "success"
    assert value.get("schema_version") == PUBLIC_RESPONSE_SCHEMA_VERSION
    assert "display_plan" in value
    assert_no_forbidden_keys(value)


def assert_public_failure(value: Mapping[str, Any]) -> None:
    assert value.get("ok") is False
    assert value.get("status") == "error"
    assert value.get("schema_version") == PUBLIC_RESPONSE_SCHEMA_VERSION
    error = value.get("error")
    assert isinstance(error, Mapping)
    assert isinstance(error.get("code"), str)
    assert isinstance(error.get("category"), str)
    assert "display_plan" not in value
    assert_sensitive_sentinels_absent(value)
    assert_no_forbidden_keys(value)


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


def clear_dependency_overrides(app: Any) -> None:
    app.dependency_overrides.clear()


def app_log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    prefix = "cvbrain_intake_v2_app "
    for record in caplog.records:
        if not record.name.startswith("cvbrain.intake_v2.app"):
            continue
        message = record.getMessage()
        assert message.startswith(prefix)
        payload = json.loads(message[len(prefix) :])
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def test_app_main_registers_intake_v2_route_without_changing_health():
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

    paths = {route.path for route in main.app.routes}
    assert ENDPOINT_PATH in paths


def test_app_level_v2_route_uses_fake_provider_override_and_returns_public_success(
    monkeypatch: pytest.MonkeyPatch,
):
    client, pipeline, provider, app = client_with_fake_v2_provider(monkeypatch)
    try:
        response = client.post(ENDPOINT_PATH, json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE})
    finally:
        clear_dependency_overrides(app)

    assert response.status_code == 200
    assert response.json() == public_success_response()
    assert_public_success(response.json())
    assert_pipeline_called_once_with_exact_inputs(pipeline, provider)


def test_app_level_v2_invalid_request_returns_safe_400_without_pipeline_or_provider_call(
    monkeypatch: pytest.MonkeyPatch,
):
    client, pipeline, provider, app = client_with_fake_v2_provider(monkeypatch)
    invalid_payloads = [
        {},
        {"source_language": SOURCE_LANGUAGE},
        {"source_text": ""},
        {"source_text": "   ", "source_language": SOURCE_LANGUAGE},
        {"source_text": SOURCE_TEXT},
        {"source_text": SOURCE_TEXT, "source_language": ""},
        {"source_text": SOURCE_TEXT, "source_language": "   "},
    ]

    try:
        for payload in invalid_payloads:
            response = client.post(ENDPOINT_PATH, json=payload)
            assert response.status_code == 400
            body = response.json()
            assert_public_failure(body)
            assert body["error"] == {"code": "invalid_request", "category": "request_validation"}
            assert_sensitive_sentinels_absent(body)
            assert_semantic_sentinels_absent(body)
    finally:
        clear_dependency_overrides(app)

    assert pipeline.calls == []
    assert provider.direct_extract_calls == 0


def test_app_level_v2_route_without_override_fails_safely_without_live_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_V2_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CVBRAIN_INTAKE_V2_OPENAI_MODEL", raising=False)
    main = app_main_module()
    clear_dependency_overrides(main.app)
    if hasattr(main, "OpenAIProviderConfigV2"):
        monkeypatch.setattr(
            main,
            "OpenAIProviderConfigV2",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("missing V2 config must not construct provider config")
            ),
        )
    if hasattr(main, "build_openai_provider_v2"):
        monkeypatch.setattr(
            main,
            "build_openai_provider_v2",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("missing V2 config must not build provider")
            ),
        )
    client = TestClient(main.app)

    response = client.post(ENDPOINT_PATH, json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE})

    assert response.status_code in {500, 503}
    body = response.json()
    assert_public_failure(body)
    assert body["error"]["category"] in {"provider", "configuration", "pipeline"}
    assert_sensitive_sentinels_absent(body)
    assert_semantic_sentinels_absent(body)


def test_app_level_v2_public_failure_envelope_is_preserved(monkeypatch: pytest.MonkeyPatch):
    expected = public_failure_response()
    pipeline = RecordingPipeline(result=expected)
    client, pipeline, provider, app = client_with_fake_v2_provider(monkeypatch, pipeline=pipeline)
    try:
        response = client.post(ENDPOINT_PATH, json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE})
    finally:
        clear_dependency_overrides(app)

    assert response.status_code == 200
    assert response.json() == expected
    assert_public_failure(response.json())
    assert_pipeline_called_once_with_exact_inputs(pipeline, provider)


def test_app_level_v2_phrase_changes_do_not_change_route_status_or_metadata_shape(
    monkeypatch: pytest.MonkeyPatch,
):
    first_pipeline = RecordingPipeline(result=public_success_response(phrase="papeles en regla"))
    first_client, first_pipeline, first_provider, first_app = client_with_fake_v2_provider(
        monkeypatch,
        pipeline=first_pipeline,
    )
    try:
        first = first_client.post(
            ENDPOINT_PATH,
            json={
                "source_text": "papeles en regla oficial de primera licencia profesional bloqueante nice to have required",
                "source_language": SOURCE_LANGUAGE,
            },
        )
    finally:
        clear_dependency_overrides(first_app)
        monkeypatch.undo()

    second_pipeline = RecordingPipeline(result=public_success_response(phrase="changed AI-owned phrase"))
    second_client, second_pipeline, second_provider, second_app = client_with_fake_v2_provider(
        monkeypatch,
        pipeline=second_pipeline,
    )
    try:
        second = second_client.post(
            ENDPOINT_PATH,
            json={"source_text": "changed AI-owned phrase with required", "source_language": SOURCE_LANGUAGE},
        )
    finally:
        clear_dependency_overrides(second_app)

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


def test_app_level_v2_response_adds_no_wordpress_ui_v1_or_legacy_shape(
    monkeypatch: pytest.MonkeyPatch,
):
    client, _pipeline, _provider, app = client_with_fake_v2_provider(monkeypatch)
    try:
        response = client.post(ENDPOINT_PATH, json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE})
    finally:
        clear_dependency_overrides(app)

    body = response.json()
    assert_no_forbidden_keys(body)
    assert "wordpress" not in body
    assert "standalone" not in body
    assert "ui_sections" not in body
    assert "v1_compatibility" not in body
    assert "flat_compatibility" not in body


def test_app_main_v2_wiring_imports_no_live_provider_config_openai_or_env_runtime():
    imports = imports_for_file(APP_MAIN_PATH)
    offenders = sorted(
        imported
        for imported in imports
        if any(imported == forbidden or imported.startswith(forbidden + ".") for forbidden in FORBIDDEN_MAIN_V2_IMPORTS)
    )
    source_text = APP_MAIN_PATH.read_text(encoding="utf-8")
    source = source_text.lower()
    tree = ast.parse(source_text)

    assert "app.intake_v2.api" in imports
    assert offenders == []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.intake_v2.provider_config":
            assert {alias.name for alias in node.names} <= ALLOWED_PROVIDER_CONFIG_IMPORTS
    assert "create_intake_v2_router" in source
    assert "get_intake_v2_provider" in source
    assert "intake_v2" in source


def test_app_level_v2_logs_are_absent_or_metadata_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    client, _pipeline, _provider, app = client_with_fake_v2_provider(monkeypatch)
    try:
        with caplog.at_level(logging.INFO, logger="cvbrain.intake_v2.app"):
            response = client.post(ENDPOINT_PATH, json={"source_text": SOURCE_TEXT, "source_language": SOURCE_LANGUAGE})
    finally:
        clear_dependency_overrides(app)

    assert response.status_code == 200
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)
    for payload in app_log_payloads(caplog):
        assert set(payload) <= ALLOWED_LOG_KEYS
