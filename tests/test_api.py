from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert data["service"] == "cvbrain-intake-api"
    assert data["product"] == "CVBrain"
    assert data["version"] == "0.1.0"


def test_analyze_account_manager():
    response = client.post(
        "/api/job-intake/analyze",
        json={
            "source_text": "Account Manager Semi Senior con experiencia en dispositivos medicos. Minima de 3 anos. Deseable CRM. Ubicación Montevideo, híbrido.",
            "source_filename": "",
            "source_mime_type": "text/plain",
            "recruiter_notes": "",
            "locale": "es-UY",
        },
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


def test_empty_text_returns_clean_error():
    response = client.post(
        "/api/job-intake/analyze",
        json={
            "source_text": "",
            "source_filename": "",
            "source_mime_type": "text/plain",
            "recruiter_notes": "",
            "locale": "es-UY",
        },
    )

    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is False
    assert "empty_source_text" in data["warnings"]
    assert data["confidence"] == 0.0
