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

STRONG_PREFERENCE_PATTERN = re.compile(
    r"\b("
    r"deseable|deseables|preferid[oa]s?|preferentemente|ideal(?:mente)?|"
    r"muy\s+valorad[oa]s?|muy\s+valorables?|"
    r"strongly\s+preferred|preferred|desirable"
    r")\b",
    re.I,
)

WEAK_PREFERENCE_PATTERN = re.compile(
    r"\b("
    r"valorables?|ser[aá]\s+valorables?|se\s+valora|se\s+valorar[aá](?:\s+especialmente)?|"
    r"plus|es\s+un\s+plus|suma|puede\s+sumar|no\s+central|"
    r"nice\s+to\s+have|would\s+be\s+a\s+plus"
    r")\b",
    re.I,
)

SOFT_PATTERN = re.compile(
    rf"(?:{STRONG_PREFERENCE_PATTERN.pattern}|{WEAK_PREFERENCE_PATTERN.pattern})",
    re.I,
)

SECTION_PATTERNS = (
    (re.compile(r"^\s*(credenciales?|requisitos?|formaci[oó]n)\s+(requerid[oa]s?|obligatori[oa]s?|excluyentes?)\s*:", re.I), MUST_HAVE),
    (re.compile(r"^\s*(must\s+have|required|requirements?|requisitos?)\s*:", re.I), MUST_HAVE),
    (re.compile(r"^\s*(should\s+have|preferid[oa]s?|deseables?|ideal|muy\s+valorables?)\s*:", re.I), PREFERRED),
    (re.compile(r"^\s*(nice\s+to\s+have|plus|valorables?|se\s+valora|se\s+valorar[aá]|suma)\s*:", re.I), NICE_TO_HAVE),
)

CONNECTOR_SPLIT_PATTERN = re.compile(r"\s+(?:y|e|and)\s+(?=(?:[A-ZÁÉÍÓÚÑ]|[a-záéíóúñ]+(?:\s+)?(?:deseable|valorable|imprescindible|excluyente|obligatorio)))")

CREDENTIAL_PATTERN = re.compile(
    r"\b(formaci[oó]n|t[ií]tulo|titulo|licencia|libreta|carnet|certificaci[oó]n|certificacion)\b",
    re.I,
)

ORPHAN_FRAGMENT_PATTERN = re.compile(
    r"^(?:y|e|o|and|or)\b|"
    r"^(?:software|hardware|redes?\s+b[aá]sicas?|soporte\s+remoto)$|"
    r"^(?:la\s+persona\s+deber[aá]\s+liderar|la\s+persona\s+deber[aá]\s+haber\s+trabajado\s+con|"
    r"la\s+persona\s+ser[aá]\s+responsable(?:\s+de)?|"
    r"se\s+requiere\s+base\s+t[eé]cnica\s+en|base\s+t[eé]cnica\s+en)$|"
    r"^(?:se\s+requiere|se\s+requieren|es\s+excluyente|son\s+excluyentes|"
    r"experiencia|experiencia\s+(?:en|con)|debe\s+manejar|manejo\s+de|dominio\s+de|conocimientos?\s+de)$",
    re.I,
)

NO_AVANZAR_PATTERN = re.compile(r"\bno\s+avanzar\b.*", re.I)
NO_PRESENTARSE_BLOCKER_PATTERN = re.compile(r"\bno\s+presentarse\s+si\s+no\b.*", re.I)
SIN_NO_AVANZAR_PATTERN = re.compile(r"\bsin\s+.+?\s+no\s+avanzar\b.*", re.I)
NO_SOLO_BLOCKER_PATTERN = re.compile(r"\bno\s+(?:solo|solamente)\b.*", re.I)
NI_NEGATIVE_FRAGMENT_PATTERN = re.compile(r"^\s*ni\s+(.+)", re.I)

MODIFIER_ONLY_FRAGMENT_PATTERNS = (
    re.compile(r"^no\s+excluyente$", re.I),
    re.compile(r"^(?:pero\s+)?no\s+debe\s+usarse\s+(?:como|as)\s+filtro(?:\s+excluyente)?$", re.I),
    re.compile(r"^(?:pero\s+)?no\s+es\s+requisito$", re.I),
    re.compile(r"^(?:pero\s+)?no\s+central$", re.I),
    re.compile(r"^(?:pero\s+)?no\s+es\s+excluyente(?:\s+salvo\b.*)?$", re.I),
    re.compile(r"^deseable$", re.I),
)

NEGATIVE_FILTER_MODIFIER_PATTERN = re.compile(
    r"\b("
    r"no\s+excluyente|"
    r"no\s+debe\s+usarse\s+(?:como|as)\s+filtro(?:\s+excluyente)?|"
    r"no\s+es\s+requisito"
    r")\b",
    re.I,
)

ALTERNATIVE_MARKER_PATTERN = re.compile(
    r"\b(?:o|u|similares?|afines?|equivalentes?|vinculad[oa]s?)\b",
    re.I,
)

STANDALONE_SKILL_PATTERN = re.compile(
    r"\b("
    r"sql|git|docker|excel|crm|erp|sap|odoo|tms|wms|power\s+bi|"
    r"microsoft\s+365|active\s+directory|itil|scrum|pmp|python|react|typescript"
    r")\b",
    re.I,
)

BLOCKER_METADATA_ARTIFACTS = {
    "source_text_span_hint_not_provided",
    "source_text_span_missing",
    "hard_filter_candidate_as_written",
    "hard_filter_approved_as_written",
}

METADATA_ARTIFACT_PATTERN = re.compile(
    r"^(?:source[_\s-]*text[_\s-]*span(?:[_\s-]*(?:missing|hint|not[_\s-]*provided))?(?:[_\s-]*for[_\s-]*blocker[_\s-]*\d+)?|"
    r"hard[_\s-]*filter[_\s-]*(?:candidate|approved)[_\s-]*as[_\s-]*written)$",
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
    blockers = _normalize_blocker_list(requirements.get("blockers", []) or [])
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
                if section_name == "credentials":
                    credential = dict(normalized)
                    buckets["credentials"].append(credential)
                    continue
                buckets[target].append(normalized)
                if _is_credential_text(_source_and_text(normalized)):
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
    requirements["blockers"] = _normalize_blocker_list(blockers)
    requirements["soft_competencies"] = _normalize_soft_competencies(requirements.get("soft_competencies", []))
    requirements = _normalize_blockers_and_negations(requirements, source_text)
    requirements = _dedupe_requirement_concepts(requirements)
    output["requirements"] = requirements
    return _sanitize_metadata_artifacts(output)


def normalize_structured_requirement_item(item: Mapping[str, Any], default_importance: Importance) -> List[Dict[str, Any]]:
    """Split and normalize one structured requirement item."""

    source_text = str(item.get("source_text") or item.get("text") or "").strip()
    text = str(item.get("text") or source_text).strip()
    raw = source_text or text
    clauses = split_requirement_clauses(raw)
    if not clauses:
        clauses = [raw]
    clause_default = MUST_HAVE if HARD_PATTERN.search(raw) else default_importance

    output: List[Dict[str, Any]] = []
    for clause in clauses:
        if _has_negative_filter_modifier(clause):
            continue
        importance = resolve_importance(clause, clause_default)
        normalized = dict(item)
        normalized["source_text"] = clause
        normalized["importance"] = importance
        if len(clauses) == 1 and _fold(clause) == _fold(raw) and not blocker_text_for_clause(clause):
            normalized["text"] = normalize_requirement_text(clause) if (
                _is_alternative_requirement_text(clause)
                or (_fold(text) == _fold(clause) and _should_normalize_requirement_text(clause))
            ) else text
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
    if STRONG_PREFERENCE_PATTERN.search(text):
        return PREFERRED
    if WEAK_PREFERENCE_PATTERN.search(text):
        return NICE_TO_HAVE
    return section_default or PREFERRED


def split_requirement_clauses(text: str) -> List[str]:
    """Split compound requirement prose into item-like clauses."""

    chunks: List[str] = []
    for sentence in re.split(r"[\n.;]+", text):
        sentence = _strip_section_heading(sentence)
        if _is_alternative_requirement_text(sentence):
            clean = sentence.strip(" -:\t\r\n")
            if clean:
                chunks.append(clean)
            continue
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
    clean = _remove_trailing_importance_modifier(clean)
    clean = _normalize_accents(clean)
    clean = re.sub(r"\s+", " ", clean).strip(" -:.,;\t\r\n")
    clean = re.sub(r"\s+para\s+visitas?\s+puntuales?.*$", "", clean, flags=re.I).strip()
    clean = _capitalize_first(clean)
    return clean


def blocker_text_for_clause(text: str) -> str:
    if re.search(r"no\s+presentarse\s+a\s+menos\s+que\s+pueda\s+viajar", text, re.I):
        return "No avanzar si no puede viajar"
    ni_fragment = NI_NEGATIVE_FRAGMENT_PATTERN.match(str(text).strip())
    if ni_fragment:
        return _normalize_blocker_text(f"No avanzar {ni_fragment.group(1)}")
    blocker = _extract_blocker_fragment(text)
    if blocker:
        return _normalize_blocker_text(blocker)
    return ""


def _is_blocker_only_clause(text: str) -> bool:
    lowered = _fold(text)
    if "no presentarse a menos que" in lowered:
        return False
    return bool(
        re.search(
            r"\bno\s+avanzar\b|\bno\s+presentarse\s+si\s+no\b|"
            r"\bsin\s+.+?\s+no\s+avanzar\b|\bno\s+considerar\b|"
            r"\bno\s+(?:solo|solamente)\b|^\s*ni\s+",
            lowered,
        )
    )


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
    if _has_negative_filter_modifier(clause):
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


def _should_normalize_requirement_text(text: str) -> bool:
    return bool(HARD_PATTERN.search(text) or SOFT_PATTERN.search(text) or _is_credential_text(text))


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


def _normalize_soft_competencies(items: Any) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return output

    for item in items:
        if not isinstance(item, Mapping):
            continue
        normalized = dict(item)
        normalized["hard_filter_candidate"] = False
        normalized["hard_filter_approved"] = False
        output.append(normalized)

    return _unique_requirement_items(output)


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

    valued_experience = re.match(
        r"^(?P<modifier>deseable|idealmente|ideal|valorable|se\s+valora|se\s+valorar[aá]|"
        r"ser[aá]\s+valorable|preferentemente|plus|suma|puede\s+sumar)\s+"
        r"experiencia\s+con\s+(?P<items>.+)$",
        clean,
        re.I,
    )
    if valued_experience and _has_list_separator(valued_experience.group("items")):
        modifier = valued_experience.group("modifier")
        return [
            f"{modifier} experiencia con {_normalize_accents(item)}"
            for item in _split_coordinated_list(valued_experience.group("items"))
        ]

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
        r"^\s*(?:(?:es|son)\s+)?(?:excluyente|excluyentes|imprescindible|obligatori[oa]s?|requerid[oa]s?|"
        r"indispensable|deseable|deseables|muy\s+valorad[oa]s?|muy\s+valorables?|"
        r"se\s+requiere|se\s+requieren|"
        r"se\s+valorar[aá](?:\s+especialmente)?|ser[aá]\s+valorable|"
        r"valorable|valorables|se\s+valora|"
        r"preferid[oa]s?|preferentemente|ideal(?:mente)?|plus|es\s+un\s+plus|suma|puede\s+sumar|"
        r"nice\s+to\s+have|would\s+be\s+a\s+plus|strongly\s+preferred|preferred|desirable)\s+",
        "",
        text,
        flags=re.I,
    )


def _remove_trailing_importance_modifier(text: str) -> str:
    clean = text.strip()
    trailing_patterns = (
        r"\s+es\s+deseable$",
        r"\s+deseables?$",
        r"\s+ser[aá]\s+valorables?$",
        r"\s+ser[aá]\s+un\s+plus$",
        r"\s+es\s+un\s+plus$",
        r"\s+puede\s+sumar(?:,?\s*(?:pero\s+)?no\s+es\s+requisito)?$",
        r"\s+suma$",
        r"\s+no\s+central$",
        r"\s+no\s+excluyente$",
        r",?\s*(?:pero\s+)?no\s+debe\s+usarse\s+(?:como|as)\s+filtro(?:\s+excluyente)?$",
        r",?\s*(?:pero\s+)?no\s+es\s+requisito$",
        r",?\s*(?:pero\s+)?no\s+es\s+excluyente(?:\s+salvo\b.*)?$",
    )
    for pattern in trailing_patterns:
        clean = re.sub(pattern, "", clean, flags=re.I).strip(" -:.,;\t\r\n")
    return clean


def _normalize_accents(text: str) -> str:
    replacements = {
        " ano ": " año ",
        " anos ": " años ",
        "basicas": "básicas",
        "comunicacion": "comunicación",
        "formacion": "formación",
        "tecnica": "técnica",
        "informatica": "informática",
        "certificaciones": "certificaciones",
        "certificacion": "certificación",
        "categoria": "categoría",
        "titulo": "título",
        "administracion": "administración",
        "libretta": "libreta",
        "telecomunicaciónes": "telecomunicaciones",
    }
    clean = f" {text} "
    for source, target in replacements.items():
        clean = re.sub(re.escape(source), target, clean, flags=re.I)
    clean = re.sub(r"\bcertificaciónes\b", "certificaciones", clean, flags=re.I)
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
    if folded == "no avanzar" or _is_metadata_artifact_text(clean):
        return True
    if _is_modifier_only_fragment(text) or _is_modifier_only_fragment(clean):
        return True
    if ORPHAN_FRAGMENT_PATTERN.search(folded):
        return True
    if _is_incomplete_para_tail(clean):
        return True
    if _has_dangling_connector_tail(clean):
        return True
    if folded in {"excluyente experiencia de al menos 1 ano resolviendo incidentes de", "experiencia de al menos 1 ano resolviendo incidentes de"}:
        return True
    return False


def _is_incomplete_para_tail(text: str) -> bool:
    folded = _fold(str(text).strip(" -:.,;\t\r\n"))
    if not folded.startswith("para "):
        return False
    if _is_credential_text(text) or STANDALONE_SKILL_PATTERN.search(text):
        return False
    return True


def _has_dangling_connector_tail(text: str) -> bool:
    folded = _fold(str(text).strip(" -:.,;\t\r\n"))
    if not folded:
        return True
    if STANDALONE_SKILL_PATTERN.fullmatch(str(text).strip(" -:.,;\t\r\n")):
        return False
    return bool(re.search(r"\b(?:con|de|en|para|o|u|y)$", folded))


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


def _normalize_blockers_and_negations(requirements: Mapping[str, Any], source_text: str) -> Dict[str, Any]:
    output: Dict[str, Any] = dict(requirements)
    blockers = _normalize_blocker_list(output.get("blockers", []) or [])
    blockers = _normalize_blocker_list(blockers + _blockers_from_text(source_text))

    for bucket in ("must_have", "should_have", "nice_to_have"):
        cleaned, blockers = _clean_requirement_items(output.get(bucket, []), blockers)
        cleaned = [
            item
            for item in cleaned
            if not _is_attached_source_blocker_fragment(item, blockers)
        ]
        output[bucket] = _unique_requirement_items(cleaned)

    cleaned_credentials, blockers = _clean_requirement_items(output.get("credentials", []), blockers)
    cleaned_credentials = [
        item
        for item in cleaned_credentials
        if not _is_attached_source_blocker_fragment(item, blockers)
    ]
    output["credentials"] = _unique_credentials_by_strongest_importance(cleaned_credentials)

    cleaned_soft, blockers = _clean_requirement_items(output.get("soft_competencies", []), blockers)
    cleaned_soft = [
        item
        for item in cleaned_soft
        if not _is_attached_source_blocker_fragment(item, blockers)
    ]
    output["soft_competencies"] = _unique_requirement_items(cleaned_soft)
    output["blockers"] = _normalize_blocker_list(blockers)
    return output


def _dedupe_requirement_concepts(requirements: Mapping[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = dict(requirements)
    blockers = _normalize_blocker_list(output.get("blockers", []) or [])
    blocker_keys = {_requirement_concept_key(blocker) for blocker in blockers}
    blocker_keys.discard("")

    selected: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for bucket in ("must_have", "should_have", "nice_to_have"):
        for item in output.get(bucket, []) or []:
            if not isinstance(item, Mapping):
                continue
            cleaned = _clean_positive_requirement_item(item)
            if not cleaned:
                continue
            key = _requirement_item_concept_key(cleaned)
            if not key or key in blocker_keys:
                continue
            record = {"bucket": bucket, "item": cleaned}
            if key not in selected:
                selected[key] = record
                order.append(key)
                continue
            if _should_replace_duplicate_requirement(selected[key], record):
                selected[key] = record

    _remove_alternative_fragment_duplicates(selected, order)
    _remove_redundant_aggregate_duplicates(selected, order)
    _remove_component_requirement_duplicates(selected, order)

    bucketed: Dict[str, List[Dict[str, Any]]] = {
        "must_have": [],
        "should_have": [],
        "nice_to_have": [],
    }
    for key in order:
        record = selected.get(key)
        if not record:
            continue
        bucketed[str(record["bucket"])].append(_strip_internal_fields(record["item"]))

    output["must_have"] = _unique_requirement_items_by_concept(bucketed["must_have"])
    output["should_have"] = _unique_requirement_items_by_concept(bucketed["should_have"])
    output["nice_to_have"] = _unique_requirement_items_by_concept(bucketed["nice_to_have"])

    positive_keys = {
        _requirement_item_concept_key(item)
        for bucket in ("must_have", "should_have", "nice_to_have")
        for item in output[bucket]
    }
    credentials = []
    for item in output.get("credentials", []) or []:
        if not isinstance(item, Mapping):
            continue
        cleaned = _clean_positive_requirement_item(item)
        if not cleaned:
            continue
        key = _requirement_item_concept_key(cleaned)
        if not key or key in blocker_keys or key in positive_keys:
            continue
        credentials.append(_strip_internal_fields(cleaned))

    output["credentials"] = _unique_credentials_by_strongest_concept(credentials)
    output["blockers"] = blockers
    return output


def _remove_alternative_fragment_duplicates(
    selected: Dict[str, Dict[str, Any]],
    order: List[str],
) -> None:
    composite_keys = [
        key
        for key in order
        if key in selected
        and isinstance(selected[key].get("item"), Mapping)
        and _is_alternative_requirement_text(str(selected[key]["item"].get("text", "")))
    ]
    if not composite_keys:
        return

    for key in list(order):
        if key not in selected or key in composite_keys:
            continue
        if any(_is_alternative_fragment_key(key, composite_key) for composite_key in composite_keys):
            del selected[key]


def _is_alternative_fragment_key(fragment_key: str, composite_key: str) -> bool:
    if not fragment_key or not composite_key or fragment_key == composite_key:
        return False
    tokens = fragment_key.split()
    if len(tokens) > 5:
        return False
    return re.search(rf"\b{re.escape(fragment_key)}\b", composite_key) is not None


def _remove_component_requirement_duplicates(
    selected: Dict[str, Dict[str, Any]],
    order: List[str],
) -> None:
    for key in list(order):
        if key not in selected:
            continue
        replacement_key = _more_complete_duplicate_key(key, selected, order)
        if replacement_key:
            del selected[key]


def _remove_redundant_aggregate_duplicates(
    selected: Dict[str, Dict[str, Any]],
    order: List[str],
) -> None:
    for key in list(order):
        if key not in selected:
            continue
        item = selected[key].get("item", {})
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text", ""))
        if _is_alternative_requirement_text(text):
            continue
        if not re.search(r"\b(?:y|e|and)\b", _fold(text)):
            continue
        component_keys = [
            other_key
            for other_key in order
            if other_key != key
            and other_key in selected
            and _component_key_inside(other_key, key)
        ]
        if len(component_keys) >= 2:
            del selected[key]


def _more_complete_duplicate_key(
    key: str,
    selected: Mapping[str, Dict[str, Any]],
    order: List[str],
) -> str:
    tokens = key.split()
    if len(tokens) > 6:
        return ""
    for other_key in order:
        if other_key == key or other_key not in selected:
            continue
        if _is_alternative_requirement_text(str(selected[other_key].get("item", {}).get("text", ""))):
            continue
        if _component_key_inside(key, other_key):
            return other_key
    return ""


def _component_key_inside(component_key: str, aggregate_key: str) -> bool:
    if not component_key or not aggregate_key or component_key == aggregate_key:
        return False
    return re.search(rf"\b{re.escape(component_key)}\b", aggregate_key) is not None


def _is_alternative_requirement_text(text: str) -> bool:
    clean = re.sub(r"\s+", " ", str(text).strip(" -:.,;\t\r\n"))
    if not clean:
        return False
    folded = _fold(clean)
    if not ALTERNATIVE_MARKER_PATTERN.search(folded):
        return False
    if re.search(r"\b(?:o|u)\b", folded):
        return True
    if re.search(r"\b(?:similares?|afines?|equivalentes?)\b", folded):
        return _has_list_separator(clean) or bool(re.search(r"\b(?:experiencia|formaci[oó]n|conocimientos?|manejo|dominio)\b", folded))
    if re.search(r"\bvinculad[oa]s?\b", folded):
        return _has_list_separator(clean) or bool(re.search(r"\b(?:sector|rubro|industria)\b", folded))
    return False


def _clean_positive_requirement_item(item: Mapping[str, Any]) -> Dict[str, Any]:
    text = normalize_requirement_text(str(item.get("text", "")).strip())
    source_text = str(item.get("source_text", "")).strip()
    if not text or _is_metadata_artifact_text(text):
        return {}
    if (
        _is_orphan_requirement_text(text)
        or _is_modifier_only_fragment(text)
        or _is_modifier_only_fragment(source_text)
    ):
        return {}
    if _is_metadata_artifact_text(source_text):
        source_text = text
    if _has_negative_filter_modifier(text) or _has_negative_filter_modifier(source_text):
        return {}
    if blocker_text_for_clause(source_text or text) and _is_blocker_only_clause(source_text or text):
        return {}
    cleaned = dict(item)
    cleaned["text"] = text
    if _is_blocker_only_clause(source_text) or _has_negative_filter_modifier(source_text):
        cleaned["source_text"] = text
    elif source_text and _is_orphan_requirement_text(source_text):
        cleaned["source_text"] = text
    cleaned["hard_filter_candidate"] = str(cleaned.get("importance", "")) == MUST_HAVE
    cleaned["hard_filter_approved"] = False
    return cleaned


def _should_replace_duplicate_requirement(existing: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    existing_item = existing.get("item", {})
    candidate_item = candidate.get("item", {})
    if not isinstance(existing_item, Mapping) or not isinstance(candidate_item, Mapping):
        return False

    existing_text = _source_and_text(existing_item)
    candidate_text = _source_and_text(candidate_item)
    existing_hard = _has_local_hard_modifier(existing_text)
    candidate_hard = _has_local_hard_modifier(candidate_text)
    existing_soft = _has_local_soft_modifier(existing_text)
    candidate_soft = _has_local_soft_modifier(candidate_text)

    if candidate_soft and not candidate_hard and not existing_hard:
        return True
    if existing_soft and not candidate_hard:
        return False

    candidate_rank = _importance_rank(str(candidate_item.get("importance", "")))
    existing_rank = _importance_rank(str(existing_item.get("importance", "")))
    return candidate_rank < existing_rank


def _has_local_hard_modifier(text: str) -> bool:
    return bool(HARD_PATTERN.search(text))


def _has_local_soft_modifier(text: str) -> bool:
    return bool(SOFT_PATTERN.search(text))


def _strip_internal_fields(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in dict(item).items() if not str(key).startswith("_cvbrain_")}


def _unique_requirement_items_by_concept(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for item in items:
        key = _requirement_item_concept_key(item)
        if key and key not in seen:
            seen.add(key)
            output.append(dict(item))
    return output


def _unique_credentials_by_strongest_concept(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for item in items:
        key = _requirement_item_concept_key(item)
        if not key:
            continue
        if key not in by_key:
            by_key[key] = dict(item)
            order.append(key)
            continue
        existing = by_key[key]
        if _importance_rank(str(item.get("importance", ""))) < _importance_rank(str(existing.get("importance", ""))):
            by_key[key] = dict(item)
    return [by_key[key] for key in order]


def _requirement_item_concept_key(item: Mapping[str, Any]) -> str:
    return _requirement_concept_key(str(item.get("text", "")))


def _requirement_concept_key(text: str) -> str:
    clean = _fold(_normalize_accents(str(text)))
    clean = re.sub(r"\blibretta\b", "libreta", clean)
    clean = re.sub(r"[\u2018\u2019\u201c\u201d\"'`]", "", clean)
    clean = re.sub(r"[^a-z0-9áéíóúñü\s/+#.-]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" -:.,;/\t\r\n")
    if not clean:
        return ""

    prefix_patterns = (
        r"^(?:es|son)\s+",
        r"^(?:excluyente|excluyentes|imprescindible|obligatorio|obligatoria|obligatorios|obligatorias|"
        r"requerido|requerida|requeridos|requeridas|indispensable)\s+",
        r"^se\s+requiere\s+",
        r"^se\s+requieren\s+",
        r"^deseable\s+",
        r"^deseables\s+",
        r"^valorable\s+",
        r"^valorables\s+",
        r"^se\s+valorara\s+",
        r"^sera\s+valorables?\s+",
        r"^se\s+valora\s+",
        r"^haber\s+",
        r"^contar\s+con\s+",
        r"^tener\s+",
        r"^poseer\s+",
        r"^experiencia\s+(?:en|con)\s+",
        r"^experiencia\s+(?!(?:en|con)\b)",
        r"^manejo\s+de\s+",
        r"^dominio\s+de\s+",
        r"^conocimientos?\s+de\s+",
    )
    previous = None
    while previous != clean:
        previous = clean
        for pattern in prefix_patterns:
            clean = re.sub(pattern, "", clean).strip(" -:.,;/\t\r\n")

    clean = re.sub(
        r"\s+(?:es\s+deseable|sera\s+valorables?|seran\s+valorables?|sera\s+un\s+plus|es\s+un\s+plus|"
        r"suma|puede\s+sumar|no\s+central|requerid[oa]s?(?:\s+por\s+.*)?|excluyentes?)$",
        "",
        clean,
    )
    clean = re.sub(
        r"\b(?:valorable|valorables|seran\s+valorables|sera\s+valorable|"
        r"sera\s+un\s+plus|plus|suma|puede\s+sumar|"
        r"excluyente|excluyentes|imprescindible|obligatorio|obligatoria|"
        r"obligatorios|obligatorias|requerido|requerida|requeridos|requeridas|"
        r"deseable|deseables|idealmente|ideal)\b",
        " ",
        clean,
    )
    clean = re.sub(r"\s+", " ", clean).strip(" -:.,;/\t\r\n")
    return clean


def _clean_requirement_items(items: Any, blockers: List[str]) -> tuple[List[Dict[str, Any]], List[str]]:
    cleaned: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return cleaned, blockers

    for item in items:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text", "")).strip()
        source_text = str(item.get("source_text", "")).strip()
        combined = f"{source_text} {text}".strip()
        blocker = blocker_text_for_clause(combined)
        if blocker:
            blockers.append(blocker)
            if _is_blocker_only_clause(combined):
                continue
        if (
            _is_modifier_only_fragment(text)
            or _is_modifier_only_fragment(source_text)
            or _has_negative_filter_modifier(text)
            or _has_negative_filter_modifier(source_text)
        ):
            continue
        cleaned.append(dict(item))

    return cleaned, _unique(blockers)


def _blockers_from_text(text: str) -> List[str]:
    blockers: List[str] = []
    for sentence in re.split(r"[\n.;]+", text or ""):
        blocker = blocker_text_for_clause(sentence)
        if blocker:
            blockers.append(blocker)
    return _unique(blockers)


def _extract_blocker_fragment(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text).strip(" -:.,;\t\r\n"))
    if not clean:
        return ""

    matches = []
    for pattern in (
        NO_AVANZAR_PATTERN,
        NO_PRESENTARSE_BLOCKER_PATTERN,
        SIN_NO_AVANZAR_PATTERN,
        NO_SOLO_BLOCKER_PATTERN,
    ):
        match = pattern.search(clean)
        if match:
            matches.append((match.start(), match.group(0)))
    if not matches:
        return ""
    return min(matches, key=lambda item: item[0])[1].strip(" -:.,;\t\r\n")


def _normalize_blocker_text(text: str) -> str:
    raw = str(text)
    had_final_period = raw.strip().endswith(".")
    clean = _normalize_accents(raw)
    clean = re.sub(r"\s+", " ", clean).strip(" -:.,;\t\r\n")
    clean = re.sub(r"^(no\s+(?:solo|solamente)\s+.+?)\s+\1$", r"\1", clean, flags=re.I)
    clean = re.sub(r"^criterio\s+de\s+no\s+avanzar\b", "No avanzar", clean, flags=re.I)
    clean = re.sub(r"\bcriterio\s+de\s*\.?\s*", "", clean, flags=re.I)
    clean = re.sub(r"\s+ni\s+", " y ", clean, flags=re.I)
    clean = re.sub(
        r"^no\s+(?:solo|solamente)\s+(.+)$",
        r"No avanzar perfiles centrados solo en \1",
        clean,
        flags=re.I,
    )
    clean = _dedupe_repeated_no_avanzar_segments(clean)
    if _fold(clean) == "no avanzar" or _is_metadata_artifact_text(clean):
        return ""
    if had_final_period and clean and not clean.endswith("."):
        clean = f"{clean}."
    return _capitalize_first(clean)


def _normalize_blocker_list(items: Iterable[str]) -> List[str]:
    return _unique(_normalize_blocker_text(str(item)) for item in items if str(item).strip())


def _dedupe_repeated_no_avanzar_segments(text: str) -> str:
    if len(re.findall(r"\bno\s+avanzar\b", text, re.I)) < 2:
        return text

    segments = [
        segment.strip(" -:.,;\t\r\n")
        for segment in re.split(r"(?=\bno\s+avanzar\b)", text, flags=re.I)
        if segment.strip(" -:.,;\t\r\n")
    ]
    if len(segments) <= 1:
        return text

    output: List[str] = []
    seen = set()
    for segment in segments:
        key = _fold(segment)
        if key == "no avanzar" or key in seen:
            continue
        seen.add(key)
        output.append(segment)
    return ". ".join(output) if output else ""


def _is_modifier_only_fragment(text: str) -> bool:
    clean = _fold(str(text)).strip(" -:.,;\t\r\n")
    if not clean:
        return True
    if _is_metadata_artifact_text(clean):
        return True
    return any(pattern.match(clean) for pattern in MODIFIER_ONLY_FRAGMENT_PATTERNS)


def _is_metadata_artifact_text(text: str) -> bool:
    clean = _fold(str(text)).strip(" -:.,;/\t\r\n")
    if not clean:
        return False
    if clean in BLOCKER_METADATA_ARTIFACTS:
        return True
    return bool(METADATA_ARTIFACT_PATTERN.match(clean))


def _sanitize_metadata_artifacts(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _sanitize_metadata_artifacts(child) for key, child in value.items()}
    if isinstance(value, list):
        output = []
        for item in value:
            if isinstance(item, str) and _is_metadata_artifact_text(item):
                continue
            output.append(_sanitize_metadata_artifacts(item))
        return output
    if isinstance(value, str) and _is_metadata_artifact_text(value):
        return ""
    return value


def _has_negative_filter_modifier(text: str) -> bool:
    clean = str(text).strip()
    if not clean or not NEGATIVE_FILTER_MODIFIER_PATTERN.search(clean):
        return False
    return not bool(SOFT_PATTERN.search(clean))


def _is_attached_source_blocker_fragment(item: Mapping[str, Any], blockers: Iterable[str]) -> bool:
    text = str(item.get("text", "")).strip()
    if not text:
        return True
    item_key = _fold(text).strip(" -:.,;\t\r\n")
    if not item_key:
        return True

    for blocker in blockers:
        blocker_key = _fold(blocker)
        if item_key not in blocker_key:
            if item_key.startswith("ni "):
                item_without_ni = item_key[3:].strip()
                if item_without_ni and item_without_ni in blocker_key:
                    return True
            continue
        if re.search(r"\bsin\b", item_key):
            return True
        if item_key.startswith("ni "):
            return True
        if re.search(rf"(?:,\s+|;\s+|\bni\s+){re.escape(item_key)}\b", blocker_key):
            return True
    return False


def _unique(items: Iterable[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for item in items:
        clean = " ".join(str(item).split())
        key = _fold(clean.strip(" -:.,;\t\r\n"))
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
