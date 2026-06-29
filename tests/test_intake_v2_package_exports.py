from __future__ import annotations

import ast
import importlib
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_MODULE = "app.intake_v2"
PACKAGE_INIT = ROOT / "app" / "intake_v2" / "__init__.py"

APPROVED_PUBLIC_EXPORTS = {
    "DISPLAY_PLAN_SCHEMA_VERSION",
    "IntakeServiceRequestV2",
    "IntakeV2ContractError",
    "IntakeV2Error",
    "JobIntelligenceDraftV2",
    "OpenAIProviderV2",
    "ProviderAttemptMetadataV2",
    "ProviderRequestV2",
    "ProviderResultV2",
    "ProviderValidationFailureV2",
    "PUBLIC_RESPONSE_SCHEMA_VERSION",
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
}

APPROVED_EXPORT_MODULES = {
    "app.intake_v2.contract": {
        "JobIntelligenceDraftV2",
        "SCHEMA_VERSION_V2",
        "job_intelligence_v2_response_schema",
        "strict_provider_schema_for_model",
        "validate_job_intelligence_draft_v2",
    },
    "app.intake_v2.display_plan": {
        "DISPLAY_PLAN_SCHEMA_VERSION",
        "V2DisplayPlanProjectionError",
        "build_display_plan_v2",
    },
    "app.intake_v2.errors": {
        "IntakeV2ContractError",
        "IntakeV2Error",
        "V2ConfigurationError",
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
    },
    "app.intake_v2.integrity": {"internalize_draft_v2"},
    "app.intake_v2.pipeline": {
        "V2PipelineError",
        "V2PipelineRequestError",
        "run_public_intake_v2",
    },
    "app.intake_v2.provider": {
        "OpenAIProviderV2",
        "ProviderAttemptMetadataV2",
        "ProviderRequestV2",
        "ProviderResultV2",
        "ProviderValidationFailureV2",
    },
    "app.intake_v2.response": {
        "PUBLIC_RESPONSE_SCHEMA_VERSION",
        "V2PublicResponseError",
        "build_public_response_v2",
    },
    "app.intake_v2.service": {
        "IntakeServiceRequestV2",
        "SERVICE_SCHEMA_VERSION",
        "V2ServiceRequestError",
        "run_intake_v2",
    },
}

FORBIDDEN_EXPORT_PATTERNS = (
    "api_key",
    "canonical",
    "config",
    "endpoint",
    "env",
    "fallback",
    "fastapi",
    "legacy",
    "mapper",
    "normalise",
    "normalize",
    "normalizer",
    "readiness",
    "route",
    "router",
    "secret",
    "starlette",
    "ui",
    "user_interface",
    "v1",
    "wordpress",
)
FORBIDDEN_EXPORT_PATTERN_EXCEPTIONS = {
    "V2ConfigurationError",
}
FORBIDDEN_IMPORT_PREFIXES = (
    "app.extractors",
    "app.main",
    "app.mappers",
    "app.normalization",
    "app.routers",
    "app.routes",
    "app.intake_v2.config",
    "app.intake_v2.endpoint",
    "app.intake_v2.factory",
    "app.intake_v2.provider_config",
    "dotenv",
    "fastapi",
    "openai",
    "starlette",
)
FORBIDDEN_INIT_IMPORTS = FORBIDDEN_IMPORT_PREFIXES + ("os", "secrets")
FORBIDDEN_INIT_SOURCE_TOKENS = ("api_key", "dotenv", "environ", "getenv", "secret", "settings")


class FakeProvider:
    def __init__(self, package: Any) -> None:
        self._package = package
        self.calls: list[Any] = []

    def extract(self, request: Any) -> Any:
        self.calls.append(request)
        assert isinstance(request, self._package.ProviderRequestV2)
        return self._package.ProviderResultV2(
            validated_draft=valid_draft(self._package),
            provider_response_id="resp_gate8_package_smoke",
            provider_request_id="req_gate8_package_smoke",
            model="fake-package-export-model",
            attempt_kind="initial",
            provider_call_count=1,
            semantic_attempt_count=1,
            repair_count=0,
            transient_retry_count=0,
            elapsed_seconds=0.01,
            parse_path="json",
        )


def is_intake_v2_module(name: str) -> bool:
    return name == PACKAGE_MODULE or name.startswith(PACKAGE_MODULE + ".")


@contextmanager
def import_fresh_package() -> Iterator[Any]:
    original_modules = {name: module for name, module in sys.modules.items() if is_intake_v2_module(name)}
    app_module = sys.modules.get("app")
    had_app_intake_attr = app_module is not None and hasattr(app_module, "intake_v2")
    original_app_intake_attr = getattr(app_module, "intake_v2", None) if app_module is not None else None

    for name in list(sys.modules):
        if is_intake_v2_module(name):
            sys.modules.pop(name, None)
    try:
        yield importlib.import_module(PACKAGE_MODULE)
    finally:
        for name in list(sys.modules):
            if is_intake_v2_module(name):
                sys.modules.pop(name, None)
        sys.modules.update(original_modules)

        current_app_module = sys.modules.get("app")
        if current_app_module is not None:
            if PACKAGE_MODULE in original_modules:
                setattr(current_app_module, "intake_v2", original_modules[PACKAGE_MODULE])
            elif had_app_intake_attr:
                setattr(current_app_module, "intake_v2", original_app_intake_attr)
            elif hasattr(current_app_module, "intake_v2"):
                delattr(current_app_module, "intake_v2")


def imported_names_for_init() -> set[str]:
    tree = ast.parse(PACKAGE_INIT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def is_forbidden_import(module: str) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_IMPORT_PREFIXES)


def is_forbidden_init_import(module: str) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_INIT_IMPORTS)


def export_name_tokens(name: str) -> tuple[str, ...]:
    camel_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", camel_split)
    return tuple(token.lower() for token in re.split(r"[^A-Za-z0-9]+", camel_split) if token)


def forbidden_export_pattern_matches(name: str, pattern: str) -> bool:
    tokens = export_name_tokens(name)
    pattern_tokens = export_name_tokens(pattern)
    if not pattern_tokens:
        return False
    if len(pattern_tokens) == 1:
        return pattern_tokens[0] in tokens
    return any(tokens[index : index + len(pattern_tokens)] == pattern_tokens for index in range(len(tokens)))


def forbidden_export_name_offenders(names: list[str]) -> list[str]:
    offenders = []
    for name in names:
        if name in FORBIDDEN_EXPORT_PATTERN_EXCEPTIONS:
            continue
        for pattern in FORBIDDEN_EXPORT_PATTERNS:
            if forbidden_export_pattern_matches(name, pattern):
                offenders.append(f"{name} contains forbidden public-boundary pattern {pattern!r}")
    return offenders


def valid_draft(package: Any) -> dict[str, Any]:
    return package.validate_job_intelligence_draft_v2(
        {
            "schema_version": package.SCHEMA_VERSION_V2,
            "job_profile": {
                "role_title": "Gate 8 package smoke title",
                "role_family": None,
                "professional_grade": None,
                "seniority": None,
                "summary": None,
                "industries": [],
            },
            "location_and_modality": {
                "raw_location": None,
                "normalized_location": None,
                "country_code": None,
                "city": None,
                "region": None,
                "work_modality": None,
                "remote_allowed": None,
                "hybrid_allowed": None,
                "onsite_required": None,
            },
            "criteria": [],
            "company_questions": [],
            "candidate_screening_questions": [],
            "search_strategy": {
                "target_titles": [],
                "search_terms": [],
                "semantic_terms": [],
                "negative_terms": [],
            },
            "search_readiness": {
                "status": "ready",
                "proceed_allowed": True,
                "recommended_action": "continue_anyway",
                "recruiter_decision_required": False,
                "continued_with_missing_information": False,
            },
            "quality_control": {
                "warnings": [],
                "confidence": 1.0,
                "contains_candidate_data": False,
                "contains_candidate_pii": False,
            },
        }
    )


def test_package_import_is_side_effect_safe():
    provider_runtime_calls: list[str] = []

    def profile(frame: Any, event: str, _arg: Any) -> None:
        if event != "call":
            return
        filename = Path(frame.f_code.co_filename)
        if filename.name != "provider.py":
            return
        if frame.f_code.co_name in {"__init__", "_client"}:
            provider_runtime_calls.append(frame.f_code.co_name)

    before_modules = dict(sys.modules)
    sys.setprofile(profile)
    try:
        with import_fresh_package() as package:
            loaded_or_replaced = {
                name for name, module in sys.modules.items() if before_modules.get(name) is not module
            }
            forbidden_loaded = sorted(module for module in loaded_or_replaced if is_forbidden_import(module))
    finally:
        sys.setprofile(None)

    assert package.__name__ == PACKAGE_MODULE
    assert provider_runtime_calls == []
    assert forbidden_loaded == []


def test_package_all_is_explicit_approved_public_surface():
    with import_fresh_package() as package:
        assert hasattr(package, "__all__")
        assert set(package.__all__) == APPROVED_PUBLIC_EXPORTS
        assert list(package.__all__) == sorted(package.__all__)
        assert all(not name.startswith("_") for name in package.__all__)


def test_approved_public_exports_resolve_from_package_surface():
    with import_fresh_package() as package:
        missing = sorted(name for name in APPROVED_PUBLIC_EXPORTS if not hasattr(package, name))
        module_missing: list[str] = []

        for module_name, names in APPROVED_EXPORT_MODULES.items():
            module = importlib.import_module(module_name)
            module_missing.extend(f"{module_name}.{name}" for name in sorted(names) if not hasattr(module, name))

        assert module_missing == []
        assert missing == []


def test_package_export_names_do_not_expose_forbidden_product_boundaries():
    with import_fresh_package() as package:
        offenders = forbidden_export_name_offenders(list(package.__all__))

        assert offenders == []


def test_forbidden_export_matcher_allows_approved_display_plan_names_only():
    approved_display_exports = [
        "DISPLAY_PLAN_SCHEMA_VERSION",
        "V2DisplayPlanProjectionError",
        "build_display_plan_v2",
    ]
    forbidden_ui_exports = ["ui", "user_interface", "wordpress_ui", "standalone_ui", "ui_component", "ui_renderer"]
    ui_offenders = forbidden_export_name_offenders(forbidden_ui_exports)

    assert forbidden_export_name_offenders(approved_display_exports) == []
    for name in forbidden_ui_exports:
        assert any(offender.startswith(f"{name} ") for offender in ui_offenders)


def test_package_init_has_no_forbidden_runtime_imports():
    offenders = sorted(module for module in imported_names_for_init() if is_forbidden_init_import(module))
    source = PACKAGE_INIT.read_text(encoding="utf-8").lower()
    source_offenders = sorted(token for token in FORBIDDEN_INIT_SOURCE_TOKENS if token in source)

    assert offenders == []
    assert source_offenders == []


def test_public_pipeline_can_run_through_package_surface_without_direct_module_imports():
    with import_fresh_package() as package:
        provider = FakeProvider(package)

        result = package.run_public_intake_v2(
            source_text="Gate 8 package smoke source text",
            source_language="explicit-test-language",
            provider=provider,
        )

        assert provider.calls
        assert result["ok"] is True
        assert result["schema_version"] == package.PUBLIC_RESPONSE_SCHEMA_VERSION
        assert "display_plan" in result
