"""CVBrain Intake v2 contracts.

Gate 1 intentionally exposes only contracts and prompt snapshots. Runtime
provider, service, canonicalization, projections, and endpoints are added in
later gates.
"""

from app.intake_v2.contract import (
    SCHEMA_VERSION_V2,
    JobIntelligenceDraftV2,
    job_intelligence_v2_response_schema,
    strict_provider_schema_for_model,
    validate_job_intelligence_draft_v2,
)
from app.intake_v2.errors import IntakeV2ContractError, IntakeV2Error

__all__ = [
    "IntakeV2ContractError",
    "IntakeV2Error",
    "JobIntelligenceDraftV2",
    "SCHEMA_VERSION_V2",
    "job_intelligence_v2_response_schema",
    "strict_provider_schema_for_model",
    "validate_job_intelligence_draft_v2",
]
