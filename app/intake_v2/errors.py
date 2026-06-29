"""CVBrain Intake v2 error types.

These errors are contract-only in Gate 1. They do not route to V1 fallbacks or
deterministic extraction.
"""

from __future__ import annotations


class IntakeV2Error(Exception):
    """Base class for Intake v2 failures."""


class IntakeV2ContractError(IntakeV2Error):
    """Raised when a draft does not satisfy the v2 typed contract."""


class V2ConfigurationError(IntakeV2Error):
    """Raised when the V2 provider is not configured."""


class V2ProviderTimeoutError(IntakeV2Error):
    """Raised when a retryable provider timeout is exhausted."""


class V2ProviderTransientError(IntakeV2Error):
    """Raised when retryable provider failures are exhausted."""


class V2ProviderTerminalError(IntakeV2Error):
    """Raised for non-retryable provider failures."""


class V2ResponseParseError(IntakeV2Error):
    """Raised when a completed provider response cannot be parsed."""


class V2DraftSchemaError(IntakeV2ContractError):
    """Raised when a draft fails the strict typed schema."""


class V2DraftContractError(IntakeV2ContractError):
    """Raised when a draft passes schema but fails V2 provider contract rules."""


class V2RepairExhaustedError(IntakeV2Error):
    """Raised when the single allowed semantic repair does not produce a valid draft."""


class V2InternalIntegrityError(IntakeV2Error):
    """Raised when V2 internal reference integrity fails."""

    def __init__(self, message: str = "Intake v2 internal integrity failed.", *, integrity: object = None) -> None:
        super().__init__(message)
        self.integrity = integrity


class V2ServiceRequestError(IntakeV2Error):
    """Raised when a V2 service request fails mechanical request validation."""

    def __init__(
        self,
        message: str = "Intake v2 service request is invalid.",
        *,
        code: str = "invalid_request",
        category: str = "request_validation",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category


class V2ShapeRecoveryError(IntakeV2ContractError):
    """Raised when structural recovery must defer to AI repair."""

    def __init__(
        self,
        message: str,
        *,
        path: str = "",
        repair_required: bool = True,
        malformed_value: object = None,
        raw_value_sha256: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.repair_required = repair_required
        self.malformed_value = malformed_value
        self.raw_value_sha256 = raw_value_sha256
