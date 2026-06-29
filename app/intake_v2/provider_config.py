"""Explicit provider dependency construction for CVBrain Intake v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.intake_v2.errors import V2ConfigurationError
from app.intake_v2.provider import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TRANSIENT_RETRIES,
    OpenAIProviderV2,
)


@dataclass(frozen=True)
class OpenAIProviderConfigV2:
    api_key: str = field(repr=False)
    model: str
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    transient_retries: int = DEFAULT_TRANSIENT_RETRIES

    def __post_init__(self) -> None:
        api_key = str(self.api_key or "").strip()
        model = str(self.model or "").strip()
        if not api_key:
            _raise_config_error()
        if not model:
            _raise_config_error()

        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "max_output_tokens", int(self.max_output_tokens))
        object.__setattr__(self, "transient_retries", int(self.transient_retries))


def build_openai_provider_v2(config: OpenAIProviderConfigV2, *, client: Any = None) -> OpenAIProviderV2:
    if not isinstance(config, OpenAIProviderConfigV2):
        _raise_config_error()

    return OpenAIProviderV2(
        api_key=config.api_key,
        model=config.model,
        client=client,
        max_output_tokens=config.max_output_tokens,
        transient_retries=config.transient_retries,
    )


def _raise_config_error() -> None:
    raise V2ConfigurationError("Intake v2 provider configuration is invalid.") from None


__all__ = [
    "OpenAIProviderConfigV2",
    "build_openai_provider_v2",
]
