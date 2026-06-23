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
    output["candidate_screening_questions"] = _dedupe_candidate_questions(
        output.get("candidate_screening_questions", []) or []
    )
    output["search_readiness"] = _readiness_with_precision(output.get("search_readiness", {}), needs_by_bucket)
    return output


def _precision_contract_errors(payload: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    requirements = payload.get("requirements", {})
    if not isinstance(requirements, Mapping):
        return ["precision_contract.requirements missing"]

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
        "criterion_id": str(item.get("criterion_id") or ""),
        "missing_dimensions": list(item.get("missing_dimensions", []) or []),
        "concept_key": _concept_key(str(item.get("text") or item.get("source_text") or question)),
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
            asked_to = str(item.get("asked_to") or "hiring_company").strip()
            missing_dimensions = [
                str(value)
                for value in item.get("missing_dimensions", []) or []
                if str(value).strip()
            ]
            criterion_id = str(item.get("criterion_id") or "").strip()
            concept_key = str(item.get("concept_key") or _question_topic_key(question) or field).strip()
        else:
            question = _clean_text(item)
            field = "requirements"
            question_id = f"precision_{_slug(question)}"
            asked_to = "hiring_company"
            missing_dimensions = []
            criterion_id = ""
            concept_key = _question_topic_key(question)
        if asked_to in {"candidate", "candidate_screening", "applicant"}:
            continue
        if not question or _is_bad_question(question):
            continue
        key = _question_key(
            question,
            audience=asked_to,
            criterion_id=criterion_id,
            missing_dimensions=missing_dimensions,
            concept_key=concept_key,
        )
        if key in seen:
            continue
        seen.add(key)
        normalized = {
            "id": question_id[:80],
            "question": question,
            "related_fields": [field],
            "blocking_level": "advisory",
            "asked_to": "hiring_company",
        }
        if criterion_id:
            normalized["criterion_id"] = criterion_id
        if missing_dimensions:
            normalized["missing_dimensions"] = _unique(missing_dimensions)
        if concept_key:
            normalized["concept_key"] = concept_key[:80]
        output.append(normalized)
    return output


def _dedupe_candidate_questions(items: Iterable[Any]) -> List[Any]:
    output: List[Any] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, Mapping):
            question = _clean_text(item.get("question") or item.get("suggested_question") or "")
        else:
            question = _clean_text(item)
        if not question:
            continue
        key = _question_key(question, audience="candidate", concept_key=_question_topic_key(question))
        if key in seen:
            continue
        seen.add(key)
        output.append(dict(item) if isinstance(item, Mapping) else question)
    return output


def _is_bad_question(question: str) -> bool:
    folded = _fold(question)
    if "?" not in question:
        return True
    return bool(
        re.search(
            r"\b(?:tenes|ten[eé]s|tienes|cumplis|cumples|pod[eé]s\s+(?:ampliar|aportar|contar|demostrar)|"
            r"puedes\s+(?:aportar|contar|demostrar)|podrias\s+ampliar|podr[ií]as\s+ampliar|"
            r"como\s+encajas|c[oó]mo\s+encajas|can\s+you\s+elaborate|search_readiness|"
            r"low_confidence|ai_schema|ai_provider)\b",
            folded,
        )
    )


def _criterion_id(bucket: str, index: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8] if text else f"{index:02d}"
    return f"{bucket}_{digest}"


def _question_key(
    question: str,
    *,
    audience: str = "hiring_company",
    criterion_id: str = "",
    missing_dimensions: Iterable[str] = (),
    concept_key: str = "",
) -> str:
    folded = _fold(question)
    folded = re.sub(r"\b(?:exacta|exacto|concreta|concreto|debe|deberia|debería|candidato|cv|validarse|validar)\b", " ", folded)
    normalized_question = re.sub(r"\s+", " ", folded).strip()
    dimensions = ",".join(sorted(str(value).strip() for value in missing_dimensions if str(value).strip()))
    concept = concept_key or _question_topic_key(question) or normalized_question
    if criterion_id and dimensions:
        return f"{audience}|{criterion_id}|{dimensions}|{concept}"
    if dimensions:
        return f"{audience}|{dimensions}|{concept}"
    return f"{audience}|{concept}|{normalized_question}"


def _question_topic_key(question: str) -> str:
    folded = _fold(question)
    if re.search(r"\b(?:licencia|libreta|carnet|conducir|categoria|categor[ií]a)\b", folded):
        return "credential:driving_license"
    if re.search(r"\b(?:papeles|documentaci[oó]n|documentos?|legal|regla)\b", folded):
        return "legal_documentation"
    if re.search(r"\b(?:experiencia|a[nñ]os?|evidencia|demostrable)\b", folded):
        return "experience:evidence"
    if re.search(r"\b(?:oficial|categoria|categor[ií]a|equivalencia|equivalente)\b", folded):
        return "level:equivalence"
    if re.search(r"\b(?:sigla|acr[oó]nimo|significa|meaning)\b", folded):
        return "undefined_acronym"
    return ""


def _concept_key(text: str) -> str:
    folded = _fold(text)
    if (
        re.search(r"\b(?:licencia|libreta|carnet)\s+(?:de\s+)?conducir\b", folded)
        or re.search(r"\b(?:licencia|libreta|carnet)\s+(?:categoria\s+)?(?![yeou]\b)[a-z0-9]\b", folded)
    ):
        return "credential:driving_license"
    if re.search(r"\b(?:papeles|documentaci[oó]n|documentos?)\s+(?:en\s+)?regla\b", folded):
        return "legal_documentation"
    folded = re.sub(r"[^a-z0-9áéíóúñü\s]+", " ", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    return folded


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
