"""Isolated HTTP adapter for CVBrain Intake v2."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hmac import compare_digest
import os
from typing import Any

from fastapi import APIRouter, Body, Header, Request
from fastapi.responses import JSONResponse

from app.intake_v2.pipeline import run_public_intake_v2


PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"
V2_ACCESS_KEY_ENV = "CVBRAIN_INTAKE_V2_API_KEY"
V2_ACCESS_KEY_HEADER = "X-CVBrain-V2-API-Key"


def create_intake_v2_router(*, provider_dependency: Callable[[], Any]) -> APIRouter:
    """Create the isolated Intake v2 router without app/main wiring."""

    router = APIRouter()

    @router.post("/intake/v2/analyze")
    def analyze_intake_v2(
        request: Request,
        payload: Any = Body(default=None),
        x_cvbrain_v2_api_key: str | None = Header(default=None, alias=V2_ACCESS_KEY_HEADER),
    ) -> JSONResponse:
        auth_failure = _v2_auth_failure_response(x_cvbrain_v2_api_key)
        if auth_failure is not None:
            return auth_failure

        if not isinstance(payload, Mapping):
            return _safe_failure_response(status_code=400, code="invalid_request", category="request_validation")

        source_text = payload.get("source_text")
        source_language = payload.get("source_language")
        if not _present_text(source_text) or not _present_text(source_language):
            return _safe_failure_response(status_code=400, code="invalid_request", category="request_validation")

        provider = _resolve_provider_dependency(request, provider_dependency)

        try:
            response = run_public_intake_v2(
                source_text=source_text,
                source_language=source_language,
                provider=provider,
            )
        except Exception:
            return _safe_failure_response(status_code=500, code="pipeline_failed", category="pipeline")

        return JSONResponse(content=response, status_code=200)

    return router


def _v2_auth_failure_response(client_key: str | None) -> JSONResponse | None:
    server_key = os.getenv(V2_ACCESS_KEY_ENV, "").strip()
    if not server_key:
        return _safe_failure_response(status_code=503, code="v2_auth_unavailable", category="configuration")

    provided_key = (client_key or "").strip()
    if not provided_key or not compare_digest(provided_key, server_key):
        return _safe_failure_response(status_code=401, code="unauthorized", category="authentication")

    return None


def _resolve_provider_dependency(request: Request, provider_dependency: Callable[[], Any]) -> Any:
    dependency = request.app.dependency_overrides.get(provider_dependency, provider_dependency)
    return dependency()


def _present_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
