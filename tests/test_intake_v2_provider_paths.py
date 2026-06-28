from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_MODULE = "app.intake_v2.provider"
SOURCE_TEXT = "Empresa busca mecanico de coches con experiencia demostrable."
MODEL = "gpt-test-v2"
API_KEY = "sk-test-secret-provider-key"
AUTH_HEADER = "Bearer secret-authorization-token"
SENSITIVE_SENTINELS = (
    "SOURCE_TEXT_SENTINEL",
    "PROMPT_BODY_SENTINEL",
    "RAW_OUTPUT_SENTINEL",
    "SECRET_TOKEN_SENTINEL",
)
APPROVED_PROVIDER_LOG_KEYS = {
    "event",
    "model",
    "provider_calls",
    "semantic_attempts",
    "semantic_repairs",
    "transient_retries",
    "timeout_seconds",
    "exception_class",
    "status_code",
    "provider_request_id",
    "provider_response_id",
    "error_category",
    "error_code",
    "parse_path",
    "validation_paths",
    "output_hash",
    "output_length",
}
FORBIDDEN_PROVIDER_LOG_KEYS = {
    "api_shape",
    "source_chars",
    "retryable",
    "model_present",
    "attempt_kind",
    "provider_call_count",
    "semantic_attempt_count",
    "repair_count",
    "transient_retry_count",
    "raw_output_sha256",
    "raw_output_length",
    "safe_error_category",
    "http_status",
}

FORBIDDEN_IMPORTS = {
    "app.normalization.requirement_importance",
    "app.normalization.role_title",
    "app.normalization.canonical_job_intelligence",
    "app.normalization.precision_questions",
    "app.mappers.recruiter_display_plan",
    "app.mappers.job_intelligence_to_flat",
    "app.extractors.deterministic",
    "app.extractors.router",
    "app.main",
}


class FakeHTTPError(Exception):
    def __init__(self, status_code: int, message: str = "provider error", body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = f"req_status_{status_code}"
        self.body = body


class SensitiveProviderError(Exception):
    status: int
    status_code: int
    request_id = "req_sensitive_safe"
    response_id = "resp_sensitive_safe"
    message = "SOURCE_TEXT_SENTINEL PROMPT_BODY_SENTINEL"
    body = "RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL"
    headers = {"authorization": "Bearer SECRET_TOKEN_SENTINEL"}

    def __init__(self, status_code: int) -> None:
        self.status = status_code
        self.status_code = status_code
        self.response = SimpleNamespace(
            text="RAW_OUTPUT_SENTINEL PROMPT_BODY_SENTINEL",
            headers={"authorization": "Bearer SECRET_TOKEN_SENTINEL"},
            json=lambda: {"leak": "SOURCE_TEXT_SENTINEL"},
        )
        super().__init__("SOURCE_TEXT_SENTINEL PROMPT_BODY_SENTINEL RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL")

    def __str__(self) -> str:
        return "SOURCE_TEXT_SENTINEL PROMPT_BODY_SENTINEL RAW_OUTPUT_SENTINEL SECRET_TOKEN_SENTINEL"

    def __repr__(self) -> str:
        return "SensitiveProviderError(SECRET_TOKEN_SENTINEL RAW_OUTPUT_SENTINEL)"


class FakeResponses:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.outcomes:
            raise AssertionError("unexpected extra provider call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.responses = FakeResponses(outcomes)
        self.timeout_options: list[float] = []

    def with_options(self, *, timeout: float) -> "FakeClient":
        self.timeout_options.append(timeout)
        return self

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.responses.calls


def provider_module() -> Any:
    try:
        return importlib.import_module(PROVIDER_MODULE)
    except ModuleNotFoundError as error:
        pytest.fail(f"Gate 2 provider module is not implemented: expected import {PROVIDER_MODULE} ({error})")


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for the Gate 2 provider contract")
    return getattr(module, name)


def contract_module() -> Any:
    return importlib.import_module("app.intake_v2.contract")


def valid_payload() -> dict[str, Any]:
    contract = contract_module()
    return {
        "schema_version": contract.SCHEMA_VERSION_V2,
        "job_profile": {
            "role_title": "Mecanico de coches",
            "role_family": "mantenimiento automotor",
            "professional_grade": None,
            "seniority": None,
            "summary": "Busqueda de mecanico de coches.",
            "industries": ["automotriz"],
        },
        "location_and_modality": {
            "raw_location": None,
            "normalized_location": None,
            "country_code": "UY",
            "city": None,
            "region": None,
            "work_modality": None,
            "remote_allowed": None,
            "hybrid_allowed": None,
            "onsite_required": None,
        },
        "criteria": [
            {
                "local_ref": "crit_1",
                "criterion_kind": "experience",
                "text": "Experiencia demostrable como mecanico",
                "source_evidence": "experiencia demostrable",
                "importance": "must_have",
                "explicit": True,
                "precision_status": "needs_clarification",
                "missing_dimensions": ["duration", "evidence"],
                "clarification_question_ref": "q_1",
            }
        ],
        "company_questions": [
            {
                "local_ref": "q_1",
                "question": "Cuantos anos o que evidencia concreta valida la experiencia demostrable?",
                "audience": "hiring_company",
                "category": "search_precision",
                "criterion_refs": ["crit_1"],
                "missing_dimensions": ["duration", "evidence"],
                "blocking_level": "blocking",
            }
        ],
        "candidate_screening_questions": [
            {
                "local_ref": "cq_1",
                "question": "Podes aportar evidencia laboral de experiencia como mecanico?",
                "audience": "candidate",
                "category": "screening",
                "criterion_refs": ["crit_1"],
                "missing_dimensions": [],
                "blocking_level": "advisory",
            }
        ],
        "search_strategy": {
            "target_titles": ["Mecanico de coches"],
            "search_terms": ["mecanico de coches"],
            "semantic_terms": ["reparaciones automotrices"],
            "negative_terms": [],
        },
        "search_readiness": {
            "status": "insufficient_for_precise_search",
            "proceed_allowed": True,
            "recommended_action": "ask_company",
            "recruiter_decision_required": True,
            "continued_with_missing_information": True,
        },
        "quality_control": {
            "warnings": [],
            "confidence": 0.74,
            "contains_candidate_data": False,
            "contains_candidate_pii": False,
        },
    }


def invalid_schema_payload() -> dict[str, Any]:
    payload = valid_payload()
    payload["criteria"][0]["importance"] = "preferred"
    return payload


def broken_ref_payload() -> dict[str, Any]:
    payload = valid_payload()
    payload["criteria"][0]["clarification_question_ref"] = "missing_question"
    return payload


def precision_inconsistent_payload() -> dict[str, Any]:
    payload = valid_payload()
    payload["criteria"][0]["precision_status"] = "needs_clarification"
    payload["criteria"][0]["missing_dimensions"] = []
    payload["criteria"][0]["clarification_question_ref"] = None
    return payload


def response(**values: Any) -> SimpleNamespace:
    defaults = {"id": "resp_1", "request_id": "req_1"}
    defaults.update(values)
    return SimpleNamespace(**defaults)


def output_text_response(payload: Mapping[str, Any], *, response_id: str = "resp_text") -> SimpleNamespace:
    return response(id=response_id, request_id=f"req_{response_id}", output_text=json.dumps(payload))


def output_array_response(payload: Mapping[str, Any]) -> SimpleNamespace:
    return response(
        id="resp_output_array",
        request_id="req_output_array",
        output=[{"content": [{"type": "output_text", "text": json.dumps(payload)}]}],
    )


def make_request(*, source_language: str = "Spanish", source_text: str = SOURCE_TEXT) -> Any:
    Request = required_attr(provider_module(), "ProviderRequestV2")
    return Request(
        source_text=source_text,
        source_language=source_language,
        locale="es-UY",
        country_context="UY",
        candidate_market="UY",
        employer_market="UY",
        model=MODEL,
        timeout_seconds=90.0,
    )


def make_provider(outcomes: list[Any], *, api_key: str = API_KEY) -> tuple[Any, FakeClient]:
    module = provider_module()
    Provider = required_attr(module, "OpenAIProviderV2")
    client = FakeClient(outcomes)
    return Provider(api_key=api_key, model=MODEL, client=client), client


def value_at(result: Any, name: str) -> Any:
    if isinstance(result, Mapping):
        return result.get(name)
    return getattr(result, name, None)


def result_metadata(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    if hasattr(result, "__dict__"):
        return dict(vars(result))
    return {}


def assert_counters(
    result: Any,
    *,
    provider_calls: int,
    semantic_attempts: int,
    repairs: int,
    transient_retries: int,
) -> None:
    assert value_at(result, "provider_call_count") == provider_calls
    assert value_at(result, "semantic_attempt_count") == semantic_attempts
    assert value_at(result, "repair_count") == repairs
    assert value_at(result, "transient_retry_count") == transient_retries


def extract_schema_from_call(call: Mapping[str, Any]) -> dict[str, Any]:
    text = call.get("text")
    assert isinstance(text, Mapping)
    text_format = text.get("format")
    assert isinstance(text_format, Mapping)
    assert text_format.get("type") == "json_schema"
    assert text_format.get("name") == "cvbrain_job_intelligence_v2"
    assert text_format.get("strict") is True
    schema = text_format.get("schema")
    assert isinstance(schema, dict)
    return schema


def assert_provider_error(name: str, func: Any) -> Any:
    error_type = required_attr(provider_module(), name)
    with pytest.raises(error_type) as exc_info:
        func()
    return exc_info.value


def assert_sensitive_sentinels_absent(value: str) -> None:
    for sentinel in SENSITIVE_SENTINELS:
        assert sentinel not in value


def provider_log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    prefix = "cvbrain_intake_v2_provider "
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith(prefix):
            continue
        payload = json.loads(message[len(prefix) :])
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def assert_provider_log_keys_are_allowlisted(caplog: pytest.LogCaptureFixture) -> None:
    payloads = provider_log_payloads(caplog)
    assert payloads
    observed_keys: set[str] = set()
    for payload in payloads:
        observed_keys.update(payload)
        assert set(payload) <= APPROVED_PROVIDER_LOG_KEYS
    assert observed_keys.isdisjoint(FORBIDDEN_PROVIDER_LOG_KEYS)


def assert_v2_error_has_no_original_exception(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is True
    for value in vars(error).values():
        assert not isinstance(value, BaseException)


def test_provider_request_requires_source_language():
    Request = required_attr(provider_module(), "ProviderRequestV2")

    with pytest.raises((TypeError, ValueError)):
        Request(
            source_text=SOURCE_TEXT,
            locale="es-UY",
            country_context="UY",
            candidate_market="UY",
            employer_market="UY",
            model=MODEL,
            timeout_seconds=90.0,
        )


def test_extraction_prompt_receives_explicit_source_language(monkeypatch: pytest.MonkeyPatch):
    seen_languages: list[str] = []

    def fake_prompt(source_language: str) -> str:
        seen_languages.append(source_language)
        return "STRICT V2 PROMPT"

    prompts = importlib.import_module("app.intake_v2.prompts")
    monkeypatch.setattr(prompts, "build_extraction_prompt", fake_prompt)
    module = provider_module()
    if hasattr(module, "build_extraction_prompt"):
        monkeypatch.setattr(module, "build_extraction_prompt", fake_prompt)

    provider, _client = make_provider([response(output_parsed=valid_payload())])
    provider.extract(make_request(source_language="Spanish"))

    assert seen_languages == ["Spanish"]


def test_provider_never_infers_source_language_from_locale_or_text(monkeypatch: pytest.MonkeyPatch):
    seen_languages: list[str] = []

    def fake_prompt(source_language: str) -> str:
        seen_languages.append(source_language)
        return "STRICT V2 PROMPT"

    prompts = importlib.import_module("app.intake_v2.prompts")
    monkeypatch.setattr(prompts, "build_extraction_prompt", fake_prompt)
    module = provider_module()
    if hasattr(module, "build_extraction_prompt"):
        monkeypatch.setattr(module, "build_extraction_prompt", fake_prompt)

    provider, _client = make_provider([response(output_parsed=valid_payload())])
    provider.extract(make_request(source_language="Spanish", source_text="Company requires an auto mechanic."))

    assert seen_languages == ["Spanish"]


def test_valid_output_parsed_one_call_no_repair():
    provider, client = make_provider([response(output_parsed=valid_payload())])

    result = provider.extract(make_request())

    assert len(client.calls) == 1
    assert value_at(result, "parse_path") == "output_parsed"
    assert value_at(result, "validated_draft")["schema_version"] == "cvbrain_job_intelligence_v2"
    assert_counters(result, provider_calls=1, semantic_attempts=1, repairs=0, transient_retries=0)


def test_valid_output_text_json_parse_path():
    provider, client = make_provider([output_text_response(valid_payload())])

    result = provider.extract(make_request())

    assert len(client.calls) == 1
    assert value_at(result, "parse_path") == "output_text"
    assert_counters(result, provider_calls=1, semantic_attempts=1, repairs=0, transient_retries=0)


def test_valid_output_array_content_output_text_parse_path():
    provider, client = make_provider([output_array_response(valid_payload())])

    result = provider.extract(make_request())

    assert len(client.calls) == 1
    assert value_at(result, "parse_path") == "output_array.output_text"
    assert_counters(result, provider_calls=1, semantic_attempts=1, repairs=0, transient_retries=0)


def test_success_result_excludes_raw_output_and_raw_payload():
    provider, _client = make_provider([output_text_response(valid_payload())])

    result = provider.extract(make_request())
    metadata = result_metadata(result)

    assert "raw_output_text" not in metadata
    assert "raw_payload" not in metadata
    assert value_at(result, "raw_output_text") is None
    assert value_at(result, "raw_payload") is None


def test_empty_completed_response_repairs_once_without_deterministic_fallback():
    provider, client = make_provider([response(id="empty", request_id="req_empty"), response(output_parsed=valid_payload())])

    result = provider.extract(make_request())

    assert len(client.calls) == 2
    assert value_at(result, "validated_draft")["schema_version"] == "cvbrain_job_intelligence_v2"
    assert value_at(result, "fallback_used") in (None, False)
    assert_counters(result, provider_calls=2, semantic_attempts=2, repairs=1, transient_retries=0)


def test_schema_invalid_then_valid_repair_uses_same_strict_v2_schema():
    provider, client = make_provider([response(output_parsed=invalid_schema_payload()), response(output_parsed=valid_payload())])

    result = provider.extract(make_request())

    assert len(client.calls) == 2
    assert_counters(result, provider_calls=2, semantic_attempts=2, repairs=1, transient_retries=0)
    expected_schema = contract_module().job_intelligence_v2_response_schema()
    assert extract_schema_from_call(client.calls[0]) == expected_schema
    assert extract_schema_from_call(client.calls[1]) == expected_schema


def test_invalid_then_invalid_repair_raises_repair_exhausted_without_third_call():
    provider, client = make_provider(
        [response(output_parsed=invalid_schema_payload()), response(output_parsed=invalid_schema_payload())]
    )

    assert_provider_error("V2RepairExhaustedError", lambda: provider.extract(make_request()))

    assert len(client.calls) == 2


def test_broken_draft_local_refs_trigger_one_repair():
    provider, client = make_provider([response(output_parsed=broken_ref_payload()), response(output_parsed=valid_payload())])

    result = provider.extract(make_request())

    assert len(client.calls) == 2
    assert_counters(result, provider_calls=2, semantic_attempts=2, repairs=1, transient_retries=0)


def test_precision_contract_inconsistency_triggers_one_repair():
    provider, client = make_provider(
        [response(output_parsed=precision_inconsistent_payload()), response(output_parsed=valid_payload())]
    )

    result = provider.extract(make_request())

    assert len(client.calls) == 2
    assert_counters(result, provider_calls=2, semantic_attempts=2, repairs=1, transient_retries=0)


def test_retryable_extraction_timeout_retries_same_operation_then_success():
    provider, client = make_provider([TimeoutError("read timeout"), response(output_parsed=valid_payload())])

    result = provider.extract(make_request())

    assert len(client.calls) == 2
    assert_counters(result, provider_calls=2, semantic_attempts=1, repairs=0, transient_retries=1)


def test_timeout_retry_exhaustion_raises_provider_timeout_without_repair():
    provider, client = make_provider([TimeoutError("read timeout"), TimeoutError("read timeout")])

    assert_provider_error("V2ProviderTimeoutError", lambda: provider.extract(make_request()))

    assert len(client.calls) == 2


def test_retryable_http_statuses_retry_same_operation():
    for status in (429, 500, 502, 503, 504):
        provider, client = make_provider([FakeHTTPError(status), response(output_parsed=valid_payload())])

        result = provider.extract(make_request())

        assert len(client.calls) == 2
        assert_counters(result, provider_calls=2, semantic_attempts=1, repairs=0, transient_retries=1)


def test_non_retryable_provider_errors_do_not_retry_or_repair():
    for outcome in (
        FakeHTTPError(400, "bad request"),
        FakeHTTPError(401, "auth failed"),
        response(refusal="refused for policy"),
    ):
        provider, client = make_provider([outcome])

        assert_provider_error("V2ProviderTerminalError", lambda: provider.extract(make_request()))

        assert len(client.calls) == 1

    provider, _client = make_provider([], api_key="")
    assert_provider_error("V2ConfigurationError", lambda: provider.extract(make_request()))


def test_api_key_never_appears_in_logs_result_or_metadata(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")
    provider, _client = make_provider([response(output_parsed=valid_payload())])

    result = provider.extract(make_request())
    serialized_result = json.dumps(result_metadata(result), sort_keys=True, default=str)

    assert API_KEY not in caplog.text
    assert API_KEY not in repr(result)
    assert API_KEY not in serialized_result


def test_authorization_headers_never_appear_in_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")
    error = FakeHTTPError(401, "auth failed", body=f"Authorization: {AUTH_HEADER}")
    provider, _client = make_provider([error])

    assert_provider_error("V2ProviderTerminalError", lambda: provider.extract(make_request()))

    assert AUTH_HEADER not in caplog.text
    assert "secret-authorization-token" not in caplog.text


def test_provider_terminal_logging_uses_metadata_only_for_sensitive_exceptions(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")
    provider, _client = make_provider([SensitiveProviderError(401)])

    error = assert_provider_error("V2ProviderTerminalError", lambda: provider.extract(make_request()))

    assert_sensitive_sentinels_absent(caplog.text)
    assert_sensitive_sentinels_absent(repr(error))
    assert_v2_error_has_no_original_exception(error)
    assert_provider_log_keys_are_allowlisted(caplog)
    assert "SensitiveProviderError" in caplog.text
    assert "terminal_http_error" in caplog.text


def test_provider_retry_logging_uses_metadata_only_for_sensitive_exceptions(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")
    provider, client = make_provider([SensitiveProviderError(500), response(output_parsed=valid_payload())])

    result = provider.extract(make_request())

    assert len(client.calls) == 2
    assert_counters(result, provider_calls=2, semantic_attempts=1, repairs=0, transient_retries=1)
    assert_sensitive_sentinels_absent(caplog.text)
    assert_provider_log_keys_are_allowlisted(caplog)
    assert "SensitiveProviderError" in caplog.text
    assert "server_error" in caplog.text


def test_provider_logs_use_only_approved_metadata_keys(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")
    raw_output = json.dumps(invalid_schema_payload(), sort_keys=True)
    provider, _client = make_provider(
        [SensitiveProviderError(500), response(output_text=raw_output), response(output_parsed=valid_payload())]
    )

    provider.extract(make_request())

    assert_provider_log_keys_are_allowlisted(caplog)
    assert_sensitive_sentinels_absent(caplog.text)


def test_provider_configuration_import_error_suppresses_original_exception(monkeypatch: pytest.MonkeyPatch):
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            raise ImportError("SECRET_TOKEN_SENTINEL")
        return real_import(name, *args, **kwargs)

    module = provider_module()
    Provider = required_attr(module, "OpenAIProviderV2")
    provider = Provider(api_key=API_KEY, model=MODEL, client=None)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    error = assert_provider_error("V2ConfigurationError", lambda: provider.extract(make_request()))

    assert_v2_error_has_no_original_exception(error)
    assert_sensitive_sentinels_absent(repr(error))


def test_response_parse_error_suppresses_raw_output_exception_context():
    provider, _client = make_provider([])
    raw_output = '{"leak": "RAW_OUTPUT_SENTINEL"'

    error = assert_provider_error("V2ResponseParseError", lambda: provider._parse_response(response(output_text=raw_output)))

    assert_v2_error_has_no_original_exception(error)
    assert_sensitive_sentinels_absent(repr(error))


def test_repair_exhausted_suppresses_validation_exception_context():
    provider, _client = make_provider([response(output_parsed=invalid_schema_payload()), response(output_parsed=invalid_schema_payload())])

    error = assert_provider_error("V2RepairExhaustedError", lambda: provider.extract(make_request()))

    assert_v2_error_has_no_original_exception(error)


def test_source_text_never_appears_in_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")
    source_marker = "UNIQUE_SOURCE_MARKER_DO_NOT_LOG"
    provider, _client = make_provider([response(output_parsed=valid_payload())])

    provider.extract(make_request(source_text=f"{SOURCE_TEXT} {source_marker}"))

    assert source_marker not in caplog.text
    assert SOURCE_TEXT not in caplog.text


def test_raw_provider_output_never_appears_in_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")
    raw_marker = "UNIQUE_RAW_OUTPUT_MARKER_DO_NOT_LOG"
    raw_output = json.dumps({"not_schema": raw_marker})
    provider, _client = make_provider([response(output_text=raw_output), response(output_parsed=valid_payload())])

    provider.extract(make_request())

    assert raw_marker not in caplog.text
    assert raw_output not in caplog.text


def test_raw_output_hash_and_validation_paths_may_be_logged(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")
    raw_output = json.dumps(invalid_schema_payload(), sort_keys=True)
    expected_hash = hashlib.sha256(raw_output.encode("utf-8")).hexdigest()
    provider, _client = make_provider([response(output_text=raw_output), response(output_parsed=valid_payload())])

    provider.extract(make_request())

    assert expected_hash in caplog.text
    assert "criteria" in caplog.text


def test_provider_module_imports_no_forbidden_v1_modules():
    for relative in ("app/intake_v2/provider.py", "app/intake_v2/shape_recovery.py"):
        path = ROOT / relative
        if not path.exists():
            pytest.fail(f"Gate 2 module is not implemented: expected {relative}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        offenders = [
            imported
            for imported in imports
            if any(imported == forbidden or imported.startswith(forbidden + ".") for forbidden in FORBIDDEN_IMPORTS)
        ]
        assert offenders == []


def test_no_deterministic_fallback_object_can_be_constructed():
    provider, client = make_provider(
        [response(output_parsed=invalid_schema_payload()), response(output_parsed=invalid_schema_payload())]
    )

    error = assert_provider_error("V2RepairExhaustedError", lambda: provider.extract(make_request()))

    assert len(client.calls) == 2
    assert "deterministic" not in repr(error).lower()
    assert "local_schema_stub_recovery" not in repr(error)


def test_extraction_and_repair_use_same_strict_v2_schema():
    provider, client = make_provider([response(output_parsed=invalid_schema_payload()), response(output_parsed=valid_payload())])

    provider.extract(make_request())

    schemas = [extract_schema_from_call(call) for call in client.calls]
    assert len(schemas) == 2
    assert schemas[0] == schemas[1] == contract_module().job_intelligence_v2_response_schema()
