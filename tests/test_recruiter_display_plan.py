import copy
import json
import unicodedata

from app.extractors import ExtractorRequest
from app.extractors.openai_structured import OpenAIStructuredExtractor
from app.mappers.job_intelligence_to_flat import derive_flat_compatibility
from app.mappers.recruiter_display_plan import build_recruiter_display_plan
from app.normalization.canonical_job_intelligence import canonicalize_job_intelligence
from app.normalization.requirement_importance import normalize_job_intelligence_requirements
from app.normalization.role_title import normalize_role_title_for_source


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOpenAIClient:
    def __init__(self, response):
        self.responses = FakeResponses(response)

    def with_options(self, **kwargs):
        return self


def fold(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else str(value)
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def requirement_item(text, importance="must_have", source_text=None):
    return {
        "criterion_id": "criterion_" + fold(text).replace(" ", "_")[:40],
        "text": text,
        "source_text": source_text or text,
        "importance": importance,
        "explicit": True,
        "hard_filter_candidate": importance == "must_have",
        "hard_filter_approved": False,
        "precision_status": "precise",
        "missing_dimensions": [],
        "clarification_question": None,
    }


def imprecise_requirement_item(text, importance, missing_dimensions, question, source_text=None):
    item = requirement_item(text, importance, source_text=source_text)
    item["precision_status"] = "needs_clarification"
    item["missing_dimensions"] = missing_dimensions
    item["clarification_question"] = question
    return item


def question_item(question, field="requirements"):
    return {
        "id": field.replace(".", "_"),
        "question": question,
        "related_fields": [field],
        "blocking_level": "advisory",
        "asked_to": "hiring_company",
    }


def missing_item(field, question):
    return {
        "id": field.replace(".", "_"),
        "field": field,
        "description": field,
        "suggested_question": question,
        "can_continue_without_answer": True,
    }


def base_job_intelligence(role_title="Sanitized Role"):
    return {
        "schema_version": "cvbrain_job_intelligence_v1",
        "job_profile": {
            "job_title": role_title,
            "normalized_role_title": role_title,
            "role_family": "",
            "seniority": "",
            "summary": "",
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
            "must_have": [],
            "should_have": [],
            "nice_to_have": [],
            "credentials": [],
            "blockers": [],
            "experience": {"minimum_years": None, "seniority": ""},
            "soft_competencies": [],
        },
        "search_strategy": {
            "target_titles": [role_title],
            "search_terms": [role_title],
            "semantic_terms": [],
            "negative_terms": [],
        },
        "missing_information": [],
        "company_clarification_questions": [],
        "candidate_screening_questions": [],
        "search_readiness": {
            "status": "usable_with_warnings",
            "proceed_allowed": True,
            "recommended_action": "continue_anyway",
            "recruiter_decision_required": False,
            "continued_with_missing_information": False,
            "recruiter_override_reason": None,
            "decision_options": ["continue_anyway", "answer_clarifying_questions", "ask_company", "use_manual_search", "cancel"],
        },
        "quality_control": {
            "warnings": [],
            "confidence": 0.74,
            "contains_candidate_data": False,
            "contains_candidate_pii": False,
        },
    }


def normalized_flat_and_plan(payload, source_text=""):
    normalized = normalize_job_intelligence_requirements(payload, source_text=source_text)
    normalized = normalize_role_title_for_source(normalized, source_text=source_text)
    flat = derive_flat_compatibility(normalized)
    return normalized, flat, flat["display_plan"]


def all_plan_text(plan):
    return fold(plan)


def test_display_plan_cleans_engineering_manager_intake_for_recruiter_ui():
    source = (
        "ingeniero recibido para Montevideo. Coordinar un grupo de diseñadores de motores. "
        "Mínimo 3 años de experiencia en gerencia. Minimo 3 años de experiencia rn gerencia es necesario. "
        "Inutil presentarse sin credenciales. Amplia experiencia en motores de fuerza es indispensable. MBS preferido."
    )
    payload = base_job_intelligence("Ingeniero recibido")
    payload["job_profile"]["summary"] = "Ingeniero para coordinar diseño de motores y gerencia técnica."
    payload["location_intelligence"]["raw"] = "Montevideo"
    payload["location_intelligence"]["normalized"] = "Montevideo"
    payload["requirements"]["must_have"] = [
        requirement_item("Coordinar un grupo de diseñadores de motores"),
        requirement_item("Mínimo 3 años de experiencia en gerencia"),
        requirement_item("Minimo 3 años de experiencia rn gerencia es necesario"),
        requirement_item("Inutil presentarse sin credenciales"),
        requirement_item("Amplia experiencia en motores de fuerza es indispensable"),
    ]
    payload["requirements"]["nice_to_have"] = [requirement_item("MBS preferido", "nice_to_have")]
    payload["requirements"]["experience"] = {"minimum_years": 3, "seniority": ""}
    payload["search_strategy"] = {
        "target_titles": ["Ingeniero recibido", "Ingeniero"],
        "search_terms": ["ingeniero", "motores de fuerza", "MBS", "Mínimo 3 años de experiencia en gerencia"],
        "semantic_terms": ["diseño de motores", "coordinación de equipo", "gerencia"],
        "negative_terms": [],
    }
    payload["company_clarification_questions"] = [
        question_item("¿Qué credenciales exactas son requeridas?", "requirements.blockers"),
        question_item("¿Qué significa MBS y cómo se valida?", "requirements.nice_to_have"),
    ]

    _, flat, plan = normalized_flat_and_plan(payload, source_text=source)

    assert plan["role_title"] in {"Ingeniero recibido", "Ingeniero"}
    assert plan["market"] == "Uruguay"
    assert plan["location_modality"] == "Montevideo"
    assert "Coordinar un grupo de diseñadores de motores" in plan["must_have"]
    assert "Mínimo 3 años de experiencia en gerencia" in plan["must_have"]
    assert "amplia experiencia en motores de fuerza" in all_plan_text(plan["must_have"])
    assert "mbs" in all_plan_text(plan["nice_to_have"] + plan["preferred"])
    assert "No avanzar sin credenciales requeridas" in plan["blockers"]
    assert "¿Qué credenciales exactas son requeridas?" in plan["questions"]
    assert "¿Qué significa MBS y cómo se valida?" in plan["questions"]
    for concept in ["ingeniero", "motores de fuerza", "diseño de motores", "coordinación de equipo", "gerencia", "MBS"]:
        assert fold(concept) in all_plan_text(plan["search_concepts"])
    forbidden = [
        "rn",
        "Inutil presentarse",
        "Cumplís con",
        "search_readiness_",
        "low_confidence:",
        "ai_schema_",
        "ai_provider_",
    ]
    recruiter_text = (
        plan["must_have"]
        + plan["preferred"]
        + plan["nice_to_have"]
        + plan["blockers"]
        + plan["questions"]
        + plan["search_concepts"]
    )
    for term in forbidden:
        assert fold(term) not in all_plan_text(recruiter_text)
    assert flat["display_plan"] == plan


def test_display_plan_uses_source_title_not_employer_context_for_senior_talent_partner():
    source = (
        "Consultora de RRHH busca Senior Talent Partner con experiencia en selección ejecutiva, hunting, "
        "entrevistas por competencias, perfiles tecnológicos y gestión con hiring managers."
    )
    payload = base_job_intelligence("Consultora de RRHH")
    payload["requirements"]["must_have"] = [
        requirement_item("Consultora de RRHH busca Senior Talent Partner con experiencia en selección ejecutiva")
    ]
    payload["search_strategy"]["search_terms"] = ["Consultora de RRHH", "Senior Talent Partner", "hunting"]

    _, _, plan = normalized_flat_and_plan(payload, source_text=source)

    assert plan["role_title"] == "Senior Talent Partner"
    assert "Consultora de RRHH busca Senior Talent Partner" not in all_plan_text(plan["must_have"])


def test_display_plan_strips_clinical_operations_lead_sentence_from_requirement():
    source = "Empresa de salud busca Clinical Operations Manager con pacientes, profesionales e indicadores operativos."
    payload = base_job_intelligence("Clinical Operations Manager")
    payload["requirements"]["must_have"] = [
        requirement_item("Empresa de salud busca Clinical Operations Manager con pacientes, profesionales e indicadores operativos")
    ]
    payload["search_strategy"]["search_terms"] = ["Clinical Operations Manager", "pacientes", "indicadores operativos"]

    _, _, plan = normalized_flat_and_plan(payload, source_text=source)

    assert plan["role_title"] == "Clinical Operations Manager"
    assert "Empresa de salud busca Clinical Operations Manager" not in all_plan_text(plan["must_have"])
    assert "pacientes" in all_plan_text(plan["must_have"] + plan["search_concepts"])


def test_display_plan_sparse_responsable_calidad_input_is_ok_and_clean():
    payload = base_job_intelligence("Responsable de Calidad Asistencial")
    payload["job_profile"]["summary"] = "Responsable de Calidad Asistencial para mutualista."
    payload["job_profile"]["primary_industries"] = ["salud"]
    payload["requirements"]["must_have"] = [
        requirement_item("Auditorías clínicas"),
        requirement_item("Indicadores"),
        requirement_item("Seniority: sin especificar"),
    ]
    payload["missing_information"] = [
        missing_item("work_modality", "¿Cuál es la ciudad/zona y la modalidad de trabajo?")
    ]
    payload["company_clarification_questions"] = [
        question_item("¿Cuál es la ciudad/zona y la modalidad de trabajo?", "location_intelligence")
    ]

    _, flat, plan = normalized_flat_and_plan(
        payload,
        source_text="Mutualista busca Responsable de Calidad Asistencial con auditorías clínicas e indicadores.",
    )

    assert flat["ok"] is True
    assert plan["role_title"] == "Responsable de Calidad Asistencial"
    assert "seniority sin especificar" not in all_plan_text(plan["must_have"])
    assert "search_readiness_" not in all_plan_text(plan)
    assert plan["questions"] == ["¿Cuál es la ciudad/zona y la modalidad de trabajo?"]


def test_display_plan_preserves_key_account_manager_and_deseables_as_optional():
    payload = base_job_intelligence("Key Account Manager")
    payload["requirements"]["must_have"] = [requirement_item("Gestión de grandes cuentas")]
    payload["requirements"]["should_have"] = [requirement_item("CRM deseable", "preferred")]
    payload["requirements"]["nice_to_have"] = [requirement_item("Inglés será valorable", "nice_to_have")]
    payload["search_strategy"]["search_terms"] = ["Key Account Manager", "KAM", "grandes cuentas", "CRM"]

    _, _, plan = normalized_flat_and_plan(
        payload,
        source_text="Empresa busca Key Account Manager con gestión de grandes cuentas. CRM deseable. Inglés será valorable.",
    )

    assert plan["role_title"] == "Key Account Manager"
    assert "crm" in all_plan_text(plan["preferred"])
    assert "ingles" in all_plan_text(plan["nice_to_have"])
    assert "CRM" not in all_plan_text(plan["must_have"])


def test_display_plan_does_not_turn_plain_responsibilities_into_must_have():
    payload = base_job_intelligence("Coordinador de Operaciones")
    payload["job_profile"]["summary"] = "Coordinar proveedores, reportar indicadores y apoyar mejora continua."
    payload["requirements"]["must_have"] = [requirement_item("Experiencia en operaciones")]
    payload["search_strategy"]["search_terms"] = ["Coordinador de Operaciones", "operaciones", "proveedores", "indicadores"]

    _, _, plan = normalized_flat_and_plan(
        payload,
        source_text="Coordinador de Operaciones. Responsabilidades: coordinar proveedores, reportar indicadores y apoyar mejora continua. Requisitos: experiencia en operaciones.",
    )

    assert plan["must_have"] == ["Experiencia en operaciones"]
    assert "coordinar proveedores" not in all_plan_text(plan["must_have"])


def test_display_plan_long_account_manager_jd_is_clean_and_compact():
    payload = base_job_intelligence("ACCOUNT MANAGER Semi Senior")
    payload["job_profile"]["seniority"] = "Semi Senior"
    payload["job_profile"]["summary"] = "Account Manager Semi Senior para cartera de clientes del sector salud."
    payload["job_profile"]["primary_industries"] = ["dispositivos médicos", "salud"]
    payload["location_intelligence"]["normalized"] = "Montevideo, Canelones"
    payload["requirements"]["must_have"] = [
        requirement_item("Experiencia mínima de 3 años en dispositivos médicos"),
        requirement_item("Grandes cuentas"),
        requirement_item("Venta técnica"),
        requirement_item("CRM y MS Office"),
    ]
    payload["requirements"]["nice_to_have"] = [
        requirement_item("Inglés deseable", "nice_to_have"),
        requirement_item("Experiencia en ultrasonido", "nice_to_have"),
    ]
    payload["requirements"]["experience"] = {"minimum_years": 3, "seniority": "Semi Senior"}
    payload["search_strategy"]["search_terms"] = [
        "ACCOUNT MANAGER Semi Senior",
        "Account Manager",
        "dispositivos médicos",
        "sector salud",
        "CRM",
        "MS Office",
        "ultrasonido",
    ]

    _, _, plan = normalized_flat_and_plan(
        payload,
        source_text="Estamos buscando un ACCOUNT MANAGER Semi Senior para desarrollar cartera de clientes del sector salud en Montevideo, Canelones e interior. Requisitos: experiencia mínima de 3 años en dispositivos médicos, grandes cuentas, venta técnica, CRM y MS Office. Deseable inglés, cartera propia y experiencia en ultrasonido.",
    )

    assert plan["role_title"] == "ACCOUNT MANAGER Semi Senior"
    assert plan["market"] == "Uruguay"
    assert "Montevideo" in plan["location_modality"]
    assert len(plan["search_concepts"]) <= 14
    assert "search_readiness_" not in all_plan_text(plan)


def test_openai_response_path_returns_display_plan_from_normalized_payload():
    payload = base_job_intelligence("Consultora de RRHH")
    payload["requirements"]["must_have"] = [
        requirement_item("No avanzar perfiles sin experiencia en selección ejecutiva"),
        requirement_item("No excluyente"),
        requirement_item("Consultora de RRHH busca Senior Talent Partner con experiencia en selección ejecutiva"),
    ]
    payload["requirements"]["nice_to_have"] = [requirement_item("Hunting será un plus", "nice_to_have")]
    payload["search_strategy"]["search_terms"] = ["Senior Talent Partner", "search_readiness_exploratory", "hunting"]
    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="test-model",
        client=FakeOpenAIClient(response={"output_parsed": payload}),
        fallback_enabled=False,
    )

    result = extractor.extract(
        ExtractorRequest(
            source_text="Consultora de RRHH busca Senior Talent Partner con experiencia en selección ejecutiva. Hunting será un plus. No avanzar perfiles sin experiencia en selección ejecutiva.",
            locale="es-UY",
            country_context="UY",
            candidate_market="UY",
            employer_market="UY",
            source_filename="",
            source_mime_type="text/plain",
            recruiter_notes="",
        )
    )

    plan = result["display_plan"]
    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert plan["role_title"] == "Senior Talent Partner"
    assert "No avanzar perfiles sin experiencia en selección ejecutiva" in plan["blockers"]
    assert "No avanzar" not in all_plan_text(plan["must_have"] + plan["preferred"] + plan["nice_to_have"])
    assert "No excluyente" not in all_plan_text(plan)
    assert "search_readiness_" not in all_plan_text(plan)


def test_display_plan_questions_come_from_one_pass_precision_contract_and_are_deduped():
    questions = [
        "¿Qué categoría, certificación o experiencia valida que el candidato sea oficial de primera?",
        "¿Cuántos años mínimos o qué evidencia concreta se considera suficiente para demostrar la experiencia?",
        "¿Qué documentación exacta debe tener el candidato en regla?",
        "¿Qué significa MBS en este contexto y cómo debe validarse en el CV?",
        "¿Cuántos años y qué tipo de experiencia en motores se consideran suficientes?",
    ]
    payload = base_job_intelligence("Mecánico de coches")
    payload["requirements"]["must_have"] = [
        imprecise_requirement_item("Oficial de primera", "must_have", ["evidence", "equivalence"], questions[0]),
        imprecise_requirement_item("Experiencia demostrable", "must_have", ["duration", "evidence"], questions[1]),
        imprecise_requirement_item("Papeles en regla", "must_have", ["legal_documentation"], questions[2]),
        imprecise_requirement_item("Amplia experiencia en motores", "must_have", ["duration", "scope"], questions[4]),
    ]
    payload["requirements"]["nice_to_have"] = [
        imprecise_requirement_item("MBS preferido", "nice_to_have", ["undefined_acronym"], questions[3])
    ]
    payload["company_clarification_questions"] = [
        question_item(questions[3], "requirements.nice_to_have"),
        question_item(questions[3], "requirements.nice_to_have"),
    ]

    normalized, flat, plan = normalized_flat_and_plan(
        payload,
        source_text=(
            "Necesitamos mecánico de coches oficial de primera, con experiencia demostrable, "
            "carnet de conducir y papeles en regla. Amplia experiencia en motores de fuerza. MBS preferido."
        ),
    )

    all_questions = plan["questions"]
    assert all(question in all_questions for question in questions)
    assert all_questions.count(questions[3]) == 1
    assert flat["recruiter_questions"].count(questions[3]) == 1
    assert normalized["search_readiness"]["status"] == "insufficient_for_precise_search"
    assert "cumplis" not in all_plan_text(all_questions)
    assert "podes ampliar" not in all_plan_text(all_questions)
    assert "search_readiness_" not in all_plan_text(plan)
    for bucket in ("must_have", "nice_to_have"):
        for item in normalized["requirements"][bucket]:
            assert item["precision_status"] in {"precise", "needs_clarification"}


def test_precise_criteria_do_not_generate_unnecessary_precision_questions():
    payload = base_job_intelligence("Gerente")
    payload["requirements"]["must_have"] = [
        requirement_item("Mínimo 3 años de experiencia en gerencia"),
    ]
    payload["requirements"]["credentials"] = [
        requirement_item("Licencia de conducir categoría C excluyente"),
    ]
    payload["location_intelligence"]["raw"] = "Trabajo híbrido en Montevideo, dos días remotos por semana"
    payload["location_intelligence"]["normalized"] = "Montevideo"
    payload["location_intelligence"]["hybrid_allowed"] = True
    payload["location_intelligence"]["remote_allowed"] = True

    _, _, plan = normalized_flat_and_plan(
        payload,
        source_text=(
            "Experiencia mínima de 3 años en gerencia. Licencia de conducir categoría C excluyente. "
            "Trabajo híbrido en Montevideo, dos días remotos por semana."
        ),
    )

    questions = all_plan_text(plan["questions"])
    assert "anos" not in questions
    assert "años" not in questions
    assert "categoria" not in questions
    assert "modalidad" not in questions


def test_optional_health_experience_can_ask_scope_without_becoming_must_have():
    question = "¿Qué contexto del sector salud es más relevante para validar esa experiencia?"
    payload = base_job_intelligence("Ejecutivo Comercial")
    payload["requirements"]["should_have"] = [
        imprecise_requirement_item("Deseable experiencia en salud", "preferred", ["scope"], question)
    ]

    _, flat, plan = normalized_flat_and_plan(
        payload,
        source_text="Deseable experiencia en salud.",
    )

    assert flat["must_have"] == []
    assert "salud" in all_plan_text(flat["should_have"] + plan["preferred"])
    assert question in plan["questions"]


def test_mechanic_display_plan_uses_canonical_registries_without_invented_specificity():
    source = (
        "Necesitamos mecanico de coches\n\n"
        "oficial de primera, con experiencia demostrable que haga todo tipo de reparaciones y con carnet de conducir\n\n"
        "asalariado o autonomo y papeles en regla\n\n"
        "salario segun convenio"
    )
    questions = [
        "¿Qué categoría, certificación o experiencia valida que el candidato sea oficial de primera?",
        "¿Cuántos años mínimos o qué evidencia concreta se considera suficiente para demostrar la experiencia?",
        "¿Qué alcance concreto de reparaciones debe poder realizar?",
        "¿Qué categoría de licencia de conducir se requiere?",
        "¿Qué documentación exacta debe tener el candidato en regla?",
    ]
    payload = base_job_intelligence("Mecánico de coches")
    payload["requirements"]["must_have"] = [
        imprecise_requirement_item("Oficial de primera", "must_have", ["evidence", "equivalence"], questions[0]),
        imprecise_requirement_item("Experiencia demostrable", "must_have", ["duration", "evidence"], questions[1]),
        imprecise_requirement_item(
            "Con experiencia demostrable que haga todo tipo de reparaciones y con carnet de conducir",
            "must_have",
            ["duration", "evidence", "scope", "license_category"],
            questions[2],
        ),
        imprecise_requirement_item("Papeles en regla", "must_have", ["legal_documentation"], questions[4]),
        requirement_item("Asalariado o autónomo"),
        requirement_item("Salario según convenio"),
    ]
    payload["requirements"]["credentials"] = [
        imprecise_requirement_item(
            "Carnet de conducir (categoría no especificada)",
            "must_have",
            ["license_category"],
            questions[3],
        ),
        imprecise_requirement_item("Carnet B", "must_have", ["license_category"], questions[3]),
    ]
    payload["requirements"]["blockers"] = ["No avanzar sin papeles en regla"]
    payload["search_strategy"]["search_terms"] = [
        "Mecánico de coches",
        "carnet B",
        "carnet de conducir",
        "salario según convenio",
    ]
    payload["search_strategy"]["semantic_terms"] = ["asalariado", "autónomo", "reparaciones generales"]
    payload["company_clarification_questions"] = [
        question_item(questions[0], "requirements.must_have"),
        question_item(questions[1], "requirements.must_have"),
        question_item(questions[2], "requirements.must_have"),
        question_item(questions[3], "requirements.credentials"),
        question_item(questions[3], "requirements.credentials"),
        question_item(questions[4], "requirements.must_have"),
        {
            "id": "candidate_bad",
            "question": "¿Tienes carnet B y puedes aportar papeles?",
            "related_fields": ["candidate_screening_questions"],
            "asked_to": "candidate",
        },
    ]
    payload["candidate_screening_questions"] = [
        {"question": "¿Puedes aportar papeles en regla?", "asked_to": "candidate"}
    ]
    payload["search_readiness"]["status"] = "ready"
    original_payload = copy.deepcopy(payload)

    canonical_once = canonicalize_job_intelligence(payload, source_text=source)
    canonical_twice = canonicalize_job_intelligence(canonical_once, source_text=source)
    normalized, flat, plan = normalized_flat_and_plan(payload, source_text=source)

    assert payload == original_payload
    assert canonical_twice == canonical_once
    assert canonicalize_job_intelligence(normalized, source_text=source) == normalized

    all_text = all_plan_text([normalized, flat, plan])
    criteria_text = all_plan_text(
        flat["must_have"]
        + flat["should_have"]
        + flat["nice_to_have"]
        + flat["credentials"]["required"]
        + flat["credentials"]["preferred"]
        + plan["tie_breakers"]
        + plan["search_concepts"]
    )
    recruiter_questions = plan["questions"]
    question_text = all_plan_text(recruiter_questions)

    assert flat["ok"] is True
    assert plan["role_title"] == "Mecánico de coches"
    assert "carnet b" not in all_text
    assert len(recruiter_questions) == 5
    assert question_text.count("carnet de conducir") == 1
    assert question_text.count("documentacion") == 1
    assert question_text.count("cuantos anos") == 1
    assert question_text.count("evidencia") == 1
    assert question_text.count("reparaciones") == 1
    assert question_text.count("oficial de primera") == 1
    assert "tienes" not in question_text
    assert "puedes aportar" not in question_text
    assert flat["recruiter_questions"] == recruiter_questions
    assert flat["candidate_screening_questions"] == ["¿Puedes aportar papeles en regla?"]
    assert all_plan_text(flat["must_have"] + flat["credentials"]["required"]).count("carnet de conducir") == 1
    assert "con experiencia demostrable que haga todo tipo de reparaciones y con carnet de conducir" not in criteria_text
    assert "salario" not in criteria_text
    assert "convenio" not in criteria_text
    assert "asalariado" not in criteria_text
    assert "autonomo" not in criteria_text
    assert normalized["job_context"]["employment_terms"] == ["Asalariado o autónomo"]
    assert normalized["job_context"]["compensation"] == ["Salario según convenio"]
    assert "papeles en regla" not in all_plan_text(plan["blockers"])
    assert plan["readiness"]["code"] != "ready"
    assert plan["readiness"]["code"] == "insufficient-for-precise-search"
    assert plan["readiness"]["severity"] == "warning"
    assert normalized["search_readiness"]["recruiter_decision_required"] is True
    assert plan["professional_grade"] == "Oficial de primera"
    assert not plan["seniority"]
    criteria = plan["criteria_review"]
    criterion_ids = [item["criterion_id"] for item in criteria]
    question_ids = [item["question_id"] for item in plan["question_registry"]]
    canonical_items = [
        item
        for bucket in ("must_have", "should_have", "nice_to_have", "credentials")
        for item in normalized["requirements"].get(bucket, [])
    ]
    by_kind = {item["canonical_kind"]: item for item in canonical_items}
    assert len(criteria) == 5
    assert len(canonical_items) == 5
    assert set(by_kind) == {
        "professional_grade",
        "experience",
        "technical_scope",
        "driving_license",
        "legal_documentation",
    }
    assert by_kind["professional_grade"]["text"] == "Oficial de primera"
    assert by_kind["professional_grade"]["missing_dimensions"] == ["equivalence", "evidence"]
    assert by_kind["experience"]["text"] == "Experiencia demostrable como mecánico"
    assert by_kind["experience"]["missing_dimensions"] == ["duration", "evidence"]
    assert by_kind["technical_scope"]["text"] == "Realizar todo tipo de reparaciones"
    assert by_kind["technical_scope"]["missing_dimensions"] == ["scope"]
    assert by_kind["driving_license"]["text"] == "Carnet de conducir"
    assert by_kind["driving_license"]["missing_dimensions"] == ["license_category"]
    assert by_kind["legal_documentation"]["text"] == "Papeles en regla"
    assert by_kind["legal_documentation"]["missing_dimensions"] == ["legal_documentation"]
    assert len([item for item in canonical_items if item.get("canonical_kind") == "technical_scope"]) == 1
    assert len(criterion_ids) == len(set(criterion_ids))
    assert len(question_ids) == len(set(question_ids))
    assert all(item["precision_status"] == "needs_clarification" for item in criteria)
    assert all(item["review_status"] == "pending_recruiter_confirmation" for item in criteria)
    assert all(item["clarification_question_id"] in question_ids for item in criteria)
    questions_by_id = {item["question_id"]: item for item in plan["question_registry"]}
    for item in criteria:
        linked = questions_by_id[item["clarification_question_id"]]
        assert item["criterion_id"] in linked["criterion_refs"]
    questions_by_ref = {ref: item["question"] for item in plan["question_registry"] for ref in item["criterion_refs"]}
    assert "oficial de primera" in all_plan_text(questions_by_ref[by_kind["professional_grade"]["criterion_id"]])
    assert "experiencia demostrable" in all_plan_text(questions_by_ref[by_kind["experience"]["criterion_id"]])
    assert "reparaciones" in all_plan_text(questions_by_ref[by_kind["technical_scope"]["criterion_id"]])
    assert "carnet de conducir" in all_plan_text(questions_by_ref[by_kind["driving_license"]["criterion_id"]])
    legal_question = all_plan_text(questions_by_ref[by_kind["legal_documentation"]["criterion_id"]])
    assert "documentacion" in legal_question
    assert "regla" in legal_question
