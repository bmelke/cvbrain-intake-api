"""Map CVBrain Job Intelligence v1 payloads into the current flat contract.

This module is intentionally library/test-only. It is not imported by
`app.main` and does not alter the live FastAPI response path.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from app.mappers.recruiter_display_plan import build_recruiter_display_plan
from app.normalization.role_title import display_role_title_from_job_profile
from app.schemas.job_intelligence_v1_contract import validate_job_intelligence_v1


FLAT_VERSION = "0.1.0"


def derive_flat_compatibility(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Derive the WordPress-compatible flat response from Job Intelligence v1."""

    validated = validate_job_intelligence_v1(payload)

    job_profile = validated["job_profile"]
    location = validated["location_intelligence"]
    requirements = validated["requirements"]
    search_strategy = validated["search_strategy"]
    readiness = validated["search_readiness"]
    quality_control = validated["quality_control"]

    warnings = _unique(
        _string_values(quality_control.get("warnings", []))
        + _string_values(location.get("warnings", []))
        + _readiness_warnings(readiness)
    )

    flat = {
        "ok": True,
        "version": FLAT_VERSION,
        "role_title": display_role_title_from_job_profile(job_profile),
        "role_family": job_profile.get("role_family", ""),
        "summary": job_profile.get("summary", ""),
        "must_have": _requirement_texts(requirements.get("must_have", [])),
        "should_have": _requirement_texts(requirements.get("should_have", [])),
        "nice_to_have": _requirement_texts(requirements.get("nice_to_have", [])),
        "blockers": _string_values(requirements.get("blockers", [])),
        "credentials": _credentials(requirements.get("credentials", [])),
        "experience": {
            "minimum_years": requirements.get("experience", {}).get("minimum_years"),
            "seniority": requirements.get("experience", {}).get("seniority")
            or job_profile.get("seniority", ""),
        },
        "location": {
            "raw": location.get("raw", ""),
            "normalized": location.get("normalized", ""),
            "remote_allowed": location.get("remote_allowed"),
            "hybrid_allowed": location.get("hybrid_allowed"),
        },
        "search_terms": _unique(
            _string_values(search_strategy.get("target_titles", []))
            + _string_values(search_strategy.get("search_terms", []))
        ),
        "semantic_terms": _unique(
            _string_values(search_strategy.get("semantic_terms", []))
            + _string_values(job_profile.get("primary_industries", []))
        ),
        "recruiter_questions": _unique(
            _question_texts(validated.get("company_clarification_questions", []))
        ),
        "candidate_screening_questions": _unique(
            _question_texts(validated.get("candidate_screening_questions", []))
        ),
        "warnings": warnings,
        "confidence": float(quality_control.get("confidence", 0.0)),
    }
    flat["display_plan"] = build_recruiter_display_plan(validated, flat)
    return flat


def _credentials(items: Iterable[Any]) -> Dict[str, List[str]]:
    required: List[str] = []
    preferred: List[str] = []

    for item in items:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        level = str(item.get("importance", item.get("requirement_level", ""))).strip()
        if level == "must_have":
            required.append(text)
        else:
            preferred.append(text)

    return {
        "required": _unique(required),
        "preferred": _unique(preferred),
    }


def _requirement_texts(items: Iterable[Any]) -> List[str]:
    output: List[str] = []
    for item in items:
        if isinstance(item, Mapping):
            text = str(item.get("text", "")).strip()
        else:
            text = str(item).strip()
        if text:
            output.append(text)
    return _unique(output)


def _question_texts(items: Iterable[Any]) -> List[str]:
    output: List[str] = []
    for item in items:
        if isinstance(item, Mapping):
            text = str(item.get("question", "")).strip()
        else:
            text = str(item).strip()
        if text:
            output.append(text)
    return output


def _readiness_warnings(readiness: Mapping[str, Any]) -> List[str]:
    status = str(readiness.get("status", "")).strip()
    if status and status != "ready":
        return [f"search_readiness_{status}"]
    return []


def _string_values(items: Iterable[Any]) -> List[str]:
    output: List[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            output.append(text)
    return output


def _unique(items: Iterable[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for item in items:
        clean = " ".join(str(item).split())
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
    return output
