from __future__ import annotations

import ast
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.intake_v2.errors import IntakeV2Error, V2ConfigurationError, V2PipelineRequestError
from app.intake_v2.provider import OpenAIProviderV2


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_CONFIG_MODULE = "app.intake_v2.provider_config"
PROVIDER_CONFIG_PATH = ROOT / "app" / "intake_v2" / "provider_config.py"
MODEL = "gpt-test-v2-provider-config"
API_KEY = "SECRET_TOKEN_SENTINEL_API_KEY_SENTINEL_BEARER_SENTINEL"
SECRET_SENTINELS = ("SECRET_TOKEN_SENTINEL", "API_KEY_SENTINEL", "BEARER_SENTINEL")
FORBIDDEN_CONFIG_IMPORTS = {
    "app.extractors",
    "app.main",
    "app.mappers",
    "app.normalization",
    "app.routers",
    "app.routes",
    "app.intake_v2.display_plan",
    "app.intake_v2.endpoint",
    "app.intake_v2.factory",
    "app.intake_v2.integrity",
    "app.intake_v2.pipeline",
    "app.intake_v2.prompts",
    "app.intake_v2.provider_factory",
    "app.intake_v2.response",
    "app.intake_v2.service",
    "dotenv",
    "fastapi",
    "openai",
    "os",
    "secrets",
    "starlette",
}
FORBIDDEN_SIGNATURE_NAMES = {
    "endpoint",
    "headers",
    "http_request",
    "request",
    "route",
    "router",
    "source_language",
    "source_text",
}
FORBIDDEN_PACKAGE_EXPORTS = {
    "OpenAIProviderConfigV2",
    "build_openai_provider_v2",
    "provider_config",
    "provider_factory",
}
ALLOWED_LOG_KEYS = {
    "event",
    "status",
    "code",
    "category",
    "model",
    "has_client",
    "max_output_tokens",
    "transient_retries",
}


class FakeClient:
    @property
    def responses(self) -> Any:
        raise AssertionError("provider construction must not access provider responses")

    def with_options(self, **_kwargs: Any) -> "FakeClient":
        raise AssertionError("provider construction must not configure or call the client")


def provider_config_module() -> Any:
    try:
        return importlib.import_module(PROVIDER_CONFIG_MODULE)
    except ModuleNotFoundError as error:
        if error.name == PROVIDER_CONFIG_MODULE:
            pytest.fail(
                f"Gate 9 provider config module is not implemented: expected import {PROVIDER_CONFIG_MODULE}"
            )
        raise


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for the Gate 9 provider construction boundary")
    return getattr(module, name)


def config_type() -> type[Any]:
    Config = required_attr(provider_config_module(), "OpenAIProviderConfigV2")
    assert inspect.isclass(Config)
    return Config


def build_provider_func() -> Any:
    builder = required_attr(provider_config_module(), "build_openai_provider_v2")
    assert callable(builder)
    return builder


def build_config(**values: Any) -> Any:
    Config = config_type()
    return Config(**values)


def build_provider_from_values(**values: Any) -> Any:
    return build_provider_func()(build_config(**values), client=FakeClient())


def rendered(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def assert_secret_sentinels_absent(value: Any) -> None:
    text = rendered(value)
    for sentinel in SECRET_SENTINELS:
        assert sentinel not in text


def assert_safe_configuration_error(error: BaseException) -> None:
    assert isinstance(error, V2ConfigurationError)
    assert isinstance(error, IntakeV2Error)
    assert error.__cause__ is None
    if error.__context__ is not None:
        assert error.__suppress_context__ is True
    for value in vars(error).values():
        assert not isinstance(value, BaseException)
    assert_secret_sentinels_absent(str(error))
    assert_secret_sentinels_absent(repr(error))
    assert_secret_sentinels_absent(getattr(error, "args", ()))
    assert_secret_sentinels_absent(vars(error))


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
    return any(module == forbidden or module.startswith(forbidden + ".") for forbidden in FORBIDDEN_CONFIG_IMPORTS)


def provider_config_log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    prefix = "cvbrain_intake_v2_provider_config "
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith(prefix):
            continue
        payload = json.loads(message[len(prefix) :])
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def test_provider_config_module_import_is_side_effect_safe():
    provider_runtime_calls: list[str] = []

    def profile(frame: Any, event: str, _arg: Any) -> None:
        if event != "call":
            return
        filename = Path(frame.f_code.co_filename)
        if filename.name != "provider.py":
            return
        if frame.f_code.co_name in {"__init__", "_client"}:
            provider_runtime_calls.append(frame.f_code.co_name)

    before_modules = dict(sys.modules)
    sys.modules.pop(PROVIDER_CONFIG_MODULE, None)
    sys.setprofile(profile)
    try:
        module = provider_config_module()
        loaded_or_replaced = {name for name, module_value in sys.modules.items() if before_modules.get(name) is not module_value}
        forbidden_loaded = sorted(name for name in loaded_or_replaced if is_forbidden_import(name))
    finally:
        sys.setprofile(None)

    assert module.__name__ == PROVIDER_CONFIG_MODULE
    assert provider_runtime_calls == []
    assert forbidden_loaded == []


def test_provider_config_module_imports_no_endpoint_env_openai_ui_or_v1_runtime():
    if not PROVIDER_CONFIG_PATH.exists():
        pytest.fail("Gate 9 provider config module is not implemented: expected app/intake_v2/provider_config.py")

    imports = imports_for_file(PROVIDER_CONFIG_PATH)
    offenders = sorted(imported for imported in imports if is_forbidden_import(imported))
    source = PROVIDER_CONFIG_PATH.read_text(encoding="utf-8").lower()
    source_offenders = sorted(
        token
        for token in ("dotenv", "environ", "getenv", "api_key_sentinel", "secret_token_sentinel", "bearer_sentinel")
        if token in source
    )

    assert offenders == []
    assert source_offenders == []


def test_explicit_config_requires_api_key_and_model_without_env_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", API_KEY)
    Config = config_type()

    with pytest.raises((TypeError, V2ConfigurationError)):
        Config(model=MODEL)
    with pytest.raises((TypeError, V2ConfigurationError)):
        Config(api_key=API_KEY)

    for values in (
        {"api_key": API_KEY, "model": MODEL, "source_language": "Spanish"},
        {"api_key": API_KEY, "model": MODEL, "source_text": "Empresa busca mecanico"},
        {"api_key": API_KEY, "model": MODEL, "request": object()},
    ):
        with pytest.raises(TypeError):
            Config(**values)


def test_provider_construction_interface_has_no_source_or_endpoint_parameters():
    Config = config_type()
    builder = build_provider_func()

    for callable_obj in (Config, builder):
        parameter_names = set(inspect.signature(callable_obj).parameters)
        assert parameter_names.isdisjoint(FORBIDDEN_SIGNATURE_NAMES)


def test_explicit_config_with_injected_client_constructs_inert_openai_provider():
    client = FakeClient()
    config = build_config(api_key=API_KEY, model=MODEL, max_output_tokens=1234, transient_retries=0)
    provider = build_provider_func()(config, client=client)

    assert isinstance(provider, OpenAIProviderV2)
    assert provider.model == MODEL
    assert provider.client is client
    assert provider.max_output_tokens == 1234
    assert provider.transient_retries == 0
    assert provider.provider_call_count == 0
    assert provider.semantic_attempt_count == 0
    assert provider.repair_count == 0
    assert provider.transient_retry_count == 0


def test_blank_config_values_fail_safely_without_secret_leakage(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO", logger="cvbrain.intake_v2.provider_config")

    for values in (
        {"api_key": "", "model": MODEL},
        {"api_key": "   ", "model": MODEL},
        {"api_key": API_KEY, "model": ""},
        {"api_key": API_KEY, "model": "   "},
    ):
        with pytest.raises(V2ConfigurationError) as exc_info:
            build_provider_from_values(**values)
        assert_safe_configuration_error(exc_info.value)

    assert_secret_sentinels_absent(caplog.text)


def test_secret_values_do_not_leak_from_config_provider_repr_or_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO", logger="cvbrain.intake_v2.provider_config")
    config = build_config(api_key=API_KEY, model=MODEL)
    provider = build_provider_func()(config, client=FakeClient())

    assert_secret_sentinels_absent(repr(config))
    assert_secret_sentinels_absent(str(config))
    assert_secret_sentinels_absent(repr(provider))
    assert_secret_sentinels_absent(str(provider))
    assert_secret_sentinels_absent(caplog.text)


def test_provider_construction_logs_are_absent_or_metadata_allowlisted(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO", logger="cvbrain.intake_v2.provider_config")

    build_provider_from_values(api_key=API_KEY, model=MODEL)

    assert_secret_sentinels_absent(caplog.text)
    for payload in provider_config_log_payloads(caplog):
        assert set(payload) <= ALLOWED_LOG_KEYS


def test_package_root_does_not_export_provider_config_boundary_yet():
    import app.intake_v2 as package

    for name in FORBIDDEN_PACKAGE_EXPORTS:
        assert name not in package.__all__

    assert not hasattr(package, "OpenAIProviderConfigV2")
    assert not hasattr(package, "build_openai_provider_v2")

    package_init = ROOT / "app" / "intake_v2" / "__init__.py"
    imports = imports_for_file(package_init)
    assert "app.intake_v2.provider_config" not in imports
    assert "app.intake_v2.provider_factory" not in imports


def test_public_pipeline_remains_provider_injection_only():
    import app.intake_v2 as package

    pipeline_path = ROOT / "app" / "intake_v2" / "pipeline.py"
    imports = imports_for_file(pipeline_path)
    forbidden_pipeline_imports = {
        "app.intake_v2.provider_config",
        "app.intake_v2.provider_factory",
        "app.intake_v2.factory",
    }

    assert imports.isdisjoint(forbidden_pipeline_imports)
    with pytest.raises(V2PipelineRequestError):
        package.run_public_intake_v2(source_text="Empresa busca mecanico", source_language="Spanish")
