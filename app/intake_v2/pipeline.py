"""Non-HTTP public pipeline for CVBrain Intake v2."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.intake_v2.display_plan import build_display_plan_v2
from app.intake_v2.errors import V2PipelineError, V2PipelineRequestError
from app.intake_v2.response import build_public_response_v2
from app.intake_v2.service import IntakeServiceRequestV2, run_intake_v2


_MISSING = object()


def run_public_intake_v2(
    *,
    source_text: Any = _MISSING,
    source_language: Any = _MISSING,
    provider: Any = _MISSING,
    locale: str = "",
    country_context: str | None = None,
    candidate_market: str | None = None,
    employer_market: str | None = None,
    model: str = "",
    timeout_seconds: float = 0.0,
) -> Mapping[str, Any]:
    """Run the approved V2 boundaries and return the public response envelope."""

    _validate_request(source_text=source_text, source_language=source_language, provider=provider)

    request = IntakeServiceRequestV2(
        source_text=source_text,
        source_language=source_language,
        locale=locale,
        country_context=country_context,
        candidate_market=candidate_market,
        employer_market=employer_market,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    service_result = run_intake_v2(request, provider=provider)

    if _is_failure(service_result):
        response_failed = False
        try:
            return build_public_response_v2(service_result)
        except Exception:
            response_failed = True
        if response_failed:
            _raise_pipeline_error(code="public_response_failed")

    display_failed = False
    try:
        display_result = build_display_plan_v2(service_result)
    except Exception:
        display_failed = True
    if display_failed:
        _raise_pipeline_error(code="display_plan_failed")

    response_failed = False
    try:
        return build_public_response_v2(service_result, display_plan=display_result)
    except Exception:
        response_failed = True
    if response_failed:
        _raise_pipeline_error(code="public_response_failed")


def _validate_request(*, source_text: Any, source_language: Any, provider: Any) -> None:
    if source_text is _MISSING or not str(source_text or "").strip():
        _raise_request_error(code="missing_source_text")
    if source_language is _MISSING or not str(source_language or "").strip():
        _raise_request_error(code="missing_source_language")
    if provider is _MISSING or provider is None:
        _raise_request_error(code="missing_provider")


def _is_failure(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    return value.get("ok") is False or value.get("status") in {"error", "failed"}


def _raise_request_error(*, code: str) -> None:
    raise V2PipelineRequestError(code=code) from None


def _raise_pipeline_error(*, code: str) -> None:
    raise V2PipelineError(code=code) from None


__all__ = [
    "V2PipelineError",
    "V2PipelineRequestError",
    "run_public_intake_v2",
]
