"""Public package surface for CVBrain Intake v2."""

from app.intake_v2.contract import (
    SCHEMA_VERSION_V2,
    JobIntelligenceDraftV2,
    job_intelligence_v2_response_schema,
    strict_provider_schema_for_model,
    validate_job_intelligence_draft_v2,
)
from app.intake_v2.display_plan import (
    DISPLAY_PLAN_SCHEMA_VERSION,
    build_display_plan_v2,
)
from app.intake_v2.errors import (
    IntakeV2ContractError,
    IntakeV2Error,
    V2ConfigurationError,
    V2DisplayPlanProjectionError,
    V2DraftContractError,
    V2DraftSchemaError,
    V2InternalIntegrityError,
    V2PipelineError,
    V2PipelineRequestError,
    V2ProviderTerminalError,
    V2ProviderTimeoutError,
    V2ProviderTransientError,
    V2PublicResponseError,
    V2RepairExhaustedError,
    V2ResponseParseError,
    V2ServiceRequestError,
    V2ShapeRecoveryError,
)
from app.intake_v2.integrity import internalize_draft_v2
from app.intake_v2.pipeline import run_public_intake_v2
from app.intake_v2.provider import (
    OpenAIProviderV2,
    ProviderAttemptMetadataV2,
    ProviderRequestV2,
    ProviderResultV2,
    ProviderValidationFailureV2,
)
from app.intake_v2.response import (
    PUBLIC_RESPONSE_SCHEMA_VERSION,
    build_public_response_v2,
)
from app.intake_v2.service import (
    SERVICE_SCHEMA_VERSION,
    IntakeServiceRequestV2,
    run_intake_v2,
)

__all__ = [
    "DISPLAY_PLAN_SCHEMA_VERSION",
    "IntakeServiceRequestV2",
    "IntakeV2ContractError",
    "IntakeV2Error",
    "JobIntelligenceDraftV2",
    "OpenAIProviderV2",
    "PUBLIC_RESPONSE_SCHEMA_VERSION",
    "ProviderAttemptMetadataV2",
    "ProviderRequestV2",
    "ProviderResultV2",
    "ProviderValidationFailureV2",
    "SCHEMA_VERSION_V2",
    "SERVICE_SCHEMA_VERSION",
    "V2ConfigurationError",
    "V2DisplayPlanProjectionError",
    "V2DraftContractError",
    "V2DraftSchemaError",
    "V2InternalIntegrityError",
    "V2PipelineError",
    "V2PipelineRequestError",
    "V2ProviderTerminalError",
    "V2ProviderTimeoutError",
    "V2ProviderTransientError",
    "V2PublicResponseError",
    "V2RepairExhaustedError",
    "V2ResponseParseError",
    "V2ServiceRequestError",
    "V2ShapeRecoveryError",
    "build_display_plan_v2",
    "build_public_response_v2",
    "internalize_draft_v2",
    "job_intelligence_v2_response_schema",
    "run_intake_v2",
    "run_public_intake_v2",
    "strict_provider_schema_for_model",
    "validate_job_intelligence_draft_v2",
]
