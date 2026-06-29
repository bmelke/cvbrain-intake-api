"""Pure display-plan projection for CVBrain Intake v2."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Dict, List

from app.intake_v2.errors import V2DisplayPlanProjectionError


DISPLAY_PLAN_SCHEMA_VERSION = "cvbrain_intake_v2_display_plan"

SECTION_DEFINITIONS = [
    ("job_profile", "Job profile"),
    ("location_and_modality", "Location and modality"),
    ("criteria", "Criteria"),
    ("company_questions", "Company questions"),
    ("candidate_screening_questions", "Candidate screening questions"),
    ("search_strategy", "Search strategy"),
    ("search_readiness", "Search readiness"),
    ("quality_control", "Quality control"),
]

JOB_PROFILE_FIELDS = [
    ("role_title", "Role title"),
    ("role_family", "Role family"),
    ("professional_grade", "Professional grade"),
    ("seniority", "Seniority"),
    ("summary", "Summary"),
    ("industries", "Industries"),
]

LOCATION_FIELDS = [
    ("raw_location", "Raw location"),
    ("normalized_location", "Normalized location"),
    ("country_code", "Country code"),
    ("city", "City"),
    ("region", "Region"),
    ("work_modality", "Work modality"),
    ("remote_allowed", "Remote allowed"),
    ("hybrid_allowed", "Hybrid allowed"),
    ("onsite_required", "Onsite required"),
]

SEARCH_STRATEGY_FIELDS = [
    ("target_titles", "Target titles"),
    ("search_terms", "Search terms"),
    ("semantic_terms", "Semantic terms"),
    ("negative_terms", "Negative terms"),
]

READINESS_FIELDS = [
    ("status", "Status"),
    ("proceed_allowed", "Proceed allowed"),
    ("recommended_action", "Recommended action"),
    ("recruiter_decision_required", "Recruiter decision required"),
    ("continued_with_missing_information", "Continued with missing information"),
]

QUALITY_CONTROL_FIELDS = [
    ("warnings", "Warnings"),
    ("confidence", "Confidence"),
    ("contains_candidate_data", "Contains candidate data"),
    ("contains_candidate_pii", "Contains candidate PII"),
]

CRITERION_DETAIL_FIELDS = [
    ("source_evidence", "Source evidence"),
    ("precision_status", "Precision status"),
    ("missing_dimensions", "Missing dimensions"),
    ("clarification_question_id", "Clarification question"),
]

QUESTION_DETAIL_FIELDS = [
    ("audience", "Audience"),
    ("category", "Category"),
    ("criterion_ids", "Criteria"),
    ("missing_dimensions", "Missing dimensions"),
    ("blocking_level", "Blocking level"),
]


def build_display_plan_v2(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Project an already-owned V2 service result into renderable sections."""

    if not isinstance(value, Mapping):
        _raise_projection_error(code="invalid_input_type", paths=["payload"])

    if value.get("ok") is False or value.get("status") == "error":
        _raise_projection_error(code="service_result_failed", paths=["status"], counts=_counts_from(value))

    document = value.get("document")
    if not isinstance(document, Mapping):
        _raise_projection_error(code="missing_internal_document", paths=["document"], counts=_counts_from(value))

    integrity = value.get("integrity")
    if not isinstance(integrity, Mapping):
        _raise_projection_error(code="missing_integrity_metadata", paths=["integrity"], counts=_counts_from(value))

    plan = {
        "schema_version": DISPLAY_PLAN_SCHEMA_VERSION,
        "sections": _sections(document),
    }
    return {"display_plan": plan}


def _sections(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for order, (code, label) in enumerate(SECTION_DEFINITIONS):
        sections.append(
            {
                "id": _section_id(order, code),
                "code": code,
                "label": label,
                "order": order,
                "items": _items_for_section(order, code, document),
            }
        )
    return sections


def _items_for_section(section_order: int, code: str, document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if code == "job_profile":
        return _mapping_field_items(section_order, _mapping_section(document, code), JOB_PROFILE_FIELDS)
    if code == "location_and_modality":
        return _mapping_field_items(section_order, _mapping_section(document, code), LOCATION_FIELDS)
    if code == "criteria":
        return _criteria_items(section_order, _list_section(document, code))
    if code == "company_questions":
        return _question_items(section_order, "company_question", _list_section(document, code))
    if code == "candidate_screening_questions":
        return _question_items(section_order, "candidate_question", _list_section(document, code))
    if code == "search_strategy":
        return _mapping_field_items(section_order, _mapping_section(document, code), SEARCH_STRATEGY_FIELDS)
    if code == "search_readiness":
        return _mapping_field_items(section_order, _mapping_section(document, code), READINESS_FIELDS)
    if code == "quality_control":
        return _mapping_field_items(section_order, _mapping_section(document, code), QUALITY_CONTROL_FIELDS)
    return []


def _mapping_field_items(
    section_order: int,
    source: Mapping[str, Any],
    fields: list[tuple[str, str]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for order, (field, label) in enumerate(fields):
        items.append(
            _display_item(
                section_order=section_order,
                order=order,
                code=field,
                kind="field",
                label=label,
                copied_value=source.get(field),
            )
        )
    return items


def _criteria_items(section_order: int, criteria: list[Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for order, raw_item in enumerate(criteria):
        criterion = raw_item if isinstance(raw_item, Mapping) else {}
        item = _display_item(
            section_order=section_order,
            order=order,
            code=f"criterion_{order}",
            kind="criterion",
            label=f"Criterion {order + 1}",
            copied_text=criterion.get("text"),
        )
        internal_id = _safe_internal_id(criterion)
        if internal_id is not None:
            item["internal_id"] = internal_id
        item["items"] = _nested_field_items(section_order, order, criterion, CRITERION_DETAIL_FIELDS)
        items.append(item)
    return items


def _question_items(section_order: int, kind: str, questions: list[Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for order, raw_item in enumerate(questions):
        question = raw_item if isinstance(raw_item, Mapping) else {}
        item = _display_item(
            section_order=section_order,
            order=order,
            code=f"{kind}_{order}",
            kind=kind,
            label=f"{kind.replace('_', ' ').title()} {order + 1}",
            copied_text=question.get("question"),
        )
        internal_id = _safe_internal_id(question)
        if internal_id is not None:
            item["internal_id"] = internal_id
        item["items"] = _nested_field_items(section_order, order, question, QUESTION_DETAIL_FIELDS)
        items.append(item)
    return items


def _nested_field_items(
    section_order: int,
    parent_order: int,
    source: Mapping[str, Any],
    fields: list[tuple[str, str]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for order, (field, label) in enumerate(fields):
        items.append(
            _display_item(
                section_order=section_order,
                order=order,
                code=f"{parent_order}_{field}",
                kind="detail",
                label=label,
                copied_value=source.get(field),
            )
        )
    return items


def _display_item(
    *,
    section_order: int,
    order: int,
    code: str,
    kind: str,
    label: str,
    copied_value: Any = None,
    copied_text: Any = None,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "id": _item_id(section_order, order),
        "code": code,
        "kind": kind,
        "label": label,
        "order": order,
    }
    if copied_text is not None:
        item["text"] = _copy(copied_text)
    elif isinstance(copied_value, list):
        item["values"] = _copy(copied_value)
    else:
        item["value"] = _copy(copied_value)
    return item


def _mapping_section(document: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    value = document.get(code)
    if isinstance(value, Mapping):
        return value
    _raise_projection_error(code="invalid_internal_document", paths=[f"document.{code}"], counts=_counts_from_document(document))


def _list_section(document: Mapping[str, Any], code: str) -> list[Any]:
    value = document.get(code)
    if isinstance(value, list):
        return value
    _raise_projection_error(code="invalid_internal_document", paths=[f"document.{code}"], counts=_counts_from_document(document))


def _safe_internal_id(value: Mapping[str, Any]) -> str | None:
    internal_id = value.get("internal_id")
    if isinstance(internal_id, str) and internal_id:
        return internal_id
    return None


def _section_id(order: int, code: str) -> str:
    return f"dp_section_{order:02d}_{code}"


def _item_id(section_order: int, order: int) -> str:
    return f"dp_item_{section_order:02d}_{order:03d}"


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _counts_from(value: Mapping[str, Any]) -> Dict[str, int]:
    integrity = value.get("integrity")
    if isinstance(integrity, Mapping) and isinstance(integrity.get("counts"), Mapping):
        return {str(key): _safe_int(child) for key, child in integrity["counts"].items()}
    document = value.get("document")
    if isinstance(document, Mapping):
        return _counts_from_document(document)
    return {}


def _counts_from_document(document: Mapping[str, Any]) -> Dict[str, int]:
    return {
        "criteria": _collection_size(document.get("criteria")),
        "company_questions": _collection_size(document.get("company_questions")),
        "candidate_screening_questions": _collection_size(document.get("candidate_screening_questions")),
    }


def _collection_size(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0


def _raise_projection_error(*, code: str, paths: list[str], counts: Mapping[str, int] | None = None) -> None:
    raise V2DisplayPlanProjectionError(code=code, paths=paths, counts=dict(counts or {})) from None


__all__ = [
    "DISPLAY_PLAN_SCHEMA_VERSION",
    "V2DisplayPlanProjectionError",
    "build_display_plan_v2",
]
