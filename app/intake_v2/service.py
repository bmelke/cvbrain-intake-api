"""Neutral service orchestration for CVBrain Intake v2."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from app.intake_v2.contract import SCHEMA_VERSION_V2
from app.intake_v2.errors import IntakeV2Error, V2InternalIntegrityError, V2ServiceRequestError
from app.intake_v2.integrity import internalize_draft_v2 as _internalize_draft_v2
from app.intake_v2.provider import ProviderRequestV2, ProviderResultV2


_MISSING = object()
SERVICE_SCHEMA_VERSION = "cvbrain_intake_v2_service"


@dataclass(frozen=True, init=False)
class IntakeServiceRequestV2:
    source_text: str
    source_language: str
    locale: str
    country_context: Optional[str]
    candidate_market: Optional[str]
    employer_market: Optional[str]
    model: str
    timeout_seconds: float

    def __init__(
        self,
        *,
        source_text: Any = _MISSING,
        source_language: Any = _MISSING,
        locale: str = "",
        country_context: Optional[str] = None,
        candidate_market: Optional[str] = None,
        employer_market: Optional[str] = None,
        model: str = "",
        timeout_seconds: float = 0.0,
    ) -> None:
        if source_text is _MISSING or not str(source_text or "").strip():
            raise V2ServiceRequestError(code="missing_source_text") from None
        if source_language is _MISSING or not str(source_language or "").strip():
            raise V2ServiceRequestError(code="missing_source_language") from None

        object.__setattr__(self, "source_text", source_text)
        object.__setattr__(self, "source_language", source_language)
        object.__setattr__(self, "locale", locale)
        object.__setattr__(self, "country_context", country_context)
        object.__setattr__(self, "candidate_market", candidate_market)
        object.__setattr__(self, "employer_market", employer_market)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)


def run_intake_v2(
    request: IntakeServiceRequestV2,
    *,
    provider: Any,
    internalize_draft_v2: Callable[[Mapping[str, Any]], Mapping[str, Any]] = _internalize_draft_v2,
) -> dict[str, Any]:
    """Run the V2 intake pipeline without interpreting domain semantics."""

    provider_request = _provider_request(request)
    try:
        provider_result = provider.extract(provider_request)
    except IntakeV2Error:
        return _failure_envelope(code="provider_failed", category="provider")
    except Exception:
        return _failure_envelope(code="provider_failed", category="provider")

    try:
        internalized = internalize_draft_v2(provider_result.validated_draft)
    except V2InternalIntegrityError as error:
        return _failure_envelope(
            code="internal_integrity_failed",
            category="internal_integrity",
            provider=provider_result,
            integrity=_safe_integrity_metadata(getattr(error, "integrity", None)),
        )
    except IntakeV2Error:
        return _failure_envelope(code="internalization_failed", category="internalization", provider=provider_result)
    except Exception:
        return _failure_envelope(code="internalization_failed", category="internalization", provider=provider_result)

    document = _mapping_value(internalized, "document")
    integrity = _mapping_value(internalized, "integrity")
    return {
        "ok": True,
        "status": "ok",
        "schema_version": SERVICE_SCHEMA_VERSION,
        "provider": _provider_metadata(provider_result),
        "document": document,
        "integrity": integrity,
    }


def _provider_request(request: IntakeServiceRequestV2) -> ProviderRequestV2:
    return ProviderRequestV2(
        source_text=request.source_text,
        source_language=request.source_language,
        locale=request.locale,
        country_context=request.country_context,
        candidate_market=request.candidate_market,
        employer_market=request.employer_market,
        model=request.model,
        timeout_seconds=request.timeout_seconds,
    )


def _failure_envelope(
    *,
    code: str,
    category: str,
    provider: Optional[ProviderResultV2] = None,
    integrity: Any = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "ok": False,
        "status": "error",
        "schema_version": SERVICE_SCHEMA_VERSION,
        "error": {
            "code": code,
            "category": category,
        },
    }
    if provider is not None:
        envelope["provider"] = _provider_metadata(provider)
    if integrity is not None:
        envelope["integrity"] = integrity
    return envelope


def _provider_metadata(result: ProviderResultV2) -> dict[str, Any]:
    return {
        "provider_response_id": result.provider_response_id,
        "provider_request_id": result.provider_request_id,
        "model": result.model,
        "attempt_kind": result.attempt_kind,
        "provider_call_count": result.provider_call_count,
        "semantic_attempt_count": result.semantic_attempt_count,
        "repair_count": result.repair_count,
        "transient_retry_count": result.transient_retry_count,
        "elapsed_seconds": result.elapsed_seconds,
        "parse_path": result.parse_path,
    }


def _mapping_value(value: Mapping[str, Any], key: str) -> Any:
    return value[key]


def _safe_integrity_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    return None


__all__ = [
    "IntakeServiceRequestV2",
    "SERVICE_SCHEMA_VERSION",
    "V2ServiceRequestError",
    "run_intake_v2",
]
