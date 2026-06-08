"""Deterministic extractor wrapper.

The wrapper delegates to the existing deterministic parser and is not wired into
the live endpoint yet.
"""

from typing import Any, Dict

from app.extractors.base import ExtractorRequest


class DeterministicExtractor:
    """Adapter around the existing deterministic analyze_text function."""

    engine = "deterministic"

    def extract(self, request: ExtractorRequest) -> Dict[str, Any]:
        from app.main import analyze_text

        payload = analyze_text(request.source_text or "")
        payload.setdefault("warnings", [])
        payload["engine"] = self.engine
        payload["fallback_used"] = False
        return payload
