import sys

from app.extractors import (
    AIExtractorStub,
    ExtractorRequest,
    ExtractorRouter,
    country_context_mismatch_warning,
)


def request():
    return ExtractorRequest(
        source_text="Account Manager Semi Senior con experiencia en dispositivos medicos. Minima de 3 anos. Deseable CRM. Ubicacion Montevideo, hibrido.",
        locale="es-UY",
        country_context="UY",
        candidate_market="UY",
        employer_market="UY",
        source_filename="",
        source_mime_type="text/plain",
        recruiter_notes="",
    )


def test_deterministic_mode_routes_to_deterministic_extractor():
    router = ExtractorRouter(env={"CVBRAIN_EXTRACTOR_MODE": "deterministic"})

    result = router.extract(request())

    assert result["ok"] is True
    assert result["engine"] == "deterministic"
    assert result["fallback_used"] is False
    assert "Account Manager" in result["role_title"]


def test_auto_mode_without_openai_key_routes_to_deterministic_extractor():
    router = ExtractorRouter(env={"CVBRAIN_EXTRACTOR_MODE": "auto"})

    result = router.extract(request())

    assert result["ok"] is True
    assert result["engine"] == "deterministic"
    assert result["fallback_used"] is False


def test_ai_mode_without_key_falls_back_when_enabled():
    router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "CVBRAIN_AI_FALLBACK_ENABLED": "true",
        }
    )

    result = router.extract(request())

    assert result["ok"] is True
    assert result["engine"] == "deterministic"
    assert result["fallback_used"] is True
    assert "ai_fallback_used" in result["warnings"]
    assert "ai_missing_api_key" in result["warnings"]


def test_ai_mode_without_key_returns_clean_error_when_fallback_disabled():
    router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "CVBRAIN_AI_FALLBACK_ENABLED": "false",
        }
    )

    result = router.extract(request())
    assert result["ok"] is False
    assert result["engine"] == "openai"
    assert result["fallback_used"] is False
    assert "ai_missing_api_key" in result["warnings"]
    assert result["search_terms"] == []


def test_ai_stub_failure_falls_back_and_adds_warning_when_key_exists():
    router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "OPENAI_API_KEY": "test-key-not-used",
            "CVBRAIN_OPENAI_MODEL": "test-model-not-used",
            "CVBRAIN_AI_FALLBACK_ENABLED": "true",
        },
        ai_extractor=AIExtractorStub(),
    )

    result = router.extract(request())
    assert result["ok"] is True
    assert result["engine"] == "deterministic"
    assert result["fallback_used"] is True
    assert "ai_extractor_not_implemented" in result["warnings"]


def test_ai_payload_includes_context_and_preserves_source_without_logs():
    payload = AIExtractorStub().build_payload(request())

    assert payload["source_text"].startswith("Account Manager Semi Senior")
    assert payload["locale"] == "es-UY"
    assert payload["country_context"] == "UY"
    assert payload["candidate_market"] == "UY"
    assert payload["employer_market"] == "UY"
    assert payload["schema_version"] == "cvbrain_job_intelligence_v1"
    assert "logs" not in payload
    assert "raw_ai_output" not in payload


def test_location_context_mismatch_warning_can_be_represented():
    warning = country_context_mismatch_warning(
        source_location="CABA / GBA",
        country_context="UY",
        expected_country="AR",
    )

    assert warning["code"] == "country_context_mismatch"
    assert warning["source_location"] == "CABA / GBA"
    assert warning["country_context"] == "UY"
    assert warning["expected_country"] == "AR"


def test_extractor_stubs_do_not_import_openai_or_make_network_calls():
    router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "OPENAI_API_KEY": "test-key-not-used",
            "CVBRAIN_OPENAI_MODEL": "test-model-not-used",
            "CVBRAIN_AI_FALLBACK_ENABLED": "true",
        },
        ai_extractor=AIExtractorStub(),
    )

    result = router.extract(request())

    assert result["fallback_used"] is True
    assert "openai" not in sys.modules


def test_ai_mode_with_key_but_missing_model_falls_back_without_constructing_client():
    router = ExtractorRouter(
        env={
            "CVBRAIN_EXTRACTOR_MODE": "ai",
            "OPENAI_API_KEY": "test-key-not-used",
            "CVBRAIN_AI_FALLBACK_ENABLED": "true",
        }
    )

    result = router.extract(request())

    assert result["ok"] is True
    assert result["engine"] == "deterministic"
    assert result["fallback_used"] is True
    assert "ai_missing_model" in result["warnings"]
    assert "openai" not in sys.modules
