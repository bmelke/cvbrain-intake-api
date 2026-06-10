import json
import unicodedata

from fastapi.testclient import TestClient

from app.extractors import ExtractorRequest
from app.extractors.openai_structured import OpenAIStructuredExtractor
from app.main import app
from app.mappers.job_intelligence_to_flat import derive_flat_compatibility
from app.normalization.requirement_importance import normalize_job_intelligence_requirements
from app.schemas.job_intelligence_v1_contract import validate_job_intelligence_v1


client = TestClient(app)

FULL_GA_SUPPORT_REQUEST = """La posicion apunta a soporte tecnico de primer nivel para usuarios internos y clientes corporativos.

Rol: Tecnico de Soporte IT Junior.

Excluyente experiencia de al menos 1 ano resolviendo incidentes de hardware, software, redes basicas y soporte remoto. Imprescindible buena comunicacion y registro de tickets.

Credenciales requeridas: formacion tecnica en informatica o certificacion equivalente. Libreta de conducir categoria A valorable para visitas puntuales.

Trabajo hibrido en Montevideo, con guardias coordinadas. Deseable conocimientos de Microsoft 365, Active Directory y herramientas de mesa de ayuda.

Sin experiencia no avanzar para este rol de soporte."""

FULL_GA_MUST_HAVE = [
    "Experiencia de al menos 1 año resolviendo incidentes de hardware",
    "Experiencia de al menos 1 año resolviendo incidentes de software",
    "Experiencia de al menos 1 año resolviendo incidentes de redes básicas",
    "Experiencia de al menos 1 año brindando soporte remoto",
    "Buena comunicación",
    "Registro de tickets",
    "Formación técnica en informática o certificación equivalente",
]

FULL_GA_PREFERRED = [
    "Conocimientos de Microsoft 365",
    "Conocimientos de Active Directory",
    "Conocimientos de herramientas de mesa de ayuda",
]

ORPHAN_FRAGMENTS = [
    "software",
    "redes basicas",
    "redes básicas",
    "y soporte remoto",
    "y registro de tickets",
    "Excluyente experiencia de al menos 1 ano resolviendo incidentes de",
]


def fold(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def assert_no_orphan_fragments(items):
    normalized_items = [fold(item).strip(" -:.,;") for item in items]
    for item in normalized_items:
        assert not item.startswith(("y ", "e ", "o ", "and ", "or ")), items
    for orphan in ORPHAN_FRAGMENTS:
        orphan_folded = fold(orphan)
        assert orphan_folded not in normalized_items, items


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


def minimal_job_intelligence(requirements):
    return {
        "schema_version": "cvbrain_job_intelligence_v1",
        "job_profile": {
            "job_title": "Technical Support",
            "normalized_role_title": "Technical Support",
            "role_family": "support",
            "seniority": "",
            "summary": "Sanitized mixed-importance intake.",
            "primary_industries": [],
            "work_modality": "",
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
            "must_have": requirements.get("must_have", []),
            "should_have": requirements.get("should_have", []),
            "nice_to_have": requirements.get("nice_to_have", []),
            "credentials": requirements.get("credentials", []),
            "blockers": requirements.get("blockers", []),
            "experience": {"minimum_years": None, "seniority": ""},
            "soft_competencies": [],
        },
        "search_strategy": {
            "target_titles": ["Technical Support"],
            "search_terms": ["Technical Support"],
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
            "decision_options": ["continue_anyway", "use_manual_search", "cancel"],
        },
        "quality_control": {
            "warnings": [],
            "confidence": 0.82,
            "contains_candidate_data": False,
            "contains_candidate_pii": False,
        },
    }


def requirement_item(text, importance):
    return {
        "text": text,
        "source_text": text,
        "importance": importance,
        "explicit": True,
        "hard_filter_candidate": importance == "must_have",
        "hard_filter_approved": False,
    }


class FakeResponses:
    def __init__(self, response):
        self.response = response

    def create(self, **kwargs):
        return self.response


class FakeOpenAIClient:
    def __init__(self, response):
        self.responses = FakeResponses(response)


def test_plain_valorable_resolves_to_nice_to_have(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "deterministic")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload("Libreta de conducir categoria A valorable para visitas puntuales."),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["must_have"] == []
    assert data["should_have"] == []
    assert data["nice_to_have"] == ["Libreta de conducir categoría A"]
    assert "libreta de conducir categoria a" not in fold(data["credentials"]["required"])
    assert "libreta de conducir categoria a" in fold(data["credentials"]["preferred"])


def test_muy_valorable_resolves_to_should_have(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "deterministic")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload("Muy valorable experiencia con Salesforce."),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["must_have"] == []
    assert data["should_have"] == ["Experiencia con Salesforce"]
    assert data["nice_to_have"] == []


def test_hard_category_soft_local_credential_item_is_not_must_have(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "deterministic")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(
            "Credenciales requeridas: formacion tecnica en informatica o certificacion equivalente. "
            "Libreta de conducir categoría A valorable para visitas puntuales."
        ),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["must_have"] == ["Formación técnica en informática o certificación equivalente"]
    assert data["should_have"] == []
    assert data["nice_to_have"] == ["Libreta de conducir categoría A"]
    assert data["credentials"]["required"] == ["Formación técnica en informática o certificación equivalente"]

    assert "libreta de conducir categoria a" not in fold(data["must_have"])
    assert "libreta de conducir categoria a" not in fold(data["should_have"])
    assert "libreta de conducir categoria a" not in fold(data["credentials"]["required"])
    assert "libreta de conducir categoria a" in fold(data["credentials"]["preferred"])
    assert "capacidad para visitas puntuales" not in fold(data["must_have"])


def test_soft_category_hard_local_travel_item_becomes_must_have_and_blocker(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "deterministic")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(
            "Nice to have: título de administración de empresas, carnet de conducir, "
            "no presentarse a menos que pueda viajar."
        ),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["nice_to_have"] == ["Título de administración de empresas", "Carnet de conducir"]
    assert data["must_have"] == ["Disponibilidad para viajar"]
    assert "disponibilidad para viajar" not in fold(data["nice_to_have"])
    assert data["blockers"] == ["No avanzar si no puede viajar"]


def test_neutral_section_mixed_local_modifiers_are_resolved_independently(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "deterministic")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(
            "Requisitos: experiencia en soporte técnico excluyente, Microsoft 365 deseable, "
            "buena comunicación imprescindible."
        ),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert "experiencia en soporte tecnico" in fold(data["must_have"])
    assert "buena comunicacion" in fold(data["must_have"])
    assert "microsoft 365" not in fold(data["must_have"])
    assert "microsoft 365" in fold(data["should_have"] + data["nice_to_have"])


def test_hard_coordinated_experience_list_expands_complete_items(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "deterministic")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(
            "Excluyente experiencia de al menos 1 ano resolviendo incidentes de hardware, "
            "software, redes basicas y soporte remoto."
        ),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["must_have"] == FULL_GA_MUST_HAVE[:4]
    assert data["should_have"] == []
    assert data["nice_to_have"] == []
    assert_no_orphan_fragments(data["must_have"])


def test_soft_coordinated_knowledge_list_expands_complete_preferred_items(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "deterministic")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(
            "Deseable conocimientos de Microsoft 365, Active Directory y herramientas de mesa de ayuda."
        ),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["must_have"] == []
    assert data["should_have"] == FULL_GA_PREFERRED
    assert data["nice_to_have"] == []
    assert_no_orphan_fragments(data["should_have"])


def test_compound_communication_and_ticketing_requirement_splits_without_dangling_conjunction(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "deterministic")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload("Imprescindible buena comunicacion y registro de tickets."),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["must_have"] == ["Buena comunicación", "Registro de tickets"]
    assert data["should_have"] == []
    assert_no_orphan_fragments(data["must_have"])


def test_structured_requirements_are_rebucketed_before_flat_mapping():
    payload = minimal_job_intelligence(
        {
            "must_have": [
                requirement_item(
                    "formacion tecnica en informatica o certificacion equivalente. "
                    "Libreta de conducir categoría A valorable para visitas puntuales.",
                    "must_have",
                )
            ],
            "nice_to_have": [
                requirement_item(
                    "título de administración de empresas, carnet de conducir, "
                    "no presentarse a menos que pueda viajar",
                    "nice_to_have",
                )
            ],
        }
    )

    normalized = normalize_job_intelligence_requirements(payload)
    flat = derive_flat_compatibility(payload)

    assert "formacion tecnica en informatica o certificacion equivalente" in fold(
        normalized["requirements"]["must_have"]
    )
    assert "libreta de conducir categoria a" not in fold(normalized["requirements"]["must_have"])
    assert "libreta de conducir categoria a" not in fold(normalized["requirements"]["should_have"])
    assert "libreta de conducir categoria a" in fold(normalized["requirements"]["nice_to_have"])
    assert "disponibilidad para viajar" in fold(normalized["requirements"]["must_have"])
    assert "no avanzar si no puede viajar" in fold(normalized["requirements"]["blockers"])

    assert "libreta de conducir categoria a" not in fold(flat["must_have"])
    assert "libreta de conducir categoria a" not in fold(flat["should_have"])
    assert "libreta de conducir categoria a" in fold(flat["nice_to_have"])
    assert "disponibilidad para viajar" in fold(flat["must_have"])
    assert "disponibilidad para viajar" not in fold(flat["nice_to_have"])
    assert "no avanzar si no puede viajar" in fold(flat["blockers"])
    assert "libreta de conducir categoria a" not in fold(flat["credentials"]["required"])
    assert "libreta de conducir categoria a" in fold(flat["credentials"]["preferred"])


def test_full_ga_support_request_resolves_item_importance_without_leakage(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)
    monkeypatch.setenv("CVBRAIN_EXTRACTOR_MODE", "deterministic")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(FULL_GA_SUPPORT_REQUEST),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True

    must = fold(data["must_have"])
    credentials_required = fold(data["credentials"]["required"])
    credentials_preferred = fold(data["credentials"]["preferred"])
    blockers = fold(data["blockers"])

    assert data["must_have"] == FULL_GA_MUST_HAVE
    assert data["should_have"] == FULL_GA_PREFERRED
    assert data["nice_to_have"] == ["Libreta de conducir categoría A"]
    assert_no_orphan_fragments(data["must_have"])

    assert "sin experiencia no avanzar" in blockers
    assert "sin experiencia no avanzar" not in must

    for forbidden in [
        "libreta de conducir",
        "microsoft 365",
        "active directory",
        "herramientas de mesa de ayuda",
    ]:
        assert forbidden not in must

    assert "libreta de conducir categoria a" not in credentials_required
    assert "libreta de conducir categoria a" in credentials_preferred
    assert "libreta de conducir categoria a" not in fold(data["should_have"])
    assert "microsoft 365" in fold(data["should_have"])
    assert "active directory" in fold(data["should_have"])
    assert "herramientas de mesa de ayuda" in fold(data["should_have"])


def test_full_ga_structured_output_is_normalized_before_schema_validation():
    payload = minimal_job_intelligence(
        {
            "must_have": [
                requirement_item(
                    "Excluyente experiencia de al menos 1 ano resolviendo incidentes de hardware, "
                    "software, redes basicas y soporte remoto",
                    "must_have",
                ),
                requirement_item("Imprescindible buena comunicacion y registro de tickets", "must_have"),
                requirement_item(
                    "Credenciales requeridas: formacion tecnica en informatica o certificacion equivalente. "
                    "Libreta de conducir categoria A valorable para visitas puntuales.",
                    "must_have",
                ),
            ],
            "should_have": [
                {
                    **requirement_item(
                        "Deseable conocimientos de Microsoft 365, Active Directory y herramientas de mesa de ayuda",
                        "preferred",
                    ),
                    "hard_filter_candidate": True,
                    "hard_filter_approved": True,
                }
            ],
            "blockers": [
                "Sin experiencia no avanzar para este rol de soporte.",
                "Sin experiencia no avanzar para este rol de soporte",
            ],
        }
    )
    payload["job_profile"]["job_title"] = "Tecnico de Soporte IT Junior"
    payload["job_profile"]["normalized_role_title"] = "Tecnico de Soporte IT Junior"
    payload["location_intelligence"]["raw"] = "Trabajo hibrido en Montevideo"
    payload["location_intelligence"]["normalized"] = "Montevideo"
    payload["location_intelligence"]["hybrid_allowed"] = True

    normalized = normalize_job_intelligence_requirements(payload)
    flat = derive_flat_compatibility(payload)

    must = fold(flat["must_have"])
    credentials_required = fold(flat["credentials"]["required"])
    credentials_preferred = fold(flat["credentials"]["preferred"])

    assert flat["must_have"] == FULL_GA_MUST_HAVE
    assert_no_orphan_fragments(flat["must_have"])

    for forbidden in [
        "libreta de conducir",
        "microsoft 365",
        "active directory",
        "herramientas de mesa de ayuda",
    ]:
        assert forbidden not in must

    assert "libreta de conducir categoria a" not in credentials_required
    assert "libreta de conducir categoria a" in credentials_preferred
    assert "formacion tecnica en informatica o certificacion equivalente" in credentials_required
    assert "formacion tecnica en informatica o certificacion equivalente" not in credentials_preferred

    assert flat["should_have"] == FULL_GA_PREFERRED
    assert flat["nice_to_have"] == ["Libreta de conducir categoría A"]
    assert "microsoft 365" in fold(flat["should_have"])
    assert "active directory" in fold(flat["should_have"])
    assert "herramientas de mesa de ayuda" in fold(flat["should_have"])
    assert normalized["requirements"]["should_have"][0]["hard_filter_approved"] is False
    assert normalized["requirements"]["blockers"] == ["Sin experiencia no avanzar para este rol de soporte."]


def test_soft_competencies_hard_filter_flags_are_removed_before_schema_validation():
    payload = minimal_job_intelligence(
        {
            "must_have": [
                requirement_item("Imprescindible buena comunicacion y registro de tickets", "must_have"),
            ],
        }
    )
    payload["requirements"]["soft_competencies"] = [
        {
            **requirement_item("Comunicación", "must_have"),
            "hard_filter_candidate": True,
            "hard_filter_approved": True,
        },
        {
            **requirement_item("Registro y documentación mediante tickets", "must_have"),
            "hard_filter_candidate": True,
            "hard_filter_approved": True,
        },
    ]

    normalized = normalize_job_intelligence_requirements(
        payload,
        source_text="Imprescindible buena comunicacion y registro de tickets.",
    )
    validate_job_intelligence_v1(normalized)
    flat = derive_flat_compatibility(normalized)

    assert flat["must_have"] == ["Buena comunicación", "Registro de tickets"]
    assert "buena comunicacion" in fold(flat["must_have"])
    assert "registro de tickets" in fold(flat["must_have"])
    for item in normalized["requirements"]["soft_competencies"]:
        assert item["hard_filter_candidate"] is False
        assert item["hard_filter_approved"] is False


def test_full_ga_openai_flow_returns_success_after_requirement_normalization():
    payload = minimal_job_intelligence(
        {
            "must_have": [
                requirement_item("Al menos 1 año de experiencia resolviendo incidentes de hardware", "must_have"),
                requirement_item(
                    "Excluyente experiencia de al menos 1 ano resolviendo incidentes de hardware, "
                    "software, redes basicas y soporte remoto",
                    "must_have",
                ),
                requirement_item("software", "must_have"),
                requirement_item("Excluyente experiencia de al menos 1 ano resolviendo incidentes de", "must_have"),
                requirement_item("redes basicas", "must_have"),
                requirement_item("y soporte remoto", "must_have"),
                requirement_item("Imprescindible buena comunicacion y registro de tickets", "must_have"),
                requirement_item("y registro de tickets", "must_have"),
                requirement_item(
                    "Credenciales requeridas: formacion tecnica en informatica o certificacion equivalente. "
                    "Libreta de conducir categoria A valorable para visitas puntuales.",
                    "must_have",
                ),
            ],
            "should_have": [
                {
                    **requirement_item(
                        "Deseable conocimientos de Microsoft 365, Active Directory y herramientas de mesa de ayuda",
                        "preferred",
                    ),
                    "hard_filter_candidate": True,
                    "hard_filter_approved": True,
                }
            ],
            "blockers": ["Sin experiencia no avanzar para este rol de soporte"],
        }
    )
    payload["requirements"]["soft_competencies"] = [
        {
            **requirement_item("Comunicación", "must_have"),
            "hard_filter_candidate": True,
            "hard_filter_approved": True,
        },
        {
            **requirement_item("Registro y documentación mediante tickets", "must_have"),
            "hard_filter_candidate": True,
            "hard_filter_approved": True,
        },
    ]
    payload["job_profile"]["job_title"] = "Tecnico de Soporte IT Junior"
    payload["job_profile"]["normalized_role_title"] = "Tecnico de Soporte IT Junior"

    extractor = OpenAIStructuredExtractor(
        api_key="test-key-not-used",
        model="gpt-5.4-nano",
        client=FakeOpenAIClient(response={"output_parsed": payload}),
    )

    result = extractor.extract(
        ExtractorRequest(
            source_text=FULL_GA_SUPPORT_REQUEST,
            locale="es-UY",
            country_context="UY",
            candidate_market="UY",
            employer_market="UY",
        )
    )

    assert result["ok"] is True
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert result["ai_model"] == "gpt-5.4-nano"
    assert result["must_have"] == FULL_GA_MUST_HAVE
    assert result["should_have"] == FULL_GA_PREFERRED
    assert result["nice_to_have"] == ["Libreta de conducir categoría A"]
    assert_no_orphan_fragments(result["must_have"])
    ji_must_have = [item["text"] for item in result["job_intelligence"]["requirements"]["must_have"]]
    assert_no_orphan_fragments(ji_must_have)
    assert ji_must_have == FULL_GA_MUST_HAVE
    assert "libreta de conducir" not in fold(result["must_have"])
    assert "microsoft 365" not in fold(result["must_have"])
    assert "active directory" not in fold(result["must_have"])
    assert "herramientas de mesa de ayuda" not in fold(result["must_have"])
    assert "libreta de conducir categoria a" not in fold(result["credentials"]["required"])
    assert "libreta de conducir categoria a" in fold(result["credentials"]["preferred"])
    for item in result["job_intelligence"]["requirements"]["soft_competencies"]:
        assert item["hard_filter_candidate"] is False
        assert item["hard_filter_approved"] is False
