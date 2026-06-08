"""Shared extractor interface primitives.

This module deliberately has no provider dependencies and performs no network IO.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


DEFAULT_SCHEMA_VERSION = "cvbrain_job_intelligence_v1"


@dataclass(frozen=True)
class ExtractorRequest:
    """Normalized request passed to extractor implementations."""

    source_text: str
    locale: str = "es-UY"
    country_context: Optional[str] = None
    candidate_market: Optional[str] = None
    employer_market: Optional[str] = None
    source_filename: str = ""
    source_mime_type: str = "text/plain"
    recruiter_notes: str = ""
    schema_version: str = DEFAULT_SCHEMA_VERSION

    def ai_payload(self) -> Dict[str, Any]:
        """Build the future AI payload without logging or redacting source text."""

        return {
            "source_text": self.source_text,
            "locale": self.locale,
            "country_context": self.country_context,
            "candidate_market": self.candidate_market,
            "employer_market": self.employer_market,
            "source_filename": self.source_filename,
            "source_mime_type": self.source_mime_type,
            "recruiter_notes": self.recruiter_notes,
            "schema_version": self.schema_version,
        }


@dataclass
class ExtractorError(Exception):
    """Clean extractor error that can be converted into flat compatibility JSON."""

    code: str
    message: str
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
        if not self.warnings:
            self.warnings = [self.code]


def country_context_mismatch_warning(
    source_location: str,
    country_context: Optional[str],
    expected_country: Optional[str] = None,
) -> Dict[str, Any]:
    """Represent a location/context conflict without changing source location."""

    return {
        "code": "country_context_mismatch",
        "severity": "medium",
        "source_location": source_location,
        "country_context": country_context,
        "expected_country": expected_country,
        "recommended_action": "Ask recruiter to confirm candidate market and location.",
    }
