"""Typed CVBrain Job Intelligence v2 provider contract.

Gate 1 defines only the AI/provider draft contract and strict schema generator.
It intentionally does not implement provider calls, canonicalization,
projections, services, endpoints, or V1 compatibility adapters.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Mapping, Optional, Type

from pydantic import BaseModel, ConfigDict, ValidationError

from app.intake_v2.errors import IntakeV2ContractError


SCHEMA_VERSION_V2 = "cvbrain_job_intelligence_v2"

CriterionImportanceV2 = Literal["must_have", "should_have", "nice_to_have", "blocker"]
PrecisionStatusV2 = Literal["precise", "needs_clarification"]
MissingDimensionV2 = Literal[
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
]
CriterionKindV2 = Literal[
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
CompanyQuestionCategoryV2 = Literal["search_precision", "job_configuration", "safety_or_policy", "technical"]
CandidateQuestionCategoryV2 = Literal["screening", "interview", "evidence"]
BlockingLevelV2 = Literal["blocking", "important", "advisory"]
WorkModalityV2 = Literal["onsite", "hybrid", "remote", "mixed"]
ReadinessStatusV2 = Literal["ready", "usable_with_warnings", "insufficient_for_precise_search", "blocked"]
RecommendedActionV2 = Literal[
    "continue_anyway",
    "answer_clarifying_questions",
    "ask_company",
    "use_manual_search",
    "cancel",
]


class StrictDraftV2Model(BaseModel):
    """Base model for strict provider-facing v2 objects."""

    model_config = ConfigDict(extra="forbid")


class CriterionDraftV2(StrictDraftV2Model):
    """A single AI-extracted candidate criterion.

    ``local_ref`` is draft-local. Public canonical IDs are generated later by
    the v2 canonical boundary and must not preserve these values as public IDs.
    """

    local_ref: str
    criterion_kind: CriterionKindV2
    text: str
    source_evidence: str
    importance: CriterionImportanceV2
    explicit: bool
    precision_status: PrecisionStatusV2
    missing_dimensions: List[MissingDimensionV2]
    clarification_question_ref: Optional[str]


class CompanyQuestionDraftV2(StrictDraftV2Model):
    """Question addressed to the recruiter or hiring company."""

    local_ref: str
    question: str
    audience: Literal["hiring_company"]
    category: CompanyQuestionCategoryV2
    criterion_refs: List[str]
    missing_dimensions: List[MissingDimensionV2]
    blocking_level: BlockingLevelV2


class CandidateScreeningQuestionDraftV2(StrictDraftV2Model):
    """Candidate-facing screening question kept separate from recruiter questions."""

    local_ref: str
    question: str
    audience: Literal["candidate"]
    category: CandidateQuestionCategoryV2
    criterion_refs: List[str]
    missing_dimensions: List[MissingDimensionV2]
    blocking_level: BlockingLevelV2


class JobProfileDraftV2(StrictDraftV2Model):
    role_title: str
    role_family: Optional[str]
    professional_grade: Optional[str]
    seniority: Optional[str]
    summary: Optional[str]
    industries: List[str]


class LocationModalityDraftV2(StrictDraftV2Model):
    raw_location: Optional[str]
    normalized_location: Optional[str]
    country_code: Optional[str]
    city: Optional[str]
    region: Optional[str]
    work_modality: Optional[WorkModalityV2]
    remote_allowed: Optional[bool]
    hybrid_allowed: Optional[bool]
    onsite_required: Optional[bool]


class SearchStrategyDraftV2(StrictDraftV2Model):
    target_titles: List[str]
    search_terms: List[str]
    semantic_terms: List[str]
    negative_terms: List[str]


class SearchReadinessDraftV2(StrictDraftV2Model):
    status: ReadinessStatusV2
    proceed_allowed: bool
    recommended_action: RecommendedActionV2
    recruiter_decision_required: bool
    continued_with_missing_information: bool


class QualityControlDraftV2(StrictDraftV2Model):
    warnings: List[str]
    confidence: float
    contains_candidate_data: bool
    contains_candidate_pii: bool


class JobIntelligenceDraftV2(StrictDraftV2Model):
    """AI/provider output for CVBrain Job Intelligence v2."""

    schema_version: Literal["cvbrain_job_intelligence_v2"]
    job_profile: JobProfileDraftV2
    location_and_modality: LocationModalityDraftV2
    criteria: List[CriterionDraftV2]
    company_questions: List[CompanyQuestionDraftV2]
    candidate_screening_questions: List[CandidateScreeningQuestionDraftV2]
    search_strategy: SearchStrategyDraftV2
    search_readiness: SearchReadinessDraftV2
    quality_control: QualityControlDraftV2


def validate_job_intelligence_draft_v2(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a v2 draft and return JSON-compatible data."""

    try:
        return JobIntelligenceDraftV2.model_validate(payload).model_dump(mode="json")
    except ValidationError as error:
        raise IntakeV2ContractError(str(error)) from error


def job_intelligence_v2_response_schema() -> Dict[str, Any]:
    """Return the strict OpenAI provider schema for JobIntelligenceDraftV2."""

    return strict_provider_schema_for_model(JobIntelligenceDraftV2)


def strict_provider_schema_for_model(model: Type[BaseModel]) -> Dict[str, Any]:
    """Generate a strict Structured Outputs-compatible schema from a Pydantic model."""

    return _strict_openai_schema(model.model_json_schema())


def _strict_openai_schema(schema: Mapping[str, Any]) -> Dict[str, Any]:
    def clean(value: Any) -> Any:
        if isinstance(value, list):
            return [clean(item) for item in value]
        if not isinstance(value, dict):
            return value

        node: Dict[str, Any] = {}
        for key, child in value.items():
            if key in {"default", "examples", "title"}:
                continue
            if key == "const":
                node["enum"] = [child]
                continue
            node[key] = clean(child)

        if "anyOf" in node:
            collapsed = _collapse_nullable_any_of(node["anyOf"])
            if collapsed is not None:
                node.pop("anyOf", None)
                node.update(collapsed)

        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["properties"] = {str(key): clean(child) for key, child in properties.items()}
                node["required"] = list(node["properties"].keys())
            node["additionalProperties"] = False

        if "$defs" in node and isinstance(node["$defs"], dict):
            node["$defs"] = {str(key): clean(child) for key, child in node["$defs"].items()}

        if "items" in node:
            node["items"] = clean(node["items"])

        return node

    return clean(dict(schema))


def _collapse_nullable_any_of(options: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(options, list) or len(options) != 2:
        return None
    null_options = [option for option in options if isinstance(option, dict) and option.get("type") == "null"]
    if len(null_options) != 1:
        return None
    non_null = next(option for option in options if option not in null_options)
    if not isinstance(non_null, dict) or "$ref" in non_null:
        return None

    collapsed = {key: value for key, value in non_null.items() if key != "type"}
    non_null_type = non_null.get("type")
    if isinstance(non_null_type, str):
        collapsed["type"] = [non_null_type, "null"]
    elif "enum" in collapsed:
        collapsed["enum"] = list(collapsed["enum"]) + [None]
    else:
        return None

    if "enum" in collapsed and None not in collapsed["enum"]:
        collapsed["enum"] = list(collapsed["enum"]) + [None]
    return collapsed
