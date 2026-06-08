import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


SANITIZED_PILOT_CASES = [
    {
        "title": "Account Manager / medical devices",
        "text": "Account Manager Semi Senior - dispositivos medicos\nExperiencia minima de 3 anos en venta tecnica B2B de dispositivos medicos para clientes de salud. Deseable CRM y pipeline. Ubicacion Montevideo, hibrido.",
        "role_contains": "Account Manager",
        "minimum_years": 3,
        "terms": ["Account Manager", "dispositivos medicos", "crm", "montevideo"],
    },
    {
        "title": "Sales Executive B2B",
        "text": "Sales Executive B2B\nBuscamos perfil comercial para ventas B2B y prospeccion de cuentas. Minima de 2 anos de experiencia. Deseable manejo de CRM. Ubicacion Montevideo.",
        "role_contains": "Sales Executive B2B",
        "minimum_years": 2,
        "terms": ["Sales Executive B2B", "ventas b2b", "crm", "montevideo"],
    },
    {
        "title": "Administrative Assistant",
        "text": "Administrative Assistant\nAsistente administrativa para soporte documental, agenda, facturacion y atencion interna. Minima de 1 ano de experiencia. Deseable Excel.",
        "role_contains": "Administrative Assistant",
        "minimum_years": 1,
        "terms": ["Administrative Assistant", "administrativa", "excel"],
    },
    {
        "title": "Technical Support",
        "text": "Technical Support\nSoporte tecnico nivel 1 para mesa de ayuda y help desk. Minima de 2 anos de experiencia. Deseable ingles y modalidad hibrida en Montevideo.",
        "role_contains": "Technical Support",
        "minimum_years": 2,
        "terms": ["Technical Support", "soporte tecnico", "help desk", "ingles", "montevideo"],
    },
    {
        "title": "Logistics Coordinator",
        "text": "Logistics Coordinator\nCoordinador de logistica para seguimiento de entregas, documentacion y proveedores. Minima de 2 anos de experiencia. Deseable Excel. Ubicacion Canelones.",
        "role_contains": "Logistics Coordinator",
        "minimum_years": 2,
        "terms": ["Logistics Coordinator", "logistica", "coordinador", "excel", "canelones"],
    },
]


def analyze_payload(source_text):
    return {
        "source_text": source_text,
        "source_filename": "",
        "source_mime_type": "text/plain",
        "recruiter_notes": "",
        "locale": "es-UY",
    }


def test_health():
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert data["service"] == "cvbrain-intake-api"
    assert data["product"] == "CVBrain"
    assert data["version"] == "0.1.0"


def test_health_remains_public_when_api_key_env_set(monkeypatch):
    monkeypatch.setenv("CVBRAIN_INTAKE_API_KEY", "test-key")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_analyze_allowed_without_api_key_env(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(
            "Account Manager Semi Senior con experiencia en dispositivos medicos. Minima de 3 anos. Deseable CRM. Ubicación Montevideo, híbrido."
        ),
    )

    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert data["version"] == "0.1.0"
    assert "Account Manager" in data["role_title"]
    assert data["experience"]["minimum_years"] == 3
    assert data["experience"]["seniority"] == "semi senior"
    assert data["location"]["normalized"] == "Montevideo"
    assert data["location"]["hybrid_allowed"] is True
    assert "credentials" in data
    assert "search_terms" in data


def test_account_manager_medical_devices_montevideo_contract(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(
            "Account Manager Semi Senior con experiencia en dispositivos médicos.\n"
            "Mínima de 3 años.\n"
            "Deseable CRM.\n"
            "Ubicación Montevideo, híbrido."
        ),
    )

    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert data["role_title"] == "Account Manager Semi Senior"
    assert "dispositivos médicos" in data["search_terms"]
    assert data["location"]["normalized"] == "Montevideo"
    assert data["location"]["hybrid_allowed"] is True
    assert data["experience"]["minimum_years"] == 3


def test_analyze_requires_api_key_when_env_set(monkeypatch):
    monkeypatch.setenv("CVBRAIN_INTAKE_API_KEY", "test-key")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload("Sales Executive B2B con experiencia comercial."),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_api_key"


def test_analyze_rejects_wrong_api_key_when_env_set(monkeypatch):
    monkeypatch.setenv("CVBRAIN_INTAKE_API_KEY", "test-key")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload("Sales Executive B2B con experiencia comercial."),
        headers={"X-CVBrain-API-Key": "wrong-key"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_api_key"


def test_analyze_allows_cvbrain_api_key_header(monkeypatch):
    monkeypatch.setenv("CVBRAIN_INTAKE_API_KEY", "test-key")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload("Sales Executive B2B con experiencia comercial."),
        headers={"X-CVBrain-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_analyze_allows_trabajoaca_api_key_header(monkeypatch):
    monkeypatch.setenv("CVBRAIN_INTAKE_API_KEY", "test-key")

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload("Sales Executive B2B con experiencia comercial."),
        headers={"X-TrabajoAca-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_empty_text_returns_clean_error(monkeypatch):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(""),
    )

    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is False
    assert "empty_source_text" in data["warnings"]
    assert data["confidence"] == 0.0


@pytest.mark.parametrize(
    "case",
    SANITIZED_PILOT_CASES,
    ids=[case["title"] for case in SANITIZED_PILOT_CASES],
)
def test_sanitized_pilot_fixtures(monkeypatch, case):
    monkeypatch.delenv("CVBRAIN_INTAKE_API_KEY", raising=False)

    response = client.post(
        "/api/job-intake/analyze",
        json=analyze_payload(case["text"]),
    )

    assert response.status_code == 200, case["title"]
    data = response.json()
    assert data["ok"] is True, case["title"]
    assert case["role_contains"] in data["role_title"], case["title"]
    assert data["experience"]["minimum_years"] == case["minimum_years"], case["title"]

    normalized_terms = [term.lower() for term in data["search_terms"]]
    for expected in case["terms"]:
        assert expected.lower() in normalized_terms, case["title"]
