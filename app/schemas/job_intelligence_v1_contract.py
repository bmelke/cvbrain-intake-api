"""Validation helpers for mocked CVBrain Job Intelligence v1 outputs.

This module is intentionally provider-free. It validates fixture and test
payloads that represent future Structured Output responses, but it does not
call OpenAI, read API keys, or change the live `/api/job-intake/analyze`
runtime path.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict


SCHEMA_VERSION = "cvbrain_job_intelligence_v1"

REQUIRED_TOP_LEVEL_SECTIONS = (
    "schema_version",
    "job_profile",
    "location_intelligence",
    "requirements",
    "search_strategy",
    "missing_information",
    "company_clarification_questions",
    "candidate_screening_questions",
    "search_readiness",
    "quality_control",
)

SEARCH_READINESS_STATUSES = {
    "ready",
    "usable_with_warnings",
    "exploratory",
    "insufficient_for_precise_search",
    "blocked_for_safety_or_technical_reason",
}

PROCEED_ALLOWED_STATUSES = {
    "ready",
    "usable_with_warnings",
    "exploratory",
    "insufficient_for_precise_search",
}

DECISION_OPTIONS = {
    "continue_anyway",
    "answer_clarifying_questions",
    "ask_company",
    "use_manual_search",
    "cancel",
}

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

FORBIDDEN_CANDIDATE_KEYS = {
    "candidate_results",
    "candidate_ids",
    "candidate_names",
    "candidate_headlines",
    "candidate_email",
    "candidate_phone",
    "candidate_address",
    "raw_cv",
    "resume_text",
}

PII_OR_SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]|sk-proj|AIza|BEGIN (?:RSA|OPENSSH|PRIVATE) KEY|"
    r"candidate_email|mailto:|tel:|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    re.I,
)


class JobIntelligenceValidationError(ValueError):
    """Raised when a mocked Job Intelligence v1 payload is not safe to map."""


class JobIntelligenceV1Output(BaseModel):
    """Pydantic target for OpenAI Structured Outputs.

    Nested sections remain dictionaries/lists because the schema is still being
    designed. The stricter semantic validation lives in
    `validate_job_intelligence_v1`.
    """

    schema_version: str
    job_profile: Dict[str, Any]
    location_intelligence: Dict[str, Any]
    requirements: Dict[str, Any]
    search_strategy: Dict[str, Any]
    missing_information: List[Any]
    company_clarification_questions: List[Any]
    candidate_screening_questions: List[Any]
    search_readiness: Dict[str, Any]
    quality_control: Dict[str, Any]
    source: Optional[Dict[str, Any]] = None
    fixture_id: Optional[str] = None
    flat_compatibility: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


def validate_job_intelligence_v1(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the minimal CVBrain Job Intelligence v1 contract used in tests.

    The validator is intentionally conservative about safety boundaries and
    intentionally light on product semantics. It checks that required sections
    exist, readiness/proceed rules are coherent, hard-filter metadata stays
    explicit, and candidate data is not present.
    """

    errors: List[str] = []

    if not isinstance(payload, Mapping):
        raise JobIntelligenceValidationError("payload must be a JSON object")

    for section in REQUIRED_TOP_LEVEL_SECTIONS:
        if section not in payload:
            errors.append(f"missing top-level section: {section}")

    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    _require_mapping(payload, "job_profile", errors)
    _require_mapping(payload, "location_intelligence", errors)
    _require_mapping(payload, "requirements", errors)
    _require_mapping(payload, "search_strategy", errors)
    _require_mapping(payload, "search_readiness", errors)
    _require_mapping(payload, "quality_control", errors)
    _require_list(payload, "missing_information", errors)
    _require_list(payload, "company_clarification_questions", errors)
    _require_list(payload, "candidate_screening_questions", errors)

    if isinstance(payload.get("requirements"), Mapping):
        _validate_requirements(payload["requirements"], errors)

    if isinstance(payload.get("search_strategy"), Mapping):
        _validate_search_strategy(payload["search_strategy"], errors)

    if isinstance(payload.get("search_readiness"), Mapping):
        _validate_search_readiness(payload["search_readiness"], errors)

    if isinstance(payload.get("quality_control"), Mapping):
        _validate_quality_control(payload["quality_control"], errors)

    if isinstance(payload.get("flat_compatibility"), Mapping):
        _validate_flat_compatibility(payload["flat_compatibility"], errors)

    forbidden_keys = sorted(_find_forbidden_candidate_keys(payload))
    if forbidden_keys:
        errors.append(f"candidate data keys are not allowed: {', '.join(forbidden_keys)}")

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if PII_OR_SECRET_PATTERN.search(serialized):
        errors.append("payload contains a secret-like or PII-like value")

    if errors:
        raise JobIntelligenceValidationError("; ".join(errors))

    return dict(payload)


def _require_mapping(payload: Mapping[str, Any], key: str, errors: List[str]) -> None:
    if key in payload and not isinstance(payload[key], Mapping):
        errors.append(f"{key} must be an object")


def _require_list(payload: Mapping[str, Any], key: str, errors: List[str]) -> None:
    if key in payload and not isinstance(payload[key], list):
        errors.append(f"{key} must be a list")


def _validate_requirements(requirements: Mapping[str, Any], errors: List[str]) -> None:
    for key in ("must_have", "should_have", "nice_to_have", "credentials", "soft_competencies"):
        if key not in requirements:
            errors.append(f"requirements.{key} is required")
        elif not isinstance(requirements[key], list):
            errors.append(f"requirements.{key} must be a list")

    if "experience" not in requirements or not isinstance(requirements.get("experience"), Mapping):
        errors.append("requirements.experience must be an object")

    for group_name, item in _iter_requirement_items(requirements):
        if not isinstance(item, Mapping):
            errors.append(f"requirements.{group_name} items must be objects")
            continue

        approved = item.get("hard_filter_approved", False)
        candidate = item.get("hard_filter_candidate", False)

        if not isinstance(candidate, bool):
            errors.append(f"requirements.{group_name}.hard_filter_candidate must be boolean")
        if not isinstance(approved, bool):
            errors.append(f"requirements.{group_name}.hard_filter_approved must be boolean")

        if approved and not candidate:
            errors.append(f"requirements.{group_name} cannot approve a non-candidate hard filter")

        if group_name in {"should_have", "nice_to_have", "soft_competencies"} and approved:
            errors.append(f"requirements.{group_name} cannot be hard_filter_approved")

        _validate_precision_fields(group_name, item, errors)


def _iter_requirement_items(requirements: Mapping[str, Any]) -> Iterable[tuple[str, Any]]:
    for group_name in ("must_have", "should_have", "nice_to_have", "credentials", "soft_competencies"):
        items = requirements.get(group_name, [])
        if isinstance(items, list):
            for item in items:
                yield group_name, item


def _validate_precision_fields(group_name: str, item: Mapping[str, Any], errors: List[str]) -> None:
    path = f"requirements.{group_name}"
    if not str(item.get("criterion_id", "")).strip():
        errors.append(f"{path}.criterion_id is required")

    status = item.get("precision_status")
    if status not in PRECISION_STATUSES:
        errors.append(f"{path}.precision_status is invalid")

    dimensions = item.get("missing_dimensions")
    if not isinstance(dimensions, list):
        errors.append(f"{path}.missing_dimensions must be a list")
        dimensions = []
    elif any(dimension not in MISSING_DIMENSIONS for dimension in dimensions):
        errors.append(f"{path}.missing_dimensions contains an invalid value")

    question = item.get("clarification_question")
    if status == "needs_clarification":
        if not dimensions:
            errors.append(f"{path}.missing_dimensions is required for imprecise criteria")
        if not isinstance(question, str) or not question.strip():
            errors.append(f"{path}.clarification_question is required for imprecise criteria")
    elif status == "precise":
        if dimensions:
            errors.append(f"{path}.missing_dimensions must be empty for precise criteria")
        if question not in (None, ""):
            errors.append(f"{path}.clarification_question must be null for precise criteria")


def _validate_search_strategy(search_strategy: Mapping[str, Any], errors: List[str]) -> None:
    for key in ("target_titles", "search_terms", "semantic_terms", "negative_terms"):
        if key not in search_strategy:
            errors.append(f"search_strategy.{key} is required")
        elif not isinstance(search_strategy[key], list):
            errors.append(f"search_strategy.{key} must be a list")


def _validate_search_readiness(search_readiness: Mapping[str, Any], errors: List[str]) -> None:
    status = search_readiness.get("status")
    proceed_allowed = search_readiness.get("proceed_allowed")

    if status not in SEARCH_READINESS_STATUSES:
        errors.append("search_readiness.status is invalid")

    if not isinstance(proceed_allowed, bool):
        errors.append("search_readiness.proceed_allowed must be boolean")
    elif status in PROCEED_ALLOWED_STATUSES and proceed_allowed is not True:
        errors.append("search_readiness.proceed_allowed must be true for non-blocked statuses")
    elif status == "blocked_for_safety_or_technical_reason" and proceed_allowed is not False:
        errors.append("blocked search_readiness must not allow proceed")

    decision_options = search_readiness.get("decision_options", [])
    if not isinstance(decision_options, list):
        errors.append("search_readiness.decision_options must be a list")
    elif any(option not in DECISION_OPTIONS for option in decision_options):
        errors.append("search_readiness.decision_options contains an invalid option")

    if status in PROCEED_ALLOWED_STATUSES and "continue_anyway" not in decision_options:
        errors.append("non-blocked search_readiness must expose continue_anyway")


def _validate_quality_control(quality_control: Mapping[str, Any], errors: List[str]) -> None:
    confidence = quality_control.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
        errors.append("quality_control.confidence must be between 0.0 and 1.0")

    if quality_control.get("contains_candidate_data") is not False:
        errors.append("quality_control.contains_candidate_data must be false")

    if quality_control.get("contains_candidate_pii") is not False:
        errors.append("quality_control.contains_candidate_pii must be false")


def _validate_flat_compatibility(flat: Mapping[str, Any], errors: List[str]) -> None:
    for key in (
        "role_title",
        "must_have",
        "should_have",
        "nice_to_have",
        "credentials",
        "experience",
        "location",
        "search_terms",
        "semantic_terms",
        "recruiter_questions",
        "warnings",
        "confidence",
    ):
        if key not in flat:
            errors.append(f"flat_compatibility.{key} is required when flat_compatibility is present")


def _find_forbidden_candidate_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_CANDIDATE_KEYS:
                found.add(key)
            found.update(_find_forbidden_candidate_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_forbidden_candidate_keys(child))
    return found
