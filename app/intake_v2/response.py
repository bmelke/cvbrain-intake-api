"""Public response envelope for CVBrain Intake v2."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Dict

from app.intake_v2.errors import V2PublicResponseError


PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"

PROVIDER_METADATA_KEYS = (
    "provider_response_id",
    "provider_request_id",
    "model",
    "attempt_kind",
    "provider_call_count",
    "semantic_attempt_count",
    "repair_count",
    "transient_retry_count",
    "elapsed_seconds",
    "parse_path",
)
INTEGRITY_METADATA_KEYS = ("ok", "paths", "counts", "codes", "categories")
FORBIDDEN_PUBLIC_KEYS = {
    "api_key",
    "auth_headers",
    "authorization",
    "bearer_token",
    "body",
    "cookie",
    "cookies",
    "debug",
    "document",
    "endpoint",
    "errors",
    "exception",
    "fastapi_response",
    "flat_compatibility",
    "headers",
    "http_status",
    "local_ref",
    "prompt",
    "prompt_body",
    "provider_body",
    "provider_payload",
    "raw_exception",
    "raw_output",
    "raw_output_text",
    "raw_provider_output",
    "request_body",
    "response_body",
    "route",
    "source_text",
    "standalone",
    "starlette_response",
    "ui_sections",
    "v1_compatibility",
    "wordpress",
}
_OMITTED = object()


def build_public_response_v2(service_result: Mapping[str, Any], *, display_plan: Any = _OMITTED) -> Dict[str, Any]:
    """Wrap safe V2 service/display artifacts in a stable public contract."""

    if not isinstance(service_result, Mapping):
        _raise_response_error(code="invalid_service_result", paths=["service_result"])

    if _is_failure(service_result):
        return _failure_response(service_result)
    if not _is_success(service_result):
        _raise_response_error(code="invalid_service_status", paths=["service_result.status"])

    plan = _display_plan_from(display_plan)
    response: Dict[str, Any] = {
        "ok": True,
        "status": "success",
        "schema_version": PUBLIC_RESPONSE_SCHEMA_VERSION,
        "display_plan": copy.deepcopy(plan),
        "metadata": _metadata(service_result, plan),
    }
    _reject_forbidden_keys(response, path="response")
    return response


def _failure_response(service_result: Mapping[str, Any]) -> Dict[str, Any]:
    error = service_result.get("error")
    if not isinstance(error, Mapping):
        _raise_response_error(code="missing_service_error", paths=["service_result.error"], counts=_counts_from(service_result))

    code = error.get("code")
    category = error.get("category")
    if not isinstance(code, str) or not code:
        _raise_response_error(code="missing_error_code", paths=["service_result.error.code"], counts=_counts_from(service_result))
    if not isinstance(category, str) or not category:
        _raise_response_error(
            code="missing_error_category",
            paths=["service_result.error.category"],
            counts=_counts_from(service_result),
        )

    response: Dict[str, Any] = {
        "ok": False,
        "status": "error",
        "schema_version": PUBLIC_RESPONSE_SCHEMA_VERSION,
        "error": {
            "code": code,
            "category": category,
        },
    }
    metadata = _metadata(service_result, None)
    if metadata:
        response["metadata"] = metadata
    _reject_forbidden_keys(response, path="response")
    return response


def _display_plan_from(value: Any) -> Mapping[str, Any]:
    if value is _OMITTED:
        _raise_response_error(code="missing_display_plan", paths=["display_plan"])
    if not isinstance(value, Mapping):
        _raise_response_error(code="invalid_display_plan", paths=["display_plan"])
    plan = value.get("display_plan")
    if not isinstance(plan, Mapping):
        _raise_response_error(code="invalid_display_plan", paths=["display_plan"])
    sections = plan.get("sections")
    if not isinstance(sections, list):
        _raise_response_error(code="invalid_display_plan", paths=["display_plan.sections"])
    _reject_forbidden_keys(plan, path="display_plan")
    return plan


def _metadata(service_result: Mapping[str, Any], display_plan: Mapping[str, Any] | None) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}

    service_schema_version = service_result.get("schema_version")
    if isinstance(service_schema_version, str) and service_schema_version:
        metadata["service_schema_version"] = service_schema_version

    if display_plan is not None:
        display_schema_version = display_plan.get("schema_version")
        if isinstance(display_schema_version, str) and display_schema_version:
            metadata["display_plan_schema_version"] = display_schema_version

    provider = _provider_metadata(service_result.get("provider"))
    if provider:
        metadata["provider"] = provider

    integrity = _integrity_metadata(service_result.get("integrity"))
    if integrity:
        metadata["integrity"] = integrity
        counts = integrity.get("counts")
        if isinstance(counts, Mapping):
            metadata["counts"] = copy.deepcopy(dict(counts))

    request_id = service_result.get("request_id")
    if isinstance(request_id, str) and request_id:
        metadata["request_id"] = request_id

    return metadata


def _provider_metadata(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: copy.deepcopy(value[key]) for key in PROVIDER_METADATA_KEYS if key in value}


def _integrity_metadata(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: copy.deepcopy(value[key]) for key in INTEGRITY_METADATA_KEYS if key in value}


def _is_success(service_result: Mapping[str, Any]) -> bool:
    return service_result.get("ok") is True or service_result.get("status") in {"ok", "success", "completed"}


def _is_failure(service_result: Mapping[str, Any]) -> bool:
    return service_result.get("ok") is False or service_result.get("status") in {"error", "failed"}


def _reject_forbidden_keys(value: Any, *, path: str) -> None:
    offenders = sorted(_forbidden_keys(value))
    if offenders:
        _raise_response_error(code="unsafe_public_response_key", paths=[path], counts={})


def _forbidden_keys(value: Any) -> set[str]:
    keys: set[str] = set()

    def walk(child: Any) -> None:
        if isinstance(child, Mapping):
            for key, item in child.items():
                key_text = str(key)
                if key_text in FORBIDDEN_PUBLIC_KEYS:
                    keys.add(key_text)
                walk(item)
        elif isinstance(child, (list, tuple)):
            for item in child:
                walk(item)

    walk(value)
    return keys


def _counts_from(service_result: Mapping[str, Any]) -> Dict[str, int]:
    integrity = service_result.get("integrity")
    if isinstance(integrity, Mapping) and isinstance(integrity.get("counts"), Mapping):
        return {str(key): _safe_int(value) for key, value in integrity["counts"].items()}
    return {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0


def _raise_response_error(*, code: str, paths: list[str], counts: Mapping[str, int] | None = None) -> None:
    raise V2PublicResponseError(code=code, paths=paths, counts=dict(counts or {})) from None


__all__ = [
    "PUBLIC_RESPONSE_SCHEMA_VERSION",
    "V2PublicResponseError",
    "build_public_response_v2",
]
