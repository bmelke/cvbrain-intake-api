"""Strict machine contract for confirmed CV search execution."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


CONTRACT_SCHEMA_VERSION = "cvbrain_confirmed_search_contract_v1"


class StrictExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceLanguageV1(StrictExecutionModel):
    source_language_mode: Literal["ai_resolved", "consumer_declared", "unresolved"]
    resolved_source_language: Optional[str]


class ReadinessV1(StrictExecutionModel):
    status: Literal["ready", "usable_with_warnings", "insufficient_for_precise_search", "blocked"]
    proceed_allowed: bool
    recruiter_decision_required: bool
    continued_with_missing_information: bool
    unresolved_question_ids: List[str]


class RoleProfileV1(StrictExecutionModel):
    primary_title: str
    alternate_titles: List[str]
    seniority: Optional[str]
    function: Optional[str]
    industry_context: List[str]


class LocationWorkArrangementV1(StrictExecutionModel):
    countries: List[str]
    regions: List[str]
    cities: List[str]
    modality: Optional[Literal["onsite", "hybrid", "remote", "mixed"]]
    remote_allowed: Optional[bool]
    hybrid_allowed: Optional[bool]
    onsite_required: Optional[bool]
    travel_requirement: Literal["required", "preferred", "not_required", "unresolved"]
    relocation_requirement: Literal["required", "preferred", "not_required", "unresolved"]


class CriterionV1(StrictExecutionModel):
    criterion_id: str
    kind: Literal[
        "experience",
        "technical_skill",
        "credential",
        "license",
        "professional_grade",
        "soft_competency",
        "responsibility_evidence",
        "industry_domain",
        "location",
        "work_modality",
        "legal_documentation",
        "blocker",
        "education",
        "language",
        "tool",
        "search_concept",
        "general_requirement",
    ]
    scope: Literal[
        "candidate_filter",
        "ranking_signal",
        "interview_only",
        "context_only",
        "exclusion",
        "prohibited",
        "unresolved",
    ]
    importance: Literal["must_have", "should_have", "nice_to_have", "blocker"]
    statement: str
    operator: Literal[
        "equals",
        "not_equals",
        "contains",
        "in",
        "greater_than_or_equal",
        "less_than_or_equal",
        "between",
        "present",
        "unresolved",
    ]
    operand: Optional[str]
    unit: Optional[str]
    evidence_requirement: Literal[
        "cv_evidence",
        "official_document",
        "portfolio",
        "reference_check",
        "interview_verification",
        "none",
        "unresolved",
    ]
    precision_status: Literal["precise", "needs_clarification"]
    missing_dimensions: List[str]
    clarification_question_ids: List[str]


class ClarificationQuestionV1(StrictExecutionModel):
    question_id: str
    statement: str
    criterion_ids: List[str]
    missing_dimensions: List[str]
    blocking_level: Literal["blocking", "important", "advisory"]


class ExperienceRequirementV1(StrictExecutionModel):
    criterion_id: str
    experience_domain: Optional[str]
    minimum_value: Optional[float]
    maximum_value: Optional[float]
    unit: Optional[str]
    recency_requirement: Optional[str]
    scale_or_scope: Optional[str]
    evidence_requirement: Literal[
        "cv_evidence",
        "official_document",
        "portfolio",
        "reference_check",
        "interview_verification",
        "none",
        "unresolved",
    ]
    precision_status: Literal["precise", "needs_clarification"]


class CredentialRequirementV1(StrictExecutionModel):
    criterion_id: str
    credential_name: Optional[str]
    credential_issuer: Optional[str]
    operator: Literal[
        "equals", "not_equals", "contains", "in", "greater_than_or_equal", "less_than_or_equal", "between", "present", "unresolved"
    ]
    evidence_requirement: Literal[
        "cv_evidence",
        "official_document",
        "portfolio",
        "reference_check",
        "interview_verification",
        "none",
        "unresolved",
    ]
    precision_status: Literal["precise", "needs_clarification"]


class LicenseRequirementV1(StrictExecutionModel):
    criterion_id: str
    license_name: Optional[str]
    license_category: Optional[str]
    jurisdictions: List[str]
    operator: Literal[
        "equals", "not_equals", "contains", "in", "greater_than_or_equal", "less_than_or_equal", "between", "present", "unresolved"
    ]
    evidence_requirement: Literal[
        "cv_evidence",
        "official_document",
        "portfolio",
        "reference_check",
        "interview_verification",
        "none",
        "unresolved",
    ]
    precision_status: Literal["precise", "needs_clarification"]


class ExclusionV1(StrictExecutionModel):
    criterion_id: str
    statement: str
    operator: Literal[
        "equals", "not_equals", "contains", "in", "greater_than_or_equal", "less_than_or_equal", "between", "present", "unresolved"
    ]
    operand: Optional[str]


class SearchStrategyV1(StrictExecutionModel):
    must_have_criterion_ids: List[str]
    preferred_criterion_ids: List[str]
    exclusion_criterion_ids: List[str]
    unresolved_criterion_ids: List[str]
    search_terms: List[str]
    semantic_terms: List[str]
    negative_terms: List[str]


class SafetyV1(StrictExecutionModel):
    protected_traits_excluded: bool
    no_candidate_selection_performed: Literal[True]
    no_candidate_data_included: Literal[True]
    contract_state: Literal["safe", "blocked", "unresolved"]


class SearchExecutionContractBodyV1(StrictExecutionModel):
    schema_version: Literal["cvbrain_confirmed_search_contract_v1"]
    source_language: SourceLanguageV1
    readiness: ReadinessV1
    role_profile: RoleProfileV1
    location_and_work_arrangement: LocationWorkArrangementV1
    criteria: List[CriterionV1]
    clarification_questions: List[ClarificationQuestionV1]
    experience_requirements: List[ExperienceRequirementV1]
    credentials: List[CredentialRequirementV1]
    licenses: List[LicenseRequirementV1]
    exclusions: List[ExclusionV1]
    search_strategy: SearchStrategyV1
    safety: SafetyV1

    @model_validator(mode="after")
    def validate_references(self) -> "SearchExecutionContractBodyV1":
        criterion_ids = [item.criterion_id for item in self.criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion IDs must be unique")
        question_ids = [item.question_id for item in self.clarification_questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("clarification question IDs must be unique")

        criterion_set = set(criterion_ids)
        question_set = set(question_ids)
        strategy_refs = (
            self.search_strategy.must_have_criterion_ids
            + self.search_strategy.preferred_criterion_ids
            + self.search_strategy.exclusion_criterion_ids
            + self.search_strategy.unresolved_criterion_ids
        )
        criterion_refs = list(strategy_refs)
        criterion_refs += [item.criterion_id for item in self.experience_requirements]
        criterion_refs += [item.criterion_id for item in self.credentials]
        criterion_refs += [item.criterion_id for item in self.licenses]
        criterion_refs += [item.criterion_id for item in self.exclusions]
        criterion_refs += [criterion_id for item in self.clarification_questions for criterion_id in item.criterion_ids]
        if any(reference not in criterion_set for reference in criterion_refs):
            raise ValueError("criterion reference does not resolve")

        question_refs = list(self.readiness.unresolved_question_ids)
        question_refs += [question_id for item in self.criteria for question_id in item.clarification_question_ids]
        if any(reference not in question_set for reference in question_refs):
            raise ValueError("clarification question reference does not resolve")

        criteria_by_id = {item.criterion_id: item for item in self.criteria}
        if any(
            criteria_by_id[item].scope != "candidate_filter"
            for item in self.search_strategy.must_have_criterion_ids
        ):
            raise ValueError("must-have strategy references must use candidate-filter scope")
        if any(
            criteria_by_id[item].scope not in {"candidate_filter", "ranking_signal"}
            for item in self.search_strategy.preferred_criterion_ids
        ):
            raise ValueError("preferred strategy references must use filter or ranking scope")
        if any(
            criteria_by_id[item].scope != "exclusion"
            for item in self.search_strategy.exclusion_criterion_ids
        ):
            raise ValueError("exclusion strategy references must use exclusion scope")
        if not self.safety.protected_traits_excluded:
            raise ValueError("protected traits must be excluded")
        return self


class SearchExecutionContractV1(SearchExecutionContractBodyV1):
    contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_digest(self) -> "SearchExecutionContractV1":
        approved = self.model_dump(mode="json", exclude={"contract_digest"})
        expected = _digest_for_approved_fields(approved)
        if self.contract_digest != expected:
            raise ValueError("contract digest does not match approved fields")
        return self


def build_search_execution_contract_v1(service_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Mechanically project a validated internal V2 document."""

    document = _mapping(service_result.get("document"), "document")
    profile = _mapping(document.get("job_profile"), "job_profile")
    location = _mapping(document.get("location_and_modality"), "location_and_modality")
    strategy = _mapping(document.get("search_strategy"), "search_strategy")
    readiness = _mapping(document.get("search_readiness"), "search_readiness")
    quality = _mapping(document.get("quality_control"), "quality_control")
    criteria_source = _mapping_list(document.get("criteria"), "criteria")
    question_source = _mapping_list(document.get("company_questions"), "company_questions")

    criteria = [_criterion(item) for item in criteria_source]
    questions = [_question(item, criteria_source, criteria) for item in question_source]
    criterion_aliases = _criterion_aliases(criteria_source, criteria)
    strategy_refs = {
        key: _resolved_refs(strategy.get(source_key, []), criterion_aliases)
        for key, source_key in (
            ("must_have_criterion_ids", "must_have_criterion_refs"),
            ("preferred_criterion_ids", "preferred_criterion_refs"),
            ("exclusion_criterion_ids", "exclusion_criterion_refs"),
            ("unresolved_criterion_ids", "unresolved_criterion_refs"),
        )
    }
    criteria_by_id = {item["criterion_id"]: item for item in criteria}

    payload: Dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "source_language": {
            "source_language_mode": strategy.get("source_language_mode", "unresolved"),
            "resolved_source_language": strategy.get("resolved_source_language"),
        },
        "readiness": {
            "status": readiness.get("status"),
            "proceed_allowed": readiness.get("proceed_allowed"),
            "recruiter_decision_required": readiness.get("recruiter_decision_required"),
            "continued_with_missing_information": readiness.get("continued_with_missing_information"),
            "unresolved_question_ids": [item["question_id"] for item in questions],
        },
        "role_profile": {
            "primary_title": profile.get("role_title", ""),
            "alternate_titles": copy.deepcopy(list(strategy.get("target_titles", []))),
            "seniority": profile.get("seniority"),
            "function": profile.get("role_family"),
            "industry_context": copy.deepcopy(list(profile.get("industries", []))),
        },
        "location_and_work_arrangement": {
            "countries": _explicit_or_single(location.get("countries"), location.get("country_code")),
            "regions": _explicit_or_single(location.get("regions"), location.get("region")),
            "cities": _explicit_or_single(location.get("cities"), location.get("city")),
            "modality": location.get("work_modality"),
            "remote_allowed": location.get("remote_allowed"),
            "hybrid_allowed": location.get("hybrid_allowed"),
            "onsite_required": location.get("onsite_required"),
            "travel_requirement": location.get("travel_requirement", "unresolved"),
            "relocation_requirement": location.get("relocation_requirement", "unresolved"),
        },
        "criteria": criteria,
        "clarification_questions": questions,
        "experience_requirements": [
            _experience(item)
            for item in criteria_source
            if item.get("criterion_kind") == "experience"
        ],
        "credentials": [_credential(item) for item in criteria_source if item.get("criterion_kind") == "credential"],
        "licenses": [_license(item) for item in criteria_source if item.get("criterion_kind") == "license"],
        "exclusions": [
            {
                "criterion_id": criterion_id,
                "statement": criteria_by_id[criterion_id]["statement"],
                "operator": criteria_by_id[criterion_id]["operator"],
                "operand": criteria_by_id[criterion_id]["operand"],
            }
            for criterion_id in strategy_refs["exclusion_criterion_ids"]
            if criterion_id in criteria_by_id
        ],
        "search_strategy": {
            **strategy_refs,
            "search_terms": copy.deepcopy(list(strategy.get("search_terms", []))),
            "semantic_terms": copy.deepcopy(list(strategy.get("semantic_terms", []))),
            "negative_terms": copy.deepcopy(list(strategy.get("negative_terms", []))),
        },
        "safety": {
            "protected_traits_excluded": strategy.get("protected_traits_excluded", True),
            "no_candidate_selection_performed": True,
            "no_candidate_data_included": not bool(quality.get("contains_candidate_data"))
            and not bool(quality.get("contains_candidate_pii")),
            "contract_state": strategy.get("contract_state", "unresolved"),
        },
    }
    canonical = SearchExecutionContractBodyV1.model_validate(payload).model_dump(mode="json")
    canonical["contract_digest"] = compute_search_execution_contract_digest(canonical)
    return SearchExecutionContractV1.model_validate(canonical).model_dump(mode="json")


def canonicalize_search_execution_contract_v1(value: Mapping[str, Any]) -> Dict[str, Any]:
    return SearchExecutionContractV1.model_validate(value).model_dump(mode="json")


def compute_search_execution_contract_digest(value: Mapping[str, Any]) -> str:
    approved = copy.deepcopy(dict(value))
    approved.pop("contract_digest", None)
    return _digest_for_approved_fields(approved)


def _digest_for_approved_fields(approved: Mapping[str, Any]) -> str:
    canonical = json.dumps(approved, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _criterion(item: Mapping[str, Any]) -> Dict[str, Any]:
    question_id = item.get("clarification_question_id")
    return {
        "criterion_id": _criterion_id(item),
        "kind": item.get("criterion_kind"),
        "scope": item.get("scope", "unresolved"),
        "importance": item.get("importance"),
        "statement": item.get("text", ""),
        "operator": item.get("operator", "unresolved"),
        "operand": item.get("operand"),
        "unit": item.get("unit"),
        "evidence_requirement": item.get("evidence_requirement", "unresolved"),
        "precision_status": item.get("precision_status"),
        "missing_dimensions": copy.deepcopy(list(item.get("missing_dimensions", []))),
        "clarification_question_ids": [question_id] if isinstance(question_id, str) and question_id else [],
    }


def _question(
    item: Mapping[str, Any],
    source_criteria: List[Mapping[str, Any]],
    criteria: List[Mapping[str, Any]],
) -> Dict[str, Any]:
    aliases = _criterion_aliases(source_criteria, criteria)
    return {
        "question_id": item.get("internal_id"),
        "statement": item.get("question", ""),
        "criterion_ids": _resolved_refs(item.get("criterion_ids", []), aliases),
        "missing_dimensions": copy.deepcopy(list(item.get("missing_dimensions", []))),
        "blocking_level": item.get("blocking_level"),
    }


def _experience(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "criterion_id": _criterion_id(item),
        "experience_domain": item.get("experience_domain"),
        "minimum_value": item.get("minimum_value"),
        "maximum_value": item.get("maximum_value"),
        "unit": item.get("unit"),
        "recency_requirement": item.get("recency_requirement"),
        "scale_or_scope": item.get("scale_or_scope"),
        "evidence_requirement": item.get("evidence_requirement", "unresolved"),
        "precision_status": item.get("precision_status"),
    }


def _credential(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "criterion_id": _criterion_id(item),
        "credential_name": item.get("credential_name"),
        "credential_issuer": item.get("credential_issuer"),
        "operator": item.get("operator", "unresolved"),
        "evidence_requirement": item.get("evidence_requirement", "unresolved"),
        "precision_status": item.get("precision_status"),
    }


def _license(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "criterion_id": _criterion_id(item),
        "license_name": item.get("license_name"),
        "license_category": item.get("license_category"),
        "jurisdictions": copy.deepcopy(list(item.get("license_jurisdictions", []))),
        "operator": item.get("operator", "unresolved"),
        "evidence_requirement": item.get("evidence_requirement", "unresolved"),
        "precision_status": item.get("precision_status"),
    }


def _criterion_id(item: Mapping[str, Any]) -> str:
    explicit = item.get("criterion_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    internal = item.get("internal_id")
    if isinstance(internal, str) and internal:
        return internal
    raise ValueError("criterion has no stable ID")


def _criterion_aliases(source: List[Mapping[str, Any]], projected: List[Mapping[str, Any]]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for item, output in zip(source, projected):
        output_id = str(output["criterion_id"])
        for candidate in (item.get("criterion_id"), item.get("internal_id")):
            if isinstance(candidate, str) and candidate:
                aliases[candidate] = output_id
    return aliases


def _resolved_refs(values: Any, aliases: Mapping[str, str]) -> List[str]:
    if not isinstance(values, list):
        raise ValueError("reference list must be a list")
    return [aliases.get(value, value) for value in values]


def _explicit_or_single(explicit: Any, single: Any) -> List[str]:
    if isinstance(explicit, list) and explicit:
        return copy.deepcopy(explicit)
    return [single] if isinstance(single, str) and single else []


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def _mapping_list(value: Any, name: str) -> List[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must be a list of mappings")
    return value


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "SearchExecutionContractV1",
    "build_search_execution_contract_v1",
    "canonicalize_search_execution_contract_v1",
    "compute_search_execution_contract_digest",
]
