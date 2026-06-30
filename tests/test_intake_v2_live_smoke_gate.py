from __future__ import annotations

import ast
import importlib
import importlib.util
import io
import json
import os
import re
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

import pytest


ROOT = Path(__file__).resolve().parents[1]
LIVE_SMOKE_MODULE = "app.intake_v2.live_smoke"
LIVE_SMOKE_PATH = ROOT / "app" / "intake_v2" / "live_smoke.py"
LIVE_SMOKE_SCRIPT_PATH = ROOT / "scripts" / "run_intake_v2_live_smoke.py"
ALLOW_FLAG = "CVBRAIN_INTAKE_V2_ALLOW_LIVE_SMOKE"
OPENAI_API_KEY_ENV = "CVBRAIN_INTAKE_V2_OPENAI_API_KEY"
OPENAI_MODEL_ENV = "CVBRAIN_INTAKE_V2_OPENAI_MODEL"
API_KEY_SENTINEL = "SECRET_TOKEN_SENTINEL_OPENAI_API_KEY_SENTINEL"
MODEL_SENTINEL = "MODEL_NAME_SENTINEL"
SOURCE_TEXT_SENTINEL = "SOURCE_TEXT_SENTINEL papeles en regla bloqueante required"
PROMPT_SENTINEL = "PROMPT_BODY_SENTINEL"
PROVIDER_PAYLOAD_SENTINEL = "PROVIDER_PAYLOAD_SENTINEL"
RAW_OUTPUT_SENTINEL = "RAW_OUTPUT_SENTINEL"
RAW_EXCEPTION_SENTINEL = "RAW_EXCEPTION_SENTINEL"
AUTH_HEADER_SENTINEL = "AUTH_HEADER_SENTINEL"
V2_API_KEY_SENTINEL = "V2_API_KEY_SENTINEL"
SENSITIVE_SENTINELS = (
    API_KEY_SENTINEL,
    MODEL_SENTINEL,
    SOURCE_TEXT_SENTINEL,
    "SOURCE_TEXT_SENTINEL",
    PROMPT_SENTINEL,
    PROVIDER_PAYLOAD_SENTINEL,
    RAW_OUTPUT_SENTINEL,
    RAW_EXCEPTION_SENTINEL,
    AUTH_HEADER_SENTINEL,
    V2_API_KEY_SENTINEL,
    "Bearer",
    "Authorization",
)
ALLOWED_STATUSES = {"skipped", "unavailable", "ready_to_run", "passed", "failed"}
DISABLED_FLAG_VALUES = (None, "", " ", "0", "false", "False", "no", "random", "true", "yes")
ENDPOINT_COUPLING_TERMS = (
    "/health",
    "/intake/v2/status",
    "/intake/v2/analyze",
    "create_intake_v2_router",
    "TestClient",
    "FastAPI",
    "app.main",
    "app.intake_v2.api",
)
FORBIDDEN_RUNTIME_IMPORTS = {
    "openai",
    "requests",
    "httpx",
    "fastapi",
    "starlette",
    "app.main",
    "app.intake_v2.api",
}


class HostileSmokeError(Exception):
    message = (
        f"{SOURCE_TEXT_SENTINEL} {PROMPT_SENTINEL} {PROVIDER_PAYLOAD_SENTINEL} "
        f"{RAW_OUTPUT_SENTINEL} {RAW_EXCEPTION_SENTINEL} {API_KEY_SENTINEL}"
    )
    body = f"provider_body={PROVIDER_PAYLOAD_SENTINEL} raw={RAW_OUTPUT_SENTINEL}"
    headers = {"authorization": f"Bearer {API_KEY_SENTINEL}", "x-auth": AUTH_HEADER_SENTINEL}

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"HostileSmokeError({RAW_EXCEPTION_SENTINEL} {API_KEY_SENTINEL})"


class FakeProvider:
    def __init__(self) -> None:
        self.extract_calls = 0

    def extract(self, _request: Any) -> Any:
        self.extract_calls += 1
        raise AssertionError("Gate 16 smoke tests must not call provider.extract directly")


@contextmanager
def fresh_live_smoke_import() -> Iterator[Any]:
    original = sys.modules.get(LIVE_SMOKE_MODULE)
    had_original = LIVE_SMOKE_MODULE in sys.modules
    package = sys.modules.get("app.intake_v2")
    had_package_attr = package is not None and hasattr(package, "live_smoke")
    original_package_attr = getattr(package, "live_smoke", None) if package is not None else None

    sys.modules.pop(LIVE_SMOKE_MODULE, None)
    if package is not None and hasattr(package, "live_smoke"):
        delattr(package, "live_smoke")

    try:
        yield live_smoke_module()
    finally:
        sys.modules.pop(LIVE_SMOKE_MODULE, None)
        if had_original:
            sys.modules[LIVE_SMOKE_MODULE] = original

        current_package = sys.modules.get("app.intake_v2")
        if current_package is not None:
            if had_package_attr:
                setattr(current_package, "live_smoke", original_package_attr)
            elif hasattr(current_package, "live_smoke"):
                delattr(current_package, "live_smoke")


def live_smoke_module() -> Any:
    try:
        return importlib.import_module(LIVE_SMOKE_MODULE)
    except ModuleNotFoundError as error:
        if error.name == LIVE_SMOKE_MODULE:
            pytest.fail(f"Gate 16 live-smoke module is not implemented: expected import {LIVE_SMOKE_MODULE}")
        raise


def run_live_smoke(
    *,
    env: Mapping[str, str],
    provider_builder: Any,
    pipeline_runner: Any,
) -> Mapping[str, Any]:
    module = live_smoke_module()
    runner = required_attr(module, "run_intake_v2_live_smoke")
    result = runner(env=env, provider_builder=provider_builder, pipeline_runner=pipeline_runner)
    assert isinstance(result, Mapping)
    assert result.get("status") in ALLOWED_STATUSES
    assert_json_safe_without_sentinels(result)
    return result


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for the Gate 16 live-smoke contract")
    return getattr(module, name)


def assert_json_safe_without_sentinels(value: Any) -> None:
    try:
        rendered = json.dumps(value, sort_keys=True)
    except TypeError as error:
        pytest.fail(f"live-smoke results must be JSON-compatible safe metadata only: {error}")
    for sentinel in SENSITIVE_SENTINELS:
        assert sentinel not in rendered
    assert_forbidden_keys_absent(value)


def assert_forbidden_keys_absent(value: Any) -> None:
    forbidden_keys = {
        "api_key",
        "authorization",
        "auth_headers",
        "bearer",
        "body",
        "env",
        "exception",
        "headers",
        "model",
        "openai_api_key",
        "prompt",
        "prompt_body",
        "provider_body",
        "provider_payload",
        "raw_exception",
        "raw_output",
        "raw_provider_output",
        "source_text",
    }
    if isinstance(value, Mapping):
        assert not (set(value) & forbidden_keys)
        for child in value.values():
            assert_forbidden_keys_absent(child)
    elif isinstance(value, list):
        for child in value:
            assert_forbidden_keys_absent(child)


def forbidden_provider_builder(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("disabled or unavailable live smoke must not construct a provider")


def forbidden_pipeline_runner(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("disabled or unavailable live smoke must not call the public pipeline")


def enabled_env() -> dict[str, str]:
    return {
        ALLOW_FLAG: "1",
        OPENAI_API_KEY_ENV: API_KEY_SENTINEL,
        OPENAI_MODEL_ENV: MODEL_SENTINEL,
    }


def import_script_with_fake_smoke(monkeypatch: pytest.MonkeyPatch, smoke_runner: Any) -> Any:
    if not LIVE_SMOKE_SCRIPT_PATH.exists():
        pytest.fail(f"Gate 16 live-smoke script is not implemented: expected {LIVE_SMOKE_SCRIPT_PATH}")

    fake_live_smoke = types.ModuleType(LIVE_SMOKE_MODULE)
    fake_live_smoke.run_intake_v2_live_smoke = smoke_runner
    monkeypatch.setitem(sys.modules, LIVE_SMOKE_MODULE, fake_live_smoke)

    module_name = "gate16_live_smoke_script_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, LIVE_SMOKE_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def test_live_smoke_module_import_is_side_effect_safe(monkeypatch: pytest.MonkeyPatch):
    importlib.import_module("app.intake_v2")

    def forbidden_getenv(_name: str, _default: Any = None) -> str:
        raise AssertionError("live-smoke module import must not read environment variables")

    monkeypatch.setattr(os, "getenv", forbidden_getenv)
    monkeypatch.setitem(sys.modules, "openai", None)

    with fresh_live_smoke_import() as module:
        assert required_attr(module, "run_intake_v2_live_smoke")


def test_live_smoke_module_source_has_no_endpoint_or_network_coupling():
    if not LIVE_SMOKE_PATH.exists():
        pytest.fail(f"Gate 16 live-smoke module is not implemented: expected {LIVE_SMOKE_PATH}")

    source = LIVE_SMOKE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported = [alias.name for alias in node.names]
            module = node.module or ""
            names = set(imported + [module])
            assert not (names & FORBIDDEN_RUNTIME_IMPORTS)

    for term in ENDPOINT_COUPLING_TERMS:
        assert term not in source

    for node in tree.body:
        segment = ast.get_source_segment(source, node) or ""
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)):
            assert "os.getenv" not in segment
            assert "os.environ" not in segment
            assert "OpenAI(" not in segment
            assert "responses.create" not in segment
            assert "run_intake_v2_live_smoke(" not in segment


@pytest.mark.parametrize("flag_value", DISABLED_FLAG_VALUES)
def test_live_smoke_is_disabled_without_exact_gate(flag_value: str | None):
    env = {
        OPENAI_API_KEY_ENV: API_KEY_SENTINEL,
        OPENAI_MODEL_ENV: MODEL_SENTINEL,
    }
    if flag_value is not None:
        env[ALLOW_FLAG] = flag_value

    result = run_live_smoke(
        env=env,
        provider_builder=forbidden_provider_builder,
        pipeline_runner=forbidden_pipeline_runner,
    )

    assert result["status"] in {"skipped", "unavailable"}


@pytest.mark.parametrize(
    "env",
    (
        {ALLOW_FLAG: "1"},
        {ALLOW_FLAG: "1", OPENAI_API_KEY_ENV: "", OPENAI_MODEL_ENV: MODEL_SENTINEL},
        {ALLOW_FLAG: "1", OPENAI_API_KEY_ENV: " ", OPENAI_MODEL_ENV: MODEL_SENTINEL},
        {ALLOW_FLAG: "1", OPENAI_API_KEY_ENV: API_KEY_SENTINEL, OPENAI_MODEL_ENV: ""},
        {ALLOW_FLAG: "1", OPENAI_API_KEY_ENV: API_KEY_SENTINEL, OPENAI_MODEL_ENV: " "},
    ),
)
def test_live_smoke_enabled_with_missing_config_skips_safely_without_provider_construction(env: Mapping[str, str]):
    result = run_live_smoke(
        env=env,
        provider_builder=forbidden_provider_builder,
        pipeline_runner=forbidden_pipeline_runner,
    )

    assert result["status"] in {"skipped", "unavailable", "failed"}


def test_live_smoke_enabled_path_uses_injected_builder_and_pipeline_with_synthetic_non_pii_source():
    builder_calls: list[Any] = []
    pipeline_calls: list[dict[str, Any]] = []

    def provider_builder(config: Any) -> FakeProvider:
        builder_calls.append(config)
        return FakeProvider()

    def pipeline_runner(**kwargs: Any) -> Mapping[str, Any]:
        pipeline_calls.append(dict(kwargs))
        return {"ok": True, "status": "success", "schema_version": "safe_fake_public_response"}

    result = run_live_smoke(
        env=enabled_env(),
        provider_builder=provider_builder,
        pipeline_runner=pipeline_runner,
    )

    assert result["status"] in {"ready_to_run", "passed"}
    assert len(builder_calls) == 1
    assert builder_calls[0].__class__.__name__ == "OpenAIProviderConfigV2"
    assert getattr(builder_calls[0], "api_key", None) == API_KEY_SENTINEL
    assert getattr(builder_calls[0], "model", None) == MODEL_SENTINEL
    assert len(pipeline_calls) == 1

    pipeline_call = pipeline_calls[0]
    assert pipeline_call.get("provider").__class__.__name__ == "FakeProvider"
    assert isinstance(pipeline_call.get("source_text"), str)
    assert 1 <= len(pipeline_call["source_text"]) <= 500
    assert isinstance(pipeline_call.get("source_language"), str)
    assert pipeline_call["source_language"].strip()
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", pipeline_call["source_text"])
    assert not re.search(r"\+?\d[\d\s().-]{7,}", pipeline_call["source_text"])
    for forbidden in ("wordpress", "staging", "candidate", "resume", "cv data", "recruiter data"):
        assert forbidden not in pipeline_call["source_text"].lower()


def test_live_smoke_failures_return_safe_metadata_without_original_exception():
    def hostile_builder(_config: Any) -> Any:
        raise HostileSmokeError()

    result = run_live_smoke(
        env=enabled_env(),
        provider_builder=hostile_builder,
        pipeline_runner=forbidden_pipeline_runner,
    )

    assert result["status"] == "failed"
    assert "original_exception" not in result
    assert "exception" not in result


def test_live_smoke_script_import_does_not_run_smoke_and_exposes_main(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def forbidden_smoke_runner(**_kwargs: Any) -> Mapping[str, Any]:
        calls.append("smoke")
        raise AssertionError("script import must not run live smoke")

    module = import_script_with_fake_smoke(monkeypatch, forbidden_smoke_runner)

    assert calls == []
    assert callable(required_attr(module, "main"))


def test_live_smoke_script_main_blocks_safely_without_gate(monkeypatch: pytest.MonkeyPatch):
    calls: list[Mapping[str, str]] = []

    def fake_smoke_runner(*, env: Mapping[str, str], **_kwargs: Any) -> Mapping[str, Any]:
        calls.append(dict(env))
        return {"ok": False, "status": "skipped", "code": "live_smoke_not_enabled"}

    module = import_script_with_fake_smoke(monkeypatch, fake_smoke_runner)
    stdout = io.StringIO()

    exit_code = module.main(env={}, stdout=stdout)

    assert exit_code != 0
    assert calls == [{}]
    assert_json_safe_without_sentinels({"stdout": stdout.getvalue()})
