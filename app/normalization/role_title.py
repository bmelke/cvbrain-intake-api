"""Normalize post-AI role titles against the original recruiter source text."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Mapping


PRESERVED_ENGLISH_TITLES = (
    "Data Engineer",
    "Product Manager",
    "DevOps Engineer",
    "QA Tester",
    "Business Analyst",
)

SPANISH_TITLE_START = (
    "Administrador",
    "Administradora",
    "Analista",
    "Asistente",
    "Coordinador",
    "Coordinadora",
    "Ejecutivo",
    "Ejecutiva",
    "Encargado",
    "Encargada",
    "Gerente",
    "Jefe",
    "Jefa",
    "Responsable",
    "Soporte",
    "Supervisor",
    "Supervisora",
    "Tecnico",
    "Técnico",
)

SOURCE_ROLE_LEAD_PATTERN = re.compile(
    r"\b(?:busca|buscamos|necesita|sumar|incorporar|rol\s*:)\s+"
    r"(?:un|una|el|la)?\s*(?P<tail>.{0,140})",
    re.I | re.S,
)

SPANISH_ROLE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(SPANISH_TITLE_START)})\b"
    r"(?:\s+(?!(?:para|con|que|deber[aá]|debe|busca|buscamos|necesita)\b)"
    r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9/+.-]+){0,7}",
    re.I,
)

SPANISH_SOURCE_MARKER_PATTERN = re.compile(
    r"\b(?:empresa|busca|buscamos|experiencia|deseable|excluyente|modalidad|montevideo|uruguay)\b",
    re.I,
)


def normalize_role_title_for_source(payload: Mapping[str, Any], source_text: str) -> Dict[str, Any]:
    """Prefer the role title phrase used by Spanish recruiter source text."""

    output: Dict[str, Any] = dict(payload)
    job_profile = dict(output.get("job_profile", {}))
    current_title = str(job_profile.get("normalized_role_title") or job_profile.get("job_title") or "").strip()
    if not current_title:
        return output

    source_title = _source_role_title(source_text)
    if not source_title:
        return output

    if _fold(source_title) == _fold(current_title):
        return output

    if not _looks_spanish_source(source_text) and not _is_preserved_english_title(source_title):
        return output

    previous_titles = [
        str(job_profile.get("normalized_role_title") or "").strip(),
        str(job_profile.get("job_title") or "").strip(),
    ]
    job_profile["job_title"] = source_title
    job_profile["normalized_role_title"] = source_title
    output["job_profile"] = job_profile
    _preserve_role_title_terms(output, source_title, previous_titles)
    return output


def _source_role_title(source_text: str) -> str:
    source = " ".join(str(source_text or "").split())
    if not source:
        return ""

    preserved = _preserved_english_title_from_source(source)
    if preserved:
        return preserved

    for lead in SOURCE_ROLE_LEAD_PATTERN.finditer(source):
        title = _spanish_title_from_text(lead.group("tail"))
        if title:
            return title

    return _spanish_title_from_text(source)


def _preserved_english_title_from_source(source: str) -> str:
    for title in PRESERVED_ENGLISH_TITLES:
        match = re.search(rf"\b{re.escape(title)}\b", source, re.I)
        if match:
            return source[match.start() : match.end()]
    return ""


def _spanish_title_from_text(text: str) -> str:
    match = SPANISH_ROLE_PATTERN.search(text)
    if not match:
        return ""
    title = match.group(0).strip(" -:.,;\t\r\n")
    title = re.sub(r"\s*/\s*", " / ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _looks_spanish_source(source_text: str) -> bool:
    return bool(SPANISH_SOURCE_MARKER_PATTERN.search(source_text or ""))


def _is_preserved_english_title(title: str) -> bool:
    folded = _fold(title)
    return any(_fold(preserved) == folded for preserved in PRESERVED_ENGLISH_TITLES)


def _preserve_role_title_terms(output: Dict[str, Any], source_title: str, previous_titles: list[str]) -> None:
    search_strategy = dict(output.get("search_strategy", {}))
    search_strategy["target_titles"] = _unique([source_title] + _strings(search_strategy.get("target_titles", [])))
    search_strategy["search_terms"] = _unique(
        [source_title] + _strings(search_strategy.get("search_terms", [])) + previous_titles
    )
    search_strategy["semantic_terms"] = _unique(_strings(search_strategy.get("semantic_terms", [])) + previous_titles)
    output["search_strategy"] = search_strategy


def _strings(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def _unique(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        clean = " ".join(str(item).split())
        key = _fold(clean)
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
    return output


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
