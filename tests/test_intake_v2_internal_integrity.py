from __future__ import annotations

import ast
import copy
import importlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.intake_v2.contract import SCHEMA_VERSION_V2, validate_job_intelligence_draft_v2


ROOT = Path(__file__).resolve().parents[1]
INTEGRITY_MODULE = "app.intake_v2.integrity"
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
ALLOWED_INTEGRITY_METADATA_KEYS = {"ok", "paths", "counts", "codes", "categories"}
FORBIDDEN_IMPORTS = {
    "app.normalization",
    "app.mappers",
    "app.extractors.deterministic",
    "app.extractors.router",
    "app.main",
}


def integrity_module() -> Any:
    try:
        return importlib.import_module(INTEGRITY_MODULE)
    except ModuleNotFoundError as error:
        pytest.fail(f"Gate 3 integrity module is not implemented: expected import {INTEGRITY_MODULE} ({error})")


def internalize_draft_v2(payload: Mapping[str, Any]) -> Any:
    module = integrity_module()
    if not hasattr(module, "internalize_draft_v2"):
        pytest.fail(f"{INTEGRITY_MODULE} must expose internalize_draft_v2")
    return module.internalize_draft_v2(payload)


def integrity_error_type() -> type[BaseException]:
    module = integrity_module()
    if not hasattr(module, "V2InternalIntegrityError"):
        pytest.fail(f"{INTEGRITY_MODULE} must expose V2InternalIntegrityError")
    error_type = module.V2InternalIntegrityError
    assert issubclass(error_type, Exception)
    return error_type


def value_at(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def internal_document(result: Any) -> Mapping[str, Any]:
    document = value_at(result, "document")
    assert isinstance(document, Mapping), "internalize_draft_v2 must return a result with a document mapping"
    return document


def integrity_metadata(result_or_error: Any) -> Mapping[str, Any]:
    metadata = value_at(result_or_error, "integrity")
    assert isinstance(metadata, Mapping), "internalization results/errors must expose safe integrity metadata"
    return metadata


def validated_payload(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return validate_job_intelligence_draft_v2(payload or valid_payload())


def valid_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION_V2,
        "job_profile": {
            "role_title": "Gate 3 mechanical role title",
            "role_family": "familia AI-preserved",
            "professional_grade": None,
            "seniority": None,
            "summary": "Preserve papeles en regla, oficial de primera, licencia profesional.",
            "industries": ["industria textual required"],
        },
        "location_and_modality": {
            "raw_location": "Montevideo source text only",
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
                "text": "papeles en regla",
                "source_evidence": "papeles en regla",
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
                "question": "Que documentacion significa papeles en regla?",
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
            "target_titles": ["Gate 3 mechanical role title"],
            "search_terms": ["papeles en regla", "licencia profesional"],
            "semantic_terms": ["oficial de primera"],
            "negative_terms": ["bloqueante"],
        },
        "search_readiness": {
            "status": "usable_with_warnings",
            "proceed_allowed": True,
            "recommended_action": "ask_company",
            "recruiter_decision_required": True,
            "continued_with_missing_information": True,
        },
        "quality_control": {
            "warnings": ["required and nice to have are source words only"],
            "confidence": 0.71,
            "contains_candidate_data": False,
            "contains_candidate_pii": False,
        },
    }


def empty_valid_payload() -> dict[str, Any]:
    payload = valid_payload()
    payload["criteria"] = []
    payload["company_questions"] = []
    payload["candidate_screening_questions"] = []
    payload["job_profile"]["industries"] = []
    payload["search_strategy"]["target_titles"] = []
    payload["search_strategy"]["search_terms"] = []
    payload["search_strategy"]["semantic_terms"] = []
    payload["search_strategy"]["negative_terms"] = []
    payload["quality_control"]["warnings"] = []
    return payload


def collect_internal_ids(document: Mapping[str, Any]) -> dict[str, list[str]]:
    return {
        "criteria": [item["internal_id"] for item in document["criteria"]],
        "company_questions": [item["internal_id"] for item in document["company_questions"]],
        "candidate_screening_questions": [item["internal_id"] for item in document["candidate_screening_questions"]],
    }


def all_internal_ids(document: Mapping[str, Any]) -> list[str]:
    collected = collect_internal_ids(document)
    return collected["criteria"] + collected["company_questions"] + collected["candidate_screening_questions"]


def semantic_snapshot(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "job_profile": document["job_profile"],
        "location_and_modality": document["location_and_modality"],
        "criteria_text": [
            (
                item["criterion_kind"],
                item["text"],
                item["source_evidence"],
                item["importance"],
                item["explicit"],
                item["precision_status"],
                item["missing_dimensions"],
            )
            for item in document["criteria"]
        ],
        "company_questions": [item["question"] for item in document["company_questions"]],
        "candidate_questions": [item["question"] for item in document["candidate_screening_questions"]],
        "search_strategy": document["search_strategy"],
        "search_readiness": document["search_readiness"],
        "quality_control": document["quality_control"],
    }


def assert_ids_are_opaque(ids: list[str]) -> None:
    assert ids
    assert len(ids) == len(set(ids))
    for internal_id in ids:
        assert isinstance(internal_id, str)
        assert internal_id.startswith("v2_")
        for forbidden in SEMANTIC_SENTINELS + SENSITIVE_SENTINELS + RAW_LOCAL_REFS:
            assert forbidden not in internal_id


def assert_safe_integrity_metadata(metadata: Mapping[str, Any]) -> None:
    assert set(metadata) <= ALLOWED_INTEGRITY_METADATA_KEYS
    serialized = json.dumps(metadata, sort_keys=True, default=str)
    for forbidden in SEMANTIC_SENTINELS + SENSITIVE_SENTINELS + RAW_LOCAL_REFS:
        assert forbidden not in serialized


def assert_safe_error(error: BaseException) -> None:
    rendered = repr(error) + " " + str(error) + " " + json.dumps(vars(error), sort_keys=True, default=str)
    for forbidden in SEMANTIC_SENTINELS + SENSITIVE_SENTINELS + RAW_LOCAL_REFS:
        assert forbidden not in rendered
    assert_safe_integrity_metadata(integrity_metadata(error))


def set_path(payload: dict[str, Any], path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    output = copy.deepcopy(payload)
    current: Any = output
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value
    return output


def replace_semantic_text(payload: dict[str, Any]) -> dict[str, Any]:
    replacement = copy.deepcopy(payload)
    replacement["job_profile"]["role_title"] = "Changed semantic title"
    replacement["job_profile"]["summary"] = "Changed domain phrase without changing structure."
    replacement["criteria"][0]["text"] = "changed domain phrase alpha"
    replacement["criteria"][0]["source_evidence"] = "changed source evidence alpha"
    replacement["criteria"][1]["text"] = "changed domain phrase beta"
    replacement["company_questions"][0]["question"] = "Changed company question text?"
    replacement["candidate_screening_questions"][0]["question"] = "Changed candidate question text?"
    replacement["search_strategy"]["search_terms"] = ["changed search term"]
    replacement["quality_control"]["warnings"] = ["changed warning"]
    return replacement


def test_internalization_assigns_stable_opaque_ids_and_preserves_semantic_fields():
    draft = validated_payload()

    first = internal_document(internalize_draft_v2(draft))
    second = internal_document(internalize_draft_v2(copy.deepcopy(draft)))

    assert collect_internal_ids(first) == collect_internal_ids(second)
    assert_ids_are_opaque(all_internal_ids(first))
    assert semantic_snapshot(first) == semantic_snapshot(second)
    assert first["criteria"][0]["text"] == "papeles en regla"
    assert first["criteria"][1]["text"] == "oficial de primera con licencia profesional"
    assert first["criteria"][2]["text"] == "bloqueante nice to have required"


def test_internalization_rewrites_references_by_local_ref_map_only():
    draft = validated_payload()

    document = internal_document(internalize_draft_v2(draft))
    criterion_ids = collect_internal_ids(document)["criteria"]
    company_question_ids = collect_internal_ids(document)["company_questions"]

    assert [item["text"] for item in document["criteria"]] == [item["text"] for item in draft["criteria"]]
    assert document["criteria"][0]["clarification_question_id"] == company_question_ids[0]
    assert document["criteria"][1]["clarification_question_id"] == company_question_ids[1]
    assert document["criteria"][2]["clarification_question_id"] is None
    assert document["company_questions"][0]["criterion_ids"] == [criterion_ids[0]]
    assert document["company_questions"][1]["criterion_ids"] == [criterion_ids[1], criterion_ids[2]]
    assert document["candidate_screening_questions"][0]["criterion_ids"] == [criterion_ids[0], criterion_ids[1]]
    assert "criterion_refs" not in document["company_questions"][0]
    assert "clarification_question_ref" not in document["criteria"][0]


def test_duplicate_local_refs_fail_mechanically_with_safe_integrity_metadata():
    payload = set_path(valid_payload(), ("criteria", 1, "local_ref"), "crit_alpha")
    payload["criteria"][0]["text"] = "SOURCE_TEXT_SENTINEL papeles en regla"
    draft = validated_payload(payload)

    with pytest.raises(integrity_error_type()) as exc_info:
        internalize_draft_v2(draft)

    assert_safe_error(exc_info.value)


def test_unresolved_local_refs_fail_mechanically_with_safe_integrity_metadata():
    payload = set_path(valid_payload(), ("company_questions", 0, "criterion_refs"), ["RAW_OUTPUT_SENTINEL_missing_ref"])
    draft = validated_payload(payload)

    with pytest.raises(integrity_error_type()) as exc_info:
        internalize_draft_v2(draft)

    assert_safe_error(exc_info.value)


def test_ai_provided_empty_collections_remain_empty_without_invented_content():
    draft = validated_payload(empty_valid_payload())

    result = internalize_draft_v2(draft)
    document = internal_document(result)
    integrity = integrity_metadata(result)

    assert document["criteria"] == []
    assert document["company_questions"] == []
    assert document["candidate_screening_questions"] == []
    assert document["job_profile"]["industries"] == []
    assert document["search_strategy"]["target_titles"] == []
    assert document["search_strategy"]["search_terms"] == []
    assert document["search_strategy"]["semantic_terms"] == []
    assert document["search_strategy"]["negative_terms"] == []
    assert integrity["counts"]["criteria"] == 0
    assert integrity["counts"]["company_questions"] == 0
    assert integrity["counts"]["candidate_screening_questions"] == 0


def test_changing_domain_phrases_does_not_change_ids_refs_or_integrity_outcome():
    base = validated_payload()
    changed = validated_payload(replace_semantic_text(valid_payload()))

    base_result = internalize_draft_v2(base)
    changed_result = internalize_draft_v2(changed)
    base_document = internal_document(base_result)
    changed_document = internal_document(changed_result)

    assert collect_internal_ids(base_document) == collect_internal_ids(changed_document)
    assert [item["criterion_ids"] for item in base_document["company_questions"]] == [
        item["criterion_ids"] for item in changed_document["company_questions"]
    ]
    assert [item["clarification_question_id"] for item in base_document["criteria"]] == [
        item["clarification_question_id"] for item in changed_document["criteria"]
    ]
    assert integrity_metadata(base_result) == integrity_metadata(changed_result)
    assert changed_document["criteria"][0]["text"] == "changed domain phrase alpha"


def test_integrity_metadata_contains_only_safe_paths_counts_codes_and_categories():
    result = internalize_draft_v2(validated_payload())
    metadata = integrity_metadata(result)

    assert_safe_integrity_metadata(metadata)
    assert isinstance(metadata["paths"], list)
    assert isinstance(metadata["counts"], Mapping)
    assert isinstance(metadata["codes"], list)
    assert metadata["counts"]["criteria"] == 3
    assert metadata["counts"]["company_questions"] == 2
    assert metadata["counts"]["candidate_screening_questions"] == 1


def test_internal_integrity_module_imports_no_v1_semantic_runtime():
    module_path = ROOT / "app/intake_v2/integrity.py"
    if not module_path.exists():
        pytest.fail("Gate 3 integrity module is not implemented: expected app/intake_v2/integrity.py")

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
