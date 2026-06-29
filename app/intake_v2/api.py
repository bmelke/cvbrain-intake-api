"""Isolated HTTP adapter for CVBrain Intake v2."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.intake_v2.pipeline import run_public_intake_v2


PUBLIC_RESPONSE_SCHEMA_VERSION = "cvbrain_intake_v2_public_response"


def create_intake_v2_router(*, provider_dependency: Callable[[], Any]) -> APIRouter:
    """Create the isolated Intake v2 router without app/main wiring."""

    router = APIRouter()

    @router.post("/intake/v2/analyze")
    def analyze_intake_v2(
        payload: Any = Body(default=None),
        provider: Any = Depends(provider_dependency),
    ) -> JSONResponse:
        if not isinstance(payload, Mapping):
            return _safe_failure_response(status_code=400, code="invalid_request", category="request_validation")

        source_text = payload.get("source_text")
        source_language = payload.get("source_language")
        if not _present_text(source_text) or not _present_text(source_language):
            return _safe_failure_response(status_code=400, code="invalid_request", category="request_validation")

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
