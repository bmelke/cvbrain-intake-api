"""Precision coverage helpers for one-pass AI intake extraction.

The AI extraction call owns the semantic judgment. This module only validates
and normalizes the precision fields returned by that call, then aggregates
safe recruiter-facing clarification questions.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping

from app.schemas.job_intelligence_v1_contract import JobIntelligenceValidationError


PRECISION_STATUSES = {"precise", "needs_clarification"}
MISSING_DIMENSIONS = {
    "duration",
    "quantity",
    "scope",
    "level",
    "evidence",
    "identity",
    "equivalence",
    "importance",
    "geography",
    "modality",
    "frequency",
    "legal_documentation",
    "credential",
    "license_category",
    "undefined_acronym",
}
STRUCTURED_REQUIREMENT_BUCKETS = (
    "must_have",
    "should_have",
    "nice_to_have",
    "credentials",
    "soft_competencies",
)


def validate_precision_contract(payload: Mapping[str, Any]) -> None:
    """Validate one-pass AI precision coverage before accepting a response."""

    errors = _precision_contract_errors(payload)
    if errors:
        raise JobIntelligenceValidationError("; ".join(errors))


def ensure_precision_contract(payload: Mapping[str, Any], *, strict: bool = False) -> Dict[str, Any]:
    """Normalize precision metadata and aggregate clarification questions."""

    if strict:
        validate_precision_contract(payload)

    output: Dict[str, Any] = dict(payload)
    requirements = dict(output.get("requirements", {}) or {})
    output["requirements"] = requirements

    precision_questions: List[Dict[str, Any]] = []
    needs_by_bucket: Dict[str, int] = {}

    for bucket in STRUCTURED_REQUIREMENT_BUCKETS:
        normalized_items: List[Dict[str, Any]] = []
        for index, item in enumerate(requirements.get(bucket, []) or []):
            if not isinstance(item, Mapping):
                continue
            normalized = _normalize_precision_item(item, bucket=bucket, index=index)
            normalized_items.append(normalized)
            if normalized.get("precision_status") == "needs_clarification":
                needs_by_bucket[bucket] = needs_by_bucket.get(bucket, 0) + 1
                question = _question_from_item(normalized, bucket)
                if question:
                    precision_questions.append(question)
        requirements[bucket] = normalized_items

    existing_questions = list(output.get("company_clarification_questions", []) or [])
    output["company_clarification_questions"] = _dedupe_questions(existing_questions + precision_questions)
    output["search_readiness"] = _readiness_with_precision(output.get("search_readiness", {}), needs_by_bucket)
    return output


def _precision_contract_errors(payload: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    requirements = payload.get("requirements", {})
    if not isinstance(requirements, Mapping):
        return ["precision_contract.requirements missing"]

    existing_questions = _question_texts(payload.get("company_clarification_questions", []))

    for bucket in STRUCTURED_REQUIREMENT_BUCKETS:
        items = requirements.get(bucket, [])
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            path = f"precision_contract.requirements.{bucket}[{index}]"
            if not isinstance(item, Mapping):
                continue
            status = item.get("precision_status")
            if status not in PRECISION_STATUSES:
                errors.append(f"{path}.precision_status missing_or_invalid")
                continue
            if not str(item.get("criterion_id", "")).strip():
                errors.append(f"{path}.criterion_id missing")
            dimensions = item.get("missing_dimensions")
            if not isinstance(dimensions, list):
                errors.append(f"{path}.missing_dimensions must_be_list")
                dimensions = []
            invalid_dimensions = [str(value) for value in dimensions if value not in MISSING_DIMENSIONS]
            if invalid_dimensions:
                errors.append(f"{path}.missing_dimensions invalid:{','.join(invalid_dimensions)}")
            question = str(item.get("clarification_question") or "").strip()
            if status == "needs_clarification":
                if not dimensions:
                    errors.append(f"{path}.missing_dimensions empty_for_needs_clarification")
                if not question:
                    errors.append(f"{path}.clarification_question missing")
                elif _is_bad_question(question):
                    errors.append(f"{path}.clarification_question not_recruiter_facing")
                elif _question_key(question) not in existing_questions:
                    errors.append(f"{path}.clarification_question not_in_company_questions")
                if not str(item.get("source_text") or item.get("text") or "").strip():
                    errors.append(f"{path}.source_text missing_for_ambiguity")
            elif status == "precise":
                if dimensions:
                    errors.append(f"{path}.missing_dimensions must_be_empty_for_precise")
                if question:
                    errors.append(f"{path}.clarification_question must_be_null_for_precise")
    return errors


def _normalize_precision_item(item: Mapping[str, Any], *, bucket: str, index: int) -> Dict[str, Any]:
    normalized = dict(item)
    text = str(normalized.get("text") or normalized.get("source_text") or "").strip()
    status = str(normalized.get("precision_status") or "precise").strip()
    if status not in PRECISION_STATUSES:
        status = "precise"
    dimensions = normalized.get("missing_dimensions")
    if not isinstance(dimensions, list):
        dimensions = []
    dimensions = _unique([str(value) for value in dimensions if value in MISSING_DIMENSIONS])
    question = str(normalized.get("clarification_question") or "").strip()

    normalized["criterion_id"] = str(normalized.get("criterion_id") or _criterion_id(bucket, index, text)).strip()
    normalized["precision_status"] = status
    normalized["missing_dimensions"] = dimensions if status == "needs_clarification" else []
    normalized["clarification_question"] = question if status == "needs_clarification" and question else None
    return normalized


def _question_from_item(item: Mapping[str, Any], bucket: str) -> Dict[str, Any]:
    question = str(item.get("clarification_question") or "").strip()
    if not question or _is_bad_question(question):
        return {}
    return {
        "id": f"precision_{_slug(str(item.get('criterion_id') or question))}",
        "question": question,
        "related_fields": [f"requirements.{bucket}"],
        "blocking_level": "advisory",
        "asked_to": "hiring_company",
    }


def _readiness_with_precision(readiness: Any, needs_by_bucket: Mapping[str, int]) -> Dict[str, Any]:
    output: Dict[str, Any] = dict(readiness) if isinstance(readiness, Mapping) else {}
    if not needs_by_bucket or output.get("status") == "blocked_for_safety_or_technical_reason":
        return output

    current = str(output.get("status") or "ready")
    mandatory_credential = bool(needs_by_bucket.get("credentials"))
    must_have = bool(needs_by_bucket.get("must_have"))
    if mandatory_credential and current == "ready":
        output["status"] = "insufficient_for_precise_search"
        output["recommended_action"] = "ask_company"
    elif must_have and current == "ready":
        output["status"] = "usable_with_warnings"
        output.setdefault("recommended_action", "answer_clarifying_questions")
    elif current == "ready" and needs_by_bucket:
        output.setdefault("recommended_action", "continue_anyway")

    output["proceed_allowed"] = True
    output["continued_with_missing_information"] = bool(mandatory_credential or must_have)
    output["recruiter_decision_required"] = bool(mandatory_credential or must_have)
    output.setdefault("recruiter_override_reason", None)
    options = list(output.get("decision_options", []) or [])
    for option in ("continue_anyway", "answer_clarifying_questions", "ask_company", "use_manual_search", "cancel"):
        if option not in options:
            options.append(option)
    output["decision_options"] = options
    return output


def _dedupe_questions(items: Iterable[Any]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, Mapping):
            question = _clean_text(item.get("question") or item.get("suggested_question") or "")
            fields = item.get("related_fields") if isinstance(item.get("related_fields"), list) else []
            field = str(fields[0]) if fields else str(item.get("field") or "requirements")
            question_id = str(item.get("id") or f"precision_{_slug(question)}")
        else:
            question = _clean_text(item)
            field = "requirements"
            question_id = f"precision_{_slug(question)}"
        if not question or _is_bad_question(question):
            continue
        key = _question_key(question)
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "id": question_id[:80],
                "question": question,
                "related_fields": [field],
                "blocking_level": "advisory",
                "asked_to": "hiring_company",
            }
        )
    return output


def _question_texts(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    return {
        _question_key(item.get("question", ""))
        for item in items
        if isinstance(item, Mapping) and str(item.get("question", "")).strip()
    }


def _is_bad_question(question: str) -> bool:
    folded = _fold(question)
    if "?" not in question:
        return True
    return bool(
        re.search(
            r"\b(?:cumplis|cumples|pod[eé]s\s+ampliar|podrias\s+ampliar|podr[ií]as\s+ampliar|"
            r"can\s+you\s+elaborate|search_readiness|low_confidence|ai_schema|ai_provider)\b",
            folded,
        )
    )


def _criterion_id(bucket: str, index: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8] if text else f"{index:02d}"
    return f"{bucket}_{digest}"


def _question_key(question: str) -> str:
    folded = _fold(question)
    folded = re.sub(r"\b(?:exacta|exacto|concreta|concreto|debe|deberia|debería|candidato|cv|validarse|validar)\b", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _fold(value)).strip("_")
    return slug or "question"


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" -:.,;\t\r\n")


def _unique(items: Iterable[str]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for item in items:
        clean = str(item).strip()
        key = _fold(clean)
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
    return output


def _fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
