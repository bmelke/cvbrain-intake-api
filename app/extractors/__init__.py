"""Extractor interfaces for CVBrain intake analysis.

These helpers are intentionally not wired into the live FastAPI endpoint yet.
"""

from app.extractors.ai_stub import AIExtractorStub
from app.extractors.base import (
    DEFAULT_SCHEMA_VERSION,
    ExtractorError,
    ExtractorRequest,
    country_context_mismatch_warning,
)
from app.extractors.deterministic import DeterministicExtractor
from app.extractors.router import ExtractorRouter

__all__ = [
    "AIExtractorStub",
    "DEFAULT_SCHEMA_VERSION",
    "DeterministicExtractor",
    "ExtractorError",
    "ExtractorRequest",
    "ExtractorRouter",
    "country_context_mismatch_warning",
]
