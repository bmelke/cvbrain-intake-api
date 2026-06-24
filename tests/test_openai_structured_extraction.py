import copy
import json
import logging
import sys
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.extractors import ExtractorRequest, ExtractorRouter
from app.extractors.openai_structured import (
    OpenAIStructuredExtractor,
    job_intelligence_v1_response_schema,
    provider_timeout_for_source_chars,
)
from app.schemas.job_intelligence_v1_contract import (
    JobIntelligenceDraft,
    job_intelligence_v1_response_schema as contract_job_intelligence_v1_response_schema,
)
from app.normalization.role_title import source_role_title_for_text
from app.main import app


ROOT = Path(__file__).resolve().parents[1]
MOCKED_OUTPUT_DIR = ROOT / "tests" / "fixtures" / "mocked_ai_outputs"

client = TestClient(app)


class FakeResponses:
    def __init__(self, response=None, responses=None, error=None):
        self.response_queue = list(responses) if responses is not None else [response]
        self.error = error
        self.calls = []

    def parse(self, **kwargs):
        raise AssertionError("OpenAIStructuredExtractor should use responses.create, not responses.parse")

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        if len(self.response_queue) > 1:
            result = self.response_queue.pop(0)
        else:
            result = self.response_queue[0]
        if isinstance(result, BaseException):
            raise result
        return result


class FakeOpenAIClient:
    def __init__(self, response=None, responses=None, error=None):
        self.responses = FakeResponses(response=response, responses=responses, error=error)
        self.with_options_calls = []

    def with_options(self, **kwargs):
        self.with_options_calls.append(kwargs)
        return self


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
        "criterion_id": "criterion_" + fold(text).replace(" ", "_")[:40],
        "text": text,
        "source_text": text,
        "importance": importance,
        "explicit": True,
        "hard_filter_candidate": importance == "must_have",
        "hard_filter_approved": False,
        "precision_status": "precise",
        "missing_dimensions": [],
        "clarification_question": None,
    }


def imprecise_requirement_item(text, importance, missing_dimensions, question):
    item = requirement_item(text, importance)
    item["precision_status"] = "needs_clarification"
    item["missing_dimensions"] = missing_dimensions
    item["clarification_question"] = question
    return item


def company_question(question, field="requirements.must_have"):
    return {
        "id": "precision_" + fold(question).replace(" ", "_")[:40],
        "question": question,
        "related_fields": [field],
        "blocking_level": "advisory",
        "asked_to": "hiring_company",
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


def role_title_payload(ai_title):
    payload = dirty_post_ai_payload()
    payload["job_profile"]["job_title"] = ai_title
    payload["job_profile"]["normalized_role_title"] = ai_title
    payload["search_strategy"]["target_titles"] = [ai_title]
    payload["search_strategy"]["search_terms"] = [ai_title]
    payload["search_strategy"]["semantic_terms"] = []
    payload["requirements"]["must_have"] = []
    payload["requirements"]["should_have"] = []
    payload["requirements"]["nice_to_have"] = []
    payload["requirements"]["credentials"] = []
    payload["requirements"]["blockers"] = []
    return payload


def experience_payload(experience_value_marker="valid"):
    payload = role_title_payload("Soporte IT")
    payload["requirements"]["must_have"] = [
        imprecise_requirement_item(
            "Experiencia demostrable en tickets",
            "must_have",
            ["duration", "evidence"],
            "¿Cuántos años mínimos o qué evidencia concreta se considera suficiente para demostrar la experiencia en tickets?",
        )
    ]
    payload["search_strategy"]["search_terms"] = ["Soporte IT", "tickets"]
    if experience_value_marker == "missing":
        payload["requirements"].pop("experience", None)
    elif experience_value_marker == "null":
        payload["requirements"]["experience"] = None
    elif experience_value_marker == "string":
        payload["requirements"]["experience"] = "experiencia demostrable en tickets"
    elif experience_value_marker == "list":
        payload["requirements"]["experience"] = ["experiencia demostrable en tickets"]
    else:
        payload["requirements"]["experience"] = {"minimum_years": None, "seniority": None}
    return payload


def desynced_role_title_payload(nested_title, normalized_title):
    payload = role_title_payload(normalized_title)
    payload["job_profile"]["job_title"] = nested_title
    payload["job_profile"]["normalized_role_title"] = normalized_title
    payload["search_strategy"]["target_titles"] = [normalized_title]
    payload["search_strategy"]["search_terms"] = [normalized_title]
    payload["flat_compatibility"] = {
        "role_title": normalized_title,
        "must_have": [],
        "should_have": [],
        "nice_to_have": [],
        "blockers": [],
        "credentials": {"required": [], "preferred": []},
        "experience": {"minimum_years": None, "seniority": ""},
        "location": {"normalized": ""},
        "search_terms": [normalized_title],
        "semantic_terms": [],
        "recruiter_questions": [],
        "warnings": [],
        "confidence": 0.91,
    }
    return payload


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
    assert "ai_schema_repaired" not in data["warnings"]
    for blocked in ["Argentina", "Buenos Aires", "CABA", "GBA"]:
        assert blocked not in serialized
    assert len(fake_client.responses.calls) == 1
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


def test_one_pass_precision_contract_accepts_valid_output_without_second_ai_call():
    question = "¿Cuántos años mínimos o qué evidencia concreta se considera suficiente para demostrar la experiencia?"
    payload = role_title_payload("Mecánico de coches")
    payload["requirements"]["must_have"] = [
        imprecise_requirement_item("Experiencia demostrable", "must_have", ["duration", "evidence"], question)
    ]
    payload["company_clarification_questions"] = []
    payload["search_readiness"]["status"] = "ready"
    fake_client = FakeOpenAIClient(response={"output_parsed": payload})
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request("Necesitamos mecánico de coches con experiencia demostrable."))

    criterion = result["job_intelligence"]["requirements"]["must_have"][0]
    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert len(fake_client.responses.calls) == 1
    assert criterion["precision_status"] == "needs_clarification"
    assert criterion["missing_dimensions"] == ["duration", "evidence"]
    assert criterion["clarification_question"] == question
    assert question in result["recruiter_questions"]
    assert question in result["display_plan"]["questions"]
    assert result["job_intelligence"]["search_readiness"]["status"] == "insufficient_for_precise_search"


def test_mechanic_sparse_input_one_pass_precision_questions_without_fallback_plan():
    source_text = (
        "Necesitamos mecanico de coches\n\n"
        "oficial de primera, con experiencia demostrable que haga todo tipo de reparaciones y con carnet de conducir\n\n"
        "asalariado o autonomo y papeles en regla\n\n"
        "salario segun convenio"
    )
    questions = [
        "¿Qué categoría, certificación o experiencia valida que el candidato sea oficial de primera?",
        "¿Cuántos años mínimos o qué evidencia concreta se considera suficiente para demostrar la experiencia?",
        "¿Qué alcance concreto de reparaciones debe poder realizar?",
        "¿Qué categoría de licencia de conducir se requiere y es excluyente o solamente preferida?",
        "¿Qué documentación exacta debe tener el candidato en regla?",
    ]
    payload = role_title_payload("Mecánico de coches")
    payload["job_profile"]["summary"] = "Mecánico de coches para reparaciones generales."
    payload["requirements"]["must_have"] = [
        imprecise_requirement_item("Oficial de primera", "must_have", ["evidence", "equivalence"], questions[0]),
        imprecise_requirement_item("Experiencia demostrable", "must_have", ["duration", "evidence"], questions[1]),
        imprecise_requirement_item(
            "Con experiencia demostrable que haga todo tipo de reparaciones y con carnet de conducir",
            "must_have",
            ["duration", "evidence", "scope", "license_category"],
            questions[2],
        ),
        imprecise_requirement_item("Carnet de conducir", "must_have", ["license_category", "importance"], questions[3]),
        imprecise_requirement_item("Papeles en regla", "must_have", ["legal_documentation"], questions[4]),
        requirement_item("Asalariado o autónomo", "must_have"),
        requirement_item("Salario según convenio", "must_have"),
    ]
    payload["requirements"]["credentials"] = [
        imprecise_requirement_item("Carnet B", "must_have", ["license_category"], questions[3]),
    ]
    payload["requirements"]["blockers"] = ["No avanzar sin papeles en regla"]
    payload["search_strategy"]["search_terms"] = ["Mecánico de coches", "carnet B", "carnet de conducir"]
    payload["search_strategy"]["semantic_terms"] = ["salario según convenio", "asalariado", "autónomo"]
    payload["search_readiness"]["status"] = "ready"
    payload["company_clarification_questions"] = []
    payload["candidate_screening_questions"] = [
        {"question": "¿Puedes aportar papeles en regla?", "asked_to": "candidate"}
    ]
    fake_client = FakeOpenAIClient(response={"output_parsed": payload})
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request(source_text))
    plan = result["display_plan"]
    question_text = fold(plan["questions"])

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert len(fake_client.responses.calls) == 1
    assert plan["role_title"] != "Rol a confirmar"
    assert "mecanico" in fold(plan["role_title"])
    assert plan["readiness"]["code"] != "ready"
    for expected in ("oficial de primera", "evidencia", "reparaciones", "carnet", "documentacion"):
        assert expected in question_text
    assert question_text.count("carnet de conducir") == 1
    assert question_text.count("documentacion") == 1
    assert question_text.count("reparaciones") == 1
    assert "carnet b" not in fold(result)
    assert "puedes aportar" not in question_text
    assert "salario" not in fold(plan["must_have"] + plan["preferred"] + plan["nice_to_have"] + plan["tie_breakers"] + plan["search_concepts"])
    assert "asalariado" not in fold(plan["must_have"] + plan["preferred"] + plan["nice_to_have"] + plan["tie_breakers"] + plan["search_concepts"])
    assert "papeles en regla" not in fold(plan["blockers"])
    criteria = plan["criteria_review"]
    criterion_ids = [item["criterion_id"] for item in criteria]
    question_ids = [item["question_id"] for item in plan["question_registry"]]
    assert len(criteria) == 5
    assert len(criterion_ids) == len(set(criterion_ids))
    assert len(question_ids) == len(set(question_ids))
    assert all(item["precision_status"] == "needs_clarification" for item in criteria)
    assert all(item["review_status"] == "pending_recruiter_confirmation" for item in criteria)
    assert all(item["clarification_question_id"] in question_ids for item in criteria)
    assert "oficial de primera" in fold(plan["professional_grade"])
    assert "Candidatos alineados a la búsqueda recibida" not in json.dumps(plan, ensure_ascii=False)
    assert "Lista para buscar" not in json.dumps(plan, ensure_ascii=False)


def test_precision_contract_missing_question_uses_existing_schema_repair_path():
    question = "¿Qué significa MBS en este contexto y cómo debe validarse en el CV?"
    invalid_payload = role_title_payload("Ingeniero recibido")
    invalid_payload["requirements"]["nice_to_have"] = [
        imprecise_requirement_item("MBS preferido", "nice_to_have", ["undefined_acronym"], question)
    ]
    invalid_payload["requirements"]["nice_to_have"][0]["clarification_question"] = None
    invalid_payload["company_clarification_questions"] = []
    repaired_payload = role_title_payload("Ingeniero recibido")
    repaired_payload["requirements"]["nice_to_have"] = [
        imprecise_requirement_item("MBS preferido", "nice_to_have", ["undefined_acronym"], question)
    ]
    repaired_payload["company_clarification_questions"] = []
    fake_client = FakeOpenAIClient(
        responses=[
            {"output_parsed": invalid_payload},
            {"output_parsed": repaired_payload},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request("Ingeniero recibido. MBS preferido."))

    repair_user_prompt = fake_client.responses.calls[1]["input"][1]["content"]
    assert result["ok"] is True
    assert result["ai_schema_repaired"] is True
    assert result["fallback_used"] is False
    assert len(fake_client.responses.calls) == 2
    assert "precision_contract.requirements.nice_to_have[0].clarification_question missing" in repair_user_prompt
    assert question in result["display_plan"]["questions"]


def test_openai_structured_prompt_includes_global_language_contract_for_spanish_source():
    fake_client = FakeOpenAIClient(response={"output_parsed": role_title_payload("Arquitecto de Software")})
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=fake_client,
    )

    result = extractor.extract(request("Empresa tecnológica busca Arquitecto de Software para plataforma SaaS."))

    system_prompt = fake_client.responses.calls[0]["input"][0]["content"]
    assert result["role_title"] == "Arquitecto de Software"
    assert "Language contract:" in system_prompt
    assert "Return only the canonical CVBrain JobIntelligenceDraft structured output." in system_prompt
    assert "Do not return flat_compatibility, display_plan" in system_prompt
    assert "Source text language detected as: Spanish" in system_prompt
    assert "All user-facing output fields must be in the same language as source_text." in system_prompt
    assert "If source_text is Spanish, write those user-facing fields in Spanish." in system_prompt
    assert "Do not translate technologies, product names, acronyms" in system_prompt
    assert "Python, Java, React, SQL, AWS, Azure, GCP, SAP, Salesforce" in system_prompt
    assert "The primary role_title must not be translated away from the source language." in system_prompt
    assert "Case contract:" in system_prompt
    assert "For output, incoming source case wins." in system_prompt
    assert "The canonical displayed title must be the literal extracted source title span" in system_prompt
    assert "Do not lowercase it." in system_prompt
    assert "Do not uppercase it." in system_prompt
    assert "Do not apply English title case, Spanish title case, sentence case" in system_prompt
    assert "Do not title-case Spanish titles unless the source itself is title-cased." in system_prompt
    assert "QA, UX, UI, UX/UI, IT, CRM, ERP, TMS, WMS, BI, AWS, Azure, GCP, SAP" in system_prompt
    assert "Coordinador/a de Admisiones" in system_prompt
    assert "Technical Support Specialist" in system_prompt
    assert "Director/a de Secundaria" in system_prompt
    assert "Consultora tecnológica" in system_prompt
    assert "Employer, client, industry, or organization descriptors" in system_prompt
    assert "Senior Talent Partner" in system_prompt
    assert "Clinical Operations Manager" in system_prompt
    assert "Public output contract:" in system_prompt
    assert "Source_text_span_missing_from_rules" in system_prompt
    assert "Source_text_" in system_prompt
    assert "_missing_or_not_applicable" in system_prompt
    assert "classification_rationale_id_missing" in system_prompt
    assert "public source_text fields" in system_prompt
    assert "Never invent a placeholder to satisfy the schema." in system_prompt
    assert "Recruiter display/search plan contract:" in system_prompt
    assert "CVBrain, not WordPress, owns the intelligence needed for recruiter-facing display plans." in system_prompt
    assert "inútil presentarse" in system_prompt
    assert "Search concepts must be short searchable concepts" in system_prompt
    assert "Candidate interview/screening questions belong only in candidate_screening_questions" in system_prompt
    assert "One-pass precision/search-actionability contract:" in system_prompt
    assert "Understandable human language is not automatically precise enough for CV search." in system_prompt
    assert "Every public candidate criterion in must_have, should_have, nice_to_have, credentials, and soft_competencies" in system_prompt
    assert "precision_status must be precise or needs_clarification" in system_prompt
    assert "missing_dimensions may use only" in system_prompt
    assert "Add every clarification_question from imprecise criteria to company_clarification_questions." in system_prompt
    assert "MBS preferido" in system_prompt
    assert "Sparse valid intake contract:" in system_prompt
    assert "Sparse recruiter text is still valid input" in system_prompt
    assert "Sparse input should lower confidence" in system_prompt
    assert "Do not invent years, modality, tools, credentials, location, industry, or requirements" in system_prompt
    assert "Requirement list inheritance contract:" in system_prompt
    assert "A parent cue applies to every sibling in its comma/OR list" in system_prompt
    assert "Experiencia con WMS" in system_prompt
    assert "Libreta de conducir será valorable si debe recorrer servicios" in system_prompt
    assert "Debe manejar métricas, calidad, ausentismo, turnos, coaching" in system_prompt
    assert "Es excluyente experiencia en RRHH generalista, con exposición a conflictos laborales" in system_prompt
    assert "Hard cues beat weak/contextual experience heuristics" in system_prompt
    assert "Long input segmentation contract:" in system_prompt
    assert "role title, responsibilities, requirements, desirable items, competencies" in system_prompt
    assert "Responsibilities, tasks, and accountabilities should inform job_tasks" in system_prompt
    assert "If a responsibilities/task section overlaps with a hard requirements section" in system_prompt
    assert "Do not turn every bullet, sentence, responsibility, or section item into must_have." in system_prompt
    assert "Section-level soft cues apply until a new section heading" in system_prompt
    assert "Deseables, Valorables, Se valorará, Plus, and Nice to have sections" in system_prompt
    assert "Competency contract:" in system_prompt
    assert "competencias excluyentes" in system_prompt
    assert "mandatory soft competencies" in system_prompt
    assert "must not become technical hard filters or blockers" in system_prompt
    assert "Orphan fragment contract:" in system_prompt
    assert "La persona deberá" in system_prompt
    assert "Forbidden naked section labels include Requisitos" in system_prompt
    assert "Para desarrollar" in system_prompt
    assert "La persona deberá liderar pagos" in system_prompt
    assert "Empresa digital busca UX/UI Designer con experiencia en producto" in system_prompt
    assert "Industria alimenticia busca Especialista en Compras para gestionar proveedores" in system_prompt
    assert "Empresa de salud busca Clinical Operations Manager con pacientes" in system_prompt
    assert "Trabajo con pacientes y profesionales" in system_prompt
    assert "Consultora de RRHH busca Senior Talent Partner" in system_prompt
    assert "Forbidden meta sentences include Estos puntos suman valor" in system_prompt
    assert "Pero no deben desplazar los requisitos excluyentes" in system_prompt
    assert "Si el input es escaso, debe salir baja confianza" in system_prompt
    assert "No schema fail" in system_prompt
    assert "No inventar años" in system_prompt
    assert "Generar recruiter_questions" in system_prompt
    assert "must never become candidate requirements" in system_prompt
    assert "Duplicate/component contract:" in system_prompt
    assert "Base técnica comprobable en redes" in system_prompt
    assert "Certificación Security+" in system_prompt
    assert "Negative-fragment contract:" in system_prompt
    assert "ni perfiles" in system_prompt


def test_openai_structured_prompt_detects_english_source_language():
    fake_client = FakeOpenAIClient(response={"output_parsed": role_title_payload("Software Architect")})
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=fake_client,
    )

    result = extractor.extract(request("Company is hiring a Software Architect for a SaaS platform."))

    system_prompt = fake_client.responses.calls[0]["input"][0]["content"]
    assert result["role_title"] == "Software Architect"
    assert "Source text language detected as: English" in system_prompt
    assert "If source_text is English, write those user-facing fields in English." in system_prompt


@pytest.mark.parametrize(
    ("source_text", "nested_title", "english_title"),
    [
        ("Empresa industrial necesita sumar un Ingeniero de Planta para producción.", "Ingeniero de Planta", "Plant Engineer"),
        (
            "Startup tecnológica busca Desarrollador Backend Python para trabajar en APIs.",
            "Desarrollador Backend Python",
            "Backend Developer (Python)",
        ),
        ("Se busca Visitador Médico para gestionar agenda de visitas.", "Visitador Médico", "Medical Sales Representative / Medical Visitor"),
        (
            "Empresa internacional busca Secretaria Recepcionista Bilingüe.",
            "Secretaria Recepcionista Bilingüe",
            "Bilingual Receptionist & Administrative Assistant",
        ),
        ("Seleccionamos Auditor Interno para controles y reportes.", "Auditor Interno", "Internal Auditor"),
        ("Consultora selecciona Reclutador IT para búsquedas técnicas.", "Reclutador IT", "Consultora"),
    ],
)
def test_nested_spanish_job_title_wins_over_english_normalized_title(source_text, nested_title, english_title):
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": desynced_role_title_payload(nested_title, english_title)}),
    )

    result = extractor.extract(request(source_text))

    assert result["role_title"] == nested_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == nested_title
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == nested_title
    assert english_title in result["search_terms"] or english_title in result["semantic_terms"]


@pytest.mark.parametrize(
    ("source_text", "ai_title", "expected_title"),
    [
        (
            "Empresa tecnológica busca Arquitecto de Software para plataforma SaaS.",
            "Software Architect",
            "Arquitecto de Software",
        ),
        (
            "Empresa proveedora busca Vendedor Técnico para soluciones industriales.",
            "Technical Sales Representative",
            "Vendedor Técnico",
        ),
        (
            "Aseguradora busca Liquidador de Siniestros para gestión de reclamos.",
            "Claims Adjuster",
            "Liquidador de Siniestros",
        ),
        (
            "Medio digital busca Periodista para cobertura de actualidad.",
            "Journalist",
            "Periodista",
        ),
        (
            "Agencia digital busca Redactor UX para contenidos de producto.",
            "UX Writer",
            "Redactor UX",
        ),
        (
            "Clínica privada busca Coordinador/a de Admisiones con experiencia en salud.",
            "Coordinador",
            "Coordinador/a de Admisiones",
        ),
        (
            "Empresa constructora busca Arquitecto/a de Obra con experiencia en dirección de obra.",
            "Arquitecto",
            "Arquitecto/a de Obra",
        ),
        (
            "Importadora busca Comprador Técnico con experiencia en repuestos industriales.",
            "Técnico",
            "Comprador Técnico",
        ),
        (
            "Consultora de RRHH busca Payroll Specialist con experiencia en liquidación de sueldos.",
            "Consultora de RRHH",
            "Payroll Specialist",
        ),
        (
            "Agencia creativa busca Diseñador/a UX/UI con experiencia en research.",
            "Diseñador",
            "Diseñador/a UX/UI",
        ),
        (
            "Empresa de software busca Technical Support Specialist con experiencia en soporte B2B.",
            "soporte B2B",
            "Technical Support Specialist",
        ),
        (
            "Consultora de RRHH busca Senior Talent Partner para selección ejecutiva y tecnológica.",
            "Consultora de RRHH",
            "Senior Talent Partner",
        ),
        (
            "Empresa de salud busca Clinical Operations Manager con pacientes, profesionales e indicadores operativos.",
            "Empresa de salud",
            "Clinical Operations Manager",
        ),
        (
            "Industria de Pando busca Comprador Técnico con proveedores industriales.",
            "Industria de Pando",
            "Comprador Técnico",
        ),
        (
            "Consultora tecnológica busca Scrum Master con experiencia facilitando ceremonias ágiles.",
            "Consultora tecnológica",
            "Scrum Master",
        ),
        (
            "Empresa inmobiliaria busca Agente Comercial con experiencia en captación de propiedades.",
            "Sales Agent",
            "Agente Comercial",
        ),
    ],
)
def test_spanish_source_title_extraction_overrides_english_ai_title_without_translation_mapping(
    source_text, ai_title, expected_title
):
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload(ai_title)}),
    )

    result = extractor.extract(request(source_text))

    assert result["role_title"] == expected_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == expected_title
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == expected_title
    assert ai_title in result["search_terms"] or ai_title in result["semantic_terms"]


def test_analyze_endpoint_syncs_top_level_and_nested_spanish_role_title(monkeypatch):
    source_text = "Startup tecnológica busca Desarrollador Backend Python para trabajar en APIs."
    fake_client = FakeOpenAIClient(
        response={
            "output_parsed": desynced_role_title_payload(
                "Desarrollador Backend Python",
                "Backend Developer (Python)",
            )
        }
    )

    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "ai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("CVBRAIN_OPENAI_MODEL", "test-model-not-used")
    monkeypatch.setenv("CVBRAIN_AI_FALLBACK_ENABLED", "false")
    monkeypatch.setattr(OpenAIStructuredExtractor, "_default_client", lambda self: fake_client)

    response = client.post("/api/job-intake/analyze", json=analyze_payload(source_text))

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["role_title"] == "Desarrollador Backend Python"
    assert data["job_intelligence"]["job_profile"]["job_title"] == "Desarrollador Backend Python"
    assert data["job_intelligence"]["job_profile"]["normalized_role_title"] == "Desarrollador Backend Python"
    assert data["role_title"] == data["job_intelligence"]["job_profile"]["job_title"]


@pytest.mark.parametrize("english_title", ["Data Engineer", "Product Manager", "QA Tester"])
def test_common_english_title_in_spanish_source_is_preserved_when_source_uses_it(english_title):
    source_title = f"{english_title} Semi Senior"
    source_text = f"Compañía tecnológica busca {source_title} para producto digital."
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload(english_title)}),
    )

    result = extractor.extract(request(source_text))

    assert result["role_title"] == source_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == source_title
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == source_title


@pytest.mark.parametrize(
    "source_title",
    [
        "Key Account Manager",
        "Strategic Account Manager",
        "Enterprise Account Executive",
        "Senior Product Manager",
        "Lead UX Designer",
        "Principal Backend Engineer",
        "Technical Support Specialist",
        "Customer Success Manager",
        "Field Service Coordinator",
        "Service Delivery Manager",
        "Regional Operations Manager",
        "Corporate Legal Manager",
    ],
)
def test_leading_title_modifiers_are_preserved_from_explicit_source_span(source_title):
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload("Account Manager")}),
    )

    result = extractor.extract(request(f"Empresa regional busca {source_title} con experiencia B2B."))

    assert result["role_title"] == source_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == source_title
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == source_title


def test_key_account_manager_full_title_span_wins_over_inner_preserved_title():
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload("Account Manager")}),
    )

    result = extractor.extract(
        request(
            "Empresa farmacéutica busca Key Account Manager con experiencia en cuentas institucionales, "
            "licitaciones, negociación, forecast y relación con distribuidores."
        )
    )

    assert result["role_title"] == "Key Account Manager"
    assert result["job_intelligence"]["job_profile"]["job_title"] == "Key Account Manager"
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == "Key Account Manager"


def test_long_form_account_manager_source_span_preserves_uppercase_and_seniority():
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload("Account Manager")}),
    )

    result = extractor.extract(
        request(
            "Estamos buscando un ACCOUNT MANAGER Semi Senior para desarrollar nuestra cartera de clientes "
            "con base en Montevideo. Requisitos: experiencia mínima de 3 años en dispositivos médicos."
        )
    )

    assert result["role_title"] == "ACCOUNT MANAGER Semi Senior"
    assert result["job_intelligence"]["job_profile"]["job_title"] == "ACCOUNT MANAGER Semi Senior"
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == "ACCOUNT MANAGER Semi Senior"


@pytest.mark.parametrize(
    ("source_text", "english_title"),
    [
        ("Empresa tecnológica busca Data Engineer para plataforma de datos.", "Data Engineer"),
        ("Startup busca Product Manager para producto digital.", "Product Manager"),
        ("Empresa busca QA Tester para pruebas manuales.", "QA Tester"),
        ("Startup busca UX/UI Designer para producto digital.", "UX/UI Designer"),
        ("Agencia busca Community Manager Senior para redes sociales.", "Community Manager Senior"),
    ],
)
def test_language_contract_preserves_explicit_english_titles_inside_spanish_source(source_text, english_title):
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload(english_title)}),
    )

    result = extractor.extract(request(source_text))

    assert result["role_title"] == english_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == english_title
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == english_title


@pytest.mark.parametrize("english_title", ["Software Architect", "Technical Sales Representative"])
def test_english_source_keeps_english_primary_role_title(english_title):
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload(english_title)}),
    )

    result = extractor.extract(request(f"Company is hiring a {english_title} for a SaaS platform."))

    assert result["role_title"] == english_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == english_title
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == english_title


@pytest.mark.parametrize(
    "source_title",
    [
        "Community Manager Senior",
        "Coordinador de logística",
        "Liquidador de siniestros",
        "Ejecutivo de licitaciones",
        "Responsable de Recursos Humanos generalista",
        "Responsable de Facilities",
        "Administrativo Comercial",
        "Electricista Industrial",
        "Diseñador Gráfico Senior",
        "Arquitecto de Software",
        "Operario Calificado CNC",
        "Escribano Junior o estudiante avanzado de notariado",
        "Redactor UX",
        "UX/UI Designer",
    ],
)
def test_explicit_source_title_casing_wins_for_top_level_and_nested_titles(source_title):
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload(source_title.title())}),
    )

    result = extractor.extract(request(f"Empresa busca {source_title} para operación local."))

    assert result["role_title"] == source_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == source_title
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == source_title
    assert result["role_title"] == result["job_intelligence"]["job_profile"]["job_title"]


def test_spanish_source_without_clear_explicit_title_does_not_invent_dictionary_translation():
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload("Technical Sales Representative")}),
    )

    result = extractor.extract(
        request(
            "Empresa del sector industrial necesita incorporar persona para desarrollar clientes y preparar cotizaciones."
        )
    )

    assert result["role_title"] == "Technical Sales Representative"
    assert result["job_intelligence"]["job_profile"]["job_title"] == "Technical Sales Representative"
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == "Technical Sales Representative"


@pytest.mark.parametrize(
    ("source_text", "ai_title", "expected_title"),
    [
        ("Buscamos Desarrollador Backend Python para APIs.", "Backend Developer (Python)", "Desarrollador Backend Python"),
        ("Buscamos Analista BI para reportes e indicadores.", "Business Intelligence Analyst", "Analista BI"),
        ("Buscamos Consultor SAP para proyectos de implementación.", "SAP Consultant", "Consultor SAP"),
    ],
)
def test_spanish_role_title_normalization_preserves_technical_tokens(source_text, ai_title, expected_title):
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload(ai_title)}),
    )

    result = extractor.extract(request(source_text))

    assert result["role_title"] == expected_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == expected_title
    assert "Pitón" not in json.dumps(result, ensure_ascii=False)
    for token in expected_title.split():
        if token.isupper() or token in {"Python", "SAP"}:
            assert token in result["role_title"]


@pytest.mark.parametrize(
    ("source_text", "dirty_ai_title", "expected_title"),
    [
        (
            "Rol: Técnico de Soporte IT Junior. Excluyente experiencia de al menos 1 año.",
            "Técnico de Soporte IT Junior. Excluyente experiencia de",
            "Técnico de Soporte IT Junior",
        ),
        (
            "Empresa de servicios busca Responsable de Recursos Humanos generalista. La persona deberá gestionar selección.",
            "Responsable de Recursos Humanos generalista. La persona",
            "Responsable de Recursos Humanos generalista",
        ),
        (
            "Importadora busca Encargado de Depósito. La persona deberá liderar equipo operativo.",
            "Encargado de Depósito. La persona",
            "Encargado de Depósito",
        ),
        (
            "Empresa de telecomunicaciones busca Técnico de Campo. Es excluyente experiencia instalando o manteniendo redes.",
            "Técnico de Campo. Es excluyente experiencia instalando o",
            "Técnico de Campo",
        ),
        (
            "Empresa busca Responsable de RRHH. La persona deberá gestionar selección.",
            "Responsable de RRHH. La persona deberá",
            "Responsable de RRHH",
        ),
        (
            "Importadora busca Encargado de Depósito. Se requiere experiencia liderando personal.",
            "Encargado de Depósito. Se requiere",
            "Encargado de Depósito",
        ),
        (
            "Empresa busca Analista BI. Será valorable experiencia con Power BI.",
            "Analista BI. Será valorable experiencia",
            "Analista BI",
        ),
        (
            "Empresa busca Ejecutivo Comercial. No avanzar perfiles sin ventas.",
            "Ejecutivo Comercial. No avanzar perfiles",
            "Ejecutivo Comercial",
        ),
        (
            "Empresa busca Técnico de Campo. Para visitas a clientes.",
            "Técnico de Campo. Para visitas",
            "Técnico de Campo",
        ),
    ],
)
def test_role_title_sentence_tail_contamination_is_clipped(source_text, dirty_ai_title, expected_title):
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        client=FakeOpenAIClient(response={"output_parsed": role_title_payload(dirty_ai_title)}),
    )

    result = extractor.extract(request(source_text))

    assert result["role_title"] == expected_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == expected_title
    assert result["job_intelligence"]["job_profile"]["normalized_role_title"] == expected_title


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


def test_provider_schema_is_generated_from_typed_job_intelligence_draft():
    provider_schema = job_intelligence_v1_response_schema()
    contract_schema = contract_job_intelligence_v1_response_schema()
    model_schema = JobIntelligenceDraft.model_json_schema()

    assert provider_schema == contract_schema
    assert set(provider_schema["required"]) == set(model_schema["properties"].keys())
    assert provider_schema["additionalProperties"] is False
    experience_schema = provider_schema["$defs"]["ExperienceDraft"]
    assert experience_schema["additionalProperties"] is False
    assert experience_schema["required"] == ["minimum_years", "seniority"]
    assert experience_schema["properties"]["minimum_years"]["type"] == ["number", "null"]
    assert experience_schema["properties"]["seniority"]["type"] == ["string", "null"]


def test_openai_structured_outputs_are_always_strict_even_if_legacy_flag_is_false():
    fake_client = FakeOpenAIClient(response={"output_parsed": role_title_payload("Soporte IT")})
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        strict_schema_enabled=False,
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request("Empresa busca Soporte IT."))

    call = fake_client.responses.calls[0]
    assert result["ok"] is True
    assert call["text"]["format"]["strict"] is True
    assert extractor.strict_schema_enabled is True
    assert extractor.configured_strict_schema_enabled is False


def test_requirements_experience_valid_object_uses_one_ai_call_and_display_plan():
    payload = experience_payload("valid")
    fake_client = FakeOpenAIClient(response={"output_parsed": payload})
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request("Empresa busca Soporte IT con experiencia demostrable en tickets."))

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert len(fake_client.responses.calls) == 1
    assert result["experience"] == {"minimum_years": None, "seniority": ""}
    assert result["job_intelligence"]["requirements"]["experience"] == {"minimum_years": None, "seniority": None}
    assert result["display_plan"]["role_title"] == "Soporte IT"


@pytest.mark.parametrize("marker", ["missing", "null"])
def test_requirements_experience_missing_or_null_gets_safe_default_without_repair(marker):
    payload = experience_payload(marker)
    fake_client = FakeOpenAIClient(response={"output_parsed": payload})
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request("Empresa busca Soporte IT con experiencia demostrable en tickets."))

    assert result["ok"] is True
    assert result["fallback_used"] is False
    assert len(fake_client.responses.calls) == 1
    assert result["job_intelligence"]["requirements"]["experience"] == {"minimum_years": None, "seniority": None}
    assert result["experience"]["minimum_years"] is None
    assert result["display_plan"]["role_title"] == "Soporte IT"


@pytest.mark.parametrize(
    ("marker", "received_type"),
    [("string", "string"), ("list", "array")],
)
def test_requirements_experience_wrong_type_invokes_schema_repair_without_discarding_content(marker, received_type):
    invalid_payload = experience_payload(marker)
    repaired_payload = copy.deepcopy(experience_payload("valid"))
    fake_client = FakeOpenAIClient(
        responses=[
            {"id": "resp_initial_invalid_experience", "output_parsed": invalid_payload},
            {"id": "resp_repaired_experience", "output_parsed": repaired_payload},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request("Empresa busca Soporte IT con experiencia demostrable en tickets."))

    repair_prompt = fake_client.responses.calls[1]["input"][1]["content"]
    assert result["ok"] is True
    assert result["fallback_used"] is False
    assert result["ai_schema_repaired"] is True
    assert len(fake_client.responses.calls) == 2
    assert f"requirements.experience expected object, received {received_type}" in repair_prompt
    assert fake_client.responses.calls[1]["text"]["format"]["strict"] is True
    assert fake_client.responses.calls[1]["text"]["format"]["schema"] == job_intelligence_v1_response_schema()
    assert result["experience"]["minimum_years"] is None
    assert "Experiencia demostrable como soporte it" in result["must_have"]
    assert "Experiencia demostrable como soporte it" in json.dumps(result["job_intelligence"], ensure_ascii=False)


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


def test_ai_schema_validation_repair_success_returns_openai_result_with_marker():
    invalid_payload = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    invalid_payload["search_readiness"]["status"] = "not_a_valid_status"
    repaired_payload = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    fake_client = FakeOpenAIClient(
        responses=[
            {"output_parsed": invalid_payload},
            {"output_parsed": repaired_payload},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request(repaired_payload["source"]["input_concept"]))

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["ai_schema_repaired"] is True
    assert "ai_schema_repaired" not in result["warnings"]
    assert len(fake_client.responses.calls) == 2
    repair_call = fake_client.responses.calls[1]
    assert repair_call["input"][0]["content"].startswith("Repair CVBrain Job Intelligence v1 JSON")
    assert "not_a_valid_status" in repair_call["input"][1]["content"]
    assert "Repair attempt: 1 of 2" in repair_call["input"][1]["content"]
    assert repair_call["text"]["format"]["name"] == "cvbrain_job_intelligence_v1"


def test_busqueda_036_like_schema_repair_second_attempt_preserves_spanish_title():
    invalid_payload = role_title_payload("Software Architect")
    invalid_payload["search_readiness"]["status"] = "not_a_valid_status"
    repair_payload = role_title_payload("Software Architect")
    repair_payload["quality_control"]["confidence"] = "invalid-confidence"
    final_payload = role_title_payload("Software Architect")
    fake_client = FakeOpenAIClient(
        responses=[
            {"id": "resp_initial_invalid", "output_parsed": invalid_payload},
            {"id": "resp_repair_invalid", "output_parsed": repair_payload},
            {"id": "resp_repair_valid", "output_parsed": final_payload},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request("Empresa tecnológica busca Arquitecto de Software para plataforma SaaS."))

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["ai_schema_repaired"] is True
    assert "ai_schema_repaired" not in result["warnings"]
    assert result["role_title"] == "Arquitecto de Software"
    assert result["job_intelligence"]["job_profile"]["job_title"] == "Arquitecto de Software"
    assert len(fake_client.responses.calls) == 3
    assert "Repair attempt: 2 of 2" in fake_client.responses.calls[2]["input"][1]["content"]


def test_ai_schema_repair_prompt_preserves_source_language_contract_and_spanish_title():
    invalid_payload = role_title_payload("Software Architect")
    invalid_payload["search_readiness"]["status"] = "not_a_valid_status"
    repaired_payload = role_title_payload("Software Architect")
    fake_client = FakeOpenAIClient(
        responses=[
            {"output_parsed": invalid_payload},
            {"output_parsed": repaired_payload},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request("Empresa tecnológica busca Arquitecto de Software para plataforma SaaS."))

    repair_prompt = fake_client.responses.calls[1]["input"][0]["content"]
    repair_user_prompt = fake_client.responses.calls[1]["input"][1]["content"]
    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["ai_schema_repaired"] is True
    assert "ai_schema_repaired" not in result["warnings"]
    assert result["role_title"] == "Arquitecto de Software"
    assert result["job_intelligence"]["job_profile"]["job_title"] == "Arquitecto de Software"
    assert "Language contract:" in repair_prompt
    assert "Source text language detected as: Spanish" in repair_prompt
    assert "All user-facing output fields must be in the same language as source_text." in repair_prompt
    assert "If source_text is Spanish, write those user-facing fields in Spanish." in repair_prompt
    assert "Case contract:" in repair_prompt
    assert "For output, incoming source case wins." in repair_prompt
    assert "Do not return a public API envelope" in repair_prompt
    assert "Return the canonical JobIntelligenceDraft schema object itself." in repair_prompt
    assert "Do not return flat_compatibility, display_plan" in repair_prompt
    assert "Agente Comercial" in repair_prompt
    assert "Director/a de Secundaria" in repair_prompt
    assert "Never respond with ok=false for normal recruiter prose" in repair_prompt
    assert "Sparse but valid recruiter prose must produce the best valid schema" in repair_prompt
    assert "low-confidence valid Job Intelligence object" in repair_prompt
    assert "Public output contract:" in repair_prompt
    assert "Source_text_span_missing_from_rules" in repair_prompt
    assert "classification_rationale_id_missing" in repair_prompt
    assert "Recruiter display/search plan contract:" in repair_prompt
    assert "CVBrain, not WordPress, owns the intelligence needed for recruiter-facing display plans." in repair_prompt
    assert "inútil presentarse" in repair_prompt
    assert "Search concepts must be short searchable concepts" in repair_prompt
    assert "One-pass precision/search-actionability contract:" in repair_prompt
    assert "Do not rely on a second semantic audit call." in repair_prompt
    assert "precision_status" in repair_prompt
    assert "clarification_question" in repair_prompt
    assert "Requirement list inheritance contract:" in repair_prompt
    assert "Libreta de conducir será valorable si debe recorrer servicios" in repair_prompt
    assert "Long input segmentation contract:" in repair_prompt
    assert "Competency contract:" in repair_prompt
    assert "competencias excluyentes" in repair_prompt
    assert "Orphan fragment contract:" in repair_prompt
    assert "Si el input es escaso, debe salir baja confianza" in repair_prompt
    assert "No inventar años" in repair_prompt
    assert "Duplicate/component contract:" in repair_prompt
    assert "Negative-fragment contract:" in repair_prompt
    assert "Software Architect" in repair_user_prompt


def test_ai_schema_repair_recovers_from_public_error_stub_for_normal_recruiter_prose():
    repaired_payload = role_title_payload("Agente Comercial")
    fake_client = FakeOpenAIClient(
        responses=[
            {"output_parsed": {"ok": False, "warnings": ["ai_schema_validation_failed"], "engine": "openai"}},
            {"output_parsed": repaired_payload},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )
    source_text = (
        "Empresa inmobiliaria busca Agente Comercial con experiencia en captación de propiedades, "
        "negociación, seguimiento de clientes y cierre de operaciones."
    )

    result = extractor.extract(request(source_text))

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["ai_schema_repaired"] is True
    assert result["role_title"] == "Agente Comercial"
    assert len(fake_client.responses.calls) == 2


def test_ai_schema_stub_recovery_handles_directora_de_secundaria_after_failed_repairs():
    fake_client = FakeOpenAIClient(
        responses=[
            {"output_parsed": {"ok": False, "warnings": ["ai_schema_validation_failed"], "engine": "openai"}},
            {"output_parsed": {"ok": False, "warnings": ["ai_schema_validation_failed"], "engine": "openai"}},
            {"output_parsed": {"ok": False, "warnings": ["ai_schema_validation_failed"], "engine": "openai"}},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )
    source_text = (
        "Colegio privado busca Director/a de Secundaria con experiencia obligatoria en gestión académica, "
        "liderazgo docente, convivencia, relación con familias e indicadores educativos. "
        "Título docente habilitante es excluyente."
    )

    result = extractor.extract(request(source_text))

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["ai_schema_repaired"] is True
    assert result["role_title"] == "Director/a de Secundaria"
    assert result["job_intelligence"]["job_profile"]["job_title"] == "Director/a de Secundaria"
    assert "Experiencia obligatoria en gestión académica" in result["must_have"]
    assert "Liderazgo docente" in result["must_have"]
    assert "Convivencia" in result["must_have"]
    assert "Relación con familias" in result["must_have"]
    assert "Indicadores educativos" in result["must_have"]
    assert "Título docente habilitante es excluyente" in result["credentials"]["required"]


@pytest.mark.parametrize(
    ("source_text", "expected_title"),
    [
        (
            "Mutualista busca Responsable de Calidad Asistencial con auditorías clínicas e indicadores. Título universitario valorable.",
            "Responsable de Calidad Asistencial",
        ),
        (
            "Alimentos busca Research & Development Manager con formulaciones e inocuidad. No avanzar perfiles sin alimentos.",
            "Research & Development Manager",
        ),
        (
            "Salud busca Clinical Operations Manager con pacientes y profesionales. Montevideo y Maldonado.",
            "Clinical Operations Manager",
        ),
        (
            "Consultora de RRHH busca Senior Talent Partner para selección ejecutiva y tecnológica.",
            "Senior Talent Partner",
        ),
        (
            "Empresa de salud busca Clinical Operations Manager con pacientes, profesionales e indicadores operativos.",
            "Clinical Operations Manager",
        ),
        (
            "Industria de Pando busca Comprador Técnico con proveedores industriales.",
            "Comprador Técnico",
        ),
        (
            "Industria química busca Técnico/a de Procesos con seguridad y turnos. Formación técnica valorable.",
            "Técnico/a de Procesos",
        ),
    ],
)
def test_sparse_valid_source_title_extraction_examples(source_text, expected_title):
    assert source_role_title_for_text(source_text) == expected_title


@pytest.mark.parametrize(
    ("source_text", "expected_title", "expected_terms", "expected_credentials", "expected_blockers", "expected_location"),
    [
        (
            "Mutualista busca Responsable de Calidad Asistencial con auditorías clínicas e indicadores. Título universitario valorable.",
            "Responsable de Calidad Asistencial",
            ["Auditorías clínicas", "Indicadores"],
            ["Título universitario valorable"],
            [],
            "",
        ),
        (
            "Alimentos busca Research & Development Manager con formulaciones e inocuidad. No avanzar perfiles sin alimentos.",
            "Research & Development Manager",
            ["Formulaciones", "Inocuidad"],
            [],
            ["No avanzar perfiles sin alimentos"],
            "",
        ),
        (
            "Salud busca Clinical Operations Manager con pacientes y profesionales. Montevideo y Maldonado.",
            "Clinical Operations Manager",
            ["Pacientes", "Profesionales"],
            [],
            [],
            "Montevideo, Maldonado",
        ),
        (
            "Industria química busca Técnico/a de Procesos con seguridad y turnos. Formación técnica valorable.",
            "Técnico/a de Procesos",
            ["Seguridad", "Turnos"],
            ["Formación técnica valorable"],
            [],
            "",
        ),
    ],
)
def test_sparse_valid_inputs_recover_from_empty_schema_stubs_without_fallback(
    source_text,
    expected_title,
    expected_terms,
    expected_credentials,
    expected_blockers,
    expected_location,
):
    fake_client = FakeOpenAIClient(
        responses=[
            {"output_parsed": {"ok": False, "warnings": ["ai_schema_validation_failed"], "engine": "openai"}},
            {"output_parsed": {"ok": False, "warnings": ["ai_schema_validation_failed"], "engine": "openai"}},
            {"output_parsed": {"ok": False, "warnings": ["ai_schema_validation_failed"], "engine": "openai"}},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request(source_text))
    serialized = fold(result)

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["ai_schema_repaired"] is True
    assert "ai_schema_validation_failed" not in result["warnings"]
    assert result["role_title"] == expected_title
    assert result["job_intelligence"]["job_profile"]["job_title"] == expected_title
    assert result["confidence"] < 0.5
    assert result["job_intelligence"]["search_readiness"]["proceed_allowed"] is True
    assert result["recruiter_questions"]
    assert result["experience"]["minimum_years"] is None
    assert result["location"]["remote_allowed"] is None
    assert result["location"]["hybrid_allowed"] is None
    assert result["must_have"] == []
    assert result["should_have"] == []
    assert result["nice_to_have"] == []
    assert result["credentials"]["preferred"] == expected_credentials
    assert result["blockers"] == expected_blockers
    assert result["location"]["normalized"] == expected_location
    for term in expected_terms:
        assert fold(term) in serialized
    assert len(fake_client.responses.calls) == 3
    assert len(fake_client.responses.calls) == 3


def test_ai_invalid_json_repair_success_returns_openai_result_with_marker():
    repaired_payload = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    fake_client = FakeOpenAIClient(
        responses=[
            {"output_text": "{not valid json"},
            {"output_parsed": repaired_payload},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request(repaired_payload["source"]["input_concept"]))

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["ai_schema_repaired"] is True
    assert "ai_schema_repaired" not in result["warnings"]
    assert len(fake_client.responses.calls) == 2
    assert "{not valid json" in fake_client.responses.calls[1]["input"][1]["content"]


def test_ai_schema_validation_repair_failure_returns_schema_error_once(caplog):
    invalid_payload = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    invalid_payload.pop("requirements")
    repair_payload = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    repair_payload["search_readiness"]["status"] = "not_a_valid_status"
    fake_client = FakeOpenAIClient(
        responses=[
            {"id": "resp_initial_invalid", "output_parsed": invalid_payload},
            {"id": "resp_repair_invalid", "output_parsed": repair_payload},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        fallback_enabled=False,
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

    with caplog.at_level(logging.WARNING, logger="cvbrain.openai_structured"):
        result = router.extract(request())

    assert result["ok"] is False
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["warnings"] == ["ai_schema_validation_failed"]
    assert len(fake_client.responses.calls) == 3
    assert "resp_repair_invalid" in "\n".join(record.getMessage() for record in caplog.records)


def test_ai_schema_validation_repair_logs_do_not_expose_fake_secrets(caplog):
    invalid_payload = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    invalid_payload["job_profile"]["summary"] = "unsafe sk-test-secret-should-not-log " + ("x" * 900)
    invalid_payload["candidate_screening_questions"] = ["sk-test-secret-should-not-log"]
    repair_payload = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    repair_payload["quality_control"]["confidence"] = "invalid-confidence"
    repair_payload["job_profile"]["summary"] = "unsafe sk-test-secret-should-not-log " + ("x" * 900)
    repair_payload["candidate_screening_questions"] = ["sk-test-secret-should-not-log"]
    fake_client = FakeOpenAIClient(
        responses=[
            {"output_parsed": invalid_payload},
            {"output_parsed": repair_payload},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="sk-test-secret-should-not-log",
        model="test-model-not-used",
        fallback_enabled=False,
        client=fake_client,
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
        result = router.extract(request())

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    assert result["ok"] is False
    assert result["warnings"] == ["ai_schema_validation_failed"]
    assert len(fake_client.responses.calls) == 3
    assert "schema_repair_start" in log_output
    assert "cvbrain.ai_schema_validation_failed" in log_output
    assert "sk-test-secret-should-not-log" not in log_output
    assert "[redacted-api-key]" in log_output


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


def test_provider_timeout_for_source_chars_uses_bounded_dynamic_policy():
    assert provider_timeout_for_source_chars(1000, configured_timeout_seconds=60) == 90
    assert provider_timeout_for_source_chars(3000, configured_timeout_seconds=60) == 150
    assert provider_timeout_for_source_chars(8000, configured_timeout_seconds=60) == 240
    assert provider_timeout_for_source_chars(15000, configured_timeout_seconds=60) == 300
    assert provider_timeout_for_source_chars(1000, configured_timeout_seconds=180) == 180
    assert provider_timeout_for_source_chars(1000, configured_timeout_seconds=500) == 300


def test_provider_timeout_retries_once_and_uses_dynamic_client_timeout():
    fixture = load_output("uy_account_manager_medical_devices_montevideo_hybrid_ai_output.json")
    source_text = (
        "Empresa busca Account Manager Semi Senior con experiencia en dispositivos médicos. "
        "Mínima de 3 años. "
    ) * 35
    fake_client = FakeOpenAIClient(
        responses=[
            TimeoutError("simulated read timeout"),
            {"output_parsed": fixture},
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        timeout_seconds=60,
        fallback_enabled=False,
        client=fake_client,
    )

    result = extractor.extract(request(source_text))

    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert len(fake_client.responses.calls) == 2
    assert [call["timeout"] for call in fake_client.with_options_calls] == [150.0, 150.0]


def test_provider_timeout_fails_cleanly_after_one_retry_without_fallback():
    fake_client = FakeOpenAIClient(
        responses=[
            TimeoutError("simulated read timeout"),
            TimeoutError("simulated read timeout again"),
        ]
    )
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model-not-used",
        timeout_seconds=60,
        fallback_enabled=False,
        client=fake_client,
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

    result = router.extract(request("Empresa busca Soporte IT. Excluyente experiencia en tickets."))

    assert result["ok"] is False
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["warnings"] == ["ai_provider_timeout"]
    assert len(fake_client.responses.calls) == 2


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
    assert "ai_provider_timeout" in fallback["warnings"]

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
    assert "ai_provider_timeout" in error["warnings"]


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
