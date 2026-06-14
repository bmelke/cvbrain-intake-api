#!/usr/bin/env python3
"""Run live CVBrain Job Intake fixture cases one by one.

This script is intentionally stdlib-only so it can run from Cloud Shell without
project-specific setup beyond Python. It never prints API keys and only sends
the text inside BUSQUEDA blocks as source_text.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


CASE_START_PATTERN = re.compile(r"^BUSQUEDA_(\d{3})$")
CASE_END_PATTERN = re.compile(r"^END_BUSQUEDA_(\d{3})$")
API_PATH = "/api/job-intake/analyze"
SUMMARY_FIELDS = [
    "id",
    "http_status",
    "ok",
    "engine",
    "fallback_used",
    "ai_model",
    "role_title",
    "role_family",
    "confidence",
    "search_readiness.status",
    "warning_count",
    "warnings",
    "must_have_count",
    "should_have_count",
    "nice_to_have_count",
    "blockers_count",
    "credentials_required_count",
    "credentials_preferred_count",
    "location.normalized",
    "experience.minimum_years",
    "execution_time_seconds",
    "result_classification",
    "notes",
]

PASS = "PASS"
WARN = "WARN"
FAIL_TECHNICAL = "FAIL_TECHNICAL"
FAIL_SCHEMA = "FAIL_SCHEMA"
FAIL_PROVIDER = "FAIL_PROVIDER"
FAIL_FALLBACK = "FAIL_FALLBACK"
FAIL_EMPTY = "FAIL_EMPTY"
FAIL_PUBLIC_ARTIFACT = "FAIL_PUBLIC_ARTIFACT"
FAIL_TITLE_CASING = "FAIL_TITLE_CASING"
FAIL_ORPHAN_FRAGMENTS = "FAIL_ORPHAN_FRAGMENTS"
FAIL_IMPORTANCE = "FAIL_IMPORTANCE"

ORPHAN_REQUIREMENTS = {
    "software",
    "hardware",
    "redes basicas",
    "redes básicas",
    "y soporte remoto",
    "y registro de tickets",
    "herramientas",
    "y herramientas",
    "de",
    "y",
}
WEAK_MODIFIER_PATTERN = re.compile(
    r"\b("
    r"valorables?|ser[aá]\s+valorables?|se\s+valora|se\s+valorar[aá](?:\s+especialmente)?|"
    r"plus|es\s+un\s+plus|suma|puede\s+sumar|no\s+central|nice\s+to\s+have|would\s+be\s+a\s+plus"
    r")\b",
    re.I,
)
STRONG_PREFERENCE_PATTERN = re.compile(
    r"\b("
    r"deseable|deseables|preferid[oa]s?|preferentemente|ideal(?:mente)?|"
    r"muy\s+valorad[oa]s?|muy\s+valorables?|"
    r"strongly\s+preferred|preferred|desirable"
    r")\b",
    re.I,
)
HARD_MODIFIER_PATTERN = re.compile(
    r"\b("
    r"excluyente|excluyentes|imprescindible|obligatori[oa]s?|requerid[oa]s?|"
    r"indispensable|m[ií]nim[oa]|sin\s+.+?\s+no\s+avanzar|"
    r"no\s+presentarse\s+si\s+no\s+.+|no\s+avanzar\s+si\s+no\s+.+|"
    r"se\s+requiere|debe(?:\s+tener|\s+manejar)?|requisito"
    r")\b",
    re.I,
)
EXPLICIT_HARD_CUE_PATTERN = re.compile(
    r"\b(?:"
    r"experiencia\s+(?:excluyente|obligatori[oa]|imprescindible|requerid[oa]|s[ií]\s+o\s+s[ií])|"
    r"debe\s+contar\s+con\s+experiencia|"
    r"es\s+(?:excluyente|obligatori[oa])\s+experiencia|"
    r"imprescindible\s+experiencia|"
    r"es\s+obligatori[oa]\s+conocimiento|"
    r"conocimiento\s+.+?\s+es\s+obligatori[oa]|"
    r"debe\s+manejar|debe\s+tener|debe\s+contar\s+con"
    r")\b",
    re.I,
)
BLOCKER_CLAUSE_PATTERN = re.compile(
    r"\b(no\s+avanzar|no\s+presentarse\s+si\s+no|no\s+considerar)\b",
    re.I,
)
METADATA_ARTIFACT_PATTERN = re.compile(
    r"\b(?:source(?:[_\s-]*text)?[_\s-]*span(?:[_\s-]*(?:missing|hint|not[_\s-]*provided|from[_\s-]*rules|for[_\s-]*blocker|\d+))*|"
    r"hard[_\s-]*filter[_\s-]*(?:candidate|approved)[_\s-]*as[_\s-]*written|"
    r"source[_\s-]*text[_\s-]*|_missing_or_not_applicable|rationale[_\s-]*id[_\s-]*missing|"
    r"classification[_\s-]*rationale[_\s-]*id[_\s-]*missing|span[_\s-]*missing|"
    r"schema[_\s-]*repair|debug[_\s-]*placeholder|internal[_\s-]*diagnostic)",
    re.I,
)


@dataclass(frozen=True)
class Case:
    id: str
    source_text: str


@dataclass
class ResponseRecord:
    http_status: int
    data: Optional[Mapping[str, Any]]
    raw_text: str
    error: str = ""


Transport = Callable[[str, str, Mapping[str, Any], float], ResponseRecord]


def parse_fixture(path: Path) -> List[Case]:
    cases: List[Case] = []
    current_id: Optional[str] = None
    current_lines: List[str] = []

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        start = CASE_START_PATTERN.match(line)
        end = CASE_END_PATTERN.match(line)

        if start:
            if current_id is not None:
                raise ValueError(f"{path}:{line_number}: nested {line} before END_{current_id}")
            current_id = f"BUSQUEDA_{start.group(1)}"
            current_lines = []
            continue

        if end:
            end_id = f"BUSQUEDA_{end.group(1)}"
            if current_id != end_id:
                raise ValueError(f"{path}:{line_number}: found END_{end_id} while parsing {current_id}")
            source_text = "\n".join(current_lines).strip()
            if not source_text:
                raise ValueError(f"{path}:{line_number}: {current_id} is empty")
            cases.append(Case(current_id, source_text))
            current_id = None
            current_lines = []
            continue

        if current_id is not None:
            current_lines.append(raw_line)

    if current_id is not None:
        raise ValueError(f"{path}: missing END_{current_id}")

    return cases


def validate_case_sequence(cases: List[Case], expected_count: int) -> None:
    if len(cases) != expected_count:
        raise ValueError(f"Expected {expected_count} cases, found {len(cases)}")
    expected_ids = [f"BUSQUEDA_{index:03d}" for index in range(1, expected_count + 1)]
    actual_ids = [case.id for case in cases]
    if actual_ids != expected_ids:
        raise ValueError(f"Expected sequential ids {expected_ids[0]}..{expected_ids[-1]}, found mismatch")


def build_request(case: Case) -> Dict[str, Any]:
    return {
        "source_text": case.source_text,
        "source_filename": "",
        "source_mime_type": "text/plain",
        "recruiter_notes": "",
        "locale": "es-UY",
        "country_context": "UY",
        "candidate_market": "UY",
        "employer_market": "UY",
    }


def endpoint_url(base_or_endpoint: str) -> str:
    clean = base_or_endpoint.strip().rstrip("/")
    if clean.endswith(API_PATH):
        return clean
    return f"{clean}{API_PATH}"


def post_json(url: str, api_key: str, payload: Mapping[str, Any], timeout: float) -> ResponseRecord:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "cvbrain-live-intake-fixture-runner/1.0",
    }
    if api_key:
        headers["X-CVBrain-API-Key"] = api_key

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_text = response.read().decode("utf-8", errors="replace")
            return _response_record(response.status, raw_text)
    except urllib.error.HTTPError as error:
        raw_text = error.read().decode("utf-8", errors="replace")
        return _response_record(error.code, raw_text)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return ResponseRecord(0, None, "", error=f"{error.__class__.__name__}: {error}")


def _response_record(http_status: int, raw_text: str) -> ResponseRecord:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as error:
        return ResponseRecord(http_status, None, raw_text, error=f"invalid_json: {error}")
    if not isinstance(parsed, Mapping):
        return ResponseRecord(http_status, None, raw_text, error="invalid_json: top-level response is not an object")
    return ResponseRecord(http_status, parsed, raw_text)


def run_fixture(
    cases: List[Case],
    out_dir: Path,
    url: str,
    api_key: str,
    timeout: float = 120.0,
    sleep_seconds: float = 1.0,
    expect_live_ai: bool = True,
    transport: Transport = post_json,
) -> Dict[str, Any]:
    requests_dir = out_dir / "requests"
    responses_dir = out_dir / "responses"
    requests_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    response_records: Dict[str, Dict[str, Any]] = {}

    for index, case in enumerate(cases):
        payload = build_request(case)
        request_path = requests_dir / f"{case.id}.request.json"
        response_path = responses_dir / f"{case.id}.response.json"
        write_json(request_path, payload)

        started = time.monotonic()
        record = transport(url, api_key, payload, timeout)
        if record.http_status == 0:
            retry_record = transport(url, api_key, payload, timeout)
            if retry_record.http_status != 0:
                record = retry_record
        elapsed = time.monotonic() - started

        response_payload = response_file_payload(record)
        write_json(response_path, response_payload)
        response_records[case.id] = response_payload

        rows.append(summarize_case(case, record, elapsed, expect_live_ai=expect_live_ai))
        if sleep_seconds > 0 and index < len(cases) - 1:
            time.sleep(sleep_seconds)

    summary = build_summary(rows)
    write_json(out_dir / "summary.json", {"summary": summary, "cases": rows})
    write_summary_csv(out_dir / "summary.csv", rows)
    write_failures_md(out_dir / "failures.md", summary, rows)
    return {"summary": summary, "cases": rows, "responses": response_records}


def response_file_payload(record: ResponseRecord) -> Dict[str, Any]:
    if record.data is not None:
        return dict(record.data)
    return {
        "ok": False,
        "_runner_error": record.error,
        "_http_status": record.http_status,
        "_raw_response": record.raw_text[:4000],
    }


def summarize_case(case: Case, record: ResponseRecord, elapsed: float, expect_live_ai: bool) -> Dict[str, Any]:
    data = dict(record.data or {})
    warnings = _string_list(data.get("warnings", []))
    credentials = data.get("credentials", {}) if isinstance(data.get("credentials"), Mapping) else {}
    location = data.get("location", {}) if isinstance(data.get("location"), Mapping) else {}
    experience = data.get("experience", {}) if isinstance(data.get("experience"), Mapping) else {}
    readiness_status = search_readiness_status(data)
    classification, notes = classify_result(case.source_text, record, expect_live_ai)

    return {
        "id": case.id,
        "http_status": record.http_status,
        "ok": data.get("ok"),
        "engine": data.get("engine", ""),
        "fallback_used": data.get("fallback_used"),
        "ai_model": data.get("ai_model", ""),
        "role_title": data.get("role_title", ""),
        "role_family": data.get("role_family", ""),
        "confidence": data.get("confidence", ""),
        "search_readiness.status": readiness_status,
        "warning_count": len(warnings),
        "warnings": "|".join(warnings),
        "must_have_count": len(_string_list(data.get("must_have", []))),
        "should_have_count": len(_string_list(data.get("should_have", []))),
        "nice_to_have_count": len(_string_list(data.get("nice_to_have", []))),
        "blockers_count": len(_string_list(data.get("blockers", []))),
        "credentials_required_count": len(_string_list(credentials.get("required", []))),
        "credentials_preferred_count": len(_string_list(credentials.get("preferred", []))),
        "location.normalized": location.get("normalized", ""),
        "experience.minimum_years": experience.get("minimum_years", ""),
        "execution_time_seconds": round(elapsed, 3),
        "result_classification": classification,
        "notes": "; ".join(notes),
    }


def classify_result(source_text: str, record: ResponseRecord, expect_live_ai: bool) -> tuple[str, List[str]]:
    data = dict(record.data or {})
    warnings = _string_list(data.get("warnings", []))
    notes: List[str] = []

    if record.http_status != 200:
        return FAIL_TECHNICAL, [record.error or f"http_status={record.http_status}"]
    if record.data is None:
        return FAIL_TECHNICAL, [record.error or "response_not_valid_json"]
    if data.get("ok") is not True:
        if "ai_schema_validation_failed" in warnings:
            return FAIL_SCHEMA, warnings
        if "ai_provider_error" in warnings:
            return FAIL_PROVIDER, warnings
        return FAIL_TECHNICAL, warnings or ["ok_not_true"]
    if "ai_schema_validation_failed" in warnings:
        return FAIL_SCHEMA, warnings
    if "ai_provider_error" in warnings:
        return FAIL_PROVIDER, warnings
    if expect_live_ai and data.get("engine") != "openai":
        return FAIL_PROVIDER, [f"engine_not_openai:{data.get('engine')}"]
    if expect_live_ai and data.get("fallback_used") is True:
        return FAIL_FALLBACK, ["fallback_used_true"]
    if _empty_core_output(data):
        return FAIL_EMPTY, ["role_title_summary_and_requirements_empty"]

    artifact_notes = public_artifact_notes(data)
    if artifact_notes:
        return FAIL_PUBLIC_ARTIFACT, artifact_notes

    title_notes = title_casing_notes_for(source_text, data)
    if title_notes:
        return FAIL_TITLE_CASING, title_notes

    orphan_notes = orphan_fragment_notes(data)
    if orphan_notes:
        return FAIL_ORPHAN_FRAGMENTS, orphan_notes

    importance_notes = importance_notes_for(source_text, data)
    if importance_notes:
        return FAIL_IMPORTANCE, importance_notes

    warning_notes = warning_notes_for(source_text, data)
    if warning_notes:
        return WARN, warning_notes

    return PASS, notes


def _empty_core_output(data: Mapping[str, Any]) -> bool:
    return not any(
        [
            str(data.get("role_title", "")).strip(),
            str(data.get("summary", "")).strip(),
            _string_list(data.get("must_have", [])),
            _string_list(data.get("should_have", [])),
            _string_list(data.get("nice_to_have", [])),
        ]
    )


def public_artifact_notes(data: Mapping[str, Any]) -> List[str]:
    notes = []
    for path, text in _public_strings(data):
        if METADATA_ARTIFACT_PATTERN.search(text):
            notes.append(f"metadata_artifact:{path}:{text[:160]}")
    return notes


def title_casing_notes_for(source_text: str, data: Mapping[str, Any]) -> List[str]:
    role_title = str(data.get("role_title", "")).strip()
    if not role_title:
        return []
    explicit_source_title = _explicit_source_role_title_span(source_text)
    if explicit_source_title and explicit_source_title != role_title:
        if _fold(explicit_source_title) == _fold(role_title):
            return [f"title_casing_mismatch:{explicit_source_title}!={role_title}"]
        return [f"title_source_span_mismatch:{explicit_source_title}!={role_title}"]
    source_span = _matching_source_span(source_text, role_title)
    if source_span and source_span != role_title:
        return [f"title_casing_mismatch:{source_span}!={role_title}"]
    return []


def orphan_fragment_notes(data: Mapping[str, Any]) -> List[str]:
    notes = []
    for bucket in ("must_have", "should_have", "nice_to_have"):
        for item in _string_list(data.get(bucket, [])):
            folded = _fold(item.strip(" -:.,;\t\r\n"))
            if folded in {_fold(value) for value in ORPHAN_REQUIREMENTS}:
                notes.append(f"orphan_fragment:{bucket}:{item}")
            if _is_incomplete_para_tail(item):
                notes.append(f"orphan_fragment:{bucket}:{item}")
    return notes


def _explicit_source_role_title_span(source_text: str) -> str:
    source = " ".join(str(source_text or "").split())
    if not source:
        return ""
    patterns = (
        re.compile(
            r"\b(?:busca|buscamos|selecciona|seleccionamos|incorpora|incorporar|"
            r"contrata|requiere|necesita|necesitamos|rol\s*:|se\s+busca)\s+"
            r"(?:(?:un|una|el|la|un/a)\s+)?(?P<tail>.{0,180})",
            re.I | re.S,
        ),
        re.compile(
            r"\b(?:posici[oó]n|puesto|perfil|vacante)\s+de\s+"
            r"(?:(?:un|una|el|la|un/a)\s+)?(?P<tail>.{0,180})",
            re.I | re.S,
        ),
    )
    for pattern in patterns:
        for lead in pattern.finditer(source):
            title = _source_title_from_tail(lead.group("tail"))
            if title:
                return title
    return ""


def _source_title_from_tail(text: str) -> str:
    text = re.split(r"[.;]", str(text or ""), maxsplit=1)[0]
    title = re.sub(
        r"(?:[.;:]\s*)?\b(?:es\s+excluyente|excluyente|la\s+persona|se\s+requiere|debe|"
        r"deseable|valorable|ser[aá]\s+valorable|no\s+avanzar|con|para)\b.*$",
        "",
        text,
        flags=re.I | re.S,
    )
    title = re.sub(r"^(?:un|una|el|la|un/a)\s+", "", title.strip(), flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" -:.,;\t\r\n")
    if not title or len(title.split()) > 9:
        return ""
    if _is_rejected_source_title(title):
        return ""
    return title if _looks_source_title_span(title) else ""


def _is_rejected_source_title(title: str) -> bool:
    folded = _fold(title)
    return bool(
        not folded
        or folded in {"empresa", "consultora", "startup", "agencia", "empresa de software"}
        or re.match(r"^(?:empresa|consultora|startup|agencia|soporte\s+b2b)\b", folded)
    )


def _looks_source_title_span(title: str) -> bool:
    folded = _fold(title)
    if re.search(
        r"\b(?:administrativ[oa]|abogad[oa]|agente|analista|arquitect[oa]|asistente|comprador[ae]?|"
        r"coordinador[ae]?|consultor[ae]?|dibujante|disenador[ae]?|diseñador[ae]?|ejecutiv[oa]|"
        r"encargad[oa]|gerente|ingenier[oa]|jefe|jefa|licenciad[oa]|operari[oa]|planificador[ae]?|"
        r"responsable|supervisor[ae]?|tecnic[oa]|t[eé]cnic[oa]|vendedor[ae]?)\b",
        folded,
    ):
        return True
    return bool(
        re.search(
            r"\b(?:manager|specialist|consultant|engineer|owner|analyst|lead|writer|designer|"
            r"developer|coordinator|architect|support|scrum|payroll|qa|ux/ui|ux|ui|it|rrhh)\b",
            folded,
        )
    )


def _matching_source_span(source_text: str, value: str) -> str:
    words = [word for word in re.split(r"\s+", value.strip()) if word]
    if not words:
        return ""
    pattern = r"\b" + r"\s+".join(re.escape(word) for word in words) + r"\b"
    match = re.search(pattern, source_text, re.I)
    if match:
        prefix = source_text[max(0, match.start() - 90) : match.start()]
        if not re.search(
            r"\b(?:busca|buscamos|selecciona|seleccionamos|necesita|incorporar|sumar|rol\s*:|"
            r"hiring|hire|seeking|looking\s+for)\b",
            prefix,
            re.I,
        ):
            return ""
        return match.group(0)
    return ""


def _public_strings(value: Any, path: str = "$") -> List[tuple[str, str]]:
    output: List[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            output.extend(_public_strings(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            output.extend(_public_strings(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        output.append((path, value))
    return output


def importance_notes_for(source_text: str, data: Mapping[str, Any]) -> List[str]:
    notes: List[str] = []
    weak_clauses = modifier_clauses(source_text, WEAK_MODIFIER_PATTERN, exclude=STRONG_PREFERENCE_PATTERN)
    preference_clauses = modifier_clauses(source_text, STRONG_PREFERENCE_PATTERN) + weak_clauses
    hard_clauses = modifier_clauses(source_text, HARD_MODIFIER_PATTERN)

    for bucket, item in _requirement_and_credential_items(data):
        if BLOCKER_CLAUSE_PATTERN.search(item):
            notes.append(f"blocker_leaked_to_requirement:{bucket}:{item}")

    for bucket in ("must_have", "should_have"):
        for item in _string_list(data.get(bucket, [])):
            if _explicit_hard_cue_governs_item(item, hard_clauses):
                continue
            if any(_clause_matches_item(clause, item) for clause in weak_clauses):
                notes.append(f"weak_modifier_over_promoted:{bucket}:{item}")

    for bucket in ("should_have", "nice_to_have"):
        for item in _string_list(data.get(bucket, [])):
            if any(_clause_matches_item(clause, item) for clause in preference_clauses):
                continue
            if any(_clause_matches_item(clause, item) for clause in hard_clauses):
                notes.append(f"hard_modifier_under_promoted:{bucket}:{item}")

    return notes


def _requirement_and_credential_items(data: Mapping[str, Any]) -> List[tuple[str, str]]:
    output: List[tuple[str, str]] = []
    for bucket in ("must_have", "should_have", "nice_to_have"):
        output.extend((bucket, item) for item in _string_list(data.get(bucket, [])))
    credentials = data.get("credentials", {}) if isinstance(data.get("credentials"), Mapping) else {}
    output.extend(("credentials.required", item) for item in _string_list(credentials.get("required", [])))
    output.extend(("credentials.preferred", item) for item in _string_list(credentials.get("preferred", [])))
    return output


def warning_notes_for(source_text: str, data: Mapping[str, Any]) -> List[str]:
    notes: List[str] = []
    confidence = data.get("confidence")
    if isinstance(confidence, (int, float)) and float(confidence) < 0.5:
        notes.append(f"low_confidence:{confidence}")
    notes.extend(semantic_review_notes(source_text, data))
    return notes


def semantic_review_notes(source_text: str, data: Mapping[str, Any]) -> List[str]:
    notes: List[str] = []
    source = _fold(source_text)
    location = data.get("location", {}) if isinstance(data.get("location"), Mapping) else {}
    work_modality = _fold(str(data.get("work_modality", "") or location.get("work_modality", "")))
    location_normalized = _fold(str(location.get("normalized", "")))
    experience = data.get("experience", {}) if isinstance(data.get("experience"), Mapping) else {}
    role_title = _fold(str(data.get("role_title", "")))
    seniority = _fold(str(experience.get("seniority", "")))
    source_has_hybrid = bool(re.search(r"\b(hibrido|híbrido|hybrid)\b", source))
    source_has_remote = bool(re.search(r"\bremoto|remote\b", source))

    for city in ("montevideo", "canelones"):
        if city in source and city not in location_normalized:
            notes.append(f"location_review:{city}_missing")

    if (
        source_has_hybrid
        and location.get("hybrid_allowed") is not True
        and not _hybrid_modality_is_usable(location, work_modality)
    ):
        notes.append("modality_review:hybrid_missing")
    if (
        source_has_remote
        and location.get("remote_allowed") is not True
        and not _remote_modality_is_usable(location, work_modality)
        and not (
            source_has_hybrid
            and (
                location.get("hybrid_allowed") is True
                or _hybrid_modality_is_usable(location, work_modality)
            )
        )
    ):
        notes.append("modality_review:remote_missing")
    if "presencial" in source and location.get("remote_allowed") is True:
        notes.append("modality_review:presencial_conflict")

    if re.search(r"\b\d+\s+(?:anos?|años?)\b", source) and experience.get("minimum_years") in (None, ""):
        notes.append("experience_review:minimum_years_missing")

    source_without_blockers = _source_without_blocker_clauses(source_text)
    for level in ("junior", "semi senior", "semisenior", "senior"):
        if level in source_without_blockers and level not in role_title and level not in seniority:
            notes.append(f"seniority_review:{level}_missing")

    if re.search(r"\b(no\s+avanzar|no\s+presentarse)\b", source) and not _string_list(data.get("blockers", [])):
        notes.append("blocker_review:blocker_missing")

    return notes


def _hybrid_modality_is_usable(location: Mapping[str, Any], work_modality: str = "") -> bool:
    raw = _fold(str(location.get("raw", "")))
    normalized = _fold(str(location.get("normalized", "")))
    return bool(re.search(r"\b(hibrido|hybrid)\b", f"{raw} {normalized} {work_modality}"))


def _remote_modality_is_usable(location: Mapping[str, Any], work_modality: str = "") -> bool:
    raw = _fold(str(location.get("raw", "")))
    normalized = _fold(str(location.get("normalized", "")))
    return bool(re.search(r"\b(remoto|remote)\b", f"{raw} {normalized} {work_modality}"))


def _source_without_blocker_clauses(source_text: str) -> str:
    kept = []
    for clause in re.split(r"[\n.;]+", source_text):
        if not re.search(r"\b(no\s+avanzar|no\s+presentarse|no\s+considerar)\b", clause, re.I):
            kept.append(clause)
    return _fold(" ".join(kept))


def modifier_clauses(
    source_text: str,
    include: re.Pattern[str],
    exclude: Optional[re.Pattern[str]] = None,
) -> List[str]:
    clauses = []
    for clause in re.split(r"[\n.;]+", source_text):
        clean = clause.strip()
        if not clean:
            continue
        if include.search(clean) and not (exclude and exclude.search(clean)):
            clauses.append(clean)
    return clauses


def _explicit_hard_cue_governs_item(item: str, hard_clauses: Iterable[str]) -> bool:
    if EXPLICIT_HARD_CUE_PATTERN.search(item):
        return True
    return any(
        EXPLICIT_HARD_CUE_PATTERN.search(clause) and _clause_matches_item(clause, item)
        for clause in hard_clauses
    )


def _clause_matches_item(clause: str, item: str) -> bool:
    clause_tokens = _meaningful_tokens(clause)
    item_tokens = _meaningful_tokens(item)
    if not clause_tokens or not item_tokens:
        return False
    overlap = clause_tokens & item_tokens
    return len(overlap) >= min(2, len(item_tokens))


def _meaningful_tokens(text: str) -> set[str]:
    stopwords = {
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "en",
        "con",
        "para",
        "por",
        "un",
        "una",
        "ser",
        "sera",
        "será",
        "muy",
        "se",
        "valora",
        "valorara",
        "valorará",
        "valorable",
        "valorables",
        "deseable",
        "deseables",
        "plus",
        "suma",
        "excluyente",
        "imprescindible",
        "requerido",
        "requerida",
        "obligatorio",
        "obligatoria",
    }
    return {
        token
        for token in re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]+", _fold(text))
        if len(token) > 2 and token not in stopwords
    }


def _is_incomplete_para_tail(text: str) -> bool:
    folded = _fold(str(text).strip(" -:.,;\t\r\n"))
    if not folded.startswith("para "):
        return False
    skill_tokens = {
        "sql",
        "git",
        "docker",
        "excel",
        "crm",
        "erp",
        "sap",
        "odoo",
        "tms",
        "wms",
        "power bi",
        "microsoft 365",
        "active directory",
    }
    return not any(skill in folded for skill in skill_tokens)


def search_readiness_status(data: Mapping[str, Any]) -> str:
    direct = data.get("search_readiness")
    if isinstance(direct, Mapping):
        return str(direct.get("status", ""))
    job_intelligence = data.get("job_intelligence")
    if isinstance(job_intelligence, Mapping):
        readiness = job_intelligence.get("search_readiness")
        if isinstance(readiness, Mapping):
            return str(readiness.get("status", ""))
    return ""


def build_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    classification_counts = Counter(str(row["result_classification"]) for row in rows)
    warning_counts: Counter[str] = Counter()
    diagnostic_counts: Counter[str] = Counter()
    note_counts: Counter[str] = Counter()
    for row in rows:
        for warning in str(row.get("warnings", "")).split("|"):
            if warning:
                if _is_diagnostic_warning(warning):
                    diagnostic_counts[warning] += 1
                else:
                    warning_counts[warning] += 1
        for note in str(row.get("notes", "")).split("; "):
            if note:
                note_counts[note.split(":", 1)[0]] += 1

    return {
        "total_cases": len(rows),
        "pass_count": classification_counts.get(PASS, 0),
        "warn_count": classification_counts.get(WARN, 0),
        "fail_count": sum(count for key, count in classification_counts.items() if key.startswith("FAIL_")),
        "classification_counts": dict(sorted(classification_counts.items())),
        "top_warnings": warning_counts.most_common(20),
        "top_diagnostics": diagnostic_counts.most_common(20),
        "top_notes": note_counts.most_common(20),
    }


def _is_diagnostic_warning(warning: str) -> bool:
    return bool(
        warning == "ai_schema_repaired"
        or warning.startswith("search_readiness_")
    )


def write_summary_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in SUMMARY_FIELDS})


def write_failures_md(path: Path, summary: Mapping[str, Any], rows: List[Dict[str, Any]]) -> None:
    failures_by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    warnings = []
    for row in rows:
        classification = str(row.get("result_classification", ""))
        if classification.startswith("FAIL_"):
            failures_by_category[classification].append(row)
        elif classification == WARN:
            warnings.append(row)

    lines = [
        "# CVBrain Live Intake Fixture Failures",
        "",
        f"- Total cases: {summary.get('total_cases', 0)}",
        f"- PASS: {summary.get('pass_count', 0)}",
        f"- WARN: {summary.get('warn_count', 0)}",
        f"- FAIL: {summary.get('fail_count', 0)}",
        "",
        "## Failures By Category",
    ]
    if not failures_by_category:
        lines.append("")
        lines.append("No failures.")
    for category, category_rows in sorted(failures_by_category.items()):
        lines.extend(["", f"### {category}", ""])
        for row in category_rows:
            lines.append(f"- `{row['id']}` status={row['http_status']} notes={row.get('notes', '')}")

    lines.extend(["", "## Warnings", ""])
    if not warnings:
        lines.append("No warning-classified cases.")
    for row in warnings:
        lines.append(f"- `{row['id']}` warnings={row.get('warnings', '')} notes={row.get('notes', '')}")

    lines.extend(["", "## Top Recurring Warnings", ""])
    for warning, count in summary.get("top_warnings", []):
        lines.append(f"- {warning}: {count}")

    lines.extend(["", "## Top Recurring Diagnostics", ""])
    for diagnostic, count in summary.get("top_diagnostics", []):
        lines.append(f"- {diagnostic}: {count}")

    lines.extend(["", "## Top Recurring Notes", ""])
    for note, count in summary.get("top_notes", []):
        lines.append(f"- {note}: {count}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _looks_english(text: str) -> bool:
    lowered = _fold(text)
    return bool(re.search(r"\b(manager|engineer|developer|analyst|support|sales)\b", lowered))


def _looks_spanish(text: str) -> bool:
    lowered = _fold(text)
    return bool(re.search(r"\b(busca|empresa|persona|experiencia|deseable|excluyente|modalidad)\b", lowered))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CVBrain live intake fixture cases one by one.")
    parser.add_argument("--input", required=True, type=Path, help="Fixture file with BUSQUEDA blocks.")
    parser.add_argument("--out", required=True, type=Path, help="Output directory, usually under /tmp.")
    parser.add_argument("--url", default=os.getenv("CVBRAIN_STAGING_URL", ""), help="Cloud Run base URL or analyze endpoint.")
    parser.add_argument(
        "--api-key",
        default=os.getenv("CVBRAIN_KEY") or os.getenv("CVBRAIN_INTAKE_API_KEY") or "",
        help="API key. If omitted, reads CVBRAIN_KEY or CVBRAIN_INTAKE_API_KEY.",
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds.")
    parser.add_argument("--sleep-seconds", type=float, default=1.0, help="Sleep between requests.")
    parser.add_argument("--expected-count", type=int, default=100, help="Expected number of parsed cases.")
    parser.add_argument(
        "--no-expect-live-ai",
        action="store_true",
        help="Do not fail if engine is not openai or fallback_used is true.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.url:
        raise SystemExit("Missing --url or CVBRAIN_STAGING_URL.")

    cases = parse_fixture(args.input)
    validate_case_sequence(cases, args.expected_count)
    url = endpoint_url(args.url)

    print(f"Parsed cases: {len(cases)}")
    print(f"URL: {url}")
    print(f"API_KEY_LENGTH: {len(args.api_key)}")
    print(f"Output: {args.out}")

    result = run_fixture(
        cases,
        out_dir=args.out,
        url=url,
        api_key=args.api_key,
        timeout=args.timeout,
        sleep_seconds=args.sleep_seconds,
        expect_live_ai=not args.no_expect_live_ai,
    )
    summary = result["summary"]
    print(f"PASS={summary['pass_count']} WARN={summary['warn_count']} FAIL={summary['fail_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
