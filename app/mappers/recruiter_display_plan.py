"""Build recruiter-facing display plans from normalized CVBrain output."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from app.normalization.role_title import display_role_title_from_job_profile


READY_LABELS = {
    "ready": ("Lista para buscar", "success"),
    "usable_with_warnings": ("Usable con advertencias", "warning"),
    "exploratory": ("Exploratoria", "info"),
    "insufficient_for_precise_search": ("Insuficiente para una busqueda precisa", "warning"),
    "blocked_for_safety_or_technical_reason": ("Bloqueada por seguridad o falla tecnica", "error"),
}

KNOWN_ACRONYMS = {
    "API",
    "AWS",
    "BI",
    "B2B",
    "B2C",
    "CRM",
    "ERP",
    "GCP",
    "IT",
    "MVP",
    "QA",
    "SAP",
    "SQL",
    "TMS",
    "UI",
    "UX",
    "WMS",
}


def build_recruiter_display_plan(
    job_intelligence: Optional[Mapping[str, Any]] = None,
    flat: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a UI-ready recruiter search plan.

    WordPress should be able to render this object after escaping values,
    without classifying requirements or applying semantic cleanup.
    """

    job_intelligence = job_intelligence or {}
    flat = flat or {}
    job_profile = _mapping(job_intelligence.get("job_profile"))
    requirements = _mapping(job_intelligence.get("requirements"))
    location = _mapping(job_intelligence.get("location_intelligence"))
    search_strategy = _mapping(job_intelligence.get("search_strategy"))
    readiness = _mapping(job_intelligence.get("search_readiness"))

    role_title = _display_role_title(
        flat.get("role_title")
        or display_role_title_from_job_profile(job_profile)
        or job_profile.get("job_title")
        or job_profile.get("normalized_role_title")
    )
    seniority = _clean_display_text(
        job_profile.get("seniority") or _mapping(flat.get("experience")).get("seniority")
    )
    market = _market_label(location, flat)
    location_modality = _location_modality_label(location, job_profile, _mapping(flat.get("location")))

    found_blockers: List[str] = []
    must_have, found_blockers = _clean_requirement_bucket(
        _texts(flat.get("must_have")) + _texts(_mapping(flat.get("credentials")).get("required")),
        role_title=role_title,
        blockers=found_blockers,
    )
    must_have = _add_experience_requirement(must_have, _mapping(flat.get("experience")))
    preferred, found_blockers = _clean_requirement_bucket(
        _texts(flat.get("should_have")) + _preferred_credentials(flat),
        role_title=role_title,
        blockers=found_blockers,
    )
    nice_to_have, found_blockers = _clean_requirement_bucket(
        _texts(flat.get("nice_to_have")),
        role_title=role_title,
        blockers=found_blockers,
    )
    blockers = _dedupe_display_items(_texts(flat.get("blockers")) + found_blockers)

    questions = _display_questions(job_intelligence, blockers, search_strategy)
    tie_breakers = _tie_breakers(preferred, nice_to_have, _texts(job_profile.get("primary_industries")))
    search_concepts = _search_concepts(
        role_title=role_title,
        search_strategy=search_strategy,
        job_profile=job_profile,
        must_have=must_have,
        preferred=preferred,
        nice_to_have=nice_to_have,
    )

    return {
        "role_title": role_title,
        "seniority": seniority,
        "market": market,
        "location_modality": location_modality,
        "summary": _what_to_search(role_title, _clean_display_text(flat.get("summary") or job_profile.get("summary"))),
        "what_to_search": _what_to_search(role_title, _clean_display_text(flat.get("summary") or job_profile.get("summary"))),
        "must_have": must_have,
        "preferred": preferred,
        "nice_to_have": nice_to_have,
        "blockers": blockers,
        "tie_breakers": tie_breakers,
        "questions": questions,
        "search_concepts": search_concepts,
        "readiness": _readiness(readiness, flat),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _texts(items: Any) -> List[str]:
    output: List[str] = []
    if not isinstance(items, list):
        return output
    for item in items:
        if isinstance(item, Mapping):
            text = item.get("text") or item.get("question") or item.get("suggested_question") or ""
        else:
            text = item
        clean = _clean_display_text(text)
        if clean:
            output.append(clean)
    return output


def _preferred_credentials(flat: Mapping[str, Any]) -> List[str]:
    credentials = _mapping(flat.get("credentials"))
    return _texts(credentials.get("preferred"))


def _clean_requirement_bucket(
    items: Iterable[str],
    role_title: str,
    blockers: List[str],
) -> Tuple[List[str], List[str]]:
    cleaned: List[str] = []
    for item in items:
        blocker = _blocker_from_text(item)
        if blocker:
            blockers.append(blocker)
            continue
        clean = _clean_requirement_text(item, role_title=role_title)
        if clean:
            cleaned.append(clean)
    return _dedupe_display_items(cleaned), _dedupe_display_items(blockers)


def _clean_requirement_text(value: Any, role_title: str = "") -> str:
    clean = _clean_display_text(value)
    if not clean:
        return ""
    clean = re.sub(r"\bexperiencia\s+rn\b", "experiencia en", clean, flags=re.I)
    clean = _strip_recruiter_lead_sentence(clean, role_title=role_title)
    if _blocker_from_text(clean):
        return ""
    if _looks_like_missing_placeholder(clean) or _looks_internal(clean) or _looks_meta_or_process(clean):
        return ""
    if re.match(r"^(?:seniority|seniority\s*:)?\s*(?:sin especificar|no especificad[oa])$", clean, re.I):
        return ""
    clean = re.sub(
        r"\s+es\s+(?:necesari[oa]|indispensable|excluyente|obligatori[oa]|requerid[oa])$",
        "",
        clean,
        flags=re.I,
    )
    return _clean_display_text(clean)


def _strip_recruiter_lead_sentence(value: str, role_title: str = "") -> str:
    clean = str(value or "").strip()
    if not re.search(r"\b(?:busca|buscamos|incorpora|selecciona|seleccionamos|contrata|requiere)\b", clean, re.I):
        return clean
    if role_title and _fold(role_title) in _fold(clean):
        pattern = re.escape(role_title)
        clean = re.sub(rf"^.*?\b{pattern}\b\s*", "", clean, flags=re.I)
    else:
        clean = re.sub(
            r"^.*?\b(?:busca|buscamos|incorpora|selecciona|seleccionamos|contrata|requiere)\b\s+",
            "",
            clean,
            flags=re.I,
        )
    clean = re.sub(r"^(?:con|para|a fin de)\s+", "", clean, flags=re.I).strip(" -:.,;")
    return clean


def _add_experience_requirement(items: List[str], experience: Mapping[str, Any]) -> List[str]:
    years = experience.get("minimum_years")
    try:
        years_int = int(years) if years is not None and str(years).strip() != "" else None
    except (TypeError, ValueError):
        years_int = None
    if years_int is None:
        return items
    haystack = _fold(" ".join(items))
    if re.search(rf"\b{years_int}\s*(?:anos?|años?|years?)\b", haystack):
        return items
    return _dedupe_display_items(items + [f"Minimo {years_int} años de experiencia"])


def _market_label(location: Mapping[str, Any], flat: Mapping[str, Any]) -> str:
    values = [
        location.get("country_code"),
        location.get("country_context"),
        flat.get("country_context"),
        flat.get("candidate_market"),
        flat.get("employer_market"),
        _mapping(flat.get("location")).get("normalized"),
        location.get("normalized"),
    ]
    folded = _fold(" ".join(str(value or "") for value in values))
    if re.search(r"\b(?:uy|uruguay|montevideo|canelones|maldonado)\b", folded):
        return "Uruguay"
    if re.search(r"\b(?:ar|argentina|buenos aires|caba|gba|amba)\b", folded):
        return "Argentina"
    if re.search(r"\b(?:us|usa|united states|estados unidos)\b", folded):
        return "Estados Unidos"
    if re.search(r"\b(?:es|spain|espana|españa)\b", folded):
        return "España"
    return ""


def _location_modality_label(
    location: Mapping[str, Any],
    job_profile: Mapping[str, Any],
    flat_location: Mapping[str, Any],
) -> str:
    parts: List[str] = []
    for value in (location.get("normalized"), flat_location.get("normalized"), location.get("raw"), flat_location.get("raw")):
        clean = _clean_display_text(value)
        if clean and not _is_country_only(clean):
            parts.append(clean)
            break

    modality = _clean_display_text(job_profile.get("work_modality"))
    if not modality:
        if location.get("hybrid_allowed") or flat_location.get("hybrid_allowed"):
            modality = "híbrido"
        elif location.get("remote_allowed") or flat_location.get("remote_allowed"):
            modality = "remoto"
        elif location.get("onsite_required"):
            modality = "presencial"
    modality = _human_modality(modality)
    if modality:
        parts.append(modality)
    return ", ".join(_dedupe_display_items(parts))


def _human_modality(value: str) -> str:
    folded = _fold(value)
    if folded == "hybrid":
        return "híbrido"
    if folded == "remote":
        return "remoto"
    if folded == "onsite":
        return "presencial"
    return value


def _is_country_only(value: str) -> bool:
    return _fold(value) in {"uy", "uruguay", "uruguay uy", "ar", "argentina", "us", "usa", "es", "espana", "españa"}


def _what_to_search(role_title: str, summary: str) -> str:
    clean = _clean_display_text(summary)
    if clean and not _looks_internal(clean) and not _looks_meta_or_process(clean):
        return clean
    if role_title:
        return f"Candidatos alineados al rol {role_title}, revisando primero indispensables y luego diferenciales."
    return "Candidatos alineados a la búsqueda recibida, separando requisitos, descartes y dudas para revisión."


def _display_questions(
    job_intelligence: Mapping[str, Any],
    blockers: List[str],
    search_strategy: Mapping[str, Any],
) -> List[str]:
    questions = _texts(job_intelligence.get("company_clarification_questions"))
    questions += _texts(job_intelligence.get("missing_information"))
    if any("credencial" in _fold(blocker) for blocker in blockers):
        questions.append("¿Qué credenciales exactas son requeridas?")

    acronyms = _unknown_acronyms(_texts(search_strategy.get("search_terms")) + _texts(search_strategy.get("semantic_terms")))
    for acronym in acronyms:
        questions.append(f"¿Qué significa {acronym} y cómo se valida?")

    output: List[str] = []
    seen_topics: set[str] = set()
    for item in _dedupe_display_items(questions):
        clean = _clean_display_text(item)
        if not clean or "?" not in clean or _looks_candidate_interview_question(clean):
            continue
        topic = _question_topic(clean)
        if topic and topic in seen_topics:
            continue
        if topic:
            seen_topics.add(topic)
        output.append(clean)
    return output[:8]


def _unknown_acronyms(items: Iterable[str]) -> List[str]:
    acronyms: List[str] = []
    for item in items:
        for match in re.findall(r"\b[A-ZÁÉÍÓÚÑ]{2,6}\b", str(item or "")):
            if match not in KNOWN_ACRONYMS:
                acronyms.append(match)
    return _dedupe_display_items(acronyms)[:3]


def _looks_candidate_interview_question(value: str) -> bool:
    folded = _fold(value)
    return bool(
        re.search(
            r"\b(?:tenes|tenias|contanos|cuentanos|podes|podrias|como\s+(?:llevas|evaluas|documentas|estructuras|implementas|gestionas|coordinas|alineas)|"
            r"usaste|usabas|usarias|reclutaste|trabajaste|manejaste|lideraste|mediste|lograste|resolviste)\b",
            folded,
        )
    )


def _question_topic(value: str) -> str:
    folded = _fold(value)
    if re.search(r"\b(?:modalidad|ubicacion|ciudad|zona|remoto|hibrido|presencial)\b", folded):
        return "location_modality"
    if re.search(r"\b(?:anos|años|experiencia|minima|minimo)\b", folded):
        return "experience"
    if re.search(r"\b(?:credencial|titulo|formacion|certificacion|habilitante)\b", folded):
        return "credentials"
    if re.search(r"\b(?:industria|sector|mercado|cliente)\b", folded):
        return "industry"
    return ""


def _tie_breakers(preferred: List[str], nice_to_have: List[str], industries: List[str]) -> List[str]:
    grounded = nice_to_have + preferred + industries
    return _dedupe_display_items(grounded, limit=6)


def _search_concepts(
    role_title: str,
    search_strategy: Mapping[str, Any],
    job_profile: Mapping[str, Any],
    must_have: List[str],
    preferred: List[str],
    nice_to_have: List[str],
) -> List[str]:
    candidates = (
        [role_title, _role_head_concept(role_title)]
        + _texts(search_strategy.get("target_titles"))
        + _texts(search_strategy.get("search_terms"))
        + _texts(search_strategy.get("semantic_terms"))
        + _texts(job_profile.get("primary_industries"))
        + _concepts_from_requirements(must_have + preferred + nice_to_have)
    )
    output: List[str] = []
    for item in candidates:
        clean = _clean_search_concept(item)
        if clean:
            output.append(clean)
    return _dedupe_display_items(output, limit=14)


def _role_head_concept(role_title: str) -> str:
    clean = _clean_display_text(role_title)
    clean = re.sub(r"\brecibid[oa]s?\b", "", clean, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip(" -:.,;")
    return clean


def _display_role_title(value: Any) -> str:
    clean = _clean_display_text(value)
    if clean and not re.search(r"[A-ZÁÉÍÓÚÑ]", clean):
        return _capitalize_first(clean)
    return clean


def _concepts_from_requirements(items: Iterable[str]) -> List[str]:
    concepts: List[str] = []
    for item in items:
        folded = _fold(item)
        clean = _clean_display_text(item)
        if "motor" in folded:
            concepts.append("motores de fuerza" if "fuerza" in folded else "diseño de motores")
        if "disenador" in folded or "diseñador" in clean.lower():
            concepts.append("diseño de motores")
        if "coordinar" in folded or "coordinacion" in folded:
            concepts.append("coordinación de equipo")
        if "gerencia" in folded:
            concepts.append("gerencia")
        if "hunting" in folded:
            concepts.append("hunting")
        if "entrevista" in folded and "competencia" in folded:
            concepts.append("entrevistas por competencias")
        if "hiring manager" in folded:
            concepts.append("hiring managers")
    return concepts


def _clean_search_concept(value: Any) -> str:
    clean = _clean_display_text(value)
    if not clean or _blocker_from_text(clean) or _looks_meta_or_process(clean):
        return ""
    clean = re.sub(
        r"^(?:experiencia\s+(?:en|con)|experiencia\s+realizando|conocimiento(?:s)?\s+de|manejo\s+de|dominio\s+de)\s+",
        "",
        clean,
        flags=re.I,
    )
    clean = re.sub(r"\bexperiencia\s+rn\b", "experiencia en", clean, flags=re.I)
    clean = _clean_display_text(clean)
    if not clean or _looks_like_missing_placeholder(clean):
        return ""
    words = clean.split()
    if len(words) > 7 or (len(words) > 5 and re.search(r"[.;:]", str(value))):
        return ""
    return clean


def _readiness(readiness: Mapping[str, Any], flat: Mapping[str, Any]) -> Dict[str, str]:
    code = _clean_display_text(readiness.get("status"))
    if not code:
        code = "usable_with_warnings" if _texts(flat.get("warnings")) else "ready"
    if code not in READY_LABELS:
        code = "usable_with_warnings"
    label, severity = READY_LABELS[code]
    return {"code": code, "label": label, "severity": severity}


def _blocker_from_text(value: Any) -> str:
    clean = _clean_display_text(value)
    if not clean:
        return ""
    folded = _fold(clean)
    if re.search(r"\binutil\s+presentarse\b", folded):
        if "credencial" in folded:
            return "No avanzar sin credenciales requeridas"
        return _capitalize_first(re.sub(r"^.*?\binutil\s+presentarse\b\s*", "No avanzar ", clean, flags=re.I))
    if re.search(r"\bno\s+presentarse\b", folded):
        return _capitalize_first(re.sub(r"^.*?\bno\s+presentarse\b\s*", "No avanzar ", clean, flags=re.I))
    if re.search(r"\bno\s+avanzar\b", folded):
        return _capitalize_first(re.sub(r"^.*?\bno\s+avanzar\b\s*", "No avanzar ", clean, flags=re.I))
    return ""


def _clean_display_text(value: Any) -> str:
    clean = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    clean = re.sub(r"\s+", " ", clean).strip(" -:.,;\t\r\n")
    if not clean or _looks_internal(clean) or _looks_like_missing_placeholder(clean):
        return ""
    return clean


def _looks_internal(value: str) -> bool:
    folded = _fold(value)
    if re.match(r"^(?:search_readiness|low_confidence|ai_schema|ai_provider|fallback)(?:[_:][a-z0-9_:-]+)?$", folded):
        return True
    if re.search(r"(?:source_text_|source_span_missing|span_missing|debug_placeholder|internal_diagnostic)", folded):
        return True
    return bool(re.match(r"^[a-z][a-z0-9]+(?:_[a-z0-9]+)+$", folded))


def _looks_like_missing_placeholder(value: str) -> bool:
    folded = _fold(value)
    return folded in {
        "",
        "sin especificar",
        "no especificado",
        "no especificada",
        "no indicado",
        "no indicada",
        "no informado",
        "no informada",
        "unspecified",
    }


def _looks_meta_or_process(value: str) -> bool:
    folded = _fold(value)
    return bool(
        re.search(
            r"\b(?:schema fail|no fallar schema|no schema fail|mantener ok true|generar recruiter questions|"
            r"devolver preguntas|no inventar anos|no inventar años|salir baja confianza|input es escaso|"
            r"evaluacion considerara|se evaluara durante entrevista|no deben desplazar)\b",
            folded,
        )
    )


def _dedupe_display_items(items: Iterable[str], limit: int = 0) -> List[str]:
    output: List[str] = []
    keys: List[str] = []
    for item in items:
        clean = _clean_display_text(item)
        if not clean:
            continue
        key = _concept_key(clean)
        if key in keys:
            continue
        replace_index = None
        skip = False
        for index, existing_key in enumerate(keys):
            if len(key) >= 5 and len(existing_key) >= 5 and (key in existing_key or existing_key in key):
                if len(clean) > len(output[index]):
                    replace_index = index
                else:
                    skip = True
                break
        if skip:
            continue
        if replace_index is not None:
            output[replace_index] = clean
            keys[replace_index] = key
            continue
        output.append(clean)
        keys.append(key)
    return output[:limit] if limit > 0 else output


def _concept_key(value: str) -> str:
    folded = _fold(value)
    folded = re.sub(r"\b(?:experiencia|amplia|minimo|minima|anos|años|de|en|con|para|un|una|grupo|equipo)\b", " ", folded)
    folded = re.sub(r"\brn\b", " en ", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    return folded


def _capitalize_first(value: str) -> str:
    clean = _clean_display_text(value)
    if not clean:
        return ""
    return clean[0].upper() + clean[1:]


def _fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
