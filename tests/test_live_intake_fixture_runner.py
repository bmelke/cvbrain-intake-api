import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_live_intake_fixture.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "live_intake" / "cvbrain_100_busquedas_hr_realistas_sin_role_hint.txt"

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
    assert result["cases"][1]["result_classification"] == "FAIL_TECHNICAL"
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


def test_runner_fails_when_weak_preference_is_promoted_to_should_have():
    classification, notes = runner.classify_result(
        "Libreta profesional puede sumar.",
        successful_record(should_have=["Libreta profesional"]),
        expect_live_ai=True,
    )

    assert classification == runner.FAIL_IMPORTANCE
    assert any(note.startswith("weak_modifier_over_promoted:should_have:") for note in notes)


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
