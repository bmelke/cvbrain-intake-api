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


def test_v2_prompt_makes_ai_own_auto_language_and_light_meaning_preserving_correction():
    extraction_prompt = prompts.build_extraction_prompt("auto")
    repair_prompt = prompts.build_repair_prompt("auto")

    for prompt in (extraction_prompt, repair_prompt):
        assert "Source text language detected as: auto." in prompt
        assert "If source_language is \"auto\", determine the source language from source_text" in prompt
        assert "Apply only light correction of obvious grammar, spelling, accent, punctuation, or typo errors" in prompt
        assert "before semantic interpretation" in prompt
        assert "Preserve original meaning" in prompt
        assert "Do not invent missing details" in prompt
        assert "Do not rewrite domain-specific facts" in prompt
        assert "titles, seniority, locations, tools, technologies, numbers, licenses, or credentials" in prompt
        assert "If a correction would be ambiguous, surface a question or missing-information item" in prompt
        assert "Do not output a full corrected source text" in prompt


def test_v2_prompt_keeps_explicit_criteria_separate_from_clarifying_questions():
    extraction_prompt = prompts.build_extraction_prompt("auto")
    repair_prompt = prompts.build_repair_prompt("auto")

    for prompt in (extraction_prompt, repair_prompt):
        assert "Explicit criteria and recruiter questions contract:" in prompt
        assert "populate explicit hard requirements under must-have criteria" in prompt
        assert "populate explicit preferred or appreciated items under nice-to-have criteria" in prompt
        assert "keep clarifying questions separate from criteria" in prompt
        assert "never use questions as a substitute for criteria" in prompt
        assert "preserve explicit criteria even when clarification is needed" in prompt
        assert "surface ambiguity as a question in addition to preserved criteria" in prompt
        assert "Clarifying questions must not replace, suppress, delete, or downgrade explicit criteria" in prompt
        assert "If evidence, validation, scope, or precision is unclear, keep the explicit criterion" in prompt
        assert "ask a separate recruiter/company clarification question" in prompt
        assert "Ambiguity becomes a question, not deletion of the explicit requirement" in prompt
        assert "Do not remove explicit requirements" in prompt
        assert "Do not downgrade a must-have to a question only" in prompt
        assert "Do not invent missing requirements" in prompt
        assert "Do not delete explicit requirements" in prompt
        assert "no less than" in prompt
        assert "fundamental" in prompt
        assert "essential" in prompt
        assert "required" in prompt
        assert "must" in prompt
        assert "appreciated" in prompt
        assert "preferred" in prompt
        assert "nice to have" in prompt
        assert "AI-owned semantic signals" in prompt
        assert "Python, WordPress, and consumers must not classify" in prompt


def test_v2_prompt_makes_search_readiness_ai_owned_and_separate_from_consumer_logic():
    extraction_prompt = prompts.build_extraction_prompt("auto")
    repair_prompt = prompts.build_repair_prompt("auto")

    for prompt in (extraction_prompt, repair_prompt):
        assert "AI-owned search readiness contract:" in prompt
        assert "determine whether the current information is enough to recommend starting a CV search" in prompt
        assert "search is recommended with current information" in prompt
        assert "search is possible but should be clarified" in prompt
        assert "search is not recommended yet because key information is missing" in prompt
        assert "Populate search_readiness from the recruiter source and extracted criteria/questions" in prompt
        assert "Populate search_readiness.recommendation_summary with human-readable recruiter-facing text" in prompt
        assert "Populate search_readiness.recommended_next_steps with human-readable recruiter-facing next steps" in prompt
        assert "recommended_next_steps" in prompt
        assert "Python, WordPress, and consumers must not decide search readiness" in prompt
        assert "must only render the AI-owned search_readiness values" in prompt
