from __future__ import annotations

import ast
import copy
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.intake_v2.contract import SCHEMA_VERSION_V2, validate_job_intelligence_draft_v2
from app.intake_v2.errors import IntakeV2Error
from app.intake_v2.integrity import internalize_draft_v2


ROOT = Path(__file__).resolve().parents[1]
DISPLAY_PLAN_MODULE = "app.intake_v2.display_plan"
SEMANTIC_SENTINELS = (
    "papeles en regla",
    "oficial de primera",
    "licencia profesional",
    "bloqueante",
    "nice to have",
    "required",
)
SENSITIVE_SENTINELS = (
    "SOURCE_TEXT_SENTINEL",
    "PROMPT_BODY_SENTINEL",
    "RAW_OUTPUT_SENTINEL",
    "SECRET_TOKEN_SENTINEL",
)
RAW_LOCAL_REFS = (
    "crit_alpha",
    "crit_beta",
    "crit_gamma",
    "company_q_alpha",
    "company_q_beta",
    "candidate_q_alpha",
)
EXPECTED_SECTION_CODES = [
    "comparison_basis",
    "must_have_criteria",
    "nice_to_have_criteria",
    "questions_for_recruiter",
    "missing_information_or_blockers",
    "search_readiness",
    "recommended_next_steps",
]
ALLOWED_TOP_LEVEL_KEYS = {"display_plan"}
ALLOWED_DISPLAY_PLAN_KEYS = {"schema_version", "version", "sections", "request_id"}
ALLOWED_SECTION_KEYS = {"id", "code", "label", "order", "items"}
ALLOWED_ITEM_KEYS = {
    "id",
    "code",
    "kind",
    "label",
    "order",
    "value",
    "values",
    "text",
    "items",
    "internal_id",
    "source_id",
}
FORBIDDEN_OUTPUT_KEYS = {
    "api_key",
    "auth_headers",
    "authorization",
    "bearer_token",
    "body",
    "debug",
    "endpoint",
    "errors",
    "exception",
    "flat_compatibility",
    "headers",
    "http_status",
    "local_ref",
    "prompt",
    "prompt_body",
    "provider_body",
    "provider_payload",
    "raw_exception",
    "raw_output",
    "raw_output_text",
    "raw_provider_output",
    "response_body",
    "source_text",
    "standalone",
    "ui_sections",
    "v1_compatibility",
    "wordpress",
}
ALLOWED_LOG_KEYS = {
    "event",
    "status",
    "code",
    "category",
    "section_count",
    "item_count",
    "request_id",
}
FORBIDDEN_IMPORTS = {
    "app.normalization.requirement_importance",
    "app.normalization.role_title",
    "app.normalization.canonical_job_intelligence",
    "app.normalization.precision_questions",
    "app.mappers.recruiter_display_plan",
    "app.mappers.job_intelligence_to_flat",
    "app.extractors.deterministic",
    "app.extractors.router",
    "app.main",
}


def display_plan_module() -> Any:
    try:
        return importlib.import_module(DISPLAY_PLAN_MODULE)
    except ModuleNotFoundError as error:
        if error.name == DISPLAY_PLAN_MODULE:
            pytest.fail(f"Gate 5 display_plan module is not implemented: expected import {DISPLAY_PLAN_MODULE} ({error})")
        raise


def required_attr(module: Any, name: str) -> Any:
    if not hasattr(module, name):
        pytest.fail(f"{module.__name__} must expose {name} for the Gate 5 display_plan boundary")
    return getattr(module, name)


def build_display_plan_v2(value: Mapping[str, Any]) -> Mapping[str, Any]:
    module = display_plan_module()
    builder = required_attr(module, "build_display_plan_v2")
    result = builder(value)
    assert isinstance(result, Mapping), "build_display_plan_v2 must return a mapping"
    return result


def projection_error_type() -> type[BaseException]:
    module = display_plan_module()
    error_type = required_attr(module, "V2DisplayPlanProjectionError")
    assert issubclass(error_type, IntakeV2Error)
    return error_type


def valid_draft(*, phrase: str = "papeles en regla") -> dict[str, Any]:
    return validate_job_intelligence_draft_v2(
        {
            "schema_version": SCHEMA_VERSION_V2,
            "job_profile": {
                "role_title": "Gate 5 role title",
                "role_family": "familia AI-preserved",
                "professional_grade": None,
                "seniority": None,
                "summary": f"{phrase}; oficial de primera; licencia profesional.",
                "industries": ["industria textual required"],
            },
            "location_and_modality": {
                "raw_location": "Montevideo",
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
                    "local_ref": "crit_alpha",
                    "criterion_kind": "legal_documentation",
                    "text": phrase,
                    "source_evidence": phrase,
                    "importance": "must_have",
                    "explicit": True,
                    "precision_status": "needs_clarification",
                    "missing_dimensions": ["legal_documentation"],
                    "clarification_question_ref": "company_q_alpha",
                },
                {
                    "local_ref": "crit_beta",
                    "criterion_kind": "license",
                    "text": "oficial de primera con licencia profesional",
                    "source_evidence": "oficial de primera; licencia profesional",
                    "importance": "nice_to_have",
                    "explicit": True,
                    "precision_status": "needs_clarification",
                    "missing_dimensions": ["license_category", "equivalence"],
                    "clarification_question_ref": "company_q_beta",
                },
                {
                    "local_ref": "crit_gamma",
                    "criterion_kind": "general_requirement",
                    "text": "bloqueante nice to have required",
                    "source_evidence": "bloqueante nice to have required",
                    "importance": "should_have",
                    "explicit": True,
                    "precision_status": "precise",
                    "missing_dimensions": [],
                    "clarification_question_ref": None,
                },
            ],
            "company_questions": [
                {
                    "local_ref": "company_q_alpha",
                    "question": f"Que documentacion significa {phrase}?",
                    "audience": "hiring_company",
                    "category": "search_precision",
                    "criterion_refs": ["crit_alpha"],
                    "missing_dimensions": ["legal_documentation"],
                    "blocking_level": "blocking",
                },
                {
                    "local_ref": "company_q_beta",
                    "question": "Que categoria o equivalencia aplica a oficial de primera y licencia profesional?",
                    "audience": "hiring_company",
                    "category": "search_precision",
                    "criterion_refs": ["crit_beta", "crit_gamma"],
                    "missing_dimensions": ["license_category", "equivalence"],
                    "blocking_level": "important",
                },
            ],
            "candidate_screening_questions": [
                {
                    "local_ref": "candidate_q_alpha",
                    "question": "Podes explicar papeles en regla y licencia profesional?",
                    "audience": "candidate",
                    "category": "screening",
                    "criterion_refs": ["crit_alpha", "crit_beta"],
                    "missing_dimensions": [],
                    "blocking_level": "advisory",
                }
            ],
            "search_strategy": {
                "target_titles": ["Gate 5 role title"],
                "search_terms": [phrase, "licencia profesional"],
                "semantic_terms": ["oficial de primera"],
                "negative_terms": ["bloqueante"],
            },
            "search_readiness": {
                "status": "usable_with_warnings",
                "proceed_allowed": True,
                "recommended_action": "ask_company",
                "recruiter_decision_required": True,
                "continued_with_missing_information": True,
                "recommendation_summary": "La busqueda puede iniciar con advertencias y requiere aclarar puntos antes de comparar CVs.",
                "recommended_next_steps": [
                    "Responder las preguntas del brief antes de contactar candidatos.",
                    "Usar los criterios explicitos como base inicial de busqueda.",
                ],
            },
            "quality_control": {
                "warnings": ["required and nice to have are source words only"],
                "confidence": 0.71,
                "contains_candidate_data": False,
                "contains_candidate_pii": False,
            },
        }
    )


def service_success_result(*, phrase: str = "papeles en regla") -> dict[str, Any]:
    internalized = internalize_draft_v2(valid_draft(phrase=phrase))
    return {
        "ok": True,
        "status": "ok",
        "schema_version": "cvbrain_intake_v2_service",
        "provider": {
            "provider_response_id": "resp_display_plan_safe",
            "provider_request_id": "req_display_plan_safe",
            "model": "gpt-test-v2-display",
            "attempt_kind": "extraction",
            "provider_call_count": 1,
            "semantic_attempt_count": 1,
            "repair_count": 0,
            "transient_retry_count": 0,
            "elapsed_seconds": 0.123,
            "parse_path": "output_parsed",
        },
        "document": internalized["document"],
        "integrity": internalized["integrity"],
    }


def display_plan_from(result: Mapping[str, Any]) -> Mapping[str, Any]:
    output = build_display_plan_v2(result)
    assert set(output) <= ALLOWED_TOP_LEVEL_KEYS
    plan = output.get("display_plan")
    assert isinstance(plan, Mapping), "projection output must include a display_plan mapping"
    return plan


def sections_from(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    assert set(plan) <= ALLOWED_DISPLAY_PLAN_KEYS
    sections = plan.get("sections")
    assert isinstance(sections, list), "display_plan.sections must be a list"
    assert all(isinstance(section, Mapping) for section in sections)
    return sections


def section_codes(plan: Mapping[str, Any]) -> list[str]:
    return [str(section.get("code")) for section in sections_from(plan)]


def assert_renderable_sections(plan: Mapping[str, Any]) -> None:
    sections = sections_from(plan)
    assert [section.get("code") for section in sections] == EXPECTED_SECTION_CODES
    for index, section in enumerate(sections):
        assert set(section) <= ALLOWED_SECTION_KEYS
        assert isinstance(section.get("id"), str) and section["id"]
        assert isinstance(section.get("code"), str) and section["code"]
        assert isinstance(section.get("label"), str) and section["label"]
        assert section.get("order", index) == index
        items = section.get("items")
        assert isinstance(items, list)
        for item_index, item in enumerate(items):
            assert isinstance(item, Mapping)
            assert set(item) <= ALLOWED_ITEM_KEYS
            assert isinstance(item.get("id"), str) and item["id"]
            assert isinstance(item.get("code"), str) and item["code"]
            assert isinstance(item.get("kind"), str) and item["kind"]
            assert isinstance(item.get("label"), str) and item["label"]
            assert item.get("order", item_index) == item_index
            assert any(key in item for key in ("value", "values", "text", "items"))


def safe_json(value: Any) -> str:
    return json.dumps(to_jsonable(value), sort_keys=True, default=str)


def to_jsonable(value: Any, seen: set[int] | None = None) -> Any:
    if seen is None:
        seen = set()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    value_id = id(value)
    if value_id in seen:
        return "<cycle>"
    seen.add(value_id)
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(child, seen) for key, child in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(child, seen) for child in value]
    if isinstance(value, BaseException):
        return {
            "type": value.__class__.__name__,
            "message": str(value),
            "repr": repr(value),
            "attributes": to_jsonable(vars(value), seen),
        }
    if hasattr(value, "__dict__"):
        return {"type": value.__class__.__name__, "attributes": to_jsonable(vars(value), seen)}
    return repr(value)


def all_keys(value: Any) -> set[str]:
    keys: set[str] = set()

    def walk(child: Any) -> None:
        if isinstance(child, Mapping):
            keys.update(str(key) for key in child)
            for item in child.values():
                walk(item)
        elif isinstance(child, (list, tuple, set)):
            for item in child:
                walk(item)
        elif isinstance(child, BaseException):
            walk(vars(child))
        elif hasattr(child, "__dict__"):
            walk(vars(child))

    walk(value)
    return keys


def id_ref_like_values(value: Any) -> list[Any]:
    values: list[Any] = []

    def is_id_ref_key(key: Any) -> bool:
        key_text = str(key)
        return (
            key_text in {"id", "ids", "ref", "refs"}
            or key_text.endswith("_id")
            or key_text.endswith("_ids")
            or key_text.endswith("_ref")
            or key_text.endswith("_refs")
        )

    def walk(child: Any) -> None:
        if isinstance(child, Mapping):
            for key, item in child.items():
                if is_id_ref_key(key):
                    values.append(item)
                walk(item)
        elif isinstance(child, (list, tuple, set)):
            for item in child:
                walk(item)

    walk(value)
    return values


def assert_sensitive_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SENSITIVE_SENTINELS:
        assert sentinel not in rendered


def assert_semantic_sentinels_absent(value: Any) -> None:
    rendered = safe_json(value)
    for sentinel in SEMANTIC_SENTINELS:
        assert sentinel not in rendered


def assert_no_forbidden_keys(value: Any) -> None:
    assert all_keys(value).isdisjoint(FORBIDDEN_OUTPUT_KEYS)


def assert_safe_projection_error(error: BaseException) -> None:
    assert isinstance(error, projection_error_type())
    assert_sensitive_sentinels_absent(error)
    assert_semantic_sentinels_absent(error)
    assert_no_forbidden_keys(error)
    assert set(vars(error)) <= {"code", "category", "paths", "counts"}
    assert isinstance(getattr(error, "code", None), str)
    assert isinstance(getattr(error, "category", None), str)
    for child in vars(error).values():
        assert not isinstance(child, BaseException)


def layout_signature(value: Any) -> Any:
    if isinstance(value, Mapping):
        stripped: dict[str, Any] = {}
        for key, child in value.items():
            if key in {"value", "values", "text"}:
                stripped[str(key)] = "<copied-value>"
            else:
                stripped[str(key)] = layout_signature(child)
        return stripped
    if isinstance(value, list):
        return [layout_signature(child) for child in value]
    return value


def display_log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    prefix = "cvbrain_intake_v2_display_plan "
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith(prefix):
            continue
        payload = json.loads(message[len(prefix) :])
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def test_display_plan_module_exposes_projection_interface():
    module = display_plan_module()

    assert callable(required_attr(module, "build_display_plan_v2"))
    assert issubclass(projection_error_type(), IntakeV2Error)


def test_display_plan_accepts_service_success_result_without_raw_inputs():
    result = service_success_result()

    plan = display_plan_from(result)

    assert_renderable_sections(plan)
    assert "display_plan" not in result
    assert "source_text" not in result
    assert "raw_output" not in result
    assert "prompt_body" not in result


def test_display_plan_sections_are_structural_and_renderable():
    plan = display_plan_from(service_success_result())

    assert section_codes(plan) == EXPECTED_SECTION_CODES
    assert_renderable_sections(plan)


def section_by_code(plan: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    for section in sections_from(plan):
        if section.get("code") == code:
            return section
    raise AssertionError(f"missing display_plan section: {code}")


def test_display_plan_exposes_stable_search_brief_sections_without_ui_inference():
    plan = display_plan_from(service_success_result())

    assert section_codes(plan) == EXPECTED_SECTION_CODES
    assert section_by_code(plan, "comparison_basis")["label"] == "What CVBrain will use to compare CVs"
    assert section_by_code(plan, "must_have_criteria")["label"] == "Must-have criteria"
    assert section_by_code(plan, "nice_to_have_criteria")["label"] == "Nice-to-have criteria"
    assert section_by_code(plan, "questions_for_recruiter")["label"] == "Questions for the recruiter"
    assert section_by_code(plan, "missing_information_or_blockers")["label"] == "Missing information / blockers"
    assert section_by_code(plan, "search_readiness")["label"] == "Search recommendation"
    assert section_by_code(plan, "recommended_next_steps")["label"] == "Recommended next steps"


def test_display_plan_preserves_criteria_questions_readiness_and_next_steps_in_stable_sections():
    hard_req = "HARD_REQ_SENTINEL"
    preferred_req = "PREF_REQ_SENTINEL"
    recruiter_question = "QUESTION_SENTINEL"
    search_recommendation = "SEARCH_RECOMMENDATION_SENTINEL"
    next_step = "NEXT_STEP_SENTINEL"
    draft = valid_draft(phrase=hard_req)
    draft["criteria"][0]["text"] = hard_req
    draft["criteria"][0]["source_evidence"] = hard_req
    draft["criteria"][0]["importance"] = "must_have"
    draft["criteria"][0]["clarification_question_ref"] = "company_q_alpha"
    draft["criteria"][1]["text"] = preferred_req
    draft["criteria"][1]["source_evidence"] = preferred_req
    draft["criteria"][1]["importance"] = "nice_to_have"
    draft["criteria"][1]["clarification_question_ref"] = "company_q_beta"
    draft["company_questions"][0]["question"] = recruiter_question
    draft["search_readiness"]["recommendation_summary"] = search_recommendation
    draft["search_readiness"]["recommended_next_steps"] = [next_step]
    result = {
        **service_success_result(),
        **internalize_draft_v2(draft),
    }

    plan = display_plan_from(result)
    must_have_text = safe_json(section_by_code(plan, "must_have_criteria"))
    nice_to_have_text = safe_json(section_by_code(plan, "nice_to_have_criteria"))
    question_text = safe_json(section_by_code(plan, "questions_for_recruiter"))
    search_readiness_text = safe_json(section_by_code(plan, "search_readiness"))
    next_steps_text = safe_json(section_by_code(plan, "recommended_next_steps"))
    full_plan = safe_json(plan)

    assert hard_req in must_have_text
    assert preferred_req in nice_to_have_text
    assert recruiter_question in question_text
    assert search_recommendation in search_readiness_text
    assert next_step in next_steps_text
    assert hard_req in full_plan
    assert preferred_req in full_plan
    assert recruiter_question not in must_have_text
    assert recruiter_question not in nice_to_have_text
    assert search_recommendation not in must_have_text
    assert search_recommendation not in nice_to_have_text
    assert next_step not in must_have_text
    assert next_step not in nice_to_have_text
    assert "provider_payload" not in full_plan
    assert "raw_output" not in full_plan


def test_display_plan_readiness_public_sections_use_schema_backed_human_text_not_machine_enums():
    result = service_success_result()
    readiness = result["document"]["search_readiness"]

    assert readiness["recommendation_summary"]
    assert readiness["recommended_next_steps"]

    plan = display_plan_from(result)
    readiness_text = safe_json(section_by_code(plan, "search_readiness"))
    next_steps_text = safe_json(section_by_code(plan, "recommended_next_steps"))

    assert readiness["recommendation_summary"] in readiness_text
    for step in readiness["recommended_next_steps"]:
        assert step in next_steps_text
    for machine_value in (
        readiness["status"],
        str(readiness["proceed_allowed"]).lower(),
        readiness["recommended_action"],
        str(readiness["recruiter_decision_required"]).lower(),
        str(readiness["continued_with_missing_information"]).lower(),
    ):
        assert machine_value not in readiness_text
        assert machine_value not in next_steps_text


def test_display_plan_preserves_ai_owned_text_exactly():
    plan = display_plan_from(service_success_result())
    rendered = safe_json(plan)

    for phrase in SEMANTIC_SENTINELS:
        assert phrase in rendered
    assert "PAPELES EN REGLA" not in rendered
    assert "Papeles En Regla" not in rendered


def test_phrase_changes_do_not_change_layout_or_metadata():
    first = display_plan_from(service_success_result(phrase="papeles en regla"))
    second = display_plan_from(service_success_result(phrase="changed AI-owned phrase"))

    assert layout_signature(first) == layout_signature(second)
    assert "papeles en regla" in safe_json(first)
    assert "changed AI-owned phrase" in safe_json(second)


def test_display_plan_excludes_unsafe_inputs_debug_fields_and_v1_projection():
    result = service_success_result()
    contaminated = copy.deepcopy(result)
    contaminated.update(
        {
            "source_text": "SOURCE_TEXT_SENTINEL papeles en regla",
            "raw_output": "RAW_OUTPUT_SENTINEL",
            "prompt_body": "PROMPT_BODY_SENTINEL",
            "provider_payload": {"secret": "SECRET_TOKEN_SENTINEL"},
            "api_key": "SECRET_TOKEN_SENTINEL",
            "auth_headers": {"authorization": "Bearer SECRET_TOKEN_SENTINEL"},
            "flat_compatibility": ["must not become V1 output"],
            "wordpress": {"ui": "must not leak"},
            "endpoint": {"http_status": 200},
        }
    )

    plan = display_plan_from(contaminated)

    assert_sensitive_sentinels_absent(plan)
    assert_no_forbidden_keys(plan)


def test_display_plan_uses_safe_item_ids_without_draft_local_refs_or_semantic_text_ids():
    plan = display_plan_from(service_success_result())
    rendered = safe_json(plan)
    dynamic_id_refs = safe_json(
        [
            value
            for value in id_ref_like_values(plan)
            if not (
                isinstance(value, str)
                and value.startswith("dp_section_")
                and any(code in value for code in EXPECTED_SECTION_CODES)
            )
        ]
    )

    for local_ref in RAW_LOCAL_REFS:
        assert local_ref not in rendered
    for phrase in SEMANTIC_SENTINELS:
        assert phrase not in dynamic_id_refs
        assert f"id_{phrase}" not in dynamic_id_refs
        assert phrase.replace(" ", "_") not in dynamic_id_refs
    for section in sections_from(plan):
        for item in section["items"]:
            item_id = str(item["id"])
            assert item_id
            for forbidden in RAW_LOCAL_REFS + SEMANTIC_SENTINELS:
                assert forbidden not in item_id


def test_service_failure_input_raises_safe_projection_error():
    failure = {
        "ok": False,
        "status": "error",
        "schema_version": "cvbrain_intake_v2_service",
        "error": {"code": "provider_failed", "category": "provider"},
        "source_text": "SOURCE_TEXT_SENTINEL papeles en regla",
        "raw_output": "RAW_OUTPUT_SENTINEL",
        "provider_payload": "SECRET_TOKEN_SENTINEL",
    }

    with pytest.raises(projection_error_type()) as exc_info:
        build_display_plan_v2(failure)

    assert_safe_projection_error(exc_info.value)


def test_invalid_missing_internal_document_raises_safe_projection_error():
    invalid = {
        "ok": True,
        "status": "ok",
        "schema_version": "cvbrain_intake_v2_service",
        "integrity": {"ok": True, "counts": {}, "codes": [], "paths": [], "categories": []},
        "source_text": "SOURCE_TEXT_SENTINEL required papeles en regla",
    }

    with pytest.raises(projection_error_type()) as exc_info:
        build_display_plan_v2(invalid)

    assert_safe_projection_error(exc_info.value)


def test_display_plan_does_not_require_ui_to_group_or_infer_content():
    plan = display_plan_from(service_success_result())

    assert_renderable_sections(plan)
    for section in sections_from(plan):
        assert section["code"] in EXPECTED_SECTION_CODES
        for item in section["items"]:
            assert "group_in_ui" not in item
            assert "infer_in_ui" not in item
            assert "classify_in_ui" not in item


def test_display_plan_module_imports_no_v1_semantic_runtime():
    module_path = ROOT / "app/intake_v2/display_plan.py"
    if not module_path.exists():
        pytest.fail("Gate 5 display_plan module is not implemented: expected app/intake_v2/display_plan.py")

    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    offenders = [
        imported
        for imported in imports
        if any(imported == forbidden or imported.startswith(forbidden + ".") for forbidden in FORBIDDEN_IMPORTS)
    ]
    assert offenders == []


def test_display_plan_logs_are_metadata_only_if_logs_are_emitted(caplog: pytest.LogCaptureFixture):
    failure = {
        "ok": False,
        "status": "error",
        "schema_version": "cvbrain_intake_v2_service",
        "error": {"code": "provider_failed", "category": "provider"},
        "source_text": "SOURCE_TEXT_SENTINEL papeles en regla",
        "raw_output": "RAW_OUTPUT_SENTINEL",
        "provider_payload": "SECRET_TOKEN_SENTINEL",
    }

    with caplog.at_level(logging.INFO, logger="cvbrain.intake_v2.display_plan"):
        with pytest.raises(projection_error_type()) as exc_info:
            build_display_plan_v2(failure)

    assert_safe_projection_error(exc_info.value)
    assert_sensitive_sentinels_absent(caplog.text)
    assert_semantic_sentinels_absent(caplog.text)
    for payload in display_log_payloads(caplog):
        assert set(payload) <= ALLOWED_LOG_KEYS

def test_display_plan_keeps_global_experience_clarifications_as_questions_not_criteria():
    draft = valid_draft(phrase="experiencia previa")
    draft["criteria"] = [
        {
            "local_ref": "crit_experience_scope",
            "criterion_kind": "experience",
            "text": "experiencia en roles similares",
            "source_evidence": "tenga experiencia",
            "importance": "must_have",
            "explicit": True,
            "precision_status": "needs_clarification",
            "missing_dimensions": ["duration", "scope", "evidence"],
            "clarification_question_ref": "company_q_experience_duration",
        },
        {
            "local_ref": "crit_confiable",
            "criterion_kind": "soft_competency",
            "text": "confiable",
            "source_evidence": "sea confiable",
            "importance": "must_have",
            "explicit": True,
            "precision_status": "needs_clarification",
            "missing_dimensions": ["evidence"],
            "clarification_question_ref": "company_q_soft_evidence",
        },
    ]
    draft["company_questions"] = [
        {
            "local_ref": "company_q_experience_duration",
            "question": "Cuanto tiempo de experiencia en roles similares se espera?",
            "audience": "hiring_company",
            "category": "search_precision",
            "criterion_refs": ["crit_experience_scope"],
            "missing_dimensions": ["duration"],
            "blocking_level": "important",
        },
        {
            "local_ref": "company_q_soft_evidence",
            "question": "Que comportamientos observables evidencian que la persona es confiable?",
            "audience": "hiring_company",
            "category": "search_precision",
            "criterion_refs": ["crit_confiable"],
            "missing_dimensions": ["evidence"],
            "blocking_level": "advisory",
        },
        {
            "local_ref": "company_q_business_baseline",
            "question": "Cual es el tipo de contrato/modalidad de contratacion, salario o rango, horario/disponibilidad, presencial/remoto/hibrido, ubicacion/zona y fecha de inicio/urgencia?",
            "audience": "hiring_company",
            "category": "job_configuration",
            "criterion_refs": [],
            "missing_dimensions": [],
            "blocking_level": "important",
        },
    ]
    draft["candidate_screening_questions"] = []
    result = {
        **service_success_result(),
        **internalize_draft_v2(draft),
    }

    plan = display_plan_from(result)
    must_have_text = safe_json(section_by_code(plan, "must_have_criteria"))
    question_text = safe_json(section_by_code(plan, "questions_for_recruiter"))
    full_plan = safe_json(plan)

    assert "experiencia en roles similares" in must_have_text
    assert "confiable" in must_have_text
    assert "Cuanto tiempo de experiencia" in question_text
    assert "comportamientos observables" in question_text
    assert "tipo de contrato/modalidad de contratacion" in question_text
    assert "salario o rango" in question_text
    assert "horario/disponibilidad" in question_text
    assert "presencial/remoto/hibrido" in question_text
    assert "ubicacion/zona" in question_text
    assert "fecha de inicio/urgencia" in question_text
    assert "Cuanto tiempo de experiencia" not in must_have_text
    assert "tipo de contrato/modalidad de contratacion" not in must_have_text
    assert "salario o rango" not in must_have_text
    assert "presencial/remoto/hibrido" not in must_have_text
    assert "edad" not in full_plan.lower()
    assert "sexo" not in full_plan.lower()
