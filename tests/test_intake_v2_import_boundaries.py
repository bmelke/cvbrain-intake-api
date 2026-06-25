from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V2_ROOT = ROOT / "app" / "intake_v2"

FORBIDDEN_IMPORTS = {
    "app.normalization.requirement_importance",
    "app.normalization.role_title",
    "app.normalization.canonical_job_intelligence",
    "app.mappers.recruiter_display_plan",
    "app.mappers.job_intelligence_to_flat",
    "app.extractors.deterministic",
    "app.main",
}


def module_name_for_path(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def path_for_module(module: str) -> Path | None:
    if not module.startswith("app.intake_v2"):
        return None
    parts = module.split(".")
    module_path = ROOT.joinpath(*parts).with_suffix(".py")
    package_path = ROOT.joinpath(*parts) / "__init__.py"
    if module_path.exists():
        return module_path
    if package_path.exists():
        return package_path
    return None


def imports_for_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def is_forbidden(module: str) -> bool:
    return any(module == forbidden or module.startswith(forbidden + ".") for forbidden in FORBIDDEN_IMPORTS)


def test_intake_v2_package_has_no_direct_forbidden_imports():
    offenders = []
    for path in sorted(V2_ROOT.glob("*.py")):
        for imported in imports_for_file(path):
            if is_forbidden(imported):
                offenders.append(f"{path.relative_to(ROOT)} imports {imported}")

    assert offenders == []


def test_intake_v2_package_has_no_indirect_forbidden_imports():
    offenders = []
    visited: set[str] = set()
    stack = [module_name_for_path(path) for path in sorted(V2_ROOT.glob("*.py"))]

    while stack:
        module = stack.pop()
        if module in visited:
            continue
        visited.add(module)
        path = path_for_module(module)
        if path is None:
            continue
        for imported in imports_for_file(path):
            if is_forbidden(imported):
                offenders.append(f"{module} imports {imported}")
            imported_path = path_for_module(imported)
            if imported_path is not None:
                stack.append(imported)

    assert offenders == []


def test_intake_v2_modules_import_without_loading_forbidden_v1_runtime():
    import app.intake_v2.contract as contract
    import app.intake_v2.errors as errors
    import app.intake_v2.prompts as prompts

    assert contract.SCHEMA_VERSION_V2 == "cvbrain_job_intelligence_v2"
    assert errors.IntakeV2Error.__name__ == "IntakeV2Error"
    assert prompts.SOURCE_V1_COMMIT_HASH
