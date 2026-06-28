"""Mechanical internal IDs and reference integrity for CVBrain Intake v2."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List

from app.intake_v2.contract import validate_job_intelligence_draft_v2
from app.intake_v2.errors import IntakeV2ContractError, V2InternalIntegrityError


INTEGRITY_CATEGORY = "internal_reference_integrity"


def internalize_draft_v2(payload: Mapping[str, Any] | Any) -> Dict[str, Any]:
    """Convert a validated V2 draft into a mechanically internalized document."""

    draft = _validated_mapping(payload)
    counts = _counts(draft)
    criteria = list(draft.get("criteria", []))
    company_questions = list(draft.get("company_questions", []))
    candidate_questions = list(draft.get("candidate_screening_questions", []))

    criteria_refs = _local_ref_map(criteria, "criteria", counts)
    company_question_refs = _local_ref_map(company_questions, "company_questions", counts)
    candidate_question_refs = _local_ref_map(candidate_questions, "candidate_screening_questions", counts)

    internalized_criteria = [
        _internalize_criterion(index, item, company_question_refs, counts) for index, item in enumerate(criteria)
    ]
    internalized_company_questions = [
        _internalize_question("company_questions", index, item, criteria_refs, counts)
        for index, item in enumerate(company_questions)
    ]
    internalized_candidate_questions = [
        _internalize_question("candidate_screening_questions", index, item, criteria_refs, counts)
        for index, item in enumerate(candidate_questions)
    ]

    document = {
        "schema_version": draft["schema_version"],
        "job_profile": copy.deepcopy(draft["job_profile"]),
        "location_and_modality": copy.deepcopy(draft["location_and_modality"]),
        "criteria": internalized_criteria,
        "company_questions": internalized_company_questions,
        "candidate_screening_questions": internalized_candidate_questions,
        "search_strategy": copy.deepcopy(draft["search_strategy"]),
        "search_readiness": copy.deepcopy(draft["search_readiness"]),
        "quality_control": copy.deepcopy(draft["quality_control"]),
    }
    return {"document": document, "integrity": _integrity_metadata(ok=True, counts=counts)}


def _validated_mapping(payload: Mapping[str, Any] | Any) -> Dict[str, Any]:
    if isinstance(payload, Mapping):
        candidate = payload
    else:
        model_dump = getattr(payload, "model_dump", None)
        if callable(model_dump):
            try:
                candidate = model_dump(mode="json")
            except TypeError:
                candidate = model_dump()
        else:
            candidate = payload
    try:
        return validate_job_intelligence_draft_v2(candidate)
    except IntakeV2ContractError:
        _raise_integrity_error("invalid_contract", ["payload"], _counts({}))


def _local_ref_map(items: Iterable[Mapping[str, Any]], collection: str, counts: Mapping[str, int]) -> Dict[str, str]:
    refs: Dict[str, str] = {}
    for index, item in enumerate(items):
        local_ref = item.get("local_ref")
        if not isinstance(local_ref, str) or not local_ref:
            _raise_integrity_error("missing_local_ref", [f"{collection}.local_ref"], counts)
        if local_ref in refs:
            _raise_integrity_error("duplicate_local_ref", [f"{collection}.local_ref"], counts)
        refs[local_ref] = _internal_id(collection, index)
    return refs


def _internalize_criterion(
    index: int,
    item: Mapping[str, Any],
    company_question_refs: Mapping[str, str],
    counts: Mapping[str, int],
) -> Dict[str, Any]:
    output = {
        key: copy.deepcopy(value)
        for key, value in item.items()
        if key not in {"local_ref", "clarification_question_ref"}
    }
    clarification_ref = item.get("clarification_question_ref")
    if clarification_ref is None:
        output["clarification_question_id"] = None
    elif isinstance(clarification_ref, str) and clarification_ref in company_question_refs:
        output["clarification_question_id"] = company_question_refs[clarification_ref]
    else:
        _raise_integrity_error("unresolved_reference", ["criteria.clarification_question_ref"], counts)
    output["internal_id"] = _internal_id("criteria", index)
    return output


def _internalize_question(
    collection: str,
    index: int,
    item: Mapping[str, Any],
    criteria_refs: Mapping[str, str],
    counts: Mapping[str, int],
) -> Dict[str, Any]:
    output = {key: copy.deepcopy(value) for key, value in item.items() if key not in {"local_ref", "criterion_refs"}}
    output["criterion_ids"] = [_resolved_criterion_id(collection, local_ref, criteria_refs, counts) for local_ref in item["criterion_refs"]]
    output["internal_id"] = _internal_id(collection, index)
    return output


def _resolved_criterion_id(
    collection: str,
    local_ref: Any,
    criteria_refs: Mapping[str, str],
    counts: Mapping[str, int],
) -> str:
    if isinstance(local_ref, str) and local_ref in criteria_refs:
        return criteria_refs[local_ref]
    _raise_integrity_error("unresolved_reference", [f"{collection}.criterion_refs"], counts)


def _internal_id(collection: str, index: int) -> str:
    digest = hashlib.sha256(f"cvbrain-v2:{collection}:{index}".encode("ascii")).hexdigest()[:20]
    return f"v2_{digest}"


def _counts(draft: Mapping[str, Any]) -> Dict[str, int]:
    return {
        "criteria": _collection_size(draft.get("criteria")),
        "company_questions": _collection_size(draft.get("company_questions")),
        "candidate_screening_questions": _collection_size(draft.get("candidate_screening_questions")),
    }


def _collection_size(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def _integrity_metadata(*, ok: bool, counts: Mapping[str, int], codes: List[str] | None = None, paths: List[str] | None = None) -> Dict[str, Any]:
    return {
        "ok": ok,
        "paths": list(paths or []),
        "counts": dict(counts),
        "codes": list(codes or []),
        "categories": [INTEGRITY_CATEGORY],
    }


def _raise_integrity_error(code: str, paths: List[str], counts: Mapping[str, int]) -> None:
    integrity = _integrity_metadata(ok=False, counts=counts, codes=[code], paths=paths)
    raise V2InternalIntegrityError(integrity=integrity) from None
