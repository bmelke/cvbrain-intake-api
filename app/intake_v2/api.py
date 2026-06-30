"""Isolated HTTP adapter for CVBrain Intake v2."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hmac import compare_digest
import json
import os
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.intake_v2.pipeline import run_public_intake_v2


PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"
V2_ACCESS_KEY_ENV = "CVBRAIN_INTAKE_V2_API_KEY"
V2_ACCESS_KEY_HEADER = "X-CVBrain-V2-API-Key"
MAX_V2_REQUEST_BODY_BYTES = 262_144
MAX_V2_SOURCE_TEXT_CHARS = 50_000


def create_intake_v2_router(*, provider_dependency: Callable[[], Any]) -> APIRouter:
    """Create the isolated Intake v2 router without app/main wiring."""

    router = APIRouter()

    @router.post("/intake/v2/analyze")
    async def analyze_intake_v2(
        request: Request,
        x_cvbrain_v2_api_key: str | None = Header(default=None, alias=V2_ACCESS_KEY_HEADER),
    ) -> JSONResponse:
        auth_failure = _v2_auth_failure_response(x_cvbrain_v2_api_key)
        if auth_failure is not None:
            return auth_failure

        content_length_failure = _content_length_failure_response(request)
        if content_length_failure is not None:
            return content_length_failure

        body = await request.body()
        if len(body) > MAX_V2_REQUEST_BODY_BYTES:
            return _request_too_large_response()

        try:
            payload = json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _safe_failure_response(status_code=400, code="invalid_request", category="request_validation")

        if not isinstance(payload, Mapping):
            return _safe_failure_response(status_code=400, code="invalid_request", category="request_validation")

        source_text = payload.get("source_text")
        source_language = payload.get("source_language")
        if not _present_text(source_text) or not _present_text(source_language):
            return _safe_failure_response(status_code=400, code="invalid_request", category="request_validation")
        if len(source_text) > MAX_V2_SOURCE_TEXT_CHARS:
            return _request_too_large_response()

        provider = _resolve_provider_dependency(request, provider_dependency)
        if provider is None:
            return _safe_readiness_response(status_code=503, status="unavailable")

        try:
            response = run_public_intake_v2(
                source_text=source_text,
                source_language=source_language,
                provider=provider,
            )
        except Exception:
            return _safe_failure_response(status_code=500, code="pipeline_failed", category="pipeline")

        return JSONResponse(content=response, status_code=200)

    @router.get("/intake/v2/status")
    def status_intake_v2(
        request: Request,
        x_cvbrain_v2_api_key: str | None = Header(default=None, alias=V2_ACCESS_KEY_HEADER),
    ) -> JSONResponse:
        auth_failure = _v2_auth_failure_response(x_cvbrain_v2_api_key)
        if auth_failure is not None:
            return auth_failure

        provider = _resolve_provider_dependency(request, provider_dependency)
        if provider is None:
            return _safe_readiness_response(status_code=503, status="unavailable")

        return _safe_readiness_response(status_code=200, status="ready")

    return router


def _v2_auth_failure_response(client_key: str | None) -> JSONResponse | None:
    server_key = os.getenv(V2_ACCESS_KEY_ENV, "").strip()
    if not server_key:
        return _safe_failure_response(status_code=503, code="v2_auth_unavailable", category="configuration")

    provided_key = (client_key or "").strip()
    if not provided_key or not compare_digest(provided_key, server_key):
        return _safe_failure_response(status_code=401, code="unauthorized", category="authentication")

    return None


def _content_length_failure_response(request: Request) -> JSONResponse | None:
    raw_content_length = request.headers.get("content-length")
    if raw_content_length is None:
        return None

    try:
        content_length = int(raw_content_length)
    except ValueError:
        return _safe_failure_response(status_code=400, code="invalid_request", category="request_validation")

    if content_length < 0:
        return _safe_failure_response(status_code=400, code="invalid_request", category="request_validation")
    if content_length > MAX_V2_REQUEST_BODY_BYTES:
        return _request_too_large_response()
    return None


def _resolve_provider_dependency(request: Request, provider_dependency: Callable[[], Any]) -> Any:
    dependency = request.app.dependency_overrides.get(provider_dependency, provider_dependency)
    return dependency()


def _present_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _request_too_large_response() -> JSONResponse:
    return _safe_failure_response(status_code=413, code="request_too_large", category="request_validation")


def _safe_readiness_response(*, status_code: int, status: str) -> JSONResponse:
    return JSONResponse(content={"status": status}, status_code=status_code)


def _safe_failure_response(*, status_code: int, code: str, category: str) -> JSONResponse:
    return JSONResponse(
        content={
            "ok": False,
            "status": "error",
            "schema_version": PUBLIC_RESPONSE_SCHEMA_VERSION,
            "error": {
                "code": code,
                "category": category,
            },
        },
        status_code=status_code,
    )


__all__ = ["create_intake_v2_router"]
