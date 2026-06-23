"""Canonical Job Intelligence normalization.

This layer owns post-AI criterion identity, atomicity, recruiter-question
references, and search-vs-job-context separation. It does not perform a second
AI pass and it does not decide candidate ranking.
"""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from app.normalization.precision_questions import ensure_precision_contract


REVIEW_PENDING = "pending_recruiter_confirmation"
SEARCH_PRECISION = "search_precision"
JOB_CONFIGURATION = "job_configuration"


def canonicalize_job_intelligence(payload: Mapping[str, Any], *, source_text: str = "") -> Dict[str, Any]:
    """Return canonical, referentially coherent Job Intelligence."""

    output: Dict[str, Any] = copy.deepcopy(dict(payload))
    _apply_professional_grade(output, source_text=source_text)
    requirements, job_context = _extract_non_search_job_context(_mapping(output.get("requirements")))
    output["requirements"] = requirements
    if job_context:
        output["job_context"] = _merge_job_context(output.get("job_context", {}), job_context)
    output["requirements"] = _canonical_requirements(output["requirements"], output)
    output = _sanitize_search_strategy_specificity(output)
    output["company_clarification_questions"] = _canonical_question_registry(output)
    _link_criteria_to_questions(output)
    output["search_readiness"] = _canonical_readiness(output.get("search_readiness", {}), output["requirements"])
    return output


def _canonical_requirements(requirements: Mapping[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    output = dict(requirements)
    output["blockers"] = _remove_blockers_that_are_unresolved_positive_criteria(output)

    selected: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for bucket in ("must_have", "should_have", "nice_to_have", "credentials", "soft_competencies"):
        for item in output.get(bucket, []) or []:
            if not isinstance(item, Mapping):
                continue
            for atomic in _atomic_criteria_for_item(item, bucket, payload):
                key = _criterion_key(atomic)
                if not key:
                    continue
                record = {"bucket": _bucket_for_item(atomic, bucket), "item": atomic, "key": key}
                if key not in selected:
                    selected[key] = record
                    order.append(key)
                    continue
                selected[key] = _merge_records(selected[key], record)

    _drop_redundant_aggregates(selected, order)

    bucketed: Dict[str, List[Dict[str, Any]]] = {
        "must_have": [],
        "should_have": [],
        "nice_to_have": [],
        "credentials": [],
        "soft_competencies": [],
    }
    used_ids: set[str] = set()
    key_to_id: Dict[str, str] = {}
    for key in order:
        record = selected.get(key)
        if not record:
            continue
        item = dict(record["item"])
        criterion_id = key_to_id.get(key) or _stable_criterion_id(key, used_ids)
        key_to_id[key] = criterion_id
        item["criterion_id"] = criterion_id
        item["canonical_key"] = key
        item["hard_filter_candidate"] = str(item.get("importance", "")) == "must_have"
        if str(record["bucket"]) == "soft_competencies":
            item["hard_filter_candidate"] = False
        item["hard_filter_approved"] = bool(item.get("hard_filter_approved") is True and item["hard_filter_candidate"])
        if item.get("precision_status") == "needs_clarification":
            item.setdefault("review_status", REVIEW_PENDING)
        else:
            item.pop("review_status", None)
        bucketed[str(record["bucket"])].append(item)

    for key in bucketed:
        output[key] = bucketed[key]
    return output


def _atomic_criteria_for_item(item: Mapping[str, Any], bucket: str, payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    base = dict(item)
    text = _clean_text(base.get("text") or base.get("source_text"))
    source = _clean_text(base.get("source_text") or text)
    combined = f"{source} {text}".strip()
    if not text or _non_search_context_kind(combined):
        return []

    atoms: List[Dict[str, Any]] = []
    role = _role_noun(payload)
    precision_signal = _has_precision_signal(base)

    professional_grade = _professional_grade(combined)
    if professional_grade and precision_signal:
        atoms.append(
            _atom(
                base,
                text=professional_grade,
                source_text=professional_grade,
                missing_dimensions=["equivalence", "level", "evidence"],
                clarification_question=_best_question(base, ("oficial", "categoria", "categoría", "equivalencia", "evidencia")),
                canonical_kind="professional_grade",
            )
        )

    if _mentions_demonstrable_experience(combined) and precision_signal:
        experience_text = f"Experiencia demostrable como {role}" if role else "Experiencia demostrable"
        atoms.append(
            _atom(
                base,
                text=experience_text,
                source_text=_source_fragment(combined, "experiencia demostrable") or experience_text,
                missing_dimensions=["duration", "evidence"],
                clarification_question=_best_question(base, ("años", "anos", "evidencia", "experiencia")),
                canonical_kind="experience",
            )
        )

    repair_scope = _todo_tipo_scope(combined)
    if repair_scope and precision_signal:
        atoms.append(
            _atom(
                base,
                text=repair_scope,
                source_text=_source_fragment(combined, "todo tipo") or repair_scope,
                missing_dimensions=["scope"],
                clarification_question=_best_question(base, ("tipo", "alcance", "scope", "reparaciones")),
                canonical_kind="technical_scope",
            )
        )

    if _is_driving_license_text(combined) and (
        precision_signal
        and ("license_category" in list(base.get("missing_dimensions", []) or []) or not _driving_license_category(combined))
    ):
        atoms.append(
            _atom(
                base,
                text=_generic_driving_license_text(combined),
                source_text=_generic_driving_license_text(combined),
                missing_dimensions=["license_category"],
                clarification_question=_best_question(base, ("licencia", "libreta", "carnet", "categoria", "categoría")),
                canonical_kind="driving_license",
            )
        )

    if _is_legal_documentation_text(combined) and precision_signal:
        atoms.append(
            _atom(
                base,
                text="Papeles en regla" if "papeles" in _fold(combined) else "Documentación en regla",
                source_text=text,
                missing_dimensions=["legal_documentation"],
                clarification_question=_best_question(base, ("documentacion", "documentación", "papeles", "legal")),
                canonical_kind="legal_documentation",
            )
        )

    if len(atoms) >= 2 and _dimensions_cover(base, atoms):
        return atoms
    if atoms and _is_redundant_component(base, atoms):
        return atoms

    base["text"] = text
    base["source_text"] = source
    base["importance"] = str(base.get("importance") or _importance_from_bucket(bucket))
    base["precision_status"] = str(base.get("precision_status") or "precise")
    base["missing_dimensions"] = _unique(str(value) for value in base.get("missing_dimensions", []) or [])
    if base["precision_status"] != "needs_clarification":
        base["missing_dimensions"] = []
        base["clarification_question"] = None
    return [base]


def _atom(
    base: Mapping[str, Any],
    *,
    text: str,
    source_text: str,
    missing_dimensions: Iterable[str],
    clarification_question: str,
    canonical_kind: str,
) -> Dict[str, Any]:
    item = dict(base)
    item["text"] = _clean_text(text)
    item["source_text"] = _clean_text(source_text) or item["text"]
    item["canonical_kind"] = canonical_kind
    item["precision_status"] = "needs_clarification"
    item["missing_dimensions"] = _unique(missing_dimensions)
    item["clarification_question"] = clarification_question or _clean_text(base.get("clarification_question"))
    item["hard_filter_approved"] = False
    return item


def _merge_records(existing: Mapping[str, Any], candidate: Mapping[str, Any]) -> Dict[str, Any]:
    existing_item = dict(existing.get("item", {}))
    candidate_item = dict(candidate.get("item", {}))
    primary, secondary = existing_item, candidate_item
    bucket = str(existing.get("bucket") or candidate.get("bucket") or "should_have")
    if _importance_rank(str(candidate_item.get("importance"))) < _importance_rank(str(existing_item.get("importance"))):
        primary, secondary = candidate_item, existing_item
        bucket = str(candidate.get("bucket") or existing.get("bucket") or "should_have")

    merged = dict(primary)
    merged["missing_dimensions"] = _unique(
        list(primary.get("missing_dimensions", []) or []) + list(secondary.get("missing_dimensions", []) or [])
    )
    if primary.get("precision_status") == "needs_clarification" or secondary.get("precision_status") == "needs_clarification":
        merged["precision_status"] = "needs_clarification"
        merged["clarification_question"] = primary.get("clarification_question") or secondary.get("clarification_question")
    return {"bucket": bucket, "item": merged, "key": existing.get("key") or candidate.get("key")}


def _canonical_question_registry(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for bucket, item in _iter_criteria(_mapping(payload.get("requirements"))):
        if item.get("precision_status") != "needs_clarification":
            continue
        question = _clean_text(item.get("clarification_question"))
        if not question or _looks_candidate_question(question):
            continue
        dimensions = _unique(str(value) for value in item.get("missing_dimensions", []) or [])
        concept = _question_concept(question) or _criterion_key(item)
        key = _question_key("hiring_company", SEARCH_PRECISION, concept, dimensions, question)
        record = {
            "question_id": _stable_question_id(key),
            "id": _stable_question_id(key),
            "question": question,
            "audience": "hiring_company",
            "asked_to": "hiring_company",
            "category": SEARCH_PRECISION,
            "criterion_refs": [str(item.get("criterion_id"))],
            "related_fields": [f"requirements.{bucket}"],
            "missing_dimensions": dimensions,
            "blocking_level": _blocking_level(item, bucket),
        }
        _store_question_record(records, order, key, record)

    existing_items = list(payload.get("company_clarification_questions", []) or [])
    for item in existing_items:
        if not isinstance(item, Mapping):
            question = _clean_text(item)
            if not question:
                continue
            item = {"question": question}
        if _question_audience(item) != "hiring_company":
            continue
        question = _clean_text(item.get("question") or item.get("suggested_question"))
        if not question or _looks_candidate_question(question):
            continue
        category = str(item.get("category") or _question_category(question)).strip() or SEARCH_PRECISION
        dimensions = _unique(str(value) for value in item.get("missing_dimensions", []) or [])
        refs = _unique(str(value) for value in item.get("criterion_refs", []) or [])
        concept = str(item.get("concept_key") or _question_concept(question)).strip()
        key = _question_key("hiring_company", category, concept, dimensions, question)
        record = _question_record(item, key, question, category, dimensions, refs)
        _store_question_record(records, order, key, record)

    return [records[key] for key in order]


def _link_criteria_to_questions(payload: Dict[str, Any]) -> None:
    by_ref: Dict[str, Dict[str, Any]] = {}
    for question in payload.get("company_clarification_questions", []) or []:
        if not isinstance(question, Mapping):
            continue
        for ref in question.get("criterion_refs", []) or []:
            by_ref[str(ref)] = dict(question)

    requirements = _mapping(payload.get("requirements"))
    for _, item in _iter_criteria(requirements):
        if item.get("precision_status") == "needs_clarification":
            question = by_ref.get(str(item.get("criterion_id")))
            if question:
                item["clarification_question_id"] = str(question.get("question_id") or question.get("id") or "")
                item["clarification_question"] = str(question.get("question") or item.get("clarification_question") or "")
                item["review_status"] = REVIEW_PENDING
            else:
                item["clarification_question_id"] = ""
                item.setdefault("review_status", REVIEW_PENDING)
        else:
            item["clarification_question"] = None
            item["clarification_question_id"] = ""
            item.pop("review_status", None)


def _canonical_readiness(readiness: Any, requirements: Mapping[str, Any]) -> Dict[str, Any]:
    output = dict(readiness) if isinstance(readiness, Mapping) else {}
    if output.get("status") == "blocked_for_safety_or_technical_reason":
        return output

    unresolved = [
        item
        for bucket, item in _iter_criteria(requirements)
        if item.get("precision_status") == "needs_clarification"
        and (str(item.get("importance")) == "must_have" or bucket == "credentials" or "legal_documentation" in item.get("missing_dimensions", []))
    ]
    if unresolved:
        output["status"] = "insufficient_for_precise_search"
        output["severity"] = "warning"
        output["label"] = "Requiere confirmación antes de una búsqueda precisa"
        output["proceed_allowed"] = True
        output["recommended_action"] = "ask_company"
        output["recruiter_decision_required"] = True
        output["continued_with_missing_information"] = True
    output.setdefault("decision_options", ["continue_anyway", "answer_clarifying_questions", "ask_company", "use_manual_search", "cancel"])
    if "continue_anyway" not in output["decision_options"]:
        output["decision_options"].insert(0, "continue_anyway")
    return output


def _apply_professional_grade(output: Dict[str, Any], *, source_text: str) -> None:
    profile = dict(output.get("job_profile", {}) or {})
    grade = _professional_grade(source_text) or _professional_grade(output.get("requirements", {}))
    if grade:
        profile["professional_grade"] = grade
        if _fold(profile.get("seniority")) == _fold(grade):
            profile["seniority"] = None
    output["job_profile"] = profile


def _drop_redundant_aggregates(selected: Dict[str, Dict[str, Any]], order: List[str]) -> None:
    for key in list(order):
        record = selected.get(key)
        if not record:
            continue
        item = record.get("item", {})
        if not isinstance(item, Mapping):
            continue
        text = _fold(item.get("text"))
        if not re.search(r"\b(?: y | e | and )\b|,", f" {text} "):
            continue
        dimensions = set(item.get("missing_dimensions", []) or [])
        component_dimensions: set[str] = set()
        component_count = 0
        for other_key, other_record in selected.items():
            if other_key == key:
                continue
            other_item = other_record.get("item", {})
            if not isinstance(other_item, Mapping):
                continue
            if _component_text_related(str(other_item.get("text", "")), str(item.get("text", ""))):
                component_count += 1
                component_dimensions.update(other_item.get("missing_dimensions", []) or [])
        if component_count >= 2 and dimensions.issubset(component_dimensions):
            del selected[key]


def _extract_non_search_job_context(requirements: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    output = dict(requirements)
    context: Dict[str, List[str]] = {"employment_terms": [], "compensation": []}
    for bucket in ("must_have", "should_have", "nice_to_have", "credentials", "soft_competencies"):
        kept: List[Dict[str, Any]] = []
        for item in output.get(bucket, []) or []:
            if not isinstance(item, Mapping):
                continue
            kind = _non_search_context_kind(f"{item.get('source_text', '')} {item.get('text', '')}")
            if kind:
                context[kind].append(_clean_text(item.get("text") or item.get("source_text")))
                continue
            kept.append(dict(item))
        output[bucket] = kept
    return output, {key: _unique(value) for key, value in context.items() if _unique(value)}


def _remove_blockers_that_are_unresolved_positive_criteria(requirements: Mapping[str, Any]) -> List[str]:
    positives = [
        item
        for _, item in _iter_criteria(requirements)
        if _is_legal_documentation_text(f"{item.get('source_text', '')} {item.get('text', '')}")
    ]
    blockers: List[str] = []
    for blocker in requirements.get("blockers", []) or []:
        if positives and _is_legal_documentation_text(str(blocker)):
            continue
        blockers.append(str(blocker))
    return _unique(blockers)


def _sanitize_search_strategy_specificity(payload: Mapping[str, Any]) -> Dict[str, Any]:
    output = dict(payload)
    requirements = _mapping(output.get("requirements"))
    missing_license_category = any(
        "license_category" in item.get("missing_dimensions", [])
        and _is_driving_license_text(f"{item.get('source_text', '')} {item.get('text', '')}")
        for _, item in _iter_criteria(requirements)
    )
    strategy = dict(output.get("search_strategy", {}) or {})
    for key in ("target_titles", "search_terms", "semantic_terms", "negative_terms"):
        values = strategy.get(key)
        if not isinstance(values, list):
            continue
        cleaned: List[str] = []
        for value in values:
            text = _clean_text(value)
            if not text:
                continue
            if _non_search_context_kind(text):
                continue
            if missing_license_category and _is_invented_driving_license_category_term(text):
                continue
            cleaned.append(text)
        strategy[key] = _unique(cleaned)
    output["search_strategy"] = strategy
    return output


def _question_record(
    item: Mapping[str, Any],
    key: str,
    question: str,
    category: str,
    dimensions: List[str],
    refs: List[str],
) -> Dict[str, Any]:
    question_id = _stable_question_id(key)
    return {
        "question_id": question_id[:100],
        "id": question_id[:100],
        "question": question,
        "audience": "hiring_company",
        "asked_to": "hiring_company",
        "category": category,
        "criterion_refs": refs,
        "related_fields": list(item.get("related_fields", []) or []),
        "missing_dimensions": dimensions,
        "blocking_level": str(item.get("blocking_level") or "advisory"),
    }


def _store_question_record(records: Dict[str, Dict[str, Any]], order: List[str], key: str, record: Dict[str, Any]) -> None:
    if key not in records:
        records[key] = record
        order.append(key)
        return
    existing = records[key]
    existing["criterion_refs"] = _unique(list(existing.get("criterion_refs", [])) + list(record.get("criterion_refs", [])))
    existing["missing_dimensions"] = _unique(list(existing.get("missing_dimensions", [])) + list(record.get("missing_dimensions", [])))
    existing["related_fields"] = _unique(list(existing.get("related_fields", [])) + list(record.get("related_fields", [])))
    existing["blocking_level"] = _stronger_blocking_level(existing.get("blocking_level"), record.get("blocking_level"))


def _question_key(audience: str, category: str, concept: str, dimensions: Iterable[str], question: str) -> str:
    dims = ",".join(sorted(str(value) for value in dimensions if str(value)))
    return "|".join([audience, category, concept or _question_concept(question), dims])


def _question_concept(question: str) -> str:
    folded = _fold(question)
    if re.search(r"\b(?:licencia|libreta|carnet|conducir|categoria|categor[ií]a)\b", folded):
        return "credential:driving_license"
    if re.search(r"\b(?:papeles|documentaci[oó]n|documentos?|legal|regla)\b", folded):
        return "legal_documentation"
    if re.search(r"\b(?:reparaciones|alcance|scope|tipo)\b", folded):
        return "technical_scope"
    if re.search(r"\b(?:oficial|equivalencia|categoria|categor[ií]a)\b", folded):
        return "professional_grade"
    if re.search(r"\b(?:experiencia|a[nñ]os?|evidencia|demostrable)\b", folded):
        return "experience"
    return _slug(question)


def _question_category(question: str) -> str:
    folded = _fold(question)
    if re.search(r"\b(?:salario|sueldo|convenio|contrataci[oó]n|asalariad|aut[oó]nom|ubicaci[oó]n|modalidad|ciudad)\b", folded):
        return JOB_CONFIGURATION
    return SEARCH_PRECISION


def _blocking_level(item: Mapping[str, Any], bucket: str) -> str:
    if str(item.get("importance")) == "must_have" or bucket == "credentials":
        return "blocking"
    if bucket == "should_have":
        return "important"
    return "advisory"


def _stronger_blocking_level(left: Any, right: Any) -> str:
    rank = {"blocking": 0, "important": 1, "advisory": 2}
    left_value = str(left or "advisory")
    right_value = str(right or "advisory")
    return left_value if rank.get(left_value, 2) <= rank.get(right_value, 2) else right_value


def _criterion_key(item: Mapping[str, Any]) -> str:
    kind = str(item.get("canonical_kind") or "")
    text = f"{item.get('source_text', '')} {item.get('text', '')}"
    if kind:
        if kind == "driving_license":
            return "credential:driving_license"
        return f"{kind}:{_concept_text(item.get('text'))}"
    if _is_driving_license_text(text):
        category = _driving_license_category(text)
        if category and "license_category" not in list(item.get("missing_dimensions", []) or []):
            return f"credential:driving_license:{category}"
        return "credential:driving_license"
    if _is_legal_documentation_text(text):
        return "legal_documentation"
    return _concept_text(item.get("text")) or _slug(item.get("text"))


def _stable_criterion_id(key: str, used_ids: set[str]) -> str:
    base = f"crit_{_slug(key)}"[:72].strip("_")
    if not base or base == "crit":
        base = f"crit_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"
    candidate = base
    index = 2
    while candidate in used_ids:
        digest = hashlib.sha1(f"{key}:{index}".encode("utf-8")).hexdigest()[:6]
        candidate = f"{base[:65]}_{digest}"
        index += 1
    used_ids.add(candidate)
    return candidate


def _stable_question_id(key: str) -> str:
    slug = _slug(key)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    return f"q_{slug[:60]}_{digest}".strip("_")


def _iter_criteria(requirements: Mapping[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for bucket in ("must_have", "should_have", "nice_to_have", "credentials", "soft_competencies"):
        for item in requirements.get(bucket, []) or []:
            if isinstance(item, Mapping):
                yield bucket, item  # type: ignore[misc]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bucket_for_item(item: Mapping[str, Any], bucket: str) -> str:
    if bucket == "soft_competencies":
        item["hard_filter_candidate"] = False
        item["hard_filter_approved"] = False
        return "soft_competencies"
    if _is_interview_only_soft_competency(item):
        item["hard_filter_candidate"] = False
        item["hard_filter_approved"] = False
        return "soft_competencies"
    if bucket == "credentials":
        return "credentials"
    return _bucket_for_importance(str(item.get("importance") or _importance_from_bucket(bucket)))


def _bucket_for_importance(importance: str) -> str:
    if importance == "must_have":
        return "must_have"
    if importance in {"preferred", "strongly_preferred"}:
        return "should_have"
    if importance == "nice_to_have":
        return "nice_to_have"
    return "should_have"


def _importance_from_bucket(bucket: str) -> str:
    if bucket == "must_have":
        return "must_have"
    if bucket == "nice_to_have":
        return "nice_to_have"
    return "preferred"


def _importance_rank(importance: str) -> int:
    return {"must_have": 0, "strongly_preferred": 1, "preferred": 2, "nice_to_have": 3}.get(importance, 4)


def _has_precision_signal(item: Mapping[str, Any]) -> bool:
    return item.get("precision_status") == "needs_clarification" or bool(item.get("missing_dimensions"))


def _is_interview_only_soft_competency(item: Mapping[str, Any]) -> bool:
    combined = _fold(f"{item.get('source_text', '')} {item.get('text', '')} {item.get('evidence_expected', '')}")
    return "interview" in combined or "entrevista" in combined


def _dimensions_cover(base: Mapping[str, Any], atoms: Iterable[Mapping[str, Any]]) -> bool:
    base_dims = set(str(value) for value in base.get("missing_dimensions", []) or [])
    if not base_dims:
        return False
    atom_dims: set[str] = set()
    for atom in atoms:
        atom_dims.update(str(value) for value in atom.get("missing_dimensions", []) or [])
    return base_dims.issubset(atom_dims)


def _is_redundant_component(base: Mapping[str, Any], atoms: Iterable[Mapping[str, Any]]) -> bool:
    base_text = _fold(base.get("text"))
    atom_texts = [_fold(atom.get("text")) for atom in atoms]
    return any(atom_text and atom_text in base_text for atom_text in atom_texts)


def _component_text_related(component: str, aggregate: str) -> bool:
    component_key = _concept_text(component)
    aggregate_key = _concept_text(aggregate)
    return bool(component_key and aggregate_key and component_key in aggregate_key)


def _merge_dimensions(base: Mapping[str, Any], candidates: Iterable[str]) -> List[str]:
    return _unique(list(base.get("missing_dimensions", []) or []) + list(candidates))


def _best_question(base: Mapping[str, Any], tokens: Iterable[str]) -> str:
    question = _clean_text(base.get("clarification_question"))
    if not question:
        return ""
    folded = _fold(question)
    if any(_fold(token) in folded for token in tokens):
        return question
    return ""


def _role_noun(payload: Mapping[str, Any]) -> str:
    profile = _mapping(payload.get("job_profile"))
    title = _clean_text(profile.get("job_title") or profile.get("normalized_role_title"))
    folded = _fold(title)
    if "mecanico" in folded or "mecánico" in title.lower():
        return "mecánico"
    return _clean_text(title).lower()


def _professional_grade(value: Any) -> str:
    text = _fold(value)
    match = re.search(r"\boficial\s+de\s+(primera|segunda|tercera)\b", text)
    return f"Oficial de {match.group(1)}" if match else ""


def _mentions_demonstrable_experience(value: str) -> bool:
    folded = _fold(value)
    return bool(re.search(r"\bexperiencia\s+demostrable\b", folded))


def _todo_tipo_scope(value: str) -> str:
    clean = _clean_text(value)
    match = re.search(r"\btodo\s+tipo\s+de\s+([^.,;\n]+)", clean, re.I)
    if not match:
        return ""
    concept = re.sub(r"\s+y\s+con\s+.*$", "", match.group(1), flags=re.I).strip(" -:.,;")
    if not concept:
        return ""
    return f"Realizar todo tipo de {concept}"


def _source_fragment(value: str, anchor: str) -> str:
    clean = _clean_text(value)
    folded = _fold(clean)
    index = folded.find(_fold(anchor))
    if index < 0:
        return ""
    return clean[index:].split(",")[0].strip(" -:.,;")


def _is_driving_license_text(text: str) -> bool:
    folded = _fold(text)
    return bool(
        re.search(r"\b(?:licencia|libreta|carnet)\s+(?:de\s+)?conducir\b", folded)
        or re.search(r"\b(?:licencia|libreta|carnet)\s+(?:categor[ií]a\s+)?(?![yeou]\b)[a-z0-9]\b", folded)
    )


def _driving_license_category(text: str) -> str:
    folded = _fold(text)
    if re.search(r"(?:no\s+especificad[ao]|sin\s+especificar|categoria\s+no\s+especificada)", folded):
        return ""
    match = re.search(
        r"\b(?:licencia|libreta|carnet)(?:\s+de\s+conducir)?\s+(?:categor[ií]a\s+)?(?![yeou]\b)([a-z0-9])\b",
        folded,
    )
    return match.group(1).upper() if match else ""


def _generic_driving_license_text(text: str) -> str:
    folded = _fold(text)
    if "libreta" in folded:
        return "Libreta de conducir"
    if "licencia" in folded:
        return "Licencia de conducir"
    return "Carnet de conducir"


def _is_legal_documentation_text(text: str) -> bool:
    folded = _fold(text)
    return bool(
        re.search(r"\b(?:papeles|documentaci[oó]n|documentos?)\s+(?:en\s+)?regla\b", folded)
        or re.search(r"\bdocumentaci[oó]n\s+legal\b", folded)
    )


def _non_search_context_kind(text: str) -> str:
    folded = _fold(text)
    if re.search(r"\b(?:salario|sueldo|remuneracion|compensacion|jornal|segun\s+convenio|convenio)\b", folded):
        return "compensation"
    if re.search(
        r"\b(?:asalariad[oa]s?|autonom[oa]s?|relacion\s+de\s+dependencia|relacion\s+laboral|"
        r"tipo\s+de\s+contratacion|contratacion|freelance|monotributo)\b",
        folded,
    ):
        return "employment_terms"
    return ""


def _is_invented_driving_license_category_term(text: str) -> bool:
    return _is_driving_license_text(text) and bool(_driving_license_category(text))


def _merge_job_context(existing: Any, added: Mapping[str, List[str]]) -> Dict[str, List[str]]:
    output: Dict[str, List[str]] = {}
    if isinstance(existing, Mapping):
        for key, value in existing.items():
            if isinstance(value, list):
                output[str(key)] = _unique(str(item) for item in value)
    for key, value in added.items():
        output[str(key)] = _unique(output.get(str(key), []) + list(value))
    return output


def _question_audience(item: Mapping[str, Any]) -> str:
    audience = str(item.get("audience") or item.get("asked_to") or "hiring_company").strip()
    return "hiring_company" if audience in {"hiring_company", "recruiter", "company"} else audience


def _looks_candidate_question(question: str) -> bool:
    folded = _fold(question)
    return bool(
        re.search(
            r"\b(?:tienes|ten[eé]s|puedes\s+aportar|pod[eé]s\s+aportar|c[oó]mo\s+encajas|how\s+do\s+you|"
            r"ask\s+the\s+candidate|candidate\s+to\s+describe)\b",
            folded,
        )
    )


def _concept_text(value: Any) -> str:
    folded = _fold(value)
    folded = re.sub(r"\((?:categoria|categor[ií]a)\s+(?:no\s+especificada|sin\s+especificar)\)", " ", folded)
    folded = re.sub(r"[^a-z0-9áéíóúñü\s]+", " ", folded)
    folded = re.sub(
        r"\b(?:experiencia|demostrable|comprobable|con|en|de|como|para|un|una|el|la|que|haga)\b",
        " ",
        folded,
    )
    folded = re.sub(r"\s+", " ", folded).strip()
    return folded


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" -:.,;\t\r\n")


def _slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _fold(value)).strip("_")
    return slug or "item"


def _unique(items: Iterable[str]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for item in items:
        clean = _clean_text(item)
        key = _fold(clean)
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
    return output


def _fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
