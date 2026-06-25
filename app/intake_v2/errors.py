"""CVBrain Intake v2 error types.

These errors are contract-only in Gate 1. They do not route to V1 fallbacks or
deterministic extraction.
"""

from __future__ import annotations


class IntakeV2Error(Exception):
    """Base class for Intake v2 failures."""


class IntakeV2ContractError(IntakeV2Error):
    """Raised when a draft does not satisfy the v2 typed contract."""
