import json
import logging
import sys
import unicodedata
from pathlib import Path

from fastapi.testclient import TestClient

from app.extractors import ExtractorRequest, ExtractorRouter
from app.extractors.openai_structured import OpenAIStructuredExtractor, job_intelligence_v1_response_schema
from app.main import app


ROOT = Path(__file__).resolve().parents[1]
MOCKED_OUTPUT_DIR = ROOT / "tests" / "fixtures" / "mocked_ai_outputs"

client = TestClient(app)


class FakeResponses:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def parse(self, **kwargs):
        raise AssertionError("OpenAIStructuredExtractor should use responses.create, not responses.parse")

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeOpenAIClient:
    def __init__(self, response=None, error=None):
        self.responses = FakeResponses(response=response, error=error)


def load_output(name):
    return json.loads((MOCKED_OUTPUT_DIR / name).read_text(encoding="utf-8"))


def request(text=None):
    return ExtractorRequest(
        source_text=text
        or "Account Manager Semi Senior con experiencia en dispositivos médicos. Mínima de 3 años. Deseable CRM. Ubicación Montevideo, híbrido.",
        locale="es-UY",
        country_context="UY",
        candidate_market="UY",
        employer_market="UY",
        source_filename="",
        source_mime_type="text/plain",
        recruiter_notes="",
    )


def analyze_payload(text):
    return {
        "source_text": text,
        "source_filename": "",
        "source_mime_type": "text/plain",
        "recruiter_notes": "",
        "locale": "es-UY",
        "country_context": "UY",
        "candidate_market": "UY",
        "employer_market": "UY",
    }


def fold(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else str(value)
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def requirement_item(text, importance):
    return {
        "text": text,
        "source_text": text,
        "importance": importance,
        "explicit": True,
        "hard_filter_candidate": importance == "must_have",
        "hard_filter_approved": False,
    }


def dirty_post_ai_payload():
    return {
        "schema_version": "cvbrain_job_intelligence_v1",
        "job_profile": {
            "job_title": "Coordinador Legal",
            "normalized_role_title": "Coordinador Legal",
            "role_family": "legal",
            "seniority": "",
            "summary": "Sanitized dirty AI payload for post-AI normalization guard.",
            "primary_industries": [],
            "work_modality": None,
        },
        "location_intelligence": {
            "raw": "",
            "normalized": "",
            "country_code": "UY",
            "remote_allowed": None,
            "hybrid_allowed": None,
            "onsite_required": None,
            "country_context_mismatch": False,
            "hard_filter_candidate": False,
            "hard_filter_approved": False,
            "warnings": [],
        },
        "requirements": {
            "must_have": [
                requirement_item("No avanzar perfiles puramente litigiosos sin experiencia corporativa", "must_have"),
                requirement_item("No excluyente", "must_have"),
                requirement_item("Manejo de Excel", "must_have"),
                requirement_item("Excel", "must_have"),
            ],
            "should_have": [
                requirement_item("Deseable", "preferred"),
            ],
            "nice_to_have": [
                requirement_item("Inglés jurídico será un plus", "nice_to_have"),
            ],
            "credentials": [
                requirement_item("No avanzar perfiles sin título habilitante", "must_have"),
                requirement_item("Título habilitante requerido", "must_have"),
            ],
            "blockers": [],
            "experience": {"minimum_years": None, "seniority": ""},
            "soft_competencies": [],
        },
        "search_strategy": {
            "target_titles": ["Coordinador Legal"],
            "search_terms": ["Coordinador Legal", "Excel"],
            "semantic_terms": [],
            "negative_terms": [],
        },
        "missing_information": [],
        "company_clarification_questions": [],
        "candidate_screening_questions": [],
        "search_readiness": {
            "status": "ready",
            "proceed_allowed": True,
            "recommended_action": "continue_anyway",
            "recruiter_decision_required": False,
            "continued_with_missing_information": False,
            "recruiter_override_reason": None,
            "decision_options": ["continue_anyway", "use_manual_search", "cancel"],
        },
        "quality_control": {
            "warnings": [],
            "confidence": 0.91,
            "contains_candidate_data": False,
            "contains_candidate_pii": False,
        },
    }


def test_deterministic_default_does_not_construct_openai_client(monkeypatch):
    monkeypatch.delenv("CVBRAIN_EXTRACTOR_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CVBRAIN_OPENAI_MODEL", raising=False)

    def fail_if_called(self):
        raise AssertionError("OpenAI client should not be constructed in deterministic default mode")

    monkeypatch.setattr(OpenAIStructuredExtractor, "_default_client", fail_if_called)

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(
            "Account Manager Semi Senior con experiencia en dispositivos médicos.\nMínima de 3 años.\nDeseable CRM.\nUbicación Montevideo, híbrido."
        ),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["engine"] == "deterministic"
    assert data["fallback_used"] is False
    assert data["role_title"] == "Account Manager Semi Senior"
    assert "job_intelligence" not in data


def test_auto_mode_without_key_routes_to_deterministic_without_network(monkeypatch):
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "auto")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_OPENAI_MODEL", "test-model-not-used")

    def fail_if_called(self):
        raise AssertionError("OpenAI client should not be constructed in auto mode without key")

    monkeypatch.setattr(OpenAIStructuredExtractor, "_default_client", fail_if_called)

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload("Sales Executive B2B. Mínima de 2 años. Ubicación Montevideo."),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["engine"] == "deterministic"
    assert data["fallback_used"] is False


def test_ai_mode_with_mocked_openai_success_derives_flat_contract(monkeypatch):
    fixture = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    fake_client = FakeOpenAIClient(response={"output_parsed": fixture})

    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "ai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("CVBRAIN_OPENAI_MODEL", "test-model-not-used")
    monkeypatch.setattr(OpenAIStructuredExtractor, "_default_client", lambda self: fake_client)

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(fixture["source"]["input_concept"]),
    )

    data = response.json()
    serialized = json.dumps(data, ensure_ascii=False)
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["engine"] == "openai"
    assert data["fallback_used"] is False
    assert data["ai_model"] == "test-model-not-used"
    assert data["role_title"] == "Account Manager Semi Senior"
    assert data["location"]["normalized"] == "Montevideo"
    assert data["location"]["hybrid_allowed"] is True
    assert data["experience"]["minimum_years"] == 3
    assert "CRM" in data["should_have"]
    assert "dispositivos médicos" in json.dumps(data["search_terms"], ensure_ascii=False)
    assert "job_intelligence" in data
    for blocked in ["Argentina", "Buenos Aires", "CABA", "GBA"]:
        assert blocked not in serialized
    call = fake_client.responses.calls[0]
    assert "response_format" not in call
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["name"] == "cvbrain_job_intelligence_v1"
    assert call["text"]["format"]["schema"]["additionalProperties"] is False
    assert call["input"][0]["role"] == "system"


def test_analyze_endpoint_ai_path_normalizes_dirty_parsed_payload_before_response(monkeypatch):
    fake_client = FakeOpenAIClient(response={"output_parsed": dirty_post_ai_payload()})

    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "ai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("CVBRAIN_OPENAI_MODEL", "test-model-not-used")
    monkeypatch.setenv("CVBRAIN_AI_FALLBACK_ENABLED", "false")
    monkeypatch.setattr(OpenAIStructuredExtractor, "_default_client", lambda self: fake_client)

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload("Sanitized legal coordinator request with mixed post-AI cleanup cases."),
    )

    data = response.json()
    requirements = data["job_intelligence"]["requirements"]
    positive_lists = (
        data["must_have"]
        + data["should_have"]
        + data["nice_to_have"]
        + data["credentials"]["required"]
        + data["credentials"]["preferred"]
    )
    positive = fold(positive_lists)
    blockers = fold(data["blockers"])

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["engine"] == "openai"
    assert data["fallback_used"] is False
    assert data["ai_model"] == "test-model-not-used"

    assert "no avanzar" not in positive
    assert "perfiles puramente litigiosos" in blockers
    assert "perfiles sin titulo habilitante" in blockers
    assert "no excluyente" not in positive
    assert '"deseable"' not in positive

    assert "ingles juridico" in fold(data["nice_to_have"])
    assert "titulo habilitante requerido" in fold(data["credentials"]["required"])
    assert fold(data["must_have"]).count("excel") == 1
    assert fold(data["must_have"] + data["should_have"] + data["nice_to_have"]).count("excel") == 1

    assert data["must_have"] == [item["text"] for item in requirements["must_have"]]
    assert data["should_have"] == [item["text"] for item in requirements["should_have"]]
    assert data["nice_to_have"] == [item["text"] for item in requirements["nice_to_have"]]
    assert data["blockers"] == requirements["blockers"]
    assert data["credentials"]["required"] == [
        item["text"] for item in requirements["credentials"] if item.get("importance") == "must_have"
    ]
    assert data["credentials"]["preferred"] == [
        item["text"] for item in requirements["credentials"] if item.get("importance") != "must_have"
    ]


def test_openai_schema_avoids_free_form_strict_schema_traps():
    schema = job_intelligence_v1_response_schema()

    def walk(value):
        if isinstance(value, dict):
            assert value.get("additionalProperties") is not True
            assert value.get("items") != {}
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)


def test_ai_invalid_json_falls_back_when_enabled():
    fake_client = FakeOpenAIClient(response={"output_text": "{not valid json"})
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=fake_client,
    )
    router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "OPENAI_API_KEY": "test-key-not-used",
            "CVBRAIN_OPENAI_MODEL": "test-model-not-used",
            "CVBRAIN_AI_FALLBACK_ENABLED": "true",
        },
        ai_extractor=extractor,
    )

    result = router.extract(request())

    assert result["ok"] is True
    assert result["engine"] == "deterministic"
    assert result["fallback_used"] is True
    assert "ai_fallback_used" in result["warnings"]
    assert "ai_invalid_json" in result["warnings"]


def test_ai_parses_responses_output_array_text():
    fixture = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(fixture, ensure_ascii=False),
                    }
                ],
            }
        ]
    }
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response=response),
    )

    result = extractor.extract(request())

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["role_title"] == "Account Manager Semi Senior"
    assert result["location"]["normalized"] == "Montevideo"


def test_ai_schema_failure_returns_clean_error_when_fallback_disabled():
    invalid_payload = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    invalid_payload.pop("requirements")
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": invalid_payload}),
    )
    router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "OPENAI_API_KEY": "test-key-not-used",
            "CVBRAIN_OPENAI_MODEL": "test-model-not-used",
            "CVBRAIN_AI_FALLBACK_ENABLED": "false",
        },
        ai_extractor=extractor,
    )

    result = router.extract(request())

    assert result["ok"] is False
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert "ai_schema_validation_failed" in result["warnings"]
    assert result["search_terms"] == []


def test_schema_failure_logs_safe_internal_diagnostics(caplog):
    source_text = (
        "La posicion apunta a soporte tecnico de primer nivel para usuarios internos y clientes corporativos. "
        "Rol: Tecnico de Soporte IT Junior. Excluyente experiencia de al menos 1 ano."
    )
    invalid_payload = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    invalid_payload["search_readiness"]["status"] = "not_a_valid_status"
    invalid_payload["candidate_screening_questions"] = ["sk-test-secret-should-not-log"]
    invalid_payload["job_profile"]["summary"] = "unsafe sk-test-secret-should-not-log " + ("x" * 900)
    extractor = OpenAIStructuredExtractor(
        api_key="sk-test-secret-should-not-log",
        model="test-model-not-used",
        fallback_enabled=False,
        client=FakeOpenAIClient(
            response={
                "id": "resp_test_schema_failure",
                "request_id": "req_test_schema_failure",
                "output_parsed": invalid_payload,
            }
        ),
    )
    router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "OPENAI_API_KEY": "sk-test-secret-should-not-log",
            "CVBRAIN_OPENAI_MODEL": "test-model-not-used",
            "CVBRAIN_AI_FALLBACK_ENABLED": "false",
        },
        ai_extractor=extractor,
    )

    with caplog.at_level(logging.WARNING, logger="cvbrain.openai_structured"):
        result = router.extract(request(source_text))

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    diagnostics_log = next(
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("cvbrain.ai_schema_validation_failed ")
    )
    diagnostics = json.loads(diagnostics_log.split("cvbrain.ai_schema_validation_failed ", 1)[1])
    assert result["ok"] is False
    assert result["warnings"] == ["ai_schema_validation_failed"]
    assert "cvbrain.ai_schema_validation_failed" in log_output
    assert "search_readiness.status" in log_output
    assert diagnostics["validation_stage"] == "job_intelligence_v1_validation"
    assert diagnostics["parse_path"] == "output_parsed"
    assert diagnostics["validation_errors"][0]["path"] == "search_readiness.status"
    assert "search_readiness.status is invalid" in diagnostics["validation_errors"][0]["message"]
    assert diagnostics["openai_response_id"] == "resp_test_schema_failure"
    assert diagnostics["openai_request_id"] == "req_test_schema_failure"
    assert len(diagnostics["sanitized_raw_output_sha256"]) == 64
    assert len(diagnostics["sanitized_raw_output_preview"]) <= 500
    assert "[redacted-api-key]" in diagnostics["sanitized_raw_output_preview"]
    assert "validation_error_count" in log_output
    assert "parsed_top_level_keys" in log_output
    assert "job_intelligence_top_level_keys" in log_output
    assert "requirements_bucket_counts" in log_output
    assert "requirement_item_summaries" in log_output
    assert "flat_output_bucket_counts" in log_output
    assert "test-model-not-used" in log_output
    assert "strict_schema_enabled" in log_output
    assert "fallback_enabled" in log_output
    assert "source_text_length" in log_output
    assert source_text not in log_output
    assert "sk-test-secret-should-not-log" not in log_output


def test_ai_timeout_fallback_and_clean_error_paths():
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(error=TimeoutError("simulated timeout")),
    )

    fallback_router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "OPENAI_API_KEY": "test-key-not-used",
            "CVBRAIN_OPENAI_MODEL": "test-model-not-used",
            "CVBRAIN_AI_FALLBACK_ENABLED": "true",
        },
        ai_extractor=extractor,
    )
    fallback = fallback_router.extract(request())
    assert fallback["ok"] is True
    assert fallback["engine"] == "deterministic"
    assert fallback["fallback_used"] is True
    assert "ai_timeout" in fallback["warnings"]

    error_router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "OPENAI_API_KEY": "test-key-not-used",
            "CVBRAIN_OPENAI_MODEL": "test-model-not-used",
            "CVBRAIN_AI_FALLBACK_ENABLED": "false",
        },
        ai_extractor=extractor,
    )
    error = error_router.extract(request())
    assert error["ok"] is False
    assert error["engine"] == "openai"
    assert "ai_timeout" in error["warnings"]


def test_provider_error_logs_safe_diagnostics_without_public_detail(caplog):
    source_text = (
        "Account Manager Semi Senior con experiencia en dispositivos médicos. "
        "Mínima de 3 años. Deseable CRM. Ubicación Montevideo, híbrido."
    )
    extractor = OpenAIStructuredExtractor(
        api_key="sk-test-secret-should-not-log",
        model="test-model-not-used",
        fallback_enabled=False,
        client=FakeOpenAIClient(error=RuntimeError("provider exploded with sk-test-secret-should-not-log")),
    )
    router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "OPENAI_API_KEY": "sk-test-secret-should-not-log",
            "CVBRAIN_OPENAI_MODEL": "test-model-not-used",
            "CVBRAIN_AI_FALLBACK_ENABLED": "false",
        },
        ai_extractor=extractor,
    )

    with caplog.at_level(logging.INFO, logger="cvbrain.openai_structured"):
        result = router.extract(request(source_text))

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    assert result["ok"] is False
    assert result["warnings"] == ["ai_provider_error"]
    assert "provider_error" in log_output
    assert "RuntimeError" in log_output
    assert "responses.create:text.format.json_schema" in log_output
    assert "source_text_length" in log_output
    assert "Account Manager Semi Senior" not in log_output
    assert "sk-test-secret-should-not-log" not in log_output
    assert "[redacted-api-key]" in log_output


def test_ambiguous_clerk_ai_output_can_continue_without_invented_specifics():
    fixture = load_output("ambiguous_clerk_continue_anyway_ai_output.json")
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": fixture}),
    )

    result = extractor.extract(request("Find all clerk applications."))
    serialized = json.dumps(result, ensure_ascii=False).lower()

    assert result["engine"] == "openai"
    assert result["job_intelligence"]["search_readiness"]["proceed_allowed"] is True
    assert result["recruiter_questions"]
    assert "search_readiness_exploratory" in result["warnings"]
    for invented in ["montevideo", "caba", "crm", "salary", "compensation"]:
        assert invented not in serialized


def test_sales_manager_negotiation_ai_output_uses_screening_not_hard_filter():
    fixture = load_output("vague_sales_manager_negotiation_ai_output.json")
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": fixture}),
    )

    result = extractor.extract(request("Sales Manager. Must be good at negotiation."))
    job_intelligence = result["job_intelligence"]
    serialized = json.dumps(result, ensure_ascii=False)

    assert job_intelligence["search_readiness"]["proceed_allowed"] is True
    assert job_intelligence["company_clarification_questions"]
    assert job_intelligence["candidate_screening_questions"]
    assert result["must_have"] == []
    assert "Negotiation" not in result["must_have"]
    assert job_intelligence["requirements"]["soft_competencies"][0]["hard_filter_approved"] is False
    for invented in ["B2B", "B2C", "CRM", "compensation", "travel", "Montevideo"]:
        assert invented not in serialized


def test_openai_tests_do_not_import_real_openai_sdk():
    assert "openai" not in sys.modules
