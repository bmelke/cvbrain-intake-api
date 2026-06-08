"""Optional OpenAI Structured Output extractor for CVBrain.

The module is safe to import without the OpenAI package installed. The official
SDK is imported only when AI extraction is actually attempted without an
injected client.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional

from app.extractors.base import ExtractorError, ExtractorRequest
from app.mappers.job_intelligence_to_flat import derive_flat_compatibility
from app.schemas.job_intelligence_v1_contract import (
    JobIntelligenceV1Output,
    JobIntelligenceValidationError,
    validate_job_intelligence_v1,
)


DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_INPUT_CHARS = 12000
DEFAULT_MAX_OUTPUT_TOKENS = 4096


SYSTEM_INSTRUCTIONS = """You are CVBrain Job Intake extraction.

Return only CVBrain Job Intelligence v1 structured output.

Rules:
- Extract only from source text and provided context.
- All interpretation is location-dependent.
- Use locale, country_context, candidate_market, and employer_market.
- Do not invent country or city.
- Do not infer Buenos Aires/CABA/GBA unless source text says it or country_context supports Argentina.
- Do not infer Montevideo/Canelones unless source text says it or country_context supports Uruguay.
- If source text conflicts with context, preserve source text and add country_context_mismatch warning.
- Do not convert CABA/GBA to Montevideo.
- Do not convert Montevideo to CABA/GBA.
- Do not infer remote/hybrid/onsite unless explicit.
- Do not invent salary, compensation, degrees, licenses, certifications, tools, team size, or travel.
- Do not promote preferred or nice-to-have items to must-have.
- Do not turn soft competencies into hard resume filters.
- Separate requirements from responsibilities.
- Separate search terms from evidence.
- Include confidence.
- Include source_span for important fields where possible.
- Add missing_information and company_clarification_questions when intake is unclear.
- company_clarification_questions are for the hiring company/requesting manager.
- candidate_screening_questions are for candidates.
- Do not block ambiguous searches by default.
- If intake is ambiguous, set search_readiness to exploratory or insufficient_for_precise_search and proceed_allowed=true.
- Only block for safety, prohibited filtering, empty input, permissions/security, or technical failure with no fallback.
- Do not include candidate results.
- Do not include candidate PII.
"""


class OpenAIStructuredExtractor:
    """OpenAI-backed extractor that returns the existing flat contract."""

    engine = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        strict_schema_enabled: bool = True,
        client: Optional[Any] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_input_chars = max_input_chars
        self.max_output_tokens = max_output_tokens
        self.strict_schema_enabled = strict_schema_enabled
        self.client = client

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "OpenAIStructuredExtractor":
        return cls(
            api_key=str(env.get("OPENAI_API_KEY", "")).strip(),
            model=str(env.get("CVBRAIN_OPENAI_MODEL", "")).strip(),
            timeout_seconds=_env_float(env, "CVBRAIN_AI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
            max_input_chars=_env_int(env, "CVBRAIN_AI_MAX_INPUT_CHARS", DEFAULT_MAX_INPUT_CHARS),
            max_output_tokens=_env_int(env, "CVBRAIN_AI_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS),
            strict_schema_enabled=_env_bool(env, "CVBRAIN_AI_STRICT_SCHEMA_ENABLED", True),
        )

    def build_payload(self, request: ExtractorRequest) -> Dict[str, Any]:
        payload = request.ai_payload()
        source_text = str(payload.get("source_text", ""))
        if len(source_text) > self.max_input_chars:
            raise ExtractorError(
                "ai_input_too_large",
                "source_text exceeds CVBRAIN_AI_MAX_INPUT_CHARS.",
            )
        return payload

    def extract(self, request: ExtractorRequest) -> Dict[str, Any]:
        ai_payload = self.build_payload(request)

        try:
            response = self._responses_parse(ai_payload)
            job_intelligence = self._extract_payload(response)
            validate_job_intelligence_v1(job_intelligence)
        except ExtractorError:
            raise
        except JobIntelligenceValidationError as error:
            raise ExtractorError(
                "ai_schema_validation_failed",
                "OpenAI output failed CVBrain Job Intelligence v1 validation.",
                warnings=["ai_schema_validation_failed"],
            ) from error
        except TimeoutError as error:
            raise ExtractorError(
                "ai_timeout",
                "OpenAI structured extraction timed out.",
                warnings=["ai_timeout"],
            ) from error
        except Exception as error:
            raise ExtractorError(
                "ai_provider_error",
                "OpenAI structured extraction failed.",
                warnings=["ai_provider_error"],
            ) from error

        flat = derive_flat_compatibility(job_intelligence)
        flat["engine"] = self.engine
        flat["fallback_used"] = False
        flat["ai_model"] = self.model
        flat["job_intelligence"] = job_intelligence
        return flat

    def _responses_parse(self, ai_payload: Mapping[str, Any]) -> Any:
        client = self._client()
        input_messages = [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {
                "role": "user",
                "content": "Extract CVBrain Job Intelligence v1 JSON from this sanitized intake payload:\n"
                + json.dumps(ai_payload, ensure_ascii=False, sort_keys=True),
            },
        ]

        if hasattr(client.responses, "parse"):
            return client.responses.parse(
                model=self.model,
                input=input_messages,
                text_format=JobIntelligenceV1Output,
                max_output_tokens=self.max_output_tokens,
            )

        return client.responses.create(
            model=self.model,
            input=input_messages,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "cvbrain_job_intelligence_v1",
                    "schema": JobIntelligenceV1Output.schema(),
                    "strict": self.strict_schema_enabled,
                }
            },
            max_output_tokens=self.max_output_tokens,
        )

    def _client(self) -> Any:
        if self.client is None:
            self.client = self._default_client()
        return self.client

    def _default_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise ExtractorError(
                "ai_openai_dependency_missing",
                "The OpenAI Python SDK is required for AI extraction.",
            ) from error

        return OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)

    def _extract_payload(self, response: Any) -> Dict[str, Any]:
        parsed = _get_response_value(response, "output_parsed")
        if parsed is not None:
            return _coerce_payload(parsed)

        output_text = _get_response_value(response, "output_text")
        if output_text:
            return _loads_json(str(output_text))

        refusal = _get_response_value(response, "refusal")
        if refusal:
            raise ExtractorError(
                "ai_refusal",
                "OpenAI refused the structured extraction request.",
                warnings=["ai_refusal"],
            )

        raise ExtractorError(
            "ai_invalid_json",
            "OpenAI response did not include structured JSON.",
            warnings=["ai_invalid_json"],
        )


def _coerce_payload(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return _loads_json(str(value))


def _loads_json(value: str) -> Dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise ExtractorError(
            "ai_invalid_json",
            "OpenAI response was not valid JSON.",
            warnings=["ai_invalid_json"],
        ) from error

    if not isinstance(payload, dict):
        raise ExtractorError(
            "ai_invalid_json",
            "OpenAI response JSON must be an object.",
            warnings=["ai_invalid_json"],
        )
    return payload


def _get_response_value(response: Any, key: str) -> Any:
    if isinstance(response, Mapping):
        return response.get(key)
    return getattr(response, key, None)


def _env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    value = str(env.get(key, "")).strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = str(env.get(key, "")).strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(env: Mapping[str, str], key: str, default: float) -> float:
    value = str(env.get(key, "")).strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default
