import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_live_intake_fixture.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "live_intake" / "cvbrain_100_busquedas_hr_realistas_sin_role_hint.txt"
CHALLENGE_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "live_intake" / "cvbrain_50_challenge_plus_regressions.txt"
CHALLENGE_V2_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "live_intake" / "cvbrain_50_challenge_v2_plus_failures.txt"
CHALLENGE_V3_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "live_intake" / "cvbrain_50_challenge_v3_plus_importance_regression.txt"
CHALLENGE_V4_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "live_intake" / "cvbrain_100_challenge_v4_plus_v3_failures.txt"
URUGUAY_MIXED_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "live_intake" / "cvbrain_100_uruguay_mixed_long_short_challenge_v1.txt"
ULTIMATE_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "live_intake" / "cvbrain_ultimate_100_mixed_long_short_v1.txt"
FORBIDDEN_ARGENTINA_LOCATION_PATTERN = re.compile(r"\b(?:Buenos\s+Aires|CABA|GBA|Argentina|AMBA)\b", re.I)

spec = importlib.util.spec_from_file_location("run_live_intake_fixture", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


def test_live_intake_parser_reads_exactly_100_real_search_cases():
    cases = runner.parse_fixture(FIXTURE_PATH)

    runner.validate_case_sequence(cases, 100)
    assert len(cases) == 100
    assert cases[0].id == "BUSQUEDA_001"
    assert cases[-1].id == "BUSQUEDA_100"
    for case in cases:
        assert case.source_text.strip()
        assert "BUSQUEDA_" not in case.source_text
        assert "END_BUSQUEDA_" not in case.source_text
        assert "role_hint" not in case.source_text.lower()


def test_challenge_fixture_reads_65_cases_and_keeps_old_regressions_exact():
    original_cases = {case.id: case.source_text for case in runner.parse_fixture(FIXTURE_PATH)}
    challenge_cases = runner.parse_fixture(CHALLENGE_FIXTURE_PATH)
    regression_mapping = {
        "BUSQUEDA_051": "BUSQUEDA_005",
        "BUSQUEDA_052": "BUSQUEDA_006",
        "BUSQUEDA_053": "BUSQUEDA_009",
        "BUSQUEDA_054": "BUSQUEDA_018",
        "BUSQUEDA_055": "BUSQUEDA_025",
        "BUSQUEDA_056": "BUSQUEDA_035",
        "BUSQUEDA_057": "BUSQUEDA_036",
        "BUSQUEDA_058": "BUSQUEDA_057",
        "BUSQUEDA_059": "BUSQUEDA_060",
        "BUSQUEDA_060": "BUSQUEDA_061",
        "BUSQUEDA_061": "BUSQUEDA_069",
        "BUSQUEDA_062": "BUSQUEDA_090",
        "BUSQUEDA_063": "BUSQUEDA_013",
        "BUSQUEDA_064": "BUSQUEDA_054",
        "BUSQUEDA_065": "BUSQUEDA_081",
    }

    runner.validate_case_sequence(challenge_cases, 65)
    assert len(challenge_cases[:50]) == 50
    for case in challenge_cases:
        assert case.source_text.strip()
        assert "BUSQUEDA_" not in case.source_text
        assert "END_BUSQUEDA_" not in case.source_text
        assert "role_hint" not in case.source_text.lower()

    by_id = {case.id: case.source_text for case in challenge_cases}
    for challenge_id, original_id in regression_mapping.items():
        assert by_id[challenge_id] == original_cases[original_id]


def test_challenge_v2_fixture_reads_59_cases_and_keeps_previous_failures_exact():
    previous_cases = {case.id: case.source_text for case in runner.parse_fixture(CHALLENGE_FIXTURE_PATH)}
    challenge_cases = runner.parse_fixture(CHALLENGE_V2_FIXTURE_PATH)
    regression_mapping = {
        "BUSQUEDA_051": "BUSQUEDA_034",
        "BUSQUEDA_052": "BUSQUEDA_007",
        "BUSQUEDA_053": "BUSQUEDA_002",
        "BUSQUEDA_054": "BUSQUEDA_012",
        "BUSQUEDA_055": "BUSQUEDA_013",
        "BUSQUEDA_056": "BUSQUEDA_030",
        "BUSQUEDA_057": "BUSQUEDA_032",
        "BUSQUEDA_058": "BUSQUEDA_044",
        "BUSQUEDA_059": "BUSQUEDA_050",
    }

    runner.validate_case_sequence(challenge_cases, 59)
    assert len(challenge_cases[:50]) == 50
    for case in challenge_cases:
        assert case.source_text.strip()
        assert "BUSQUEDA_" not in case.source_text
        assert "END_BUSQUEDA_" not in case.source_text
        assert "role_hint" not in case.source_text.lower()

    by_id = {case.id: case.source_text for case in challenge_cases}
    for challenge_id, previous_id in regression_mapping.items():
        assert by_id[challenge_id] == previous_cases[previous_id]


def test_challenge_v3_fixture_reads_51_cases_and_keeps_importance_regression_exact():
    previous_cases = {case.id: case.source_text for case in runner.parse_fixture(CHALLENGE_V2_FIXTURE_PATH)}
    challenge_cases = runner.parse_fixture(CHALLENGE_V3_FIXTURE_PATH)

    runner.validate_case_sequence(challenge_cases, 51)
    assert len(challenge_cases[:50]) == 50
    for case in challenge_cases:
        assert case.source_text.strip()
        assert "BUSQUEDA_" not in case.source_text
        assert "END_BUSQUEDA_" not in case.source_text
        assert "role_hint" not in case.source_text.lower()
    assert challenge_cases[-1].source_text == previous_cases["BUSQUEDA_001"]


def test_challenge_v4_fixture_reads_102_cases_and_keeps_v3_failures_exact():
    v3_cases = {case.id: case.source_text for case in runner.parse_fixture(CHALLENGE_V3_FIXTURE_PATH)}
    challenge_cases = runner.parse_fixture(CHALLENGE_V4_FIXTURE_PATH)
    raw_first_line = CHALLENGE_V4_FIXTURE_PATH.read_text(encoding="utf-8").splitlines()[0]

    runner.validate_case_sequence(challenge_cases, 102)
    assert raw_first_line == "BUSQUEDA_001"
    assert len(challenge_cases[:100]) == 100
    for case in challenge_cases:
        assert case.source_text.strip()
        assert "BUSQUEDA_" not in case.source_text
        assert "END_BUSQUEDA_" not in case.source_text
        assert "role_hint" not in case.source_text.lower()

    by_id = {case.id: case.source_text for case in challenge_cases}
    assert by_id["BUSQUEDA_101"] == v3_cases["BUSQUEDA_028"]
    assert by_id["BUSQUEDA_102"] == v3_cases["BUSQUEDA_046"]


def test_uruguay_mixed_long_short_fixture_reads_100_cases_without_metadata_or_forbidden_locations():
    cases = runner.parse_fixture(URUGUAY_MIXED_FIXTURE_PATH)
    raw_lines = URUGUAY_MIXED_FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
    serialized = "\n".join(case.source_text for case in cases)

    runner.validate_case_sequence(cases, 100)
    assert raw_lines[0] == "BUSQUEDA_001"
    assert len(cases[:20]) == 20
    assert len(cases[20:]) == 80
    assert all(len(case.source_text.split()) >= 120 for case in cases[:20])
    assert all(len(case.source_text.split()) <= 40 for case in cases[20:])
    assert all(_sentence_count(case.source_text) <= 4 for case in cases[20:])
    assert not FORBIDDEN_ARGENTINA_LOCATION_PATTERN.search(serialized)
    for case in cases:
        assert case.source_text.strip()
        assert "BUSQUEDA_" not in case.source_text
        assert "END_BUSQUEDA_" not in case.source_text
        assert "role_hint" not in case.source_text.lower()
        assert "TASK " not in case.source_text


def test_uruguay_mixed_fixture_first_long_account_manager_case_is_uruguay_adaptation():
    first_case = runner.parse_fixture(URUGUAY_MIXED_FIXTURE_PATH)[0]
    payload = runner.build_request(first_case)

    assert first_case.id == "BUSQUEDA_001"
    assert "ACCOUNT MANAGER Semi Senior" in first_case.source_text
    assert "Montevideo" in first_case.source_text
    assert "Canelones" in first_case.source_text
    assert "interior del país" in first_case.source_text
    assert "dispositivos médicos" in first_case.source_text
    assert "competencias excluyentes" in first_case.source_text.lower()
    assert not FORBIDDEN_ARGENTINA_LOCATION_PATTERN.search(first_case.source_text)
    assert payload["source_text"] == first_case.source_text
    assert payload["locale"] == "es-UY"
    assert "role_hint" not in json.dumps(payload, ensure_ascii=False).lower()


def test_ultimate_mixed_long_short_fixture_reads_100_uruguay_cases_without_metadata_or_forbidden_locations():
    cases = runner.parse_fixture(ULTIMATE_FIXTURE_PATH)
    raw_lines = ULTIMATE_FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
    serialized = "\n".join(case.source_text for case in cases)

    runner.validate_case_sequence(cases, 100)
    assert raw_lines[0] == "BUSQUEDA_001"
    assert len(cases[:60]) == 60
    assert len(cases[60:]) == 40
    assert all(len(case.source_text.split()) <= 45 for case in cases[:60])
    assert all(len(case.source_text.split()) >= 55 for case in cases[60:])
    assert not FORBIDDEN_ARGENTINA_LOCATION_PATTERN.search(serialized)
    for case in cases:
        assert case.source_text.strip()
        assert "BUSQUEDA_" not in case.source_text
        assert "END_BUSQUEDA_" not in case.source_text
        assert "role_hint" not in case.source_text.lower()
        assert "TASK " not in case.source_text


def _sentence_count(text):
    return len([chunk for chunk in runner.re.split(r"[.!?]+", text) if chunk.strip()])


def test_build_request_sends_only_real_hr_text_and_allowed_payload_fields():
    case = runner.Case("BUSQUEDA_001", "Necesitamos Analista Contable con Excel.")
    payload = runner.build_request(case)

    assert set(payload) == {
        "source_text",
        "source_filename",
        "source_mime_type",
        "recruiter_notes",
        "locale",
        "country_context",
        "candidate_market",
        "employer_market",
    }
    assert payload["source_text"] == "Necesitamos Analista Contable con Excel."
    assert "role_hint" not in json.dumps(payload, ensure_ascii=False).lower()
    assert "BUSQUEDA_" not in json.dumps(payload, ensure_ascii=False)


def test_timeout_for_source_chars_uses_dynamic_thresholds():
    assert runner.timeout_for_source_chars(1000) == 90
    assert runner.timeout_for_source_chars(3000) == 150
    assert runner.timeout_for_source_chars(8000) == 240
    assert runner.timeout_for_source_chars(15000) == 300


def test_runner_records_source_chars_and_dynamic_timeout_metadata(tmp_path):
    short_source = "Buscamos Analista Contable con Excel."
    medium_source = "x" * 3000
    cases = [
        runner.Case("BUSQUEDA_001", short_source),
        runner.Case("BUSQUEDA_002", medium_source),
    ]
    observed_timeouts = []

    def fake_transport(url, api_key, payload, timeout):
        observed_timeouts.append(timeout)
        return successful_record(role_title="Analista Contable")

    result = runner.run_fixture(
        cases,
        out_dir=tmp_path,
        url="https://example.test/api/job-intake/analyze",
        api_key="test-key-not-printed",
        sleep_seconds=0,
        transport=fake_transport,
    )

    assert observed_timeouts == [90.0, 150.0]
    assert result["cases"][0]["source_chars"] == len(short_source)
    assert result["cases"][0]["timeout_seconds"] == 90.0
    assert result["cases"][1]["source_chars"] == len(medium_source)
    assert result["cases"][1]["timeout_seconds"] == 150.0

    request_file = json.loads((tmp_path / "requests" / "BUSQUEDA_002.request.json").read_text())
    response_file = json.loads((tmp_path / "responses" / "BUSQUEDA_002.response.json").read_text())
    assert request_file["_runner_metadata"]["source_chars"] == len(medium_source)
    assert request_file["_runner_metadata"]["timeout_seconds"] == 150.0
    assert response_file["_runner_metadata"]["source_chars"] == len(medium_source)
    assert response_file["_runner_metadata"]["timeout_seconds"] == 150.0


def test_fixed_timeout_override_does_not_affect_short_inputs_dynamically(tmp_path):
    cases = [runner.Case("BUSQUEDA_001", "Buscamos Administrativo. Deseable Excel.")]
    observed_timeouts = []

    def fake_transport(url, api_key, payload, timeout):
        observed_timeouts.append(timeout)
        return successful_record(role_title="Administrativo")

    result = runner.run_fixture(
        cases,
        out_dir=tmp_path,
        url="https://example.test/api/job-intake/analyze",
        api_key="test-key-not-printed",
        timeout=0.01,
        sleep_seconds=0,
        transport=fake_transport,
    )

    assert observed_timeouts == [0.01]
    assert result["cases"][0]["timeout_seconds"] == 0.01
    assert result["cases"][0]["source_chars"] == len(cases[0].source_text)


def test_504_empty_body_is_classified_as_timeout_not_invalid_json():
    record = runner._response_record(504, "")

    classification, notes = runner.classify_result(
        "Texto largo normal de recruiter que excedió el timeout.",
        record,
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_TIMEOUT
    assert notes == ["timeout_504"]
    assert record.error == "timeout_504: empty response body"
    assert "invalid_json" not in record.error


def test_provider_timeout_warning_is_classified_as_timeout_not_provider_error():
    record = runner.ResponseRecord(
        200,
        {
            "ok": False,
            "warnings": ["ai_provider_timeout"],
            "engine": "openai",
            "fallback_used": False,
        },
        "{}",
    )

    classification, notes = runner.classify_result(
        "Texto normal de recruiter que agotó el timeout del proveedor.",
        record,
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_TIMEOUT
    assert notes == ["ai_provider_timeout"]


def test_runner_records_timeout_failure_metadata_for_empty_504(tmp_path):
    source = "Texto largo de recruiter. " * 200
    cases = [runner.Case("BUSQUEDA_001", source)]

    def fake_transport(url, api_key, payload, timeout):
        return runner._response_record(504, "")

    result = runner.run_fixture(
        cases,
        out_dir=tmp_path,
        url="https://example.test/api/job-intake/analyze",
        api_key="test-key-not-printed",
        sleep_seconds=0,
        transport=fake_transport,
    )

    row = result["cases"][0]
    response_file = json.loads((tmp_path / "responses" / "BUSQUEDA_001.response.json").read_text())
    assert row["result_classification"] == runner.FAIL_TIMEOUT
    assert row["failure_class"] == "timeout"
    assert row["notes"] == "timeout_504"
    assert row["source_chars"] == len(source)
    assert row["timeout_seconds"] == 150.0
    assert row["status_code"] == 504
    assert response_file["_runner_error"] == "timeout_504: empty response body"
    assert response_file["_runner_metadata"]["failure_class"] == "timeout"
    assert response_file["_runner_metadata"]["source_chars"] == len(source)
    assert response_file["_runner_metadata"]["timeout_seconds"] == 150.0


def test_runner_writes_outputs_and_continues_after_failed_case(tmp_path):
    cases = [
        runner.Case("BUSQUEDA_001", "Buscamos Soporte IT. Excluyente experiencia en tickets."),
        runner.Case("BUSQUEDA_002", "Buscamos Administrativo. Deseable Excel."),
    ]
    calls = []

    def fake_transport(url, api_key, payload, timeout):
        calls.append(payload["source_text"])
        if len(calls) == 1:
            return runner.ResponseRecord(
                200,
                {
                    "ok": True,
                    "engine": "openai",
                    "fallback_used": False,
                    "ai_model": "test-model",
                    "role_title": "Soporte IT",
                    "role_family": "support",
                    "summary": "Soporte IT con tickets.",
                    "must_have": ["Experiencia en tickets"],
                    "should_have": [],
                    "nice_to_have": [],
                    "blockers": [],
                    "credentials": {"required": [], "preferred": []},
                    "location": {"normalized": ""},
                    "experience": {"minimum_years": None},
                    "warnings": [],
                    "confidence": 0.91,
                },
                "{}",
            )
        return runner.ResponseRecord(0, None, "", "TimeoutError: timed out")

    result = runner.run_fixture(
        cases,
        out_dir=tmp_path,
        url="https://example.test/api/job-intake/analyze",
        api_key="test-key-not-printed",
        timeout=0.01,
        sleep_seconds=0,
        transport=fake_transport,
    )

    assert (tmp_path / "requests" / "BUSQUEDA_001.request.json").exists()
    assert (tmp_path / "responses" / "BUSQUEDA_001.response.json").exists()
    assert (tmp_path / "requests" / "BUSQUEDA_002.request.json").exists()
    assert (tmp_path / "responses" / "BUSQUEDA_002.response.json").exists()
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "summary.csv").exists()
    assert (tmp_path / "failures.md").exists()

    first_request = json.loads((tmp_path / "requests" / "BUSQUEDA_001.request.json").read_text())
    assert "role_hint" not in json.dumps(first_request, ensure_ascii=False).lower()
    assert result["summary"]["total_cases"] == 2
    assert result["summary"]["pass_count"] == 1
    assert result["summary"]["fail_count"] == 1
    assert result["cases"][1]["result_classification"] == runner.FAIL_TIMEOUT
    assert result["cases"][1]["failure_class"] == "timeout"
    assert len(calls) == 3


def successful_record(**overrides):
    data = {
        "ok": True,
        "engine": "openai",
        "fallback_used": False,
        "ai_model": "test-model",
        "role_title": "Sanitized Role",
        "role_family": "",
        "summary": "Sanitized recruiter request.",
        "must_have": [],
        "should_have": [],
        "nice_to_have": [],
        "blockers": [],
        "credentials": {"required": [], "preferred": []},
        "location": {"normalized": ""},
        "experience": {"minimum_years": None},
        "warnings": [],
        "confidence": 0.91,
    }
    data.update(overrides)
    return runner.ResponseRecord(200, data, "{}")


def test_runner_accepts_busqueda_001_plus_as_nice_to_have_not_under_promoted():
    classification, notes = runner.classify_result(
        "Inglés jurídico será un plus.",
        successful_record(nice_to_have=["Inglés jurídico"]),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_accepts_busqueda_027_suma_as_nice_to_have_not_under_promoted():
    classification, notes = runner.classify_result(
        "Libreta de conducir suma.",
        successful_record(
            nice_to_have=["Libreta de conducir"],
            credentials={"required": [], "preferred": ["Libreta de conducir"]},
        ),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_accepts_se_valorara_and_puede_sumar_as_nice_to_have():
    classification, notes = runner.classify_result(
        "Se valorará experiencia con TMS, WMS y Excel. Libreta profesional puede sumar.",
        successful_record(nice_to_have=["TMS", "WMS", "Excel", "Libreta profesional"]),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_accepts_busqueda_004_deseable_as_should_have():
    classification, notes = runner.classify_result(
        "CRM es deseable.",
        successful_record(should_have=["CRM"]),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_accepts_idealmente_as_should_have_without_importance_failure():
    classification, notes = runner.classify_result(
        "Idealmente experiencia en empresas de servicios.",
        successful_record(should_have=["Experiencia en empresas de servicios"]),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_accepts_busqueda_091_deseable_group_as_should_have():
    classification, notes = runner.classify_result(
        "Deseable inglés, protocolo y experiencia con eventos empresariales.",
        successful_record(should_have=["Inglés", "Protocolo", "Experiencia con eventos empresariales"]),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_accepts_deseables_section_item_even_when_it_overlaps_hard_section_terms():
    source_text = (
        "Requisitos excluyentes: experiencia comercial en salud, laboratorios, equipamiento médico, "
        "dispositivos médicos o servicios vinculados al sector.\n"
        "Deseables: Experiencia en dispositivos médicos del sector imágenes o ultrasonido."
    )

    classification, notes = runner.classify_result(
        source_text,
        successful_record(
            must_have=[
                "Experiencia comercial en salud, laboratorios, equipamiento médico, dispositivos médicos o servicios vinculados al sector"
            ],
            should_have=["Experiencia en dispositivos médicos del sector imágenes o ultrasonido"],
        ),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_accepts_responsibility_overlap_when_hard_requirement_is_represented_elsewhere():
    source_text = (
        "Requisitos excluyentes: experiencia en SOC, SIEM, hardening, incident response, playbooks "
        "y liderazgo técnico.\n"
        "Responsabilidades: definir playbooks y liderar incident response."
    )

    classification, notes = runner.classify_result(
        source_text,
        successful_record(
            must_have=["Experiencia en SOC, SIEM, hardening, incident response, playbooks y liderazgo técnico"],
            should_have=["Definir playbooks y liderar incident response"],
        ),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_fails_when_hard_commercial_training_is_under_promoted():
    classification, notes = runner.classify_result(
        "Es excluyente experiencia gestionando franquiciados, estándares operativos, auditorías, capacitación y seguimiento comercial.",
        successful_record(should_have=["Capacitación y seguimiento comercial"]),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_IMPORTANCE
    assert any(note.startswith("hard_modifier_under_promoted:should_have:") for note in notes)


def test_runner_accepts_openai_api_valorable_as_nice_to_have():
    classification, notes = runner.classify_result(
        "Experiencia con OpenAI APIs será valorable.",
        successful_record(nice_to_have=["Experiencia con OpenAI APIs"]),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_treats_repair_and_readiness_as_diagnostics_not_warn(tmp_path):
    cases = [
        runner.Case("BUSQUEDA_001", "Find all clerk applications."),
    ]

    def fake_transport(url, api_key, payload, timeout):
        return successful_record(
            role_title="Clerk",
            warnings=["ai_schema_repaired", "search_readiness_exploratory"],
            recruiter_questions=["What industry should be searched?"],
            ai_schema_repaired=True,
        )

    result = runner.run_fixture(
        cases,
        out_dir=tmp_path,
        url="https://example.test/api/job-intake/analyze",
        api_key="test-key-not-printed",
        timeout=0.01,
        sleep_seconds=0,
        transport=fake_transport,
    )

    assert result["cases"][0]["result_classification"] == runner.PASS
    assert result["summary"]["warn_count"] == 0
    assert result["summary"]["top_warnings"] == []
    assert ("ai_schema_repaired", 1) in result["summary"]["top_diagnostics"]
    assert ("search_readiness_exploratory", 1) in result["summary"]["top_diagnostics"]


def test_runner_does_not_warn_when_hybrid_modality_is_usable_without_extra_detail():
    classification, notes = runner.classify_result(
        "Empresa busca Analista Contable. Trabajo híbrido en Montevideo.",
        successful_record(
            role_title="Analista Contable",
            location={"raw": "Trabajo híbrido en Montevideo", "normalized": "Montevideo híbrido"},
        ),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_does_not_warn_when_remote_hybrid_is_preserved_in_location_text():
    classification, notes = runner.classify_result(
        "Software house busca Implementador. Remoto/híbrido.",
        successful_record(
            role_title="Implementador",
            location={"raw": "Remoto/híbrido", "normalized": "Remoto/híbrido", "hybrid_allowed": True},
        ),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_does_not_warn_when_remote_hybrid_is_modeled_as_hybrid_modality():
    classification, notes = runner.classify_result(
        "Software house busca Implementador. Remoto/híbrido.",
        successful_record(
            role_title="Implementador",
            work_modality="hybrid",
            location={"raw": "", "normalized": "", "hybrid_allowed": True},
        ),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_does_not_warn_for_seniority_only_inside_blockers():
    classification, notes = runner.classify_result(
        "Empresa busca Gerente Corporativo de Legales. No avanzar perfiles junior de asesoría legal.",
        successful_record(
            role_title="Gerente Corporativo de Legales",
            blockers=["No avanzar perfiles junior de asesoría legal"],
        ),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_fails_when_weak_preference_is_promoted_to_should_have():
    classification, notes = runner.classify_result(
        "Libreta profesional puede sumar.",
        successful_record(should_have=["Libreta profesional"]),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_IMPORTANCE
    assert any(note.startswith("weak_modifier_over_promoted:should_have:") for note in notes)


def test_runner_fails_when_valorable_with_conditional_debe_is_promoted_to_must_have():
    classification, notes = runner.classify_result(
        "Libreta de conducir será valorable si debe recorrer servicios.",
        successful_record(must_have=["Libreta de conducir"]),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_IMPORTANCE
    assert any(note.startswith("weak_modifier_over_promoted:must_have:") for note in notes)


@pytest.mark.parametrize(
    ("source_text", "must_item"),
    [
        (
            "Empresa busca rol con experiencia excluyente en producción continua. Se valorará experiencia en mejora continua.",
            "Experiencia excluyente en producción continua",
        ),
        (
            "Empresa busca rol con experiencia obligatoria en coordinación de mostradores. Conocimiento de nomencladores será valorable.",
            "Experiencia obligatoria en coordinación de mostradores",
        ),
        (
            "Empresa busca rol con experiencia imprescindible en seguridad industrial. ISO 14001 será valorable.",
            "Experiencia imprescindible en seguridad industrial",
        ),
        (
            "Empresa busca rol con experiencia requerida en documentación GMP. Inglés técnico será un plus.",
            "Experiencia requerida en documentación GMP",
        ),
        (
            "Empresa busca rol que debe contar con experiencia en producción, mantenimiento y seguridad. SAP será valorable.",
            "Mantenimiento",
        ),
        (
            "Empresa busca rol. Es obligatorio conocimiento de SAP, Excel y Power BI. Python será valorable.",
            "Excel",
        ),
    ],
)
def test_runner_does_not_flag_explicit_hard_cue_as_weak_over_promoted(source_text, must_item):
    classification, notes = runner.classify_result(
        source_text,
        successful_record(must_have=[must_item], nice_to_have=["Automatización"]),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_keeps_failing_true_weak_over_promoted_experience():
    classification, notes = runner.classify_result(
        "Se valorará experiencia en mejora continua y Lean.",
        successful_record(must_have=["Experiencia en mejora continua"]),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_IMPORTANCE
    assert any(note.startswith("weak_modifier_over_promoted:must_have:") for note in notes)


def test_runner_fails_when_no_avanzar_leaks_into_requirements():
    classification, notes = runner.classify_result(
        "No avanzar perfiles puramente litigiosos sin experiencia corporativa.",
        successful_record(must_have=["No avanzar perfiles puramente litigiosos sin experiencia corporativa"]),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_IMPORTANCE
    assert any(note.startswith("blocker_leaked_to_requirement:must_have:") for note in notes)


def test_runner_fails_when_naked_no_avanzar_leaks_into_requirements():
    classification, notes = runner.classify_result(
        "No avanzar perfiles no calificados.",
        successful_record(nice_to_have=["No avanzar"]),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_IMPORTANCE
    assert any(note.startswith("blocker_leaked_to_requirement:nice_to_have:") for note in notes)


def test_runner_fails_when_public_metadata_artifact_leaks():
    classification, notes = runner.classify_result(
        "Empresa busca Operario Calificado CNC.",
        successful_record(blockers=["Source_text_classification_rationale_id_missing_or_not_applicable"]),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_PUBLIC_ARTIFACT
    assert any(note.startswith("metadata_artifact:") for note in notes)


def test_runner_fails_when_role_title_casing_does_not_match_source_span():
    classification, notes = runner.classify_result(
        "Empresa metalúrgica busca Operario Calificado CNC para planta.",
        successful_record(role_title="Operario calificado CNC"),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_TITLE_CASING
    assert notes == ["title_casing_mismatch:Operario Calificado CNC!=Operario calificado CNC"]


@pytest.mark.parametrize(
    ("source_text", "wrong_title", "expected_title"),
    [
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
            "Consultora tecnológica busca Scrum Master con experiencia facilitando ceremonias ágiles.",
            "Consultora tecnológica",
            "Scrum Master",
        ),
    ],
)
def test_runner_fails_when_role_title_misses_explicit_source_span(source_text, wrong_title, expected_title):
    classification, notes = runner.classify_result(
        source_text,
        successful_record(role_title=wrong_title),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_TITLE_SOURCE_SPAN
    assert notes == [f"title_source_span_mismatch:{expected_title}!={wrong_title}"]


def test_runner_fails_when_key_account_manager_title_span_is_clipped():
    classification, notes = runner.classify_result(
        "Empresa farmacéutica busca Key Account Manager con experiencia en cuentas institucionales.",
        successful_record(role_title="Account Manager"),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_TITLE_SOURCE_SPAN
    assert notes == ["title_source_span_mismatch:Key Account Manager!=Account Manager"]


def test_runner_accepts_exact_role_title_source_casing():
    classification, notes = runner.classify_result(
        "Estudio profesional busca Escribano Junior o estudiante avanzado de notariado.",
        successful_record(role_title="Escribano Junior o estudiante avanzado de notariado"),
        expect_live_ai=True,
    )

    assert classification == runner.PASS
    assert notes == []


def test_runner_keeps_ai_schema_validation_failed_as_schema_failure():
    classification, notes = runner.classify_result(
        "Sanitized request.",
        runner.ResponseRecord(
            200,
            {
                "ok": False,
                "warnings": ["ai_schema_validation_failed"],
                "engine": "openai",
                "fallback_used": False,
            },
            "{}",
        ),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_SCHEMA
    assert notes == ["ai_schema_validation_failed"]
