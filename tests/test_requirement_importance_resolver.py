import json
import unicodedata

from fastapi.testclient import TestClient

from app.main import app
from app.mappers.job_intelligence_to_flat import derive_flat_compatibility
from app.normalization.requirement_importance import normalize_job_intelligence_requirements


client = TestClient(app)


def fold(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


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
    assert "formacion tecnica en informatica o certificacion equivalente" in fold(data["must_have"])
    assert "formacion tecnica en informatica o certificacion equivalente" in fold(data["credentials"]["required"])

    assert "libreta de conducir categoria a" not in fold(data["must_have"])
    assert "libreta de conducir categoria a" not in fold(data["credentials"]["required"])
    assert "libreta de conducir categoria a" in fold(data["should_have"] + data["nice_to_have"])
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
    assert "titulo de administracion de empresas" in fold(data["nice_to_have"])
    assert "carnet de conducir" in fold(data["nice_to_have"])
    assert "disponibilidad para viajar" in fold(data["must_have"])
    assert "disponibilidad para viajar" not in fold(data["nice_to_have"])
    assert "no avanzar si no puede viajar" in fold(data["blockers"])


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
    assert "libreta de conducir categoria a" in fold(normalized["requirements"]["should_have"])
    assert "disponibilidad para viajar" in fold(normalized["requirements"]["must_have"])
    assert "no avanzar si no puede viajar" in fold(normalized["requirements"]["blockers"])

    assert "libreta de conducir categoria a" not in fold(flat["must_have"])
    assert "libreta de conducir categoria a" in fold(flat["should_have"] + flat["nice_to_have"])
    assert "disponibilidad para viajar" in fold(flat["must_have"])
    assert "disponibilidad para viajar" not in fold(flat["nice_to_have"])
    assert "no avanzar si no puede viajar" in fold(flat["blockers"])
    assert "libreta de conducir categoria a" not in fold(flat["credentials"]["required"])
    assert "libreta de conducir categoria a" in fold(flat["credentials"]["preferred"])
