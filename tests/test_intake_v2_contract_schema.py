from __future__ import annotations

import ast
import copy
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.intake_v2.contract import (
    JobIntelligenceDraftV2,
    SCHEMA_VERSION_V2,
    job_intelligence_v2_response_schema,
    strict_provider_schema_for_model,
    validate_job_intelligence_draft_v2,
)
from app.intake_v2.errors import IntakeV2ContractError


ROOT = Path(__file__).resolve().parents[1]


def valid_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION_V2,
        "job_profile": {
            "role_title": "Mecánico de coches",
            "role_family": "mantenimiento automotor",
            "professional_grade": None,
            "seniority": None,
            "summary": "Búsqueda de mecánico de coches.",
            "industries": ["automotriz"],
        },
        "location_and_modality": {
            "raw_location": None,
            "normalized_location": None,
            "country_code": "UY",
            "city": None,
            "region": None,
            "work_modality": None,
            "remote_allowed": None,
            "hybrid_allowed": None,
            "onsite_required": None,
        },
        "criteria": [
            {
                "local_ref": "crit_1",
                "criterion_kind": "experience",
                "text": "Experiencia demostrable como mecánico",
                "source_evidence": "experiencia demostrable",
                "importance": "must_have",
                "explicit": True,
                "precision_status": "needs_clarification",
                "missing_dimensions": ["duration", "evidence"],
                "clarification_question_ref": "q_1",
            },
            {
                "local_ref": "crit_2",
                "criterion_kind": "license",
                "text": "Carnet de conducir",
                "source_evidence": "con carnet de conducir",
                "importance": "must_have",
                "explicit": True,
                "precision_status": "needs_clarification",
                "missing_dimensions": ["license_category"],
                "clarification_question_ref": "q_2",
            },
        ],
        "company_questions": [
            {
                "local_ref": "q_1",
                "question": "¿Cuántos años o qué evidencia concreta valida la experiencia demostrable?",
                "audience": "hiring_company",
                "category": "search_precision",
                "criterion_refs": ["crit_1"],
                "missing_dimensions": ["duration", "evidence"],
                "blocking_level": "blocking",
            },
            {
                "local_ref": "q_2",
                "question": "¿Qué categoría de carnet de conducir se requiere?",
                "audience": "hiring_company",
                "category": "search_precision",
                "criterion_refs": ["crit_2"],
                "missing_dimensions": ["license_category"],
                "blocking_level": "blocking",
            },
        ],
        "candidate_screening_questions": [
            {
                "local_ref": "cq_1",
                "question": "¿Podés aportar evidencia laboral de experiencia como mecánico?",
                "audience": "candidate",
                "category": "screening",
                "criterion_refs": ["crit_1"],
                "missing_dimensions": [],
                "blocking_level": "advisory",
            }
        ],
        "search_strategy": {
            "target_titles": ["Mecánico de coches"],
            "search_terms": ["mecánico de coches"],
            "semantic_terms": ["reparaciones automotrices"],
            "negative_terms": [],
        },
        "search_readiness": {
            "status": "insufficient_for_precise_search",
            "proceed_allowed": True,
            "recommended_action": "ask_company",
            "recruiter_decision_required": True,
            "continued_with_missing_information": True,
        },
        "quality_control": {
            "warnings": [],
            "confidence": 0.74,
            "contains_candidate_data": False,
            "contains_candidate_pii": False,
        },
    }


def object_nodes(schema: Mapping[str, Any]):
    if isinstance(schema, Mapping):
        if schema.get("type") == "object" or "properties" in schema:
            yield schema
        for value in schema.values():
            yield from object_nodes(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from object_nodes(item)


def set_path(payload: dict[str, Any], path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    output = copy.deepcopy(payload)
    target: Any = output
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    return output


def delete_path(payload: dict[str, Any], path: tuple[Any, ...]) -> dict[str, Any]:
    output = copy.deepcopy(payload)
    target: Any = output
    for part in path[:-1]:
        target = target[part]
    del target[path[-1]]
    return output


def assert_contract_rejects(payload: Mapping[str, Any]) -> None:
    with pytest.raises(IntakeV2ContractError):
        validate_job_intelligence_draft_v2(payload)


def test_schema_derives_from_job_intelligence_draft_v2():
    assert job_intelligence_v2_response_schema() == strict_provider_schema_for_model(JobIntelligenceDraftV2)


def test_strict_provider_schema_conversion_is_deterministic():
    assert job_intelligence_v2_response_schema() == job_intelligence_v2_response_schema()


def test_every_schema_object_forbids_additional_properties_and_defines_required_keys():
    for node in object_nodes(job_intelligence_v2_response_schema()):
        assert node.get("additionalProperties") is False
        assert set(node.get("required", [])) == set(node.get("properties", {}).keys())


def test_application_model_and_provider_schema_stay_in_parity():
    model_schema = JobIntelligenceDraftV2.model_json_schema()
    provider_schema = job_intelligence_v2_response_schema()

    assert set(provider_schema["properties"]) == set(model_schema["properties"])
    assert set(provider_schema["$defs"]["CriterionDraftV2"]["properties"]) == set(
        model_schema["$defs"]["CriterionDraftV2"]["properties"]
    )
    assert set(provider_schema["$defs"]["CompanyQuestionDraftV2"]["properties"]) == set(
        model_schema["$defs"]["CompanyQuestionDraftV2"]["properties"]
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("criteria", 0, "importance"), "preferred"),
        (("criteria", 0, "precision_status"), "unclear"),
        (("company_questions", 0, "audience"), "candidate"),
        (("company_questions", 0, "category"), "interview"),
        (("candidate_screening_questions", 0, "audience"), "hiring_company"),
        (("search_readiness", "status"), "exploratory"),
    ],
)
def test_invalid_enum_values_fail(path, value):
    assert_contract_rejects(set_path(valid_payload(), path, value))


@pytest.mark.parametrize(
    "path",
    [
        ("criteria", 0, "local_ref"),
        ("criteria", 0, "criterion_kind"),
        ("criteria", 0, "source_evidence"),
        ("company_questions", 0, "criterion_refs"),
        ("job_profile", "role_title"),
        ("search_strategy", "search_terms"),
    ],
)
def test_missing_required_semantic_fields_fail(path):
    assert_contract_rejects(delete_path(valid_payload(), path))


def test_null_optional_values_are_accepted():
    payload = valid_payload()
    payload["job_profile"]["role_family"] = None
    payload["job_profile"]["professional_grade"] = None
    payload["job_profile"]["seniority"] = None
    payload["job_profile"]["summary"] = None
    payload["location_and_modality"]["raw_location"] = None
    payload["location_and_modality"]["work_modality"] = None
    payload["criteria"][0]["clarification_question_ref"] = None

    assert validate_job_intelligence_draft_v2(payload)["schema_version"] == SCHEMA_VERSION_V2


def test_extra_fields_and_display_plan_are_rejected():
    payload = valid_payload()
    payload["display_plan"] = {"role_title": "Mecánico"}
    assert_contract_rejects(payload)

    nested = valid_payload()
    nested["criteria"][0]["unexpected"] = "value"
    assert_contract_rejects(nested)


def test_display_plan_and_flat_duplicate_arrays_are_absent_from_provider_schema():
    schema = job_intelligence_v2_response_schema()
    serialized = json.dumps(schema, sort_keys=True)
    top_level_keys = set(schema["properties"])

    assert "display_plan" not in serialized
    assert "flat_compatibility" not in serialized
    assert not ({"must_have", "should_have", "nice_to_have", "blockers", "credentials"} & top_level_keys)


def test_v1_models_and_runtime_files_remain_unchanged():
    v1_paths = [
        "app/extractors/openai_structured.py",
        "app/extractors/router.py",
        "app/extractors/deterministic.py",
        "app/schemas/job_intelligence_v1_contract.py",
        "app/normalization/requirement_importance.py",
        "app/normalization/role_title.py",
        "app/normalization/canonical_job_intelligence.py",
        "app/mappers/job_intelligence_to_flat.py",
        "app/mappers/recruiter_display_plan.py",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", *v1_paths],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.strip() == ""
    assert_app_main_v2_registration_delta_is_allowlisted()


def assert_app_main_v2_registration_delta_is_allowlisted() -> None:
    app_main_path = ROOT / "app" / "main.py"
    source = app_main_path.read_text()
    tree = ast.parse(source)

    assert "from app.intake_v2.api import create_intake_v2_router" in source
    assert "def get_intake_v2_provider() -> Any:" in source
    assert "create_intake_v2_router(provider_dependency=get_intake_v2_provider)" in source

    v2_related_lines = {
        line.strip()
        for line in source.splitlines()
        if "intake_v2" in line or "create_intake_v2_router" in line
    }
    assert v2_related_lines == {
        "from app.intake_v2.api import create_intake_v2_router",
        "def get_intake_v2_provider() -> Any:",
        "app.include_router(create_intake_v2_router(provider_dependency=get_intake_v2_provider))",
    }

    forbidden_imports = {
        "app.intake_v2.provider_config",
        "app.intake_v2.provider_factory",
        "app.intake_v2.provider",
        "openai",
        "dotenv",
    }
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    )
    assert not (forbidden_imports & imported_modules)

    provider_hook = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "get_intake_v2_provider"
    )
    assert len(provider_hook.body) == 1
    return_statement = provider_hook.body[0]
    assert isinstance(return_statement, ast.Return)
    assert isinstance(return_statement.value, ast.Constant)
    assert return_statement.value.value is None

    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--", "app/main.py"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    removed_lines = [line for line in diff if line.startswith("-") and not line.startswith("---")]
    added_lines = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
    assert removed_lines == []
    assert [line for line in added_lines if line] == [
        "from app.intake_v2.api import create_intake_v2_router",
        "def get_intake_v2_provider() -> Any:",
        "    return None",
        "app.include_router(create_intake_v2_router(provider_dependency=get_intake_v2_provider))",
    ]
