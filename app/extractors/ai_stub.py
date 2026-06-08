"""AI extractor stub.

This class prepares the future payload shape but never calls OpenAI or any other
external provider.
"""

from typing import Any, Dict

from app.extractors.base import ExtractorError, ExtractorRequest


class AIExtractorStub:
    """Future OpenAI extractor placeholder with no network behavior."""

    engine = "openai"

    def build_payload(self, request: ExtractorRequest) -> Dict[str, Any]:
        return request.ai_payload()

    def extract(self, request: ExtractorRequest) -> Dict[str, Any]:
        self.build_payload(request)
        raise ExtractorError(
            "ai_extractor_not_implemented",
            "AI extractor is not implemented yet.",
        )
