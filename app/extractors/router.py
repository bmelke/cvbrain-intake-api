"""Extractor router for optional AI/deterministic selection."""

import os
from typing import Any, Dict, Mapping, Optional

from app.extractors.base import ExtractorError, ExtractorRequest
from app.extractors.deterministic import DeterministicExtractor


SERVICE_VERSION = "0.1.0"
ALLOWED_MODES = {"deterministic", "ai", "auto"}


def env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    value = str(env.get(key, "")).strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


class ExtractorRouter:
    """Routes extraction to deterministic or future AI implementations."""

    def __init__(
        self,
        deterministic_extractor: Optional[DeterministicExtractor] = None,
        ai_extractor: Optional[Any] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.deterministic_extractor = deterministic_extractor or DeterministicExtractor()
        self.ai_extractor = ai_extractor
        self.env = env if env is not None else os.environ

    def mode(self) -> str:
        mode = str(self.env.get("CVBRAIN_EXTRACTOR_MODE", "deterministic")).strip().lower()
        if mode not in ALLOWED_MODES:
            raise ExtractorError(
                "invalid_extractor_mode",
                f"Unsupported CVBRAIN_EXTRACTOR_MODE: {mode}",
            )
        return mode

    def fallback_enabled(self) -> bool:
        return env_bool(self.env, "CVBRAIN_AI_FALLBACK_ENABLED", True)

    def openai_api_key_available(self) -> bool:
        return bool(str(self.env.get("OPENAI_API_KEY", "")).strip())

    def openai_model_available(self) -> bool:
        return bool(str(self.env.get("CVBRAIN_OPENAI_MODEL", "")).strip())

    def extract(self, request: ExtractorRequest) -> Dict[str, Any]:
        mode = self.mode()

        if mode == "deterministic":
            return self._deterministic(request, fallback_used=False)

        if mode == "auto" and not (self.openai_api_key_available() and self.openai_model_available()):
            return self._deterministic(request, fallback_used=False)

        if mode == "ai" and not self.openai_api_key_available():
            return self._fallback_or_error(
                request,
                ExtractorError(
                    "ai_missing_api_key",
                    "OPENAI_API_KEY is required when CVBRAIN_EXTRACTOR_MODE=ai.",
                ),
            )

        if mode == "ai" and not self.openai_model_available():
            return self._fallback_or_error(
                request,
                ExtractorError(
                    "ai_missing_model",
                    "CVBRAIN_OPENAI_MODEL is required when CVBRAIN_EXTRACTOR_MODE=ai.",
                ),
            )

        try:
            ai_extractor = self._ai_extractor()
            payload = ai_extractor.extract(request)
        except ExtractorError as error:
            return self._fallback_or_error(request, error)

        payload.setdefault("warnings", [])
        payload["engine"] = getattr(ai_extractor, "engine", "ai")
        payload["fallback_used"] = False
        return payload

    def build_ai_payload(self, request: ExtractorRequest) -> Dict[str, Any]:
        return self._ai_extractor().build_payload(request)

    def _ai_extractor(self) -> Any:
        if self.ai_extractor is None:
            from app.extractors.openai_structured import OpenAIStructuredExtractor

            self.ai_extractor = OpenAIStructuredExtractor.from_env(self.env)
        return self.ai_extractor

    def _deterministic(
        self,
        request: ExtractorRequest,
        fallback_used: bool,
        warning: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = self.deterministic_extractor.extract(request)
        payload["engine"] = "deterministic"
        payload["fallback_used"] = fallback_used
        if warning:
            warnings = list(payload.get("warnings", []))
            warnings.extend(["ai_fallback_used", warning])
            payload["warnings"] = list(dict.fromkeys(warnings))
        return payload

    def _fallback_or_error(self, request: ExtractorRequest, error: ExtractorError) -> Dict[str, Any]:
        if error.code == "ai_schema_validation_failed":
            return self._error_response(error)
        if self.fallback_enabled():
            return self._deterministic(request, fallback_used=True, warning=error.code)
        return self._error_response(error)

    def _error_response(self, error: ExtractorError) -> Dict[str, Any]:
        warnings = list(dict.fromkeys(error.warnings or [error.code]))
        response = {
            "ok": False,
            "version": SERVICE_VERSION,
            "role_title": "",
            "role_family": "",
            "summary": "",
            "must_have": [],
            "should_have": [],
            "nice_to_have": [],
            "blockers": [],
            "credentials": {"required": [], "preferred": []},
            "experience": {"minimum_years": None, "seniority": ""},
            "location": {
                "raw": "",
                "normalized": "",
                "remote_allowed": None,
                "hybrid_allowed": None,
            },
            "search_terms": [],
            "semantic_terms": [],
            "recruiter_questions": [],
            "warnings": warnings,
            "confidence": 0.0,
            "engine": "openai",
            "fallback_used": False,
        }
        return response
