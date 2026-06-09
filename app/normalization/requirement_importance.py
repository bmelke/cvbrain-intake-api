"""Resolve recruiter requirement importance at item level.

Section labels provide defaults, but local item modifiers are authoritative.
This keeps soft items out of hard filters even when they appear under a hard
heading, and promotes explicit hard blockers inside otherwise soft sections.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional


Importance = str

MUST_HAVE = "must_have"
STRONGLY_PREFERRED = "strongly_preferred"
PREFERRED = "preferred"
NICE_TO_HAVE = "nice_to_have"

HARD_PATTERN = re.compile(
    r"\b("
    r"excluyente|excluyentes|imprescindible|obligatori[oa]s?|requerid[oa]s?|"
    r"indispensable|m[ií]nim[oa]|requisito\s+excluyente|"
    r"sin\s+.+?\s+no\s+avanzar|no\s+avanzar\s+si\s+no\s+.+|"
    r"no\s+presentarse\s+si\s+no\s+.+|no\s+presentarse\s+a\s+menos\s+que\s+.+|"
    r"solo\s+avanzar\s+si\s+.+|con\s+experiencia\s+en\s+.+"
    r")\b",
    re.I,
)

SOFT_PATTERN = re.compile(
    r"\b("
    r"deseable|deseables|valorable|valorables|preferid[oa]s?|preferentemente|"
    r"ideal|plus|se\s+valora|nice\s+to\s+have|would\s+be\s+a\s+plus|preferred|desirable"
    r")\b",
    re.I,
)

SECTION_PATTERNS = (
    (re.compile(r"^\s*(credenciales?|requisitos?|formaci[oó]n)\s+(requerid[oa]s?|obligatori[oa]s?|excluyentes?)\s*:", re.I), MUST_HAVE),
    (re.compile(r"^\s*(must\s+have|required|requirements?|requisitos?)\s*:", re.I), MUST_HAVE),
    (re.compile(r"^\s*(should\s+have|preferid[oa]s?|deseables?|valorables?)\s*:", re.I), PREFERRED),
    (re.compile(r"^\s*(nice\s+to\s+have|plus|ideal)\s*:", re.I), NICE_TO_HAVE),
)

CONNECTOR_SPLIT_PATTERN = re.compile(r"\s+(?:y|e|and)\s+(?=(?:[A-ZÁÉÍÓÚÑ]|[a-záéíóúñ]+(?:\s+)?(?:deseable|valorable|imprescindible|excluyente|obligatorio)))")

CREDENTIAL_PATTERN = re.compile(
    r"\b(formaci[oó]n|t[ií]tulo|titulo|licencia|libreta|carnet|certificaci[oó]n|certificacion)\b",
    re.I,
)


@dataclass(frozen=True)
class RequirementItem:
    text: str
    importance: Importance
    source_text: str
    is_credential: bool = False
    blocker: str = ""


def resolve_requirements_from_text(text: str) -> Dict[str, Any]:
    """Split raw recruiter text and assign final item-level importance."""

    items = [_resolve_clause(clause, default) for clause, default in _iter_clauses_with_defaults(text)]
    items = [item for item in items if item and item.text]

    must_have: List[str] = []
    should_have: List[str] = []
    nice_to_have: List[str] = []
    blockers: List[str] = []
    credentials_required: List[str] = []
    credentials_preferred: List[str] = []

    for item in items:
        assert item is not None
        if item.importance == MUST_HAVE:
            must_have.append(item.text)
            if item.blocker:
                blockers.append(item.blocker)
        elif item.importance in {STRONGLY_PREFERRED, PREFERRED}:
            should_have.append(item.text)
        else:
            nice_to_have.append(item.text)

        if item.is_credential:
            if item.importance == MUST_HAVE:
                credentials_required.append(item.text)
            else:
                credentials_preferred.append(item.text)

    return {
        "items": items,
        "must_have": _unique(must_have),
        "should_have": _unique(should_have),
        "nice_to_have": _unique(nice_to_have),
        "blockers": _unique(blockers),
        "credentials": {
            "required": _unique(credentials_required),
            "preferred": _unique(credentials_preferred),
        },
    }


def normalize_job_intelligence_requirements(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize Job Intelligence requirement sections using local modifiers.

    The returned payload keeps the public schema but may move individual items
    across requirement buckets when their own phrase contradicts the section.
    """

    output: Dict[str, Any] = dict(payload)
    requirements = dict(output.get("requirements", {}))

    buckets: Dict[str, List[Dict[str, Any]]] = {
        "must_have": [],
        "should_have": [],
        "nice_to_have": [],
        "credentials": [],
    }
    blockers = [str(item).strip() for item in requirements.get("blockers", []) or [] if str(item).strip()]

    for section_name, default in (
        ("must_have", MUST_HAVE),
        ("should_have", PREFERRED),
        ("nice_to_have", NICE_TO_HAVE),
        ("credentials", PREFERRED),
    ):
        for item in requirements.get(section_name, []) or []:
            if not isinstance(item, Mapping):
                continue
            normalized_items = normalize_structured_requirement_item(item, default)
            for normalized in normalized_items:
                target = _bucket_for_importance(str(normalized.get("importance", default)))
                buckets[target].append(normalized)
                blocker = blocker_text_for_clause(str(normalized.get("source_text", "")))
                if target == "must_have" and blocker:
                    blockers.append(blocker)
                if section_name == "credentials" or _is_credential_text(_source_and_text(normalized)):
                    credential = dict(normalized)
                    buckets["credentials"].append(credential)

    requirements["must_have"] = _unique_requirement_items(buckets["must_have"])
    requirements["should_have"] = _unique_requirement_items(buckets["should_have"])
    requirements["nice_to_have"] = _unique_requirement_items(buckets["nice_to_have"])
    requirements["credentials"] = _unique_requirement_items(buckets["credentials"])
    requirements["blockers"] = _unique(blockers)
    output["requirements"] = requirements
    return output


def normalize_structured_requirement_item(item: Mapping[str, Any], default_importance: Importance) -> List[Dict[str, Any]]:
    """Split and normalize one structured requirement item."""

    source_text = str(item.get("source_text") or item.get("text") or "").strip()
    text = str(item.get("text") or source_text).strip()
    raw = source_text or text
    clauses = split_requirement_clauses(raw)
    if not clauses:
        clauses = [raw]

    output: List[Dict[str, Any]] = []
    for clause in clauses:
        importance = resolve_importance(clause, default_importance)
        normalized = dict(item)
        normalized["source_text"] = clause
        normalized["importance"] = importance
        if len(clauses) == 1 and _fold(clause) == _fold(raw) and not blocker_text_for_clause(clause):
            normalized["text"] = text
        else:
            normalized["text"] = normalize_requirement_text(clause)
        normalized["hard_filter_candidate"] = importance == MUST_HAVE
        normalized["hard_filter_approved"] = False
        if normalized["text"]:
            output.append(normalized)
    return output


def resolve_importance(text: str, section_default: Importance = PREFERRED) -> Importance:
    """Resolve final importance. Local modifiers outrank section defaults."""

    if SOFT_PATTERN.search(text):
        return NICE_TO_HAVE if section_default == NICE_TO_HAVE else PREFERRED
    if HARD_PATTERN.search(text):
        return MUST_HAVE
    return section_default or PREFERRED


def split_requirement_clauses(text: str) -> List[str]:
    """Split compound requirement prose into item-like clauses."""

    chunks: List[str] = []
    for sentence in re.split(r"[\n.;]+", text):
        sentence = _strip_section_heading(sentence)
        for part in re.split(r",|•|\u2022", sentence):
            for connector_part in CONNECTOR_SPLIT_PATTERN.split(part):
                clean = connector_part.strip(" -:\t\r\n")
                if clean:
                    chunks.append(clean)
    return _unique(chunks)


def normalize_requirement_text(text: str) -> str:
    clean = _strip_section_heading(text)
    travel = re.search(r"no\s+presentarse\s+a\s+menos\s+que\s+pueda\s+viajar", clean, re.I)
    if travel:
        return "Disponibilidad para viajar"
    clean = re.sub(r"\s+", " ", clean).strip(" -:.,;\t\r\n")
    return clean


def blocker_text_for_clause(text: str) -> str:
    if re.search(r"no\s+presentarse\s+a\s+menos\s+que\s+pueda\s+viajar", text, re.I):
        return "No avanzar si no puede viajar"
    if re.search(r"sin\s+.+?\s+no\s+avanzar|no\s+avanzar\s+si\s+no\s+.+|no\s+presentarse\s+si\s+no\s+.+", text, re.I):
        return normalize_requirement_text(text)
    return ""


def _iter_clauses_with_defaults(text: str) -> Iterable[tuple[str, Importance]]:
    current_default: Importance = PREFERRED
    for sentence in re.split(r"[\n.;]+", text):
        sentence = sentence.strip(" -\t\r\n")
        if not sentence:
            continue
        default = _section_default(sentence)
        if default:
            current_default = default
        for clause in split_requirement_clauses(sentence):
            yield clause, current_default


def _resolve_clause(clause: str, default: Importance) -> Optional[RequirementItem]:
    clean = normalize_requirement_text(clause)
    if not clean:
        return None
    importance = resolve_importance(clause, default)
    return RequirementItem(
        text=clean,
        importance=importance,
        source_text=clause,
        is_credential=_is_credential_text(clause),
        blocker=blocker_text_for_clause(clause) if importance == MUST_HAVE else "",
    )


def _section_default(text: str) -> Optional[Importance]:
    for pattern, importance in SECTION_PATTERNS:
        if pattern.search(text):
            return importance
    return None


def _strip_section_heading(text: str) -> str:
    return re.sub(
        r"^\s*(?:nice\s+to\s+have|must\s+have|required|requirements?|requisitos?|credenciales?(?:\s+(?:requerid[oa]s?|obligatori[oa]s?|excluyentes?))?|formaci[oó]n(?:\s+(?:requerid[oa]s?|obligatori[oa]s?|excluyentes?))?)\s*:\s*",
        "",
        text.strip(),
        flags=re.I,
    )


def _bucket_for_importance(importance: str) -> str:
    if importance == MUST_HAVE:
        return "must_have"
    if importance in {STRONGLY_PREFERRED, PREFERRED}:
        return "should_have"
    return "nice_to_have"


def _source_and_text(item: Mapping[str, Any]) -> str:
    return f"{item.get('source_text', '')} {item.get('text', '')}"


def _is_credential_text(text: str) -> bool:
    return bool(CREDENTIAL_PATTERN.search(text))


def _unique(items: Iterable[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for item in items:
        clean = " ".join(str(item).split())
        key = _fold(clean)
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
    return output


def _unique_requirement_items(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for item in items:
        text = str(item.get("text", "")).strip()
        key = (_fold(text), str(item.get("importance", "")).strip())
        if text and key not in seen:
            seen.add(key)
            output.append(dict(item))
    return output


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
