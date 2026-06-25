from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path

from app.intake_v2 import prompts


ROOT = Path(__file__).resolve().parents[1]
V1_PROMPT_SOURCE = ROOT / "app" / "extractors" / "openai_structured.py"
V1_PROMPT_SOURCE_REPO_PATH = V1_PROMPT_SOURCE.relative_to(ROOT)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def git_stdout(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def v1_prompt_source_from_recorded_commit() -> str:
    return git_stdout(
        "show",
        f"{prompts.SOURCE_V1_COMMIT_HASH}:{V1_PROMPT_SOURCE_REPO_PATH.as_posix()}",
    )


def v1_constant(name: str) -> str:
    module = ast.parse(v1_prompt_source_from_recorded_commit())
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"missing V1 prompt constant: {name}")


def reverse_schema_alignment_changes(text: str, target: str) -> str:
    output = text
    for change in prompts.SCHEMA_ALIGNMENT_CHANGES:
        if change["target"] != target:
            continue
        output = output.replace(change["new_text"], change["old_text"])
    return output


def test_prompt_snapshot_records_v1_source_commit():
    assert git_stdout(
        "rev-parse",
        "--verify",
        f"{prompts.SOURCE_V1_COMMIT_HASH}^{{commit}}",
    ) == prompts.SOURCE_V1_COMMIT_HASH
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", prompts.SOURCE_V1_COMMIT_HASH, "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def test_preserved_prompt_hashes_match_v1_source_constants():
    extraction = v1_constant("SYSTEM_INSTRUCTIONS")
    language = v1_constant("LANGUAGE_CONTRACT")
    public = v1_constant("PUBLIC_EXTRACTION_CONTRACT")

    assert prompts.PRESERVED_EXTRACTION_CONTRACT == extraction
    assert prompts.PRESERVED_LANGUAGE_CONTRACT == language
    assert prompts.PRESERVED_PUBLIC_OUTPUT_CONTRACT == public
    assert prompts.PRESERVED_EXTRACTION_CONTRACT_SHA256 == sha256_text(extraction)
    assert prompts.PRESERVED_LANGUAGE_CONTRACT_SHA256 == sha256_text(language)
    assert prompts.PRESERVED_PUBLIC_CONTRACT_SHA256 == sha256_text(public)


def test_v2_prompt_keeps_preserved_semantics_with_schema_only_changes():
    assert prompts.SCHEMA_ALIGNMENT_CHANGES
    assert {change["classification"] for change in prompts.SCHEMA_ALIGNMENT_CHANGES} == {"schema-only"}

    assert reverse_schema_alignment_changes(prompts.V2_EXTRACTION_CONTRACT, "extraction") == prompts.PRESERVED_EXTRACTION_CONTRACT
    assert reverse_schema_alignment_changes(prompts.V2_PUBLIC_OUTPUT_CONTRACT, "public") == prompts.PRESERVED_PUBLIC_OUTPUT_CONTRACT
    assert prompts.V2_LANGUAGE_CONTRACT == prompts.PRESERVED_LANGUAGE_CONTRACT


def test_v2_prompt_uses_v2_schema_names_without_adding_outputs():
    prompt = prompts.build_extraction_prompt("Spanish")

    assert "JobIntelligenceDraftV2" in prompt
    assert "local_ref" in prompt
    assert "source_evidence" in prompt
    assert "clarification_question_ref" in prompt
    assert "The AI returns" not in prompt
    assert "Do not return flat_compatibility, display_plan" in prompt
