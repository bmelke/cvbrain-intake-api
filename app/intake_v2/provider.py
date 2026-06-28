"""Neutral OpenAI provider boundary for CVBrain Intake v2."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Dict, Literal, Optional

from pydantic import ValidationError

from app.intake_v2.contract import JobIntelligenceDraftV2, job_intelligence_v2_response_schema
from app.intake_v2.errors import (
    IntakeV2Error,
    V2ConfigurationError,
    V2DraftContractError,
    V2DraftSchemaError,
    V2ProviderTerminalError,
    V2ProviderTimeoutError,
    V2ProviderTransientError,
    V2RepairExhaustedError,
    V2ResponseParseError,
    V2ShapeRecoveryError,
)
from app.intake_v2.prompts import build_extraction_prompt, build_repair_prompt
from app.intake_v2.shape_recovery import recover_provider_shape_v2


AttemptKindV2 = Literal["extraction", "repair"]
ParsePathV2 = Literal["output_parsed", "output_text", "output_array.output_text"]

DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_MEDIUM_TIMEOUT_SECONDS = 150.0
DEFAULT_LONG_TIMEOUT_SECONDS = 240.0
DEFAULT_MAX_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_TRANSIENT_RETRIES = 1
LOGGER = logging.getLogger("cvbrain.intake_v2.provider")


@dataclass(frozen=True)
class ProviderRequestV2:
    source_text: str
    source_language: str
    locale: str
    country_context: Optional[str]
    candidate_market: Optional[str]
    employer_market: Optional[str]
    model: str
    timeout_seconds: float

    def __post_init__(self) -> None:
        if not str(self.source_language or "").strip():
            raise ValueError("source_language is required")


@dataclass(frozen=True)
class ProviderAttemptMetadataV2:
    attempt_kind: AttemptKindV2
    provider_call_index: int
    semantic_attempt_index: int
    timeout_seconds: float
    elapsed_seconds: float
    transient_retry_count: int
    parse_path: Optional[str] = None
    provider_response_id: Optional[str] = None
    provider_request_id: Optional[str] = None


@dataclass(frozen=True)
class ProviderValidationFailureV2:
    failure_kind: str
    validation_paths: tuple[str, ...]
    expected: str
    received: str
    message: str
    raw_output_sha256: str
    parse_path: str
    repairable: bool


@dataclass(frozen=True)
class ProviderResultV2:
    validated_draft: Dict[str, Any]
    provider_response_id: Optional[str]
    provider_request_id: Optional[str]
    model: str
    attempt_kind: AttemptKindV2
    provider_call_count: int
    semantic_attempt_count: int
    repair_count: int
    transient_retry_count: int
    elapsed_seconds: float
    parse_path: str


@dataclass
class _ParseResult:
    payload: Dict[str, Any]
    parse_path: str
    provider_response_id: Optional[str]
    provider_request_id: Optional[str]
    raw_output_text: str


class OpenAIProviderV2:
    """OpenAI Responses provider that returns only validated V2 drafts."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        client: Optional[Any] = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        transient_retries: int = DEFAULT_TRANSIENT_RETRIES,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        self.client = client
        self.max_output_tokens = max_output_tokens
        self.transient_retries = transient_retries
        self.provider_call_count = 0
        self.semantic_attempt_count = 0
        self.repair_count = 0
        self.transient_retry_count = 0

    def extract(self, request: ProviderRequestV2) -> ProviderResultV2:
        if not self.api_key:
            self._log_event("configuration_error", error_code="missing_api_key")
            raise V2ConfigurationError("OPENAI_API_KEY is required for Intake v2 provider.")
        if not self.model:
            self._log_event("configuration_error", error_code="missing_model")
            raise V2ConfigurationError("model is required for Intake v2 provider.")

        self._reset_counters()
        started = time.monotonic()
        extraction_failure: Optional[BaseException] = None
        extraction_parse: Optional[_ParseResult] = None

        try:
            extraction_parse = self._attempt_provider_request(request, "extraction")
            draft = self._recover_and_validate(extraction_parse.payload)
            return self._result(request, extraction_parse, draft, "extraction", started)
        except (V2ResponseParseError, V2ShapeRecoveryError, V2DraftSchemaError, V2DraftContractError) as error:
            extraction_failure = error
            self._log_validation_failure(error, extraction_parse, attempt_kind="extraction")

        repair_parse = self._attempt_repair(request, extraction_parse, extraction_failure)
        repair_failed = False
        try:
            draft = self._recover_and_validate(repair_parse.payload)
        except (V2ResponseParseError, V2ShapeRecoveryError, V2DraftSchemaError, V2DraftContractError) as repair_error:
            self._log_validation_failure(repair_error, repair_parse, attempt_kind="repair")
            repair_failed = True
        if repair_failed:
            raise V2RepairExhaustedError("Intake v2 repair did not produce a valid draft.") from None

        return self._result(request, repair_parse, draft, "repair", started)

    def _attempt_repair(
        self,
        request: ProviderRequestV2,
        failed_parse: Optional[_ParseResult],
        failure: BaseException,
    ) -> _ParseResult:
        self.repair_count += 1
        validation_paths = _validation_paths_for_error(failure)
        return self._attempt_provider_request(
            request,
            "repair",
            invalid_output=failed_parse.raw_output_text if failed_parse is not None else "",
            failure=failure,
            validation_paths=validation_paths,
        )

    def _attempt_provider_request(
        self,
        request: ProviderRequestV2,
        attempt_kind: AttemptKindV2,
        *,
        invalid_output: str = "",
        failure: Optional[BaseException] = None,
        validation_paths: tuple[str, ...] = (),
    ) -> _ParseResult:
        client = self._client_for_request(request)
        input_messages = self._input_messages(request, attempt_kind, invalid_output, failure, validation_paths)
        text_format = self._text_format(attempt_kind)
        self.semantic_attempt_count += 1
        response = self._call_provider_with_retry(
            request,
            attempt_kind,
            lambda: client.responses.create(
                model=request.model or self.model,
                input=input_messages,
                text={"format": text_format},
                max_output_tokens=self.max_output_tokens,
            ),
        )
        return self._parse_response(response)

    def _call_provider_with_retry(
        self,
        request: ProviderRequestV2,
        attempt_kind: AttemptKindV2,
        call: Callable[[], Any],
    ) -> Any:
        max_attempts = self.transient_retries + 1
        for attempt in range(1, max_attempts + 1):
            raised_error: Optional[BaseException] = None
            self.provider_call_count += 1
            try:
                return call()
            except IntakeV2Error:
                raise
            except Exception as error:
                retryable = _is_retryable_provider_error(error)
                if not retryable:
                    self._log_provider_error("provider_terminal_error", request, attempt_kind, error)
                    raised_error = V2ProviderTerminalError("Intake v2 provider request failed.")
                elif attempt >= max_attempts:
                    self._log_provider_error("provider_retry_exhausted", request, attempt_kind, error)
                    if _is_provider_timeout_error(error):
                        raised_error = V2ProviderTimeoutError("Intake v2 provider request timed out.")
                    else:
                        raised_error = V2ProviderTransientError("Intake v2 provider transient error exhausted retries.")
                if raised_error is None:
                    self.transient_retry_count += 1
                    self._log_provider_error("provider_retryable_error", request, attempt_kind, error)
            if raised_error is not None:
                raise raised_error from None
        raise V2ProviderTransientError("Intake v2 provider transient error exhausted retries.") from None

    def _input_messages(
        self,
        request: ProviderRequestV2,
        attempt_kind: AttemptKindV2,
        invalid_output: str,
        failure: Optional[BaseException],
        validation_paths: tuple[str, ...],
    ) -> list[dict[str, str]]:
        context = {
            "source_text": request.source_text,
            "source_language": request.source_language,
            "locale": request.locale,
            "country_context": request.country_context,
            "candidate_market": request.candidate_market,
            "employer_market": request.employer_market,
        }
        if attempt_kind == "extraction":
            return [
                {"role": "system", "content": build_extraction_prompt(request.source_language)},
                {
                    "role": "user",
                    "content": "Extract CVBrain Job Intelligence v2 JSON from this intake payload:\n"
                    + json.dumps(context, ensure_ascii=False, sort_keys=True),
                },
            ]
        repair_payload = {
            "original_intake_payload": context,
            "validation_paths": list(validation_paths),
            "failure_class": failure.__class__.__name__ if failure is not None else "",
            "invalid_output": invalid_output,
        }
        return [
            {"role": "system", "content": build_repair_prompt(request.source_language)},
            {
                "role": "user",
                "content": "Repair this invalid CVBrain Job Intelligence v2 response:\n"
                + json.dumps(repair_payload, ensure_ascii=False, sort_keys=True),
            },
        ]

    def _text_format(self, attempt_kind: AttemptKindV2) -> Dict[str, Any]:
        return {
            "type": "json_schema",
            "name": "cvbrain_job_intelligence_v2",
            "description": f"CVBrain Job Intelligence v2 {attempt_kind} output.",
            "schema": job_intelligence_v2_response_schema(),
            "strict": True,
        }

    def _client_for_request(self, request: ProviderRequestV2) -> Any:
        client = self._client()
        timeout = provider_timeout_for_source_chars(
            len(str(request.source_text or "")),
            configured_timeout_seconds=request.timeout_seconds,
        )
        with_options = getattr(client, "with_options", None)
        if callable(with_options):
            return with_options(timeout=timeout)
        return client

    def _client(self) -> Any:
        if self.client is None:
            try:
                from openai import OpenAI
            except ImportError:
                OpenAI = None
            if OpenAI is None:
                raise V2ConfigurationError("The OpenAI Python SDK is required for Intake v2 provider.") from None
            self.client = OpenAI(api_key=self.api_key)
        return self.client

    def _parse_response(self, response: Any) -> _ParseResult:
        provider_response_id = _string_or_none(_get_response_value(response, "id"))
        provider_request_id = _string_or_none(_get_response_value(response, "request_id"))

        parsed = _get_response_value(response, "output_parsed")
        if parsed is not None:
            payload = recover_provider_shape_v2(parsed)
            return _ParseResult(payload, "output_parsed", provider_response_id, provider_request_id, _raw_output(response, payload))

        output_text = _get_response_value(response, "output_text")
        if output_text:
            text = str(output_text)
            return _ParseResult(_loads_json(text), "output_text", provider_response_id, provider_request_id, text)

        output_array_text = _output_text_from_output_items(_get_response_value(response, "output"))
        if output_array_text:
            return _ParseResult(
                _loads_json(output_array_text),
                "output_array.output_text",
                provider_response_id,
                provider_request_id,
                output_array_text,
            )

        refusal = _get_response_value(response, "refusal")
        if refusal:
            raise V2ProviderTerminalError("Intake v2 provider refused the request.")

        raise V2ResponseParseError("Intake v2 provider response did not include structured JSON.")

    def _recover_and_validate(self, payload: Any) -> Dict[str, Any]:
        schema_validation_paths: Optional[tuple[str, ...]] = None
        try:
            recovered = recover_provider_shape_v2(payload)
            draft = JobIntelligenceDraftV2.model_validate(recovered).model_dump(mode="json")
        except V2ShapeRecoveryError:
            raise
        except ValidationError as error:
            schema_validation_paths = _validation_paths_from_pydantic(error)
        if schema_validation_paths is not None:
            schema_error = V2DraftSchemaError("Intake v2 draft failed strict schema.")
            schema_error.validation_paths = schema_validation_paths
            raise schema_error from None
        self._validate_draft_contract(draft)
        return draft

    def _validate_draft_contract(self, draft: Mapping[str, Any]) -> None:
        criteria = draft.get("criteria")
        company_questions = draft.get("company_questions")
        candidate_questions = draft.get("candidate_screening_questions")
        if not isinstance(criteria, list) or not isinstance(company_questions, list) or not isinstance(candidate_questions, list):
            raise V2DraftContractError("provider draft semantic collections must be lists")

        criterion_refs = _unique_refs(criteria, "criteria")
        company_question_refs = _unique_refs(company_questions, "company_questions")
        candidate_question_refs = _unique_refs(candidate_questions, "candidate_screening_questions")
        overlap = company_question_refs & candidate_question_refs
        if overlap:
            raise V2DraftContractError(f"duplicate question local_ref: {sorted(overlap)[0]}")

        for question in company_questions + candidate_questions:
            for criterion_ref in question.get("criterion_refs", []):
                if criterion_ref not in criterion_refs:
                    raise V2DraftContractError(f"question criterion_ref does not resolve: {criterion_ref}")

        for criterion in criteria:
            local_ref = str(criterion.get("local_ref", ""))
            precision_status = criterion.get("precision_status")
            missing_dimensions = criterion.get("missing_dimensions", [])
            clarification_ref = criterion.get("clarification_question_ref")
            if clarification_ref is not None and clarification_ref not in company_question_refs:
                raise V2DraftContractError(f"clarification_question_ref does not resolve to company question: {clarification_ref}")
            if precision_status == "needs_clarification":
                if not missing_dimensions:
                    raise V2DraftContractError(f"criteria.{local_ref}.missing_dimensions must not be empty")
                if not clarification_ref or clarification_ref not in company_question_refs:
                    raise V2DraftContractError(f"criteria.{local_ref}.clarification_question_ref must resolve to company question")
            if precision_status == "precise":
                if missing_dimensions:
                    raise V2DraftContractError(f"criteria.{local_ref}.missing_dimensions must be empty")
                if clarification_ref is not None:
                    raise V2DraftContractError(f"criteria.{local_ref}.clarification_question_ref must be null")

    def _result(
        self,
        request: ProviderRequestV2,
        parse: _ParseResult,
        draft: Dict[str, Any],
        attempt_kind: AttemptKindV2,
        started: float,
    ) -> ProviderResultV2:
        return ProviderResultV2(
            validated_draft=draft,
            provider_response_id=parse.provider_response_id,
            provider_request_id=parse.provider_request_id,
            model=request.model or self.model,
            attempt_kind=attempt_kind,
            provider_call_count=self.provider_call_count,
            semantic_attempt_count=self.semantic_attempt_count,
            repair_count=self.repair_count,
            transient_retry_count=self.transient_retry_count,
            elapsed_seconds=round(time.monotonic() - started, 6),
            parse_path=parse.parse_path,
        )

    def _reset_counters(self) -> None:
        self.provider_call_count = 0
        self.semantic_attempt_count = 0
        self.repair_count = 0
        self.transient_retry_count = 0

    def _log_event(self, event: str, **metadata: Any) -> None:
        safe_metadata = {
            "event": event,
        }
        if self.model:
            safe_metadata["model"] = self.model
        safe_metadata.update(_safe_log_metadata(metadata))
        LOGGER.info("cvbrain_intake_v2_provider %s", json.dumps(safe_metadata, sort_keys=True))

    def _log_validation_failure(
        self,
        error: BaseException,
        parse: Optional[_ParseResult],
        *,
        attempt_kind: AttemptKindV2,
    ) -> None:
        raw_output = parse.raw_output_text if parse is not None else ""
        self._log_event(
            "validation_failure",
            parse_path=parse.parse_path if parse is not None else "response_unavailable",
            validation_paths=list(_validation_paths_for_error(error)),
            output_hash=_sha256_hex(raw_output),
            output_length=len(raw_output),
            exception_class=error.__class__.__name__,
            provider_response_id=parse.provider_response_id if parse is not None else None,
            provider_request_id=parse.provider_request_id if parse is not None else None,
            provider_calls=self.provider_call_count,
            semantic_attempts=self.semantic_attempt_count,
            semantic_repairs=self.repair_count,
            transient_retries=self.transient_retry_count,
            error_code=f"{attempt_kind}_validation_failure",
        )

    def _log_provider_error(
        self,
        event: str,
        request: ProviderRequestV2,
        attempt_kind: AttemptKindV2,
        error: BaseException,
    ) -> None:
        self._log_event(
            event,
            timeout_seconds=request.timeout_seconds,
            transient_retries=self.transient_retry_count,
            provider_calls=self.provider_call_count,
            semantic_attempts=self.semantic_attempt_count,
            semantic_repairs=self.repair_count,
            error_code=f"{attempt_kind}_{event}",
            **_safe_exception_metadata(error),
        )


def provider_timeout_for_source_chars(
    source_chars: int,
    configured_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_timeout_seconds: float = DEFAULT_MAX_TIMEOUT_SECONDS,
) -> float:
    try:
        chars = max(0, int(source_chars))
    except (TypeError, ValueError):
        chars = 0
    try:
        configured = max(0.0, float(configured_timeout_seconds))
    except (TypeError, ValueError):
        configured = 0.0
    try:
        max_timeout = max(1.0, float(max_timeout_seconds))
    except (TypeError, ValueError):
        max_timeout = DEFAULT_MAX_TIMEOUT_SECONDS

    if chars <= 2000:
        dynamic = DEFAULT_TIMEOUT_SECONDS
    elif chars <= 6000:
        dynamic = DEFAULT_MEDIUM_TIMEOUT_SECONDS
    elif chars <= 12000:
        dynamic = DEFAULT_LONG_TIMEOUT_SECONDS
    else:
        dynamic = DEFAULT_MAX_TIMEOUT_SECONDS
    return min(max_timeout, max(dynamic, configured))


def _loads_json(value: str) -> Dict[str, Any]:
    invalid_json = False
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        invalid_json = True
        payload = None
    if invalid_json:
        raise V2ResponseParseError("Intake v2 provider response was not valid JSON.") from None
    if not isinstance(payload, dict):
        raise V2ResponseParseError("Intake v2 provider response JSON must be an object.")
    return payload


def _get_response_value(response: Any, key: str) -> Any:
    if isinstance(response, Mapping):
        return response.get(key)
    return getattr(response, key, None)


def _output_text_from_output_items(output: Any) -> str:
    texts: list[str] = []
    if not isinstance(output, list):
        return ""
    for item in output:
        content = _get_response_value(item, "content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if _get_response_value(content_item, "type") != "output_text":
                continue
            text = _get_response_value(content_item, "text")
            if text:
                texts.append(str(text))
    return "".join(texts).strip()


def _raw_output(response: Any, payload: Optional[Mapping[str, Any]] = None) -> str:
    output_text = _get_response_value(response, "output_text")
    if output_text:
        return str(output_text)
    output_array_text = _output_text_from_output_items(_get_response_value(response, "output"))
    if output_array_text:
        return output_array_text
    parsed = _get_response_value(response, "output_parsed")
    if parsed is not None:
        try:
            return json.dumps(recover_provider_shape_v2(parsed), ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            return str(parsed)
    if payload is not None:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return ""


def _unique_refs(items: list[Any], label: str) -> set[str]:
    refs: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise V2DraftContractError(f"{label} item must be an object")
        local_ref = str(item.get("local_ref", "")).strip()
        if not local_ref:
            raise V2DraftContractError(f"{label} item missing local_ref")
        if local_ref in refs:
            raise V2DraftContractError(f"duplicate {label} local_ref: {local_ref}")
        refs.add(local_ref)
    return refs


def _is_retryable_provider_error(error: BaseException) -> bool:
    if _is_provider_timeout_error(error):
        return True
    return _provider_status_code(error) in {429, 500, 502, 503, 504}


def _is_provider_timeout_error(error: BaseException) -> bool:
    if isinstance(error, TimeoutError):
        return True
    if _provider_status_code(error) in {408, 504}:
        return True
    return "timeout" in error.__class__.__name__.lower()


def _provider_status_code(error: BaseException) -> Optional[int]:
    for attr in ("status_code", "status"):
        value = getattr(error, attr, None)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _validation_paths_for_error(error: BaseException) -> tuple[str, ...]:
    validation_paths = getattr(error, "validation_paths", None)
    if isinstance(validation_paths, tuple) and all(isinstance(path, str) for path in validation_paths):
        return validation_paths
    path = getattr(error, "path", "")
    if isinstance(path, str) and path:
        return (str(path),)
    return ()


def _validation_paths_from_pydantic(error: ValidationError) -> tuple[str, ...]:
    paths: list[str] = []
    for item in error.errors():
        location = item.get("loc")
        if not isinstance(location, tuple):
            continue
        parts = [str(part) for part in location if not isinstance(part, int)]
        if parts:
            paths.append(".".join(parts))
    return tuple(dict.fromkeys(paths))


def _safe_exception_metadata(error: BaseException) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "exception_class": error.__class__.__name__,
        "error_category": _safe_error_category(error),
    }
    status = _provider_status_code(error)
    if status is not None:
        metadata["status_code"] = status
    request_id = _safe_provider_scalar(getattr(error, "request_id", None))
    if request_id:
        metadata["provider_request_id"] = request_id
    response_id = _safe_provider_scalar(getattr(error, "response_id", None))
    if response_id:
        metadata["provider_response_id"] = response_id
    return metadata


def _safe_error_category(error: BaseException) -> str:
    status = _provider_status_code(error)
    if _is_provider_timeout_error(error):
        return "timeout"
    if status == 429:
        return "rate_limited"
    if status is not None and 500 <= status <= 599:
        return "server_error"
    if status in {400, 401, 403, 404}:
        return "terminal_http_error"
    return "provider_error"


def _safe_provider_scalar(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value):
        return None
    return value


def _safe_log_metadata(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    allowed_string_keys = {
        "error_category",
        "error_code",
        "event",
        "exception_class",
        "model",
        "output_hash",
        "parse_path",
        "provider_request_id",
        "provider_response_id",
    }
    allowed_numeric_keys = {
        "output_length",
        "provider_calls",
        "semantic_attempts",
        "semantic_repairs",
        "status_code",
        "timeout_seconds",
        "transient_retries",
    }
    for key, value in metadata.items():
        if value is None:
            continue
        if key in {"validation_paths"} and isinstance(value, list):
            safe[key] = [item for item in value if isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", item)]
            continue
        if key in allowed_numeric_keys and isinstance(value, (int, float)) and not isinstance(value, bool):
            safe[key] = value
            continue
        if key in allowed_string_keys and isinstance(value, str):
            safe[key] = value[:160]
    return safe


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)
