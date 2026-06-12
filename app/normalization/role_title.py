"""Normalize post-AI role titles against the original recruiter source text."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Mapping


PRESERVED_ENGLISH_TITLES = (
    "Data Engineer",
    "Product Manager",
    "DevOps Engineer",
    "QA Automation Engineer",
    "QA Tester",
    "Account Manager",
    "Customer Success Manager",
    "UX/UI Designer",
    "Community Manager Senior",
    "Community Manager",
    "Business Analyst",
    "BI Analyst",
    "Full Stack Developer",
    "Backend Developer",
    "Frontend Developer",
)

SPANISH_TITLE_START = (
    "Administrador",
    "Administradora",
    "Analista",
    "Arquitecto",
    "Arquitecta",
    "Asistente",
    "Coordinador",
    "Coordinadora",
    "Consultor",
    "Consultora",
    "Desarrollador",
    "Desarrolladora",
    "Ejecutivo",
    "Ejecutiva",
    "Encargado",
    "Encargada",
    "Gerente",
    "Ingeniero",
    "Ingeniera",
    "Jefe",
    "Jefa",
    "Liquidador",
    "Liquidadora",
    "Periodista",
    "Responsable",
    "Redactor",
    "Redactora",
    "Reclutador",
    "Reclutadora",
    "Secretaria",
    "Secretario",
    "Soporte",
    "Supervisor",
    "Supervisora",
    "Tecnico",
    "Técnico",
    "Vendedor",
    "Vendedora",
    "Visitador",
    "Visitadora",
    "Auditor",
    "Auditora",
)

SOURCE_ROLE_LEAD_PATTERNS = (
    re.compile(
        r"\b(?:busca|buscamos|seleccionamos|selecciona|necesita|necesitamos|"
        r"sumar|incorporar|incorpora|incorporamos|contrata|requiere|"
        r"queremos\s+incorporar|rol\s*:|se\s+busca|nos\s+encontramos\s+en\s+b[uú]squeda\s+de)\s+"
        r"(?:(?:un|una|el|la|un/a)\s+)?(?P<tail>.{0,180})",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:posici[oó]n|puesto|perfil|vacante)\s+de\s+"
        r"(?:(?:un|una|el|la|un/a)\s+)?(?P<tail>.{0,180})",
        re.I | re.S,
    ),
    re.compile(
        r"\bpara\s+cubrir\s+(?:(?:un|una|el|la|un/a)\s+)?(?P<tail>.{0,180})",
        re.I | re.S,
    ),
    re.compile(
        r"\bsumar\s+(?:a\s+)?(?:(?:un|una|el|la|un/a)\s+)?(?P<tail>.{0,180})",
        re.I | re.S,
    ),
    re.compile(
        r"\bpara\s+empresa\b.{0,140}?\bbuscamos\s+(?:un|una|el|la)?\s*(?P<tail>.{0,160})",
        re.I | re.S,
    ),
)

TITLE_SENTENCE_TAIL_PATTERN = re.compile(
    r"(?:[.;:]\s*)?\b(?:es\s+excluyente|excluyente|la\s+persona|se\s+requiere|debe|"
    r"deseable|valorable|ser[aá]\s+valorable|no\s+avanzar|para)\b.*$",
    re.I | re.S,
)

SPANISH_ROLE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(SPANISH_TITLE_START)})\b"
    r"(?:\s+(?!(?:para|con|que|deber[aá]|debe|busca|buscamos|necesita|"
    r"es|excluyente|la|se|deseable|valorable)\b)"
    r"[A-Za-zÁÉÍÓÚÜáéíóúüÑñ0-9/+.-]+){0,7}",
    re.I,
)

SPANISH_SOURCE_MARKER_PATTERN = re.compile(
    r"\b(?:empresa|busca|buscamos|seleccionamos|experiencia|deseable|excluyente|"
    r"modalidad|montevideo|uruguay|b[uú]squeda|se\s+busca)\b",
    re.I,
)

REJECTED_TITLE_EXACT = {
    "agencia",
    "consultora",
    "empresa",
    "empresa tecnologica",
    "empresa tecnológica",
    "startup",
    "multinacional",
}

REJECTED_TITLE_PREFIX_PATTERN = re.compile(
    r"^(?:soporte\s+a|responsable\s+de|gesti[oó]n\s+de|empresa\s+|startup\s+|agencia\s+|multinacional\s+)",
    re.I,
)


def normalize_role_title_for_source(payload: Mapping[str, Any], source_text: str) -> Dict[str, Any]:
    """Prefer the role title phrase used by Spanish recruiter source text."""

    output: Dict[str, Any] = dict(payload)
    job_profile = dict(output.get("job_profile", {}))
    job_title = _clean_role_title(str(job_profile.get("job_title") or "").strip())
    normalized_title = _clean_role_title(str(job_profile.get("normalized_role_title") or "").strip())
    current_title = normalized_title or job_title
    if not current_title:
        return output

    source_title = _source_role_title(source_text)
    source_is_spanish = _looks_spanish_source(source_text)
    previous_titles = _unique(
        [
            str(job_profile.get("normalized_role_title") or "").strip(),
            str(job_profile.get("job_title") or "").strip(),
        ]
    )

    canonical_title = ""
    if source_title and _is_preserved_english_title(source_title):
        if current_title and _fold(current_title).startswith(_fold(source_title)):
            canonical_title = current_title
        else:
            canonical_title = source_title
    elif source_title:
        canonical_title = source_title
    elif source_is_spanish and _looks_spanish_title(job_title):
        canonical_title = job_title
    elif _looks_spanish_title(job_title) and _looks_english_title(normalized_title):
        canonical_title = job_title
    elif current_title:
        canonical_title = current_title

    if not canonical_title:
        return output

    if (
        canonical_title == str(job_profile.get("job_title") or "").strip()
        and canonical_title == str(job_profile.get("normalized_role_title") or "").strip()
    ):
        return output

    job_profile["job_title"] = canonical_title
    job_profile["normalized_role_title"] = canonical_title
    output["job_profile"] = job_profile
    _preserve_role_title_terms(output, canonical_title, previous_titles)
    return output


def display_role_title_from_job_profile(job_profile: Mapping[str, Any]) -> str:
    """Return the canonical display title from a normalized job_profile."""

    job_title = _clean_role_title(str(job_profile.get("job_title") or "").strip())
    normalized_title = _clean_role_title(str(job_profile.get("normalized_role_title") or "").strip())
    if job_title and _looks_spanish_title(job_title) and _looks_english_title(normalized_title):
        return job_title
    return normalized_title or job_title


def _source_role_title(source_text: str) -> str:
    source = " ".join(str(source_text or "").split())
    if not source:
        return ""

    preserved = _preserved_english_title_from_source(source)
    if preserved:
        return preserved

    for pattern in SOURCE_ROLE_LEAD_PATTERNS:
        for lead in pattern.finditer(source):
            title = _spanish_title_from_text(lead.group("tail"))
            if title:
                return title

    return _spanish_title_from_text(source)


def _preserved_english_title_from_source(source: str) -> str:
    for title in PRESERVED_ENGLISH_TITLES:
        match = re.search(rf"(?<![A-Za-z0-9/+.-]){re.escape(title)}(?![A-Za-z0-9/+.-])", source, re.I)
        if match:
            return source[match.start() : match.end()]
    return ""


def _spanish_title_from_text(text: str) -> str:
    match = SPANISH_ROLE_PATTERN.search(_clean_role_title(text))
    if not match:
        return ""
    title = _clean_role_title(match.group(0))
    if _is_rejected_title(title):
        return ""
    return title


def _clean_role_title(text: str) -> str:
    title = TITLE_SENTENCE_TAIL_PATTERN.sub("", str(text or ""))
    title = title.strip(" -:.,;\t\r\n")
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _looks_spanish_source(source_text: str) -> bool:
    return bool(SPANISH_SOURCE_MARKER_PATTERN.search(source_text or ""))


def _looks_spanish_title(title: str) -> bool:
    clean = _clean_role_title(title)
    return bool(
        clean
        and not _is_preserved_english_title(clean)
        and not _is_rejected_title(clean)
        and SPANISH_ROLE_PATTERN.match(clean)
    )


def _looks_english_title(title: str) -> bool:
    clean = _clean_role_title(title)
    if not clean:
        return False
    if _is_preserved_english_title(clean):
        return True
    return bool(re.search(r"\b(?:manager|engineer|developer|representative|receptionist|auditor|assistant|analyst|visitor)\b", clean, re.I))


def _is_preserved_english_title(title: str) -> bool:
    folded = _fold(title)
    return any(_fold(preserved) == folded for preserved in PRESERVED_ENGLISH_TITLES)


def _is_rejected_title(title: str) -> bool:
    folded = _fold(_clean_role_title(title))
    if not folded:
        return True
    if folded in {_fold(value) for value in REJECTED_TITLE_EXACT}:
        return True
    return bool(REJECTED_TITLE_PREFIX_PATTERN.search(folded))


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
