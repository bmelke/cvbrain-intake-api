"""Optional OpenAI Structured Output extractor for CVBrain.

The module is safe to import without the OpenAI package installed. The official
SDK is imported only when AI extraction is actually attempted without an
injected client.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, Mapping, Optional

from app.extractors.base import ExtractorError, ExtractorRequest
from app.mappers.job_intelligence_to_flat import derive_flat_compatibility
from app.normalization.requirement_importance import normalize_job_intelligence_requirements
from app.normalization.role_title import normalize_role_title_for_source
from app.schemas.job_intelligence_v1_contract import (
    JobIntelligenceValidationError,
    validate_job_intelligence_v1,
)


DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_INPUT_CHARS = 12000
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_SCHEMA_REPAIR_ATTEMPTS = 2
RAW_OUTPUT_PREVIEW_CHARS = 500
OPENAI_API_SHAPE = "responses.create:text.format.json_schema"
LOGGER = logging.getLogger("cvbrain.openai_structured")


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
- Section/category labels are defaults only; local item modifiers are final authority.
- Split compound requirement text into individual items before assigning importance.
- Strong preference modifiers such as deseable, preferentemente, ideal, muy valorable, or strongly preferred map to should_have.
- Weak preference modifiers such as valorable, se valora, plus, suma, nice to have, or would be a plus map to nice_to_have.
- Soft local modifiers downgrade items even under hard sections.
- Hard local modifiers such as excluyente, imprescindible, obligatorio, no presentarse a menos que, or sin X no avanzar upgrade items even under soft sections.
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

REPAIR_INSTRUCTIONS = """Repair CVBrain Job Intelligence v1 JSON.

The previous model response did not validate. Return only corrected JSON that
matches the CVBrain Job Intelligence v1 schema. Do not add commentary, markdown,
or extra keys. Preserve the original source facts. Do not invent missing facts.
Do not include candidate data or candidate PII.
"""

LANGUAGE_CONTRACT = """Language contract:
- Source text language detected as: {source_language}.
- All user-facing output fields must be in the same language as source_text.
- User-facing fields include role_title, requirements, blockers, recruiter/company questions, candidate questions, warnings, notes, seniority labels, role family labels where applicable, summaries, missing information, and job profile fields.
- If source_text is Spanish, write those user-facing fields in Spanish.
- If source_text is English, write those user-facing fields in English.
- Do not translate technologies, product names, acronyms, certifications, platforms, frameworks, or titles explicitly written in English by the recruiter.
- Preserve terms such as Python, Java, React, SQL, AWS, Azure, GCP, SAP, Salesforce, CRM, ERP, TMS, WMS, BI, QA, UX, UI, DevOps, B2B, and B2C.
- Preserve explicitly English role titles when source_text uses them, such as Data Engineer, Product Manager, DevOps Engineer, QA Automation Engineer, QA Tester, Account Manager, Customer Success Manager, UX/UI Designer, Community Manager Senior, and Community Manager.
- The primary role_title must not be translated away from the source language.
- For Spanish source_text, prefer the exact Spanish title phrase from source_text when present, for example Arquitecto de Software, Vendedor Técnico, Liquidador de Siniestros, or Periodista.
- For Spanish source_text that explicitly uses an English title such as Data Engineer, Product Manager, DevOps Engineer, QA Automation Engineer, QA Tester, Account Manager, Customer Success Manager, UX/UI Designer, Community Manager Senior, Community Manager, Business Analyst, BI Analyst, Full Stack Developer, Backend Developer, or Frontend Developer, preserve that English title.

Case contract:
- For matching and validation purposes, upper/lower case differences should usually be ignored.
- For output, incoming source case wins.
- If the recruiter source contains an explicit role title span, preserve that source span's casing and punctuation in role_title, job_profile.job_title, and job_profile.normalized_role_title.
- Do not title-case Spanish titles unless the source itself is title-cased.
- Do not lowercase acronyms or technical abbreviations.
- Preserve acronyms, products, and technologies exactly where possible: QA, UX, UI, UX/UI, IT, CRM, ERP, TMS, WMS, BI, AWS, Azure, GCP, SAP, Salesforce, B2B, B2C, and SaaS.
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
        fallback_enabled: bool = True,
        extractor_mode: str = "ai",
        client: Optional[Any] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_input_chars = max_input_chars
        self.max_output_tokens = max_output_tokens
        self.strict_schema_enabled = strict_schema_enabled
        self.fallback_enabled = fallback_enabled
        self.extractor_mode = extractor_mode
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
            fallback_enabled=_env_bool(env, "CVBRAIN_AI_FALLBACK_ENABLED", True),
            extractor_mode=str(env.get("CVBRAIN_EXTRACTOR_MODE", "ai")).strip().lower() or "ai",
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
        parsed_job_intelligence: Optional[Dict[str, Any]] = None
        job_intelligence: Optional[Dict[str, Any]] = None
        response: Optional[Any] = None
        repaired = False

        self._log_event(
            "request_start",
            request_payload=ai_payload,
            parse_path="not_started",
        )

        try:
            response = self._responses_parse(ai_payload)
            try:
                parsed_job_intelligence, job_intelligence = self._parse_normalize_validate_response(response, request)
            except JobIntelligenceValidationError as error:
                response, parsed_job_intelligence, job_intelligence = self._repair_schema(
                    ai_payload=ai_payload,
                    request=request,
                    failed_response=response,
                    failed_parsed_payload=parsed_job_intelligence,
                    failed_job_intelligence=job_intelligence,
                    error=error,
                )
                repaired = True
            except ExtractorError as error:
                if error.code != "ai_invalid_json":
                    raise
                try:
                    response, parsed_job_intelligence, job_intelligence = self._repair_schema(
                        ai_payload=ai_payload,
                        request=request,
                        failed_response=response,
                        failed_parsed_payload=parsed_job_intelligence,
                        failed_job_intelligence=job_intelligence,
                        error=error,
                    )
                    repaired = True
                except ExtractorError as repair_error:
                    if self.fallback_enabled and repair_error.code == "ai_schema_validation_failed":
                        raise error from repair_error
                    raise
        except ExtractorError as error:
            self._log_exception(
                error.code,
                error,
                request_payload=ai_payload,
            )
            raise
        except JobIntelligenceValidationError as error:
            self._log_schema_validation_failure(
                error,
                request_payload=ai_payload,
                response=response,
                parsed_job_intelligence=parsed_job_intelligence,
                job_intelligence=job_intelligence,
            )
            self._log_exception(
                "schema_validation_failed",
                error,
                request_payload=ai_payload,
            )
            raise _schema_validation_failed_error() from error
        except TimeoutError as error:
            self._log_exception(
                "timeout",
                error,
                request_payload=ai_payload,
            )
            raise ExtractorError(
                "ai_timeout",
                "OpenAI structured extraction timed out.",
                warnings=["ai_timeout"],
            ) from error
        except Exception as error:
            self._log_exception(
                "provider_error",
                error,
                request_payload=ai_payload,
            )
            raise ExtractorError(
                "ai_provider_error",
                "OpenAI structured extraction failed.",
                warnings=["ai_provider_error"],
            ) from error

        self._log_event(
            "request_success",
            request_payload=ai_payload,
            parse_path="validated_job_intelligence",
            parsed_json_keys=sorted(job_intelligence.keys()),
        )

        flat = derive_flat_compatibility(job_intelligence)
        flat["engine"] = self.engine
        flat["fallback_used"] = False
        flat["ai_model"] = self.model
        flat["job_intelligence"] = job_intelligence
        if repaired:
            flat["ai_schema_repaired"] = True
        return flat

    def _parse_normalize_validate_response(
        self,
        response: Any,
        request: ExtractorRequest,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        parsed_job_intelligence = self._extract_payload(response)
        job_intelligence = normalize_job_intelligence_requirements(
            parsed_job_intelligence,
            source_text=request.source_text,
        )
        job_intelligence = normalize_role_title_for_source(job_intelligence, source_text=request.source_text)
        validate_job_intelligence_v1(job_intelligence)
        return parsed_job_intelligence, job_intelligence

    def _repair_schema(
        self,
        ai_payload: Mapping[str, Any],
        request: ExtractorRequest,
        failed_response: Any,
        failed_parsed_payload: Optional[Mapping[str, Any]],
        failed_job_intelligence: Optional[Mapping[str, Any]],
        error: BaseException,
    ) -> tuple[Any, Dict[str, Any], Dict[str, Any]]:
        current_response = failed_response
        current_parsed_payload = failed_parsed_payload
        current_job_intelligence = failed_job_intelligence
        current_error: BaseException = error

        for attempt in range(1, DEFAULT_SCHEMA_REPAIR_ATTEMPTS + 1):
            invalid_output = _raw_output_for_diagnostics(current_response, current_parsed_payload)
            self._log_event(
                "schema_repair_start",
                request_payload=ai_payload,
                parse_path=_response_parse_path(current_response),
                repair_attempt=attempt,
                exception_class=current_error.__class__.__name__,
                sanitized_exception_message=_sanitize_text(str(current_error)),
                validation_error_fields=_validation_error_fields(str(current_error)),
                sanitized_raw_output_sha256=_sha256_hex(_sanitize_text(invalid_output, limit=20000)),
            )

            repair_response: Optional[Any] = None
            repair_parsed_payload: Optional[Dict[str, Any]] = None
            repair_job_intelligence: Optional[Dict[str, Any]] = None
            try:
                repair_response = self._responses_repair(ai_payload, invalid_output, current_error, attempt=attempt)
                repair_parsed_payload, repair_job_intelligence = self._parse_normalize_validate_response(
                    repair_response,
                    request,
                )
            except JobIntelligenceValidationError as repair_error:
                self._log_schema_validation_failure(
                    repair_error,
                    request_payload=ai_payload,
                    response=repair_response,
                    parsed_job_intelligence=repair_parsed_payload,
                    job_intelligence=repair_job_intelligence,
                )
                current_response = repair_response
                current_parsed_payload = repair_parsed_payload
                current_job_intelligence = repair_job_intelligence
                current_error = repair_error
                continue
            except ExtractorError as repair_error:
                self._log_exception(
                    "schema_repair_failed",
                    repair_error,
                    request_payload=ai_payload,
                )
                current_response = repair_response
                current_parsed_payload = repair_parsed_payload
                current_job_intelligence = repair_job_intelligence
                current_error = repair_error
                continue
            except Exception as repair_error:
                self._log_exception(
                    "schema_repair_failed",
                    repair_error,
                    request_payload=ai_payload,
                )
                current_response = repair_response
                current_parsed_payload = repair_parsed_payload
                current_job_intelligence = repair_job_intelligence
                current_error = repair_error
                continue

            self._log_event(
                "schema_repair_success",
                request_payload=ai_payload,
                parse_path=_response_parse_path(repair_response),
                repair_attempt=attempt,
                parsed_json_keys=sorted(repair_job_intelligence.keys()),
            )
            return repair_response, repair_parsed_payload, repair_job_intelligence

        raise _schema_validation_failed_error() from current_error

    def _responses_parse(self, ai_payload: Mapping[str, Any]) -> Any:
        client = self._client()
        input_messages = [
            {"role": "system", "content": _system_instructions_for_payload(ai_payload)},
            {
                "role": "user",
                "content": "Extract CVBrain Job Intelligence v1 JSON from this sanitized intake payload:\n"
                + json.dumps(ai_payload, ensure_ascii=False, sort_keys=True),
            },
        ]

        return client.responses.create(
            model=self.model,
            input=input_messages,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "cvbrain_job_intelligence_v1",
                    "description": "CVBrain Job Intelligence v1 extraction output.",
                    "schema": job_intelligence_v1_response_schema(),
                    "strict": self.strict_schema_enabled,
                }
            },
            max_output_tokens=self.max_output_tokens,
        )

    def _responses_repair(
        self,
        ai_payload: Mapping[str, Any],
        invalid_output: str,
        error: BaseException,
        attempt: int,
    ) -> Any:
        client = self._client()
        input_messages = [
            {"role": "system", "content": _repair_instructions_for_payload(ai_payload)},
            {
                "role": "user",
                "content": "Repair this invalid CVBrain Job Intelligence v1 response.\n"
                f"Repair attempt: {attempt} of {DEFAULT_SCHEMA_REPAIR_ATTEMPTS}.\n"
                "Validation error:\n"
                + _sanitize_text(str(error), limit=1200)
                + "\n\nOriginal sanitized intake payload:\n"
                + json.dumps(ai_payload, ensure_ascii=False, sort_keys=True)
                + "\n\nInvalid output to repair:\n"
                + str(invalid_output),
            },
        ]

        return client.responses.create(
            model=self.model,
            input=input_messages,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "cvbrain_job_intelligence_v1",
                    "description": "Repaired CVBrain Job Intelligence v1 extraction output.",
                    "schema": job_intelligence_v1_response_schema(),
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
            payload = _coerce_payload(parsed)
            self._log_event(
                "response_parse",
                parse_path="output_parsed",
                raw_output_text_found=False,
                parsed_json_keys=sorted(payload.keys()),
            )
            return payload

        output_text = _get_response_value(response, "output_text")
        if output_text:
            payload = _loads_json(str(output_text))
            self._log_event(
                "response_parse",
                parse_path="output_text",
                raw_output_text_found=True,
                parsed_json_keys=sorted(payload.keys()),
            )
            return payload

        output_text = _output_text_from_output_items(_get_response_value(response, "output"))
        if output_text:
            payload = _loads_json(output_text)
            self._log_event(
                "response_parse",
                parse_path="output_array.output_text",
                raw_output_text_found=True,
                parsed_json_keys=sorted(payload.keys()),
            )
            return payload

        refusal = _get_response_value(response, "refusal")
        if refusal:
            self._log_event(
                "response_refusal",
                parse_path="refusal",
                sanitized_exception_message=_sanitize_text(str(refusal)),
            )
            raise ExtractorError(
                "ai_refusal",
                "OpenAI refused the structured extraction request.",
                warnings=["ai_refusal"],
            )

        self._log_event(
            "response_parse_failed",
            parse_path="missing_output_text",
            raw_output_text_found=False,
            response_keys=_safe_keys(response),
        )
        raise ExtractorError(
            "ai_invalid_json",
            "OpenAI response did not include structured JSON.",
            warnings=["ai_invalid_json"],
        )

    def _log_event(self, event: str, **metadata: Any) -> None:
        safe_metadata = {
            "event": event,
            "extractor_mode": self.extractor_mode,
            "model": self.model,
            "api_shape": OPENAI_API_SHAPE,
            "strict_schema_enabled": self.strict_schema_enabled,
            "fallback_enabled": self.fallback_enabled,
        }
        safe_metadata.update(_safe_log_metadata(metadata))
        LOGGER.info("cvbrain_openai_extractor %s", json.dumps(safe_metadata, sort_keys=True))

    def _log_exception(
        self,
        event: str,
        error: BaseException,
        request_payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._log_event(
            event,
            request_payload=request_payload,
            exception_class=error.__class__.__name__,
            sanitized_exception_message=_sanitize_text(str(error)),
            openai_request_id=getattr(error, "request_id", None),
            http_status=getattr(error, "status_code", None),
            sanitized_openai_error_body=_sanitize_text(str(getattr(error, "body", ""))),
        )

    def _log_schema_validation_failure(
        self,
        error: JobIntelligenceValidationError,
        request_payload: Mapping[str, Any],
        response: Optional[Any],
        parsed_job_intelligence: Optional[Mapping[str, Any]],
        job_intelligence: Optional[Mapping[str, Any]],
    ) -> None:
        message = str(error)
        raw_output = _raw_output_for_diagnostics(response, parsed_job_intelligence)
        sanitized_raw_output = _sanitize_text(raw_output, limit=20000)
        diagnostics = {
            "event": "cvbrain.ai_schema_validation_failed",
            "exception_class": error.__class__.__name__,
            "sanitized_exception_message": _sanitize_text(message),
            "validation_stage": "job_intelligence_v1_validation",
            "parse_path": _response_parse_path(response),
            "validation_errors": _validation_errors(message),
            "validation_error_fields": _validation_error_fields(message),
            "validation_error_count": _validation_error_count(message),
            "parsed_top_level_keys": _safe_keys(parsed_job_intelligence or {}),
            "job_intelligence_top_level_keys": _safe_keys(job_intelligence or {}),
            "requirements_bucket_counts": _requirements_bucket_counts(job_intelligence),
            "requirement_item_summaries": _requirement_item_summaries(job_intelligence),
            "flat_output_bucket_counts": _flat_output_bucket_counts(job_intelligence),
            "model": self.model,
            "extractor_mode": self.extractor_mode,
            "strict_schema_enabled": self.strict_schema_enabled,
            "fallback_enabled": self.fallback_enabled,
            "openai_response_id": _sanitize_text(str(_get_response_value(response, "id") or "")),
            "openai_request_id": _sanitize_text(str(_get_response_value(response, "request_id") or "")),
            "sanitized_raw_output_sha256": _sha256_hex(sanitized_raw_output),
            "sanitized_raw_output_preview": _sanitize_text(raw_output, limit=RAW_OUTPUT_PREVIEW_CHARS),
            "locale": request_payload.get("locale"),
            "country_context": request_payload.get("country_context"),
            "candidate_market": request_payload.get("candidate_market"),
            "employer_market": request_payload.get("employer_market"),
            "source_mime_type": request_payload.get("source_mime_type"),
            "source_filename_present": bool(request_payload.get("source_filename")),
            "source_text_length": len(str(request_payload.get("source_text", ""))),
            "recruiter_notes_present": bool(str(request_payload.get("recruiter_notes", "")).strip()),
        }
        LOGGER.warning(
            "cvbrain.ai_schema_validation_failed %s",
            json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
        )


def detect_source_language(source_text: str) -> str:
    """Detect the recruiter source language at the level needed for prompts."""

    text = str(source_text or "")
    if not text.strip():
        return "English"
    spanish_markers = re.findall(
        r"\b(?:empresa|busca|buscamos|seleccionamos|experiencia|deseable|excluyente|"
        r"imprescindible|requerido|requerida|modalidad|ubicaci[oó]n|montevideo|uruguay|"
        r"b[uú]squeda|se\s+busca|para|de|con|sin|debe|manejo|conocimiento|"
        r"licencia|libreta|t[ií]tulo|formaci[oó]n|h[ií]brido|presencial|remoto)\b",
        text,
        flags=re.I,
    )
    english_markers = re.findall(
        r"\b(?:company|hiring|requires|required|preferred|experience|location|remote|"
        r"hybrid|onsite|must|should|nice\s+to\s+have|degree|certification)\b",
        text,
        flags=re.I,
    )
    spanish_chars = re.findall(r"[áéíóúñüÁÉÍÓÚÑÜ]", text)
    if spanish_chars or len(spanish_markers) > len(english_markers):
        return "Spanish"
    return "English"


def _language_contract_for_payload(ai_payload: Mapping[str, Any]) -> str:
    language = detect_source_language(str(ai_payload.get("source_text", "")))
    return LANGUAGE_CONTRACT.format(source_language=language)


def _system_instructions_for_payload(ai_payload: Mapping[str, Any]) -> str:
    return SYSTEM_INSTRUCTIONS.rstrip() + "\n\n" + _language_contract_for_payload(ai_payload).strip() + "\n"


def _repair_instructions_for_payload(ai_payload: Mapping[str, Any]) -> str:
    return REPAIR_INSTRUCTIONS.rstrip() + "\n\n" + _language_contract_for_payload(ai_payload).strip() + "\n"


def job_intelligence_v1_response_schema() -> Dict[str, Any]:
    """OpenAI Structured Outputs-compatible JSON schema.

    This schema avoids free-form `{}` items and `additionalProperties: true`,
    which are common causes of provider-side schema failures. Fields that are
    optional in product semantics are represented as nullable required fields.
    """

    requirement_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "text": {"type": "string"},
            "source_text": {"type": "string"},
            "importance": {
                "type": "string",
                "enum": ["must_have", "strongly_preferred", "preferred", "nice_to_have", "low_importance"],
            },
            "explicit": {"type": "boolean"},
            "hard_filter_candidate": {"type": "boolean"},
            "hard_filter_approved": {"type": "boolean"},
        },
        "required": [
            "text",
            "source_text",
            "importance",
            "explicit",
            "hard_filter_candidate",
            "hard_filter_approved",
        ],
    }

    missing_information_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string"},
            "field": {"type": "string"},
            "description": {"type": "string"},
            "suggested_question": {"type": "string"},
            "can_continue_without_answer": {"type": "boolean"},
        },
        "required": ["id", "field", "description", "suggested_question", "can_continue_without_answer"],
    }

    company_question_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string"},
            "question": {"type": "string"},
            "related_fields": {"type": "array", "items": {"type": "string"}},
            "blocking_level": {"type": "string", "enum": ["advisory", "blocking"]},
            "asked_to": {"type": "string", "enum": ["hiring_company"]},
        },
        "required": ["id", "question", "related_fields", "blocking_level", "asked_to"],
    }

    candidate_screening_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string"},
            "question": {"type": "string"},
            "related_competency": {"type": "string"},
            "evidence_expected": {"type": "string", "enum": ["resume", "interview", "screening", "reference"]},
            "hard_filter_candidate": {"type": "boolean"},
            "hard_filter_approved": {"type": "boolean"},
        },
        "required": [
            "id",
            "question",
            "related_competency",
            "evidence_expected",
            "hard_filter_candidate",
            "hard_filter_approved",
        ],
    }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "enum": ["cvbrain_job_intelligence_v1"]},
            "job_profile": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "job_title": {"type": "string"},
                    "normalized_role_title": {"type": "string"},
                    "role_family": {"type": "string"},
                    "seniority": {"type": "string"},
                    "summary": {"type": "string"},
                    "primary_industries": {"type": "array", "items": {"type": "string"}},
                    "work_modality": {"type": ["string", "null"], "enum": ["onsite", "hybrid", "remote", None]},
                },
                "required": [
                    "job_title",
                    "normalized_role_title",
                    "role_family",
                    "seniority",
                    "summary",
                    "primary_industries",
                    "work_modality",
                ],
            },
            "location_intelligence": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "raw": {"type": "string"},
                    "normalized": {"type": "string"},
                    "country_code": {"type": "string"},
                    "remote_allowed": {"type": ["boolean", "null"]},
                    "hybrid_allowed": {"type": ["boolean", "null"]},
                    "onsite_required": {"type": ["boolean", "null"]},
                    "country_context_mismatch": {"type": "boolean"},
                    "hard_filter_candidate": {"type": "boolean"},
                    "hard_filter_approved": {"type": "boolean"},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "raw",
                    "normalized",
                    "country_code",
                    "remote_allowed",
                    "hybrid_allowed",
                    "onsite_required",
                    "country_context_mismatch",
                    "hard_filter_candidate",
                    "hard_filter_approved",
                    "warnings",
                ],
            },
            "requirements": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "must_have": {"type": "array", "items": requirement_item},
                    "should_have": {"type": "array", "items": requirement_item},
                    "nice_to_have": {"type": "array", "items": requirement_item},
                    "credentials": {"type": "array", "items": requirement_item},
                    "blockers": {"type": "array", "items": {"type": "string"}},
                    "experience": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "minimum_years": {"type": ["integer", "null"]},
                            "seniority": {"type": "string"},
                        },
                        "required": ["minimum_years", "seniority"],
                    },
                    "soft_competencies": {"type": "array", "items": requirement_item},
                },
                "required": [
                    "must_have",
                    "should_have",
                    "nice_to_have",
                    "credentials",
                    "blockers",
                    "experience",
                    "soft_competencies",
                ],
            },
            "search_strategy": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "target_titles": {"type": "array", "items": {"type": "string"}},
                    "search_terms": {"type": "array", "items": {"type": "string"}},
                    "semantic_terms": {"type": "array", "items": {"type": "string"}},
                    "negative_terms": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["target_titles", "search_terms", "semantic_terms", "negative_terms"],
            },
            "missing_information": {"type": "array", "items": missing_information_item},
            "company_clarification_questions": {"type": "array", "items": company_question_item},
            "candidate_screening_questions": {"type": "array", "items": candidate_screening_item},
            "search_readiness": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": [
                            "ready",
                            "usable_with_warnings",
                            "exploratory",
                            "insufficient_for_precise_search",
                            "blocked_for_safety_or_technical_reason",
                        ],
                    },
                    "proceed_allowed": {"type": "boolean"},
                    "recommended_action": {
                        "type": "string",
                        "enum": [
                            "continue_anyway",
                            "answer_clarifying_questions",
                            "ask_company",
                            "use_manual_search",
                            "cancel",
                        ],
                    },
                    "recruiter_decision_required": {"type": "boolean"},
                    "continued_with_missing_information": {"type": "boolean"},
                    "recruiter_override_reason": {"type": ["string", "null"]},
                    "decision_options": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "continue_anyway",
                                "answer_clarifying_questions",
                                "ask_company",
                                "use_manual_search",
                                "cancel",
                            ],
                        },
                    },
                },
                "required": [
                    "status",
                    "proceed_allowed",
                    "recommended_action",
                    "recruiter_decision_required",
                    "continued_with_missing_information",
                    "recruiter_override_reason",
                    "decision_options",
                ],
            },
            "quality_control": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "contains_candidate_data": {"type": "boolean"},
                    "contains_candidate_pii": {"type": "boolean"},
                },
                "required": ["warnings", "confidence", "contains_candidate_data", "contains_candidate_pii"],
            },
        },
        "required": [
            "schema_version",
            "job_profile",
            "location_intelligence",
            "requirements",
            "search_strategy",
            "missing_information",
            "company_clarification_questions",
            "candidate_screening_questions",
            "search_readiness",
            "quality_control",
        ],
    }


def _schema_validation_failed_error() -> ExtractorError:
    return ExtractorError(
        "ai_schema_validation_failed",
        "OpenAI output failed CVBrain Job Intelligence v1 validation.",
        warnings=["ai_schema_validation_failed"],
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


def _output_text_from_output_items(output: Any) -> str:
    texts = []
    if not isinstance(output, list):
        return ""

    for item in output:
        content = _get_response_value(item, "content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            content_type = _get_response_value(content_item, "type")
            if content_type == "output_text":
                text = _get_response_value(content_item, "text")
                if text:
                    texts.append(str(text))

    return "".join(texts).strip()


def _safe_keys(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return sorted(str(key) for key in value.keys())
    keys = []
    for key in ("id", "object", "status", "output", "output_text", "error", "refusal"):
        if hasattr(value, key):
            keys.append(key)
    return keys


def _safe_log_metadata(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if key == "request_payload" and isinstance(value, Mapping):
            safe["locale"] = value.get("locale")
            safe["country_context"] = value.get("country_context")
            safe["candidate_market"] = value.get("candidate_market")
            safe["employer_market"] = value.get("employer_market")
            safe["source_mime_type"] = value.get("source_mime_type")
            safe["source_filename_present"] = bool(value.get("source_filename"))
            safe["source_text_length"] = len(str(value.get("source_text", "")))
            safe["recruiter_notes_present"] = bool(str(value.get("recruiter_notes", "")).strip())
            continue
        if key in {"parsed_json_keys", "response_keys"} and isinstance(value, list):
            safe[key] = [str(item)[:80] for item in value]
            continue
        if key in {
            "parse_path",
            "exception_class",
            "sanitized_exception_message",
            "openai_request_id",
            "http_status",
            "sanitized_openai_error_body",
        }:
            safe[key] = _sanitize_text(str(value))
            continue
        if key == "raw_output_text_found":
            safe[key] = bool(value)
            continue
        safe[key] = _sanitize_text(str(value))
    return safe


def _validation_error_count(message: str) -> int:
    parts = [part.strip() for part in str(message).split(";") if part.strip()]
    return len(parts) if parts else 0


def _validation_errors(message: str) -> list[Dict[str, str]]:
    output = []
    for part in [chunk.strip() for chunk in str(message).split(";") if chunk.strip()]:
        fields = _validation_error_fields(part)
        output.append(
            {
                "path": fields[0] if fields else "",
                "message": _sanitize_text(part, 240),
            }
        )
    return output


def _validation_error_fields(message: str) -> list[str]:
    fields = []
    for part in [chunk.strip() for chunk in str(message).split(";") if chunk.strip()]:
        match = re.search(r"\b([a-zA-Z_]+(?:\.[a-zA-Z_]+)+)\b", part)
        if match:
            fields.append(match.group(1))
            continue
        top_level = re.search(r"missing top-level section:\s*([a-zA-Z_]+)", part)
        if top_level:
            fields.append(top_level.group(1))
    return list(dict.fromkeys(fields))


def _response_parse_path(response: Any) -> str:
    if response is None:
        return "response_unavailable"
    if _get_response_value(response, "output_parsed") is not None:
        return "output_parsed"
    if _get_response_value(response, "output_text"):
        return "output_text"
    if _output_text_from_output_items(_get_response_value(response, "output")):
        return "output_array.output_text"
    if _get_response_value(response, "refusal"):
        return "refusal"
    return "unknown"


def _raw_output_for_diagnostics(response: Any, parsed_payload: Optional[Mapping[str, Any]]) -> str:
    output_text = _get_response_value(response, "output_text")
    if output_text:
        return str(output_text)

    output_items_text = _output_text_from_output_items(_get_response_value(response, "output"))
    if output_items_text:
        return output_items_text

    output_parsed = _get_response_value(response, "output_parsed")
    if output_parsed is not None:
        try:
            return json.dumps(_coerce_payload(output_parsed), ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(output_parsed)

    if parsed_payload is not None:
        try:
            return json.dumps(parsed_payload, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(parsed_payload)

    return ""


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _requirements_bucket_counts(job_intelligence: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    requirements = _requirements_mapping(job_intelligence)
    return {
        "must_have": _list_count(requirements.get("must_have")),
        "should_have": _list_count(requirements.get("should_have")),
        "nice_to_have": _list_count(requirements.get("nice_to_have")),
        "credentials": _list_count(requirements.get("credentials")),
        "blockers": _list_count(requirements.get("blockers")),
        "soft_competencies": _list_count(requirements.get("soft_competencies")),
    }


def _flat_output_bucket_counts(job_intelligence: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    requirements = _requirements_mapping(job_intelligence)
    credentials = [item for item in requirements.get("credentials", []) if isinstance(item, Mapping)]
    return {
        "must_have": _list_count(requirements.get("must_have")),
        "should_have": _list_count(requirements.get("should_have")),
        "nice_to_have": _list_count(requirements.get("nice_to_have")),
        "blockers": _list_count(requirements.get("blockers")),
        "credentials_required": sum(1 for item in credentials if str(item.get("importance", "")) == "must_have"),
        "credentials_preferred": sum(1 for item in credentials if str(item.get("importance", "")) != "must_have"),
    }


def _requirement_item_summaries(job_intelligence: Optional[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    requirements = _requirements_mapping(job_intelligence)
    summaries: list[Dict[str, Any]] = []
    for bucket in ("must_have", "should_have", "nice_to_have", "credentials", "soft_competencies"):
        items = requirements.get(bucket, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                summaries.append(
                    {
                        "bucket": bucket,
                        "text": _sanitize_text(str(item), 160),
                        "source_text": "",
                        "importance": "",
                        "explicit": None,
                        "hard_filter_candidate": None,
                        "hard_filter_approved": None,
                    }
                )
                continue
            summaries.append(
                {
                    "bucket": bucket,
                    "text": _sanitize_text(str(item.get("text", "")), 160),
                    "source_text": _sanitize_text(str(item.get("source_text", "")), 120),
                    "importance": _sanitize_text(str(item.get("importance", "")), 40),
                    "explicit": item.get("explicit") if isinstance(item.get("explicit"), bool) else None,
                    "hard_filter_candidate": item.get("hard_filter_candidate")
                    if isinstance(item.get("hard_filter_candidate"), bool)
                    else None,
                    "hard_filter_approved": item.get("hard_filter_approved")
                    if isinstance(item.get("hard_filter_approved"), bool)
                    else None,
                }
            )
    blockers = requirements.get("blockers", [])
    if isinstance(blockers, list):
        for blocker in blockers:
            summaries.append(
                {
                    "bucket": "blockers",
                    "text": _sanitize_text(str(blocker), 160),
                    "source_text": "",
                    "importance": "blocker",
                    "explicit": None,
                    "hard_filter_candidate": None,
                    "hard_filter_approved": None,
                }
            )
    return summaries[:80]


def _requirements_mapping(job_intelligence: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not isinstance(job_intelligence, Mapping):
        return {}
    requirements = job_intelligence.get("requirements", {})
    return requirements if isinstance(requirements, Mapping) else {}


def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _sanitize_text(value: str, limit: int = 800) -> str:
    if not value:
        return ""
    redacted = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted-api-key]", value)
    redacted = re.sub(r"sk-proj-[A-Za-z0-9_-]+", "[redacted-api-key]", redacted)
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [redacted]", redacted, flags=re.I)
    redacted = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[redacted-email]", redacted)
    redacted = redacted.replace("\n", " ")
    return redacted[:limit]


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
