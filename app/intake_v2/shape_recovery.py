"""Structural shape recovery for CVBrain Intake v2 provider drafts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Dict

from app.intake_v2.errors import V2ShapeRecoveryError


REQUIRED_LIST_PATHS = (
    ("criteria",),
    ("company_questions",),
    ("candidate_screening_questions",),
    ("job_profile", "industries"),
    ("search_strategy", "target_titles"),
    ("search_strategy", "search_terms"),
    ("search_strategy", "semantic_terms"),
    ("search_strategy", "negative_terms"),
    ("quality_control", "warnings"),
)

REQUIRED_OBJECT_PATHS = (
    ("job_profile",),
    ("location_and_modality",),
    ("search_strategy",),
    ("search_readiness",),
    ("quality_control",),
)

REQUIRED_SCALAR_PATHS = (
    ("schema_version",),
    ("job_profile", "role_title"),
    ("search_readiness", "status"),
    ("search_readiness", "proceed_allowed"),
    ("search_readiness", "recommended_action"),
    ("search_readiness", "recruiter_decision_required"),
    ("search_readiness", "continued_with_missing_information"),
    ("quality_control", "confidence"),
    ("quality_control", "contains_candidate_data"),
    ("quality_control", "contains_candidate_pii"),
)


def recover_provider_shape_v2(payload: Any) -> Dict[str, Any]:
    """Recover only non-semantic SDK/container shape before V2 validation."""

    recovered = _to_json_compatible(payload)
    if not isinstance(recovered, dict):
        _raise_shape_error("", recovered, "payload must be a JSON object")

    for path in REQUIRED_OBJECT_PATHS:
        value, present = _value_at(recovered, path)
        if not present or value is None:
            _raise_shape_error(_path_name(path), value, "required object is missing or null")
        if not isinstance(value, dict):
            _raise_shape_error(_path_name(path), value, "required object has wrong type")

    for path in REQUIRED_LIST_PATHS:
        value, present = _value_at(recovered, path)
        if not present or value is None:
            _raise_shape_error(_path_name(path), value, "required semantic list is missing or null")
        if not isinstance(value, list):
            _raise_shape_error(_path_name(path), value, "required semantic list has wrong type")

    for path in REQUIRED_SCALAR_PATHS:
        value, present = _value_at(recovered, path)
        if not present:
            _raise_shape_error(_path_name(path), None, "required scalar is missing")
        if isinstance(value, (dict, list)):
            _raise_shape_error(_path_name(path), value, "required scalar has wrong type")

    return recovered


def _to_json_compatible(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_json_compatible(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_compatible(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _to_json_compatible(model_dump(mode="json"))
        except TypeError:
            return _to_json_compatible(model_dump())
    as_dict = getattr(value, "dict", None)
    if callable(as_dict):
        return _to_json_compatible(as_dict())
    return value


def _value_at(payload: Mapping[str, Any], path: tuple[str, ...]) -> tuple[Any, bool]:
    current: Any = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None, False
        current = current[part]
    return current, True


def _raise_shape_error(path: str, value: Any, message: str) -> None:
    raise V2ShapeRecoveryError(
        f"{path or 'payload'}: {message}",
        path=path,
        repair_required=True,
        malformed_value=value,
        raw_value_sha256=_sha256_json(value),
    )


def _sha256_json(value: Any) -> str:
    try:
        serialized = json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        serialized = str(value)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _path_name(path: tuple[str, ...]) -> str:
    return ".".join(path)
