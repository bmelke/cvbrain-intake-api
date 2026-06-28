"""CVBrain Intake v2 contracts and provider boundary.

Gate 2 exposes the neutral provider boundary. Service orchestration,
canonicalization, projections, and endpoints are added in later gates.
"""

from app.intake_v2.contract import (
    SCHEMA_VERSION_V2,
    JobIntelligenceDraftV2,
    job_intelligence_v2_response_schema,
    strict_provider_schema_for_model,
    validate_job_intelligence_draft_v2,
)
from app.intake_v2.errors import (
    IntakeV2ContractError,
    IntakeV2Error,
    V2ConfigurationError,
    V2DraftContractError,
    V2DraftSchemaError,
    V2ProviderTerminalError,
    V2ProviderTimeoutError,
    V2ProviderTransientError,
    V2RepairExhaustedError,
    V2ResponseParseError,
    V2ShapeRecoveryError,
)
from app.intake_v2.provider import (
    OpenAIProviderV2,
    ProviderAttemptMetadataV2,
    ProviderRequestV2,
    ProviderResultV2,
    ProviderValidationFailureV2,
)

__all__ = [
    "IntakeV2ContractError",
    "IntakeV2Error",
    "JobIntelligenceDraftV2",
    "OpenAIProviderV2",
    "ProviderAttemptMetadataV2",
    "ProviderRequestV2",
    "ProviderResultV2",
    "ProviderValidationFailureV2",
    "SCHEMA_VERSION_V2",
    "V2ConfigurationError",
    "V2DraftContractError",
    "V2DraftSchemaError",
    "V2ProviderTerminalError",
    "V2ProviderTimeoutError",
    "V2ProviderTransientError",
    "V2RepairExhaustedError",
    "V2ResponseParseError",
    "V2ShapeRecoveryError",
    "job_intelligence_v2_response_schema",
    "strict_provider_schema_for_model",
    "validate_job_intelligence_draft_v2",
]
