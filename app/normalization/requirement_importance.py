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

ORPHAN_FRAGMENT_PATTERN = re.compile(
    r"^(?:y|e|o|and|or)\b|^(?:software|hardware|redes?\s+b[aá]sicas?|soporte\s+remoto)$",
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
            if item.blocker:
                blockers.append(item.blocker)
                if _is_blocker_only_clause(item.source_text):
                    continue
            must_have.append(item.text)
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


def normalize_job_intelligence_requirements(payload: Mapping[str, Any], source_text: Optional[str] = None) -> Dict[str, Any]:
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
    source_text = source_text or ""

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
                blocker = blocker_text_for_clause(str(normalized.get("source_text", "")))
                if target == "must_have" and blocker:
                    blockers.append(blocker)
                    if _is_blocker_only_clause(str(normalized.get("source_text", ""))):
                        continue
                buckets[target].append(normalized)
                if section_name == "credentials" or _is_credential_text(_source_and_text(normalized)):
                    credential = dict(normalized)
                    buckets["credentials"].append(credential)

    if source_text:
        for source_item in _source_requirement_items(source_text):
            source_mapping = _requirement_item_to_mapping(source_item)
            target = _bucket_for_importance(source_item.importance)
            if source_item.blocker:
                blockers.append(source_item.blocker)
                if _is_blocker_only_clause(source_item.source_text):
                    continue
            buckets[target].append(source_mapping)
            if source_item.is_credential:
                buckets["credentials"].append(dict(source_mapping))

    must_have = _unique_requirement_items(buckets["must_have"])
    should_have = _unique_requirement_items(buckets["should_have"])
    nice_to_have = _unique_requirement_items(buckets["nice_to_have"])

    must_keys = _item_keys(must_have)
    should_have = [item for item in should_have if _fold(str(item.get("text", ""))) not in must_keys]
    should_keys = _item_keys(should_have)
    nice_to_have = [
        item
        for item in nice_to_have
        if _fold(str(item.get("text", ""))) not in must_keys | should_keys
    ]

    requirements["must_have"] = must_have
    requirements["should_have"] = should_have
    requirements["nice_to_have"] = nice_to_have
    requirements["credentials"] = _unique_credentials_by_strongest_importance(buckets["credentials"])
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
        if normalized["text"] and not _is_orphan_requirement_text(normalized["text"]):
            output.append(normalized)
    return output


def resolve_importance(text: str, section_default: Importance = PREFERRED) -> Importance:
    """Resolve final importance. Local modifiers outrank section defaults."""

    if HARD_PATTERN.search(text):
        return MUST_HAVE
    if SOFT_PATTERN.search(text):
        return NICE_TO_HAVE if section_default == NICE_TO_HAVE else PREFERRED
    return section_default or PREFERRED


def split_requirement_clauses(text: str) -> List[str]:
    """Split compound requirement prose into item-like clauses."""

    chunks: List[str] = []
    for sentence in re.split(r"[\n.;]+", text):
        sentence = _strip_section_heading(sentence)
        expanded = _expand_coordinated_sentence(sentence)
        if expanded:
            chunks.extend(expanded)
            continue
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
    driver = re.search(r"\b(libreta|carnet|licencia)\s+de\s+conducir\s+categor[ií]a\s+([A-Z0-9]+)", clean, re.I)
    if driver:
        doc = _capitalize_first(_normalize_accents(driver.group(1)))
        return f"{doc} de conducir categoría {driver.group(2).upper()}"
    clean = _remove_importance_label(clean)
    clean = _normalize_accents(clean)
    clean = re.sub(r"\s+", " ", clean).strip(" -:.,;\t\r\n")
    clean = re.sub(r"\s+para\s+visitas?\s+puntuales?.*$", "", clean, flags=re.I).strip()
    clean = _capitalize_first(clean)
    return clean


def blocker_text_for_clause(text: str) -> str:
    if re.search(r"no\s+presentarse\s+a\s+menos\s+que\s+pueda\s+viajar", text, re.I):
        return "No avanzar si no puede viajar"
    if re.search(r"sin\s+.+?\s+no\s+avanzar|no\s+avanzar\s+si\s+no\s+.+|no\s+presentarse\s+si\s+no\s+.+", text, re.I):
        return normalize_requirement_text(text)
    return ""


def _is_blocker_only_clause(text: str) -> bool:
    lowered = _fold(text)
    if "no presentarse a menos que" in lowered:
        return False
    return bool(re.search(r"\bsin\s+.+?\s+no\s+avanzar\b|\bno\s+avanzar\s+si\s+no\b|\bno\s+considerar\b", lowered))


def _iter_clauses_with_defaults(text: str) -> Iterable[tuple[str, Importance]]:
    for sentence in re.split(r"[\n.;]+", text):
        sentence = sentence.strip(" -\t\r\n")
        if not sentence:
            continue
        default = _section_default(sentence)
        if not default:
            default = resolve_importance(sentence, PREFERRED)
        for clause in split_requirement_clauses(sentence):
            yield clause, default


def _resolve_clause(clause: str, default: Importance) -> Optional[RequirementItem]:
    clean = normalize_requirement_text(clause)
    if not clean:
        return None
    if _is_orphan_requirement_text(clean):
        return None
    importance = resolve_importance(clause, default)
    if not _has_requirement_signal(clause, clean, importance):
        return None
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


def _has_requirement_signal(source_text: str, normalized_text: str, importance: Importance) -> bool:
    source = _strip_section_heading(source_text)
    folded_text = _fold(normalized_text)

    if HARD_PATTERN.search(source) or SOFT_PATTERN.search(source) or _section_default(source_text):
        return True
    if _is_credential_text(source) or _is_credential_text(normalized_text):
        return True
    if folded_text.startswith(("experiencia ", "conocimientos ", "manejo ", "dominio ")):
        return True
    if folded_text in {"buena comunicacion", "registro de tickets", "disponibilidad para viajar"}:
        return True
    if importance == MUST_HAVE and blocker_text_for_clause(source):
        return True
    return False


def _source_requirement_items(text: str) -> List[RequirementItem]:
    items = [_resolve_clause(clause, default) for clause, default in _iter_clauses_with_defaults(text)]
    return [item for item in items if item and item.text]


def _requirement_item_to_mapping(item: RequirementItem) -> Dict[str, Any]:
    return {
        "text": item.text,
        "source_text": item.source_text,
        "importance": item.importance,
        "explicit": True,
        "hard_filter_candidate": item.importance == MUST_HAVE,
        "hard_filter_approved": False,
    }


def _expand_coordinated_sentence(sentence: str) -> List[str]:
    clean = re.sub(r"\s+", " ", sentence.strip(" -:.,;\t\r\n"))
    if not clean:
        return []

    experience = re.match(
        r"^(?:excluyente\s+|imprescindible\s+|obligatori[oa]\s+|requerid[oa]\s+)?"
        r"(?:experiencia\s+de\s+al\s+menos\s+(\d+)\s+(?:a[nñ]os?|anos?)\s+resolviendo\s+incidentes\s+de\s+)(.+)$",
        clean,
        re.I,
    )
    if experience:
        years = experience.group(1)
        return _experience_incident_items(years, experience.group(2))

    experience_alt = re.match(
        r"^(?:al\s+menos\s+)?(\d+)\s+(?:a[nñ]os?|anos?)\s+de\s+experiencia\s+resolviendo\s+incidentes\s+de\s+(.+)$",
        clean,
        re.I,
    )
    if experience_alt:
        years = experience_alt.group(1)
        return _experience_incident_items(years, experience_alt.group(2))

    knowledge = re.match(
        r"^(?:deseable\s+|valorable\s+|preferentemente\s+|preferred\s+|desirable\s+)?"
        r"(conocimientos?|manejo|dominio)\s+(?:de|with|of)\s+(.+)$",
        clean,
        re.I,
    )
    if knowledge and _has_list_separator(knowledge.group(2)):
        label = knowledge.group(1).lower()
        prefix = "Conocimientos de"
        if "manejo" in label:
            prefix = "Manejo de"
        elif "dominio" in label:
            prefix = "Dominio de"
        return [f"{prefix} {_normalize_accents(item)}" for item in _split_coordinated_list(knowledge.group(2))]

    english_knowledge = re.match(
        r"^(?:preferred\s+|desirable\s+|nice\s+to\s+have\s+)?(?:knowledge|experience)\s+(?:of|with)\s+(.+)$",
        clean,
        re.I,
    )
    if english_knowledge and _has_list_separator(english_knowledge.group(1)):
        return [f"Knowledge of {item}" for item in _split_coordinated_list(english_knowledge.group(1))]

    communication = re.match(
        r"^(?:imprescindible\s+|excluyente\s+|obligatori[oa]\s+|requerid[oa]\s+)?"
        r"buena\s+comunicaci[oó]n\s+y\s+registro\s+de\s+tickets$",
        clean,
        re.I,
    )
    if communication:
        return ["Buena comunicación", "Registro de tickets"]

    return []


def _experience_incident_items(years: str, raw_items: str) -> List[str]:
    output: List[str] = []
    for item in _split_coordinated_list(raw_items):
        clean_item = _normalize_accents(item)
        if re.search(r"\bsoporte\s+remoto\b", clean_item, re.I):
            output.append(f"Experiencia de al menos {years} año brindando soporte remoto")
        else:
            output.append(f"Experiencia de al menos {years} año resolviendo incidentes de {clean_item}")
    return output


def _split_coordinated_list(text: str) -> List[str]:
    normalized = re.sub(r"\s+(?:y|e|and|o|or)\s+", ", ", text.strip(), flags=re.I)
    return [
        item.strip(" -:.,;\t\r\n")
        for item in normalized.split(",")
        if item.strip(" -:.,;\t\r\n")
    ]


def _has_list_separator(text: str) -> bool:
    return bool(re.search(r",|\s+(?:y|e|and|o|or)\s+", text, re.I))


def _remove_importance_label(text: str) -> str:
    return re.sub(
        r"^\s*(?:excluyente|excluyentes|imprescindible|obligatori[oa]s?|requerid[oa]s?|"
        r"indispensable|deseable|deseables|valorable|valorables|preferentemente|ideal|"
        r"plus|nice\s+to\s+have|preferred|desirable)\s+",
        "",
        text,
        flags=re.I,
    )


def _normalize_accents(text: str) -> str:
    replacements = {
        " ano ": " año ",
        " anos ": " años ",
        "basicas": "básicas",
        "comunicacion": "comunicación",
        "formacion": "formación",
        "tecnica": "técnica",
        "informatica": "informática",
        "certificacion": "certificación",
        "categoria": "categoría",
        "titulo": "título",
        "administracion": "administración",
    }
    clean = f" {text} "
    for source, target in replacements.items():
        clean = re.sub(re.escape(source), target, clean, flags=re.I)
    return clean.strip()


def _capitalize_first(text: str) -> str:
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _is_orphan_requirement_text(text: str) -> bool:
    clean = normalize_requirement_text(text)
    folded = _fold(clean.strip(" -:.,;\t\r\n"))
    if not folded:
        return True
    if ORPHAN_FRAGMENT_PATTERN.search(folded):
        return True
    if folded in {"excluyente experiencia de al menos 1 ano resolviendo incidentes de", "experiencia de al menos 1 ano resolviendo incidentes de"}:
        return True
    return False


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


def _unique_credentials_by_strongest_importance(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for item in items:
        text = str(item.get("text", "")).strip()
        key = _fold(text)
        if not text:
            continue
        if key not in by_key:
            by_key[key] = dict(item)
            order.append(key)
            continue
        existing = by_key[key]
        if _importance_rank(str(item.get("importance", ""))) < _importance_rank(str(existing.get("importance", ""))):
            by_key[key] = dict(item)
    return [by_key[key] for key in order]


def _item_keys(items: Iterable[Mapping[str, Any]]) -> set[str]:
    return {_fold(str(item.get("text", ""))) for item in items if str(item.get("text", "")).strip()}


def _importance_rank(importance: str) -> int:
    if importance == MUST_HAVE:
        return 0
    if importance in {STRONGLY_PREFERRED, PREFERRED}:
        return 1
    return 2


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
