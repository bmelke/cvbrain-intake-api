"""Isolated live-smoke gate for CVBrain Intake v2."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable


ALLOW_LIVE_SMOKE_ENV = "CVBRAIN_INTAKE_V2_ALLOW_LIVE_SMOKE"
OPENAI_API_KEY_ENV = "CVBRAIN_INTAKE_V2_OPENAI_API_KEY"
OPENAI_MODEL_ENV = "CVBRAIN_INTAKE_V2_OPENAI_MODEL"
LIVE_SMOKE_SCHEMA_VERSION = "cvbrain_intake_v2_live_smoke"
SYNTHETIC_SOURCE_TEXT = "Synthetic job intake smoke text for a fictional role."
SYNTHETIC_SOURCE_LANGUAGE = "en"


def run_intake_v2_live_smoke(
    *,
    env: Mapping[str, str] | None = None,
    provider_builder: Callable[[Any], Any] | None = None,
    pipeline_runner: Callable[..., Mapping[str, Any]] | None = None,
    source_text: str = SYNTHETIC_SOURCE_TEXT,
    source_language: str = SYNTHETIC_SOURCE_LANGUAGE,
) -> Mapping[str, Any]:
    """Run a gated smoke preflight and return safe status metadata only."""

    values = dict(env or {})
    if values.get(ALLOW_LIVE_SMOKE_ENV) != "1":
        return _result(status="skipped", code="live_smoke_not_enabled", ok=False)

    api_key = str(values.get(OPENAI_API_KEY_ENV, "") or "").strip()
    model = str(values.get(OPENAI_MODEL_ENV, "") or "").strip()
    if not api_key or not model:
        return _result(status="unavailable", code="live_smoke_provider_config_missing", ok=False)

    try:
        Config, default_builder = _provider_config()
        builder = provider_builder or default_builder
        provider = builder(Config(api_key=api_key, model=model))
        runner = pipeline_runner or _pipeline_runner()
        runner(source_text=str(source_text), source_language=str(source_language), provider=provider)
    except Exception:
        return _result(status="failed", code="live_smoke_failed", ok=False)

    return _result(status="passed", code="live_smoke_passed", ok=True)


def _provider_config() -> tuple[type[Any], Callable[[Any], Any]]:
    from app.intake_v2.provider_config import OpenAIProviderConfigV2, build_openai_provider_v2

    return OpenAIProviderConfigV2, build_openai_provider_v2


def _pipeline_runner() -> Callable[..., Mapping[str, Any]]:
    from app.intake_v2.pipeline import run_public_intake_v2

    return run_public_intake_v2


def _result(*, status: str, code: str, ok: bool) -> dict[str, Any]:
    return {
        "ok": ok,
        "status": status,
        "schema_version": LIVE_SMOKE_SCHEMA_VERSION,
        "code": code,
        "category": "live_smoke",
    }


__all__ = [
    "ALLOW_LIVE_SMOKE_ENV",
    "LIVE_SMOKE_SCHEMA_VERSION",
    "OPENAI_API_KEY_ENV",
    "OPENAI_MODEL_ENV",
    "run_intake_v2_live_smoke",
]
