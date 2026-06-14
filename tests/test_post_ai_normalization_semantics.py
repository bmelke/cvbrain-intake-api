import json
import unicodedata

import pytest

from app.mappers.job_intelligence_to_flat import derive_flat_compatibility
from app.normalization.requirement_importance import normalize_job_intelligence_requirements


def fold(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else str(value)
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def requirement_item(text, importance="must_have", source_text=None):
    return {
        "text": text,
        "source_text": source_text or text,
        "importance": importance,
        "explicit": True,
        "hard_filter_candidate": importance == "must_have",
        "hard_filter_approved": False,
    }


def minimal_job_intelligence(requirements):
    return {
        "schema_version": "cvbrain_job_intelligence_v1",
        "job_profile": {
            "job_title": "Sanitized Role",
            "normalized_role_title": "Sanitized Role",
            "role_family": "",
            "seniority": "",
            "summary": "Sanitized post-AI normalization fixture.",
            "primary_industries": [],
            "work_modality": "",
        },
        "location_intelligence": {
            "raw": "",
            "normalized": "",
            "country_code": "UY",
            "remote_allowed": None,
            "hybrid_allowed": None,
            "onsite_required": None,
            "country_context_mismatch": False,
            "hard_filter_candidate": False,
            "hard_filter_approved": False,
            "warnings": [],
        },
        "requirements": {
            "must_have": requirements.get("must_have", []),
            "should_have": requirements.get("should_have", []),
            "nice_to_have": requirements.get("nice_to_have", []),
            "credentials": requirements.get("credentials", []),
            "blockers": requirements.get("blockers", []),
            "experience": {"minimum_years": None, "seniority": ""},
            "soft_competencies": requirements.get("soft_competencies", []),
        },
        "search_strategy": {
            "target_titles": ["Sanitized Role"],
            "search_terms": ["Sanitized Role"],
            "semantic_terms": [],
            "negative_terms": [],
        },
        "missing_information": [],
        "company_clarification_questions": [],
        "candidate_screening_questions": [],
        "search_readiness": {
            "status": "usable_with_warnings",
            "proceed_allowed": True,
            "recommended_action": "continue_anyway",
            "recruiter_decision_required": False,
            "continued_with_missing_information": False,
            "recruiter_override_reason": None,
            "decision_options": ["continue_anyway", "use_manual_search", "cancel"],
        },
        "quality_control": {
            "warnings": [],
            "confidence": 0.82,
            "contains_candidate_data": False,
            "contains_candidate_pii": False,
        },
    }


def normalize_and_flatten(requirements, source_text=""):
    normalized = normalize_job_intelligence_requirements(
        minimal_job_intelligence(requirements),
        source_text=source_text,
    )
    flat = derive_flat_compatibility(normalized)
    return normalized, flat


def nested_texts(normalized, bucket):
    return [item["text"] for item in normalized["requirements"][bucket]]


def nested_credentials(normalized, importance):
    return [
        item["text"]
        for item in normalized["requirements"]["credentials"]
        if item.get("importance") == importance
    ]


def all_requirement_and_credential_text(normalized, flat):
    nested = []
    for bucket in ("must_have", "should_have", "nice_to_have", "credentials"):
        nested.extend(nested_texts(normalized, bucket))
    flat_values = (
        flat["must_have"]
        + flat["should_have"]
        + flat["nice_to_have"]
        + flat["credentials"]["required"]
        + flat["credentials"]["preferred"]
    )
    return fold(nested + flat_values)


def assert_not_in_requirements_or_credentials(normalized, flat, *terms):
    haystack = all_requirement_and_credential_text(normalized, flat)
    for term in terms:
        assert fold(term) not in haystack


def assert_blockers_contain(normalized, flat, *terms):
    blockers = fold(normalized["requirements"]["blockers"] + flat["blockers"])
    for term in terms:
        assert fold(term) in blockers


def assert_flat_matches_nested_requirements(normalized, flat):
    assert flat["must_have"] == nested_texts(normalized, "must_have")
    assert flat["should_have"] == nested_texts(normalized, "should_have")
    assert flat["nice_to_have"] == nested_texts(normalized, "nice_to_have")
    assert flat["blockers"] == normalized["requirements"]["blockers"]
    assert flat["credentials"]["required"] == nested_credentials(normalized, "must_have")
    assert flat["credentials"]["preferred"] == [
        item["text"]
        for item in normalized["requirements"]["credentials"]
        if item.get("importance") != "must_have"
    ]


def all_user_facing_text(normalized, flat):
    return fold(
        [
            flat["role_title"],
            flat["summary"],
            flat["must_have"],
            flat["should_have"],
            flat["nice_to_have"],
            flat["blockers"],
            flat["credentials"],
            flat["warnings"],
            flat["recruiter_questions"],
            normalized["requirements"]["must_have"],
            normalized["requirements"]["should_have"],
            normalized["requirements"]["nice_to_have"],
            normalized["requirements"]["credentials"],
            normalized["requirements"]["blockers"],
            normalized["requirements"].get("soft_competencies", []),
            normalized.get("missing_information", []),
            normalized.get("company_clarification_questions", []),
            normalized.get("candidate_screening_questions", []),
            normalized.get("quality_control", {}).get("warnings", []),
        ]
    )


def test_busqueda_001_blockers_and_modifier_only_fragments_are_removed_from_requirements():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia real en áreas legales corporativas"),
                requirement_item(
                    "No avanzar perfiles puramente litigiosos sin experiencia corporativa ni perfiles junior de asesoría legal"
                ),
                requirement_item("Pero no debe usarse como filtro excluyente"),
            ],
            "nice_to_have": [
                requirement_item("Inglés jurídico será un plus", "nice_to_have"),
            ],
        },
        source_text=(
            "Inglés jurídico será un plus, pero no debe usarse como filtro excluyente. "
            "No avanzar perfiles puramente litigiosos sin experiencia corporativa ni perfiles junior de asesoría legal."
        ),
    )

    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "No avanzar perfiles puramente litigiosos",
        "perfiles junior de asesoría legal",
        "Pero no debe usarse como filtro excluyente",
    )
    assert_blockers_contain(normalized, flat, "litigiosos", "experiencia corporativa", "junior", "asesoría legal")
    assert "ingles juridico" in fold(flat["nice_to_have"])
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_008_no_excluyente_and_no_avanzar_retail_exclusions_are_not_requirements():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia vendiendo a empresas"),
                requirement_item("No excluyente"),
            ],
            "nice_to_have": [
                requirement_item("No avanzar vendedores de mostrador"),
                requirement_item("Consumo masivo o retail sin experiencia B2B"),
            ],
        },
        source_text=(
            "Inglés técnico será valorable, no excluyente. "
            "No avanzar vendedores de mostrador, consumo masivo o retail sin experiencia B2B."
        ),
    )

    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "No excluyente",
        "No avanzar vendedores de mostrador",
        "Consumo masivo o retail sin experiencia B2B",
    )
    assert_blockers_contain(normalized, flat, "vendedores de mostrador", "consumo masivo", "retail", "B2B")
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_027_no_avanzar_and_no_es_excluyente_do_not_leak_to_requirements():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia comercial vinculada a salud o visita médica"),
                requirement_item("Pero no es excluyente salvo que el cliente indique movilidad propia"),
            ],
            "nice_to_have": [
                requirement_item("Libreta de conducir suma", "nice_to_have"),
                requirement_item("No avanzar vendedores sin contacto con el sector salud", "nice_to_have"),
            ],
            "credentials": [
                requirement_item("Libreta de conducir suma", "nice_to_have"),
            ],
        },
        source_text=(
            "Libreta de conducir suma, pero no es excluyente salvo que el cliente indique movilidad propia. "
            "No avanzar vendedores sin contacto con el sector salud."
        ),
    )

    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "No avanzar vendedores sin contacto",
        "Pero no es excluyente salvo",
    )
    assert_blockers_contain(normalized, flat, "vendedores", "contacto", "sector salud")
    assert "libreta de conducir" in fold(flat["nice_to_have"])
    assert "libreta de conducir" not in fold(flat["credentials"]["preferred"])
    assert "libreta de conducir" not in fold(flat["credentials"]["required"])
    assert_flat_matches_nested_requirements(normalized, flat)


@pytest.mark.parametrize(
    ("required_credential", "blocker_text", "expected_blocker_terms"),
    [
        (
            "Título habilitante",
            "No avanzar candidatos sin título habilitante ni administrativos de seguridad",
            ("candidatos", "título habilitante", "administrativos de seguridad"),
        ),
        (
            "Formación notarial",
            "No avanzar administrativos sin formación notarial",
            ("administrativos", "formación notarial"),
        ),
    ],
)
def test_busqueda_044_and_083_credentials_keep_required_title_but_drop_blockers(
    required_credential,
    blocker_text,
    expected_blocker_terms,
):
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item(f"Es excluyente contar con {required_credential.lower()}"),
            ],
            "should_have": [
                requirement_item(blocker_text, "preferred"),
            ],
            "credentials": [
                requirement_item(required_credential, "must_have"),
                requirement_item(blocker_text, "must_have"),
                requirement_item("Deseable", "preferred"),
            ],
        },
        source_text=f"Es excluyente contar con {required_credential.lower()}. {blocker_text}.",
    )

    assert fold(required_credential) in fold(flat["must_have"])
    assert fold(required_credential) not in fold(flat["credentials"]["required"])
    assert_not_in_requirements_or_credentials(normalized, flat, blocker_text, "Deseable")
    assert_blockers_contain(normalized, flat, *expected_blocker_terms)
    assert_flat_matches_nested_requirements(normalized, flat)


def test_naked_modifier_fragments_are_dropped_from_all_requirement_buckets_and_credentials():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("No excluyente"),
                requirement_item("Pero no debe usarse como filtro excluyente"),
                requirement_item("Pero no es requisito"),
                requirement_item("Pero no central"),
            ],
            "should_have": [
                requirement_item("Deseable", "preferred"),
            ],
            "credentials": [
                requirement_item("Deseable", "preferred"),
                requirement_item("Pero no es requisito", "preferred"),
            ],
        }
    )

    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "No excluyente",
        "Pero no debe usarse como filtro excluyente",
        "Pero no es requisito",
        "Pero no central",
        "Deseable",
    )
    assert_flat_matches_nested_requirements(normalized, flat)


def test_local_negative_modifier_wins_over_desirable_section_default():
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item("Inglés no excluyente", "preferred"),
                requirement_item("Francés pero no debe usarse as filtro", "preferred"),
                requirement_item("CRM es deseable", "preferred"),
            ],
            "credentials": [
                requirement_item("Libreta de conducir no excluyente", "preferred"),
            ],
        }
    )

    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "Inglés",
        "no excluyente",
        "Francés",
        "no debe usarse as filtro",
        "Libreta de conducir",
    )
    assert flat["should_have"] == ["CRM"]
    assert flat["nice_to_have"] == []
    assert flat["credentials"]["preferred"] == []
    assert_flat_matches_nested_requirements(normalized, flat)


def test_generic_no_avanzar_a_ni_b_becomes_blocker_not_requirements():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia comercial consultiva"),
                requirement_item("No avanzar perfiles retail sin ventas B2B ni vendedores sin cartera corporativa"),
            ],
            "should_have": [
                requirement_item("Vendedores sin cartera corporativa", "preferred"),
            ],
        },
        source_text="No avanzar perfiles retail sin ventas B2B ni vendedores sin cartera corporativa.",
    )

    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "No avanzar perfiles retail",
        "Vendedores sin cartera corporativa",
    )
    assert_blockers_contain(normalized, flat, "retail", "ventas B2B", "vendedores", "cartera corporativa")
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_001_duplicate_management_position_requirement_is_kept_once():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Haber ocupado posiciones gerenciales en áreas legales corporativas"),
                requirement_item("Es excluyente haber ocupado posiciones gerenciales en áreas legales corporativas"),
            ],
            "should_have": [
                requirement_item("La persona deberá liderar", "preferred"),
                requirement_item("Se requiere base técnica en", "preferred"),
                requirement_item("Ni perfiles junior de asesoría legal", "preferred"),
            ],
        }
    )

    must = fold(flat["must_have"])
    assert must.count("posiciones gerenciales en areas legales corporativas") == 1
    assert "es excluyente haber ocupado" not in must
    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "La persona deberá liderar",
        "Se requiere base técnica en",
        "Ni perfiles junior",
    )
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_008_duplicate_cloud_security_and_infra_concepts_are_collapsed():
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item("Conocimientos de cloud", "preferred"),
                requirement_item("Conocimiento de ciberseguridad", "preferred"),
                requirement_item("Manejo de servicios gestionados", "preferred"),
                requirement_item("Conocimientos de infraestructura", "preferred"),
            ],
            "nice_to_have": [
                requirement_item("Conocimiento de cloud será un plus", "nice_to_have"),
                requirement_item("Conocimientos de ciberseguridad", "nice_to_have"),
                requirement_item("Servicios gestionados", "nice_to_have"),
                requirement_item("Infraestructura", "nice_to_have"),
            ],
        }
    )

    combined = fold(flat["should_have"] + flat["nice_to_have"])
    assert combined.count("cloud") == 1
    assert combined.count("ciberseguridad") == 1
    assert combined.count("servicios gestionados") == 1
    assert combined.count("infraestructura") == 1
    assert "cloud" in fold(flat["nice_to_have"])
    assert "cloud" not in fold(flat["should_have"])
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_084_duplicate_libretta_typo_and_mobility_requirement_is_collapsed():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Libretta y movilidad requerida"),
                requirement_item("Libreta y movilidad"),
            ],
        }
    )

    assert flat["must_have"] == ["Libreta y movilidad requerida"]
    assert "libretta" not in fold(flat["must_have"])
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_093_duplicate_required_driving_license_between_requirement_and_credential_is_collapsed():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Libreta de conducir requerida por traslados"),
            ],
            "credentials": [
                requirement_item("Libreta de conducir requerida por traslados", "must_have"),
            ],
        }
    )

    assert flat["must_have"] == ["Libreta de conducir requerida por traslados"]
    assert flat["credentials"]["required"] == []
    assert "libreta de conducir requerida por traslados" not in fold(flat["credentials"]["preferred"])
    assert_flat_matches_nested_requirements(normalized, flat)


def test_cleanup_preserves_legitimate_short_skill_tokens():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("SQL"),
                requirement_item("Git"),
                requirement_item("Docker"),
                requirement_item("Excel"),
            ],
        }
    )

    assert flat["must_have"] == ["SQL", "Git", "Docker", "Excel"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_016_ni_wordpress_fragment_is_blocker_not_should_have():
    blocker_source = "No avanzar maquetadores sin lógica frontend ni perfiles WordPress puros"
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia en aplicaciones web reales"),
                requirement_item("No solamente implementaciones WordPress sin desarrollo a medida"),
            ],
            "should_have": [
                requirement_item("Ni perfiles WordPress puros", "preferred", source_text=blocker_source),
            ],
        },
        source_text=blocker_source,
    )

    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "Ni perfiles WordPress puros",
        "No solamente implementaciones WordPress",
    )
    assert_blockers_contain(normalized, flat, "maquetadores", "lógica frontend", "WordPress", "centrados solo")
    assert_flat_matches_nested_requirements(normalized, flat)


@pytest.mark.parametrize(
    ("case_label", "fragment", "preserved_skill"),
    [
        ("BUSQUEDA_025", "Se requiere", "SQL"),
        ("BUSQUEDA_032", "Experiencia con", "Docker"),
        ("BUSQUEDA_055", "Conocimiento de", "Git"),
        ("BUSQUEDA_061", "Es excluyente", "Excel"),
        ("BUSQUEDA_061", "Experiencia en", "Excel"),
        ("BUSQUEDA_061", "Manejo de", "Excel"),
    ],
)
def test_prefix_only_orphan_fragments_are_dropped_but_short_skills_remain(
    case_label,
    fragment,
    preserved_skill,
):
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item(fragment),
                requirement_item(preserved_skill),
            ],
        }
    )

    assert case_label
    assert_not_in_requirements_or_credentials(normalized, flat, fragment)
    assert preserved_skill in flat["must_have"]
    assert_flat_matches_nested_requirements(normalized, flat)


@pytest.mark.parametrize("fragment", ["Experiencia", "Debe manejar"])
def test_remaining_orphan_requirement_artifacts_are_dropped(fragment):
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item(fragment),
                requirement_item("SQL"),
            ],
            "should_have": [
                requirement_item(fragment, "preferred"),
            ],
        }
    )

    assert_not_in_requirements_or_credentials(normalized, flat, fragment)
    assert flat["must_have"] == ["SQL"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_blocker_metadata_artifacts_are_dropped():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia comercial B2B"),
            ],
            "blockers": [
                "source_text_span_hint_not_provided",
                "hard_filter_candidate_as_written",
                "hard_filter_approved_as_written",
                "No avanzar perfiles sin experiencia comercial",
            ],
        }
    )

    assert flat["blockers"] == ["No avanzar perfiles sin experiencia comercial"]
    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "source_text_span_hint_not_provided",
        "hard_filter_candidate_as_written",
        "hard_filter_approved_as_written",
    )
    assert_flat_matches_nested_requirements(normalized, flat)


def test_source_text_span_missing_metadata_artifact_is_dropped_from_blockers_and_requirements():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Source_text_span_missing"),
                requirement_item("Experiencia comercial B2B"),
            ],
            "blockers": [
                "Source_text_span_missing",
                "No avanzar perfiles sin experiencia comercial",
            ],
        }
    )

    output = all_user_facing_text(normalized, flat)
    assert "source_text_span_missing" not in output
    assert flat["blockers"] == ["No avanzar perfiles sin experiencia comercial"]
    assert flat["must_have"] == ["Experiencia comercial B2B"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_source_text_span_missing_for_blocker_artifact_is_removed_from_user_facing_fields():
    payload = minimal_job_intelligence(
        {
            "must_have": [
                requirement_item("Source_text_span_missing_for_blocker_1"),
                requirement_item("Experiencia comercial B2B"),
            ],
            "blockers": [
                "Source_text_span_missing_for_blocker_1",
                "No avanzar perfiles sin experiencia comercial",
            ],
            "soft_competencies": [
                requirement_item("Source_text_span_missing_for_blocker_1", "preferred"),
            ],
        }
    )
    payload["quality_control"]["warnings"] = ["Source_text_span_missing_for_blocker_1"]
    payload["missing_information"] = [
        {
            "field": "Source_text_span_missing_for_blocker_1",
            "suggested_question": "Source_text_span_missing_for_blocker_1",
        }
    ]
    payload["company_clarification_questions"] = [
        {"question": "Source_text_span_missing_for_blocker_1"}
    ]

    normalized = normalize_job_intelligence_requirements(payload)
    flat = derive_flat_compatibility(normalized)

    output = all_user_facing_text(normalized, flat)
    assert "source_text_span_missing" not in output
    assert "for_blocker" not in output
    assert flat["blockers"] == ["No avanzar perfiles sin experiencia comercial"]
    assert flat["must_have"] == ["Experiencia comercial B2B"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_source_text_span_missing_from_rules_artifact_is_removed_from_nested_and_flat_blockers():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia operativa"),
            ],
            "blockers": [
                "Source_text_span_missing_from_rules",
                "No avanzar perfiles sin experiencia operativa",
            ],
        }
    )

    output = all_user_facing_text(normalized, flat)
    assert "source_text_span_missing" not in output
    assert "from_rules" not in output
    assert normalized["requirements"]["blockers"] == ["No avanzar perfiles sin experiencia operativa"]
    assert flat["blockers"] == ["No avanzar perfiles sin experiencia operativa"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_internal_metadata_artifact_class_is_removed_recursively_from_public_fields():
    payload = minimal_job_intelligence(
        {
            "must_have": [
                requirement_item("Source_text_classification_rationale_id_missing_or_not_applicable"),
                requirement_item("Experiencia operativa"),
            ],
            "blockers": [
                "Source_text_classification_rationale_id_missing_or_not_applicable",
                "No avanzar perfiles sin experiencia operativa",
            ],
            "soft_competencies": [
                requirement_item(
                    "Comunicación con clientes",
                    "preferred",
                    source_text="Source_text_classification_rationale_id_missing_or_not_applicable",
                ),
            ],
        }
    )
    payload["quality_control"]["warnings"] = ["debug_placeholder_source_text_missing"]
    payload["company_clarification_questions"] = [
        {"question": "Source_text_classification_rationale_id_missing_or_not_applicable"}
    ]

    normalized = normalize_job_intelligence_requirements(payload)
    flat = derive_flat_compatibility(normalized)

    output = all_user_facing_text(normalized, flat)
    assert "source_text_" not in output
    assert "missing_or_not_applicable" not in output
    assert "classification_rationale_id_missing" not in output
    assert flat["blockers"] == ["No avanzar perfiles sin experiencia operativa"]
    assert flat["must_have"] == ["Experiencia operativa"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_nested_negative_soft_competency_source_text_is_removed_and_becomes_blocker():
    blocker_source = "Criterio de no avanzar si solo tiene experiencia académica"
    normalized, flat = normalize_and_flatten(
        {
            "soft_competencies": [
                requirement_item("Criterio de no avanzar si solo tiene experiencia académica", "preferred"),
                requirement_item("No solo ejecución operativa", "preferred"),
                requirement_item("Ni perfiles junior", "preferred", source_text="No avanzar perfiles seniority bajo ni perfiles junior"),
                requirement_item("Comunicación con clientes", "preferred"),
            ],
        },
        source_text=blocker_source,
    )

    output = all_user_facing_text(normalized, flat)
    assert "criterio de no avanzar" not in output
    assert "no solo" not in output
    assert "ni perfiles junior" not in output
    assert "comunicacion con clientes" in output
    assert_blockers_contain(normalized, flat, "no avanzar", "experiencia académica", "centrados solo", "perfiles junior")
    assert_flat_matches_nested_requirements(normalized, flat)


def test_negative_blocker_fragment_is_removed_from_soft_competency_source_text():
    normalized, flat = normalize_and_flatten(
        {
            "soft_competencies": [
                requirement_item(
                    "Comunicación con clientes",
                    "preferred",
                    source_text="Comunicación con clientes ni perfiles comerciales sin experiencia en atención estructurada",
                ),
            ],
        }
    )

    output = all_user_facing_text(normalized, flat)
    assert "ni perfiles" not in output
    assert "sin experiencia en atencion estructurada" not in output
    assert "comunicacion con clientes" in output
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_050_ni_cobradores_fragment_is_blocker_not_must_have():
    blocker_source = "No avanzar cobradores sin experiencia corporativa ni cobradores solo de consumo individual"
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia en cobranzas corporativas"),
                requirement_item("Ni cobradores solo de consumo individual", source_text=blocker_source),
            ],
        },
        source_text=blocker_source,
    )

    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "Ni cobradores solo de consumo individual",
        "consumo individual",
    )
    assert_blockers_contain(normalized, flat, "cobradores", "experiencia corporativa", "consumo individual")
    assert_flat_matches_nested_requirements(normalized, flat)


def test_no_solo_and_no_solamente_qualification_clauses_are_not_must_have():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("No solo tareas administrativas"),
                requirement_item("No solamente soporte operativo"),
                requirement_item("Experiencia comercial B2B"),
            ],
        }
    )

    assert_not_in_requirements_or_credentials(
        normalized,
        flat,
        "No solo tareas administrativas",
        "No solamente soporte operativo",
    )
    assert flat["must_have"] == ["Experiencia comercial B2B"]
    assert_blockers_contain(normalized, flat, "centrados solo en tareas administrativas", "centrados solo en soporte operativo")
    assert_flat_matches_nested_requirements(normalized, flat)


def test_blocker_text_dedupes_repeated_no_avanzar_and_drops_naked_blocker():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia comercial B2B"),
            ],
            "blockers": [
                "No avanzar perfiles sin experiencia. No avanzar perfiles sin experiencia",
                "No avanzar",
            ],
        }
    )

    blockers = flat["blockers"]
    assert blockers == ["No avanzar perfiles sin experiencia"]
    assert fold(blockers).count("no avanzar") == 1
    assert "no avanzar" != fold(blockers[0]).strip(" .")
    assert_flat_matches_nested_requirements(normalized, flat)


@pytest.mark.parametrize(
    ("case_label", "bucket"),
    [
        ("BUSQUEDA_047", "must_have"),
        ("BUSQUEDA_048", "must_have"),
        ("BUSQUEDA_069", "nice_to_have"),
    ],
)
def test_naked_no_avanzar_requirement_is_dropped_without_creating_empty_blocker(case_label, bucket):
    requirements = {
        "must_have": [requirement_item("Experiencia comprobable")],
        bucket: [requirement_item("No avanzar", "nice_to_have" if bucket == "nice_to_have" else "must_have")],
    }
    normalized, flat = normalize_and_flatten(requirements)

    assert case_label
    assert_not_in_requirements_or_credentials(normalized, flat, "No avanzar")
    assert flat["blockers"] == []
    assert_flat_matches_nested_requirements(normalized, flat)


@pytest.mark.parametrize(
    ("case_label", "tail"),
    [
        ("BUSQUEDA_020", "Para coordinar operaciones de importación"),
        ("BUSQUEDA_072", "Para atención telefónica"),
    ],
)
def test_incomplete_para_phrase_tails_are_dropped(case_label, tail):
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item(tail, "preferred"),
                requirement_item("Inglés deseable", "preferred"),
            ],
        }
    )

    assert case_label
    assert_not_in_requirements_or_credentials(normalized, flat, tail)
    assert flat["should_have"] == ["Inglés"]
    assert_flat_matches_nested_requirements(normalized, flat)


@pytest.mark.parametrize(
    "fragment",
    [
        "La persona deberá haber trabajado con",
        "La persona será responsable",
        "La persona será responsable de",
        "SaaS o",
    ],
)
def test_incomplete_orphan_phrase_tails_and_dangling_connectors_are_dropped(fragment):
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item(fragment, "preferred"),
                requirement_item("SaaS", "preferred"),
            ],
        }
    )

    assert_not_in_requirements_or_credentials(normalized, flat, fragment)
    assert flat["should_have"] == ["SaaS"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_la_persona_debera_orphan_fragment_is_dropped_everywhere():
    normalized, flat = normalize_and_flatten(
        {
            "nice_to_have": [
                requirement_item("La persona deberá", "nice_to_have"),
                requirement_item("Excel deseable", "preferred"),
            ],
            "soft_competencies": [
                requirement_item("La persona deberá", "preferred"),
            ],
        }
    )

    output = all_user_facing_text(normalized, flat)
    assert "la persona debera" not in output
    assert flat["should_have"] == ["Excel"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_boilerplate_subject_prefix_is_removed_from_public_requirements():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("La persona deberá liderar pagos"),
                requirement_item("La persona deberá negociar condiciones"),
                requirement_item("La persona será responsable de salón"),
            ],
        }
    )

    assert flat["must_have"] == ["Liderar pagos", "Negociar condiciones", "Responsable de salón"]
    assert "la persona debera" not in all_user_facing_text(normalized, flat)
    assert "la persona sera responsable" not in all_user_facing_text(normalized, flat)
    assert_flat_matches_nested_requirements(normalized, flat)


@pytest.mark.parametrize(
    ("lead_sentence", "expected_requirement"),
    [
        (
            "Empresa digital busca UX/UI Designer con experiencia en producto",
            "Experiencia en producto",
        ),
        (
            "Industria alimenticia busca Especialista en Compras para gestionar proveedores",
            "Gestionar proveedores",
        ),
        (
            "Empresa de servicios busca Responsable de Atención al Cliente para liderar equipo multicanal",
            "Liderar equipo multicanal",
        ),
    ],
)
def test_recruiter_lead_title_context_sentence_is_split_into_actual_requirement(
    lead_sentence,
    expected_requirement,
):
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item(lead_sentence),
            ],
        }
    )

    assert flat["must_have"] == [expected_requirement]
    output = all_user_facing_text(normalized, flat)
    assert "busca ux/ui designer" not in output
    assert "busca especialista en compras" not in output
    assert "busca responsable de atencion al cliente" not in output
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_006_weak_preferences_stay_nice_to_have_after_source_normalization():
    source_text = (
        "Se valorará experiencia con TMS, WMS, Excel y tableros de indicadores. "
        "Libreta profesional puede sumar, pero no es requisito."
    )
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item("TMS", "preferred", source_text="Se valorará experiencia con TMS"),
                requirement_item("WMS", "preferred", source_text="Se valorará experiencia con WMS"),
                requirement_item("Excel", "preferred", source_text="Se valorará experiencia con Excel"),
                requirement_item(
                    "Tableros de indicadores",
                    "preferred",
                    source_text="Se valorará experiencia con tableros de indicadores",
                ),
            ],
            "must_have": [
                requirement_item(
                    "Libreta profesional",
                    "must_have",
                    source_text="Libreta profesional puede sumar, pero no es requisito",
                ),
            ],
        },
        source_text=source_text,
    )

    assert "tms" not in fold(flat["must_have"] + flat["should_have"])
    assert "wms" not in fold(flat["must_have"] + flat["should_have"])
    assert "excel" not in fold(flat["must_have"] + flat["should_have"])
    assert "tableros de indicadores" not in fold(flat["must_have"] + flat["should_have"])
    assert "libreta profesional" not in fold(flat["must_have"] + flat["should_have"])
    nice = fold(flat["nice_to_have"])
    for expected in ("tms", "wms", "excel", "tableros de indicadores", "libreta profesional"):
        assert expected in nice
    assert "libreta profesional" not in fold(flat["credentials"]["required"])
    assert_flat_matches_nested_requirements(normalized, flat)


def test_soft_parent_cue_inherits_to_every_comma_list_sibling():
    source_text = "Se valorará experiencia con TMS, WMS, Excel y tableros de indicadores."
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item("TMS", "preferred"),
                requirement_item("WMS", "preferred"),
                requirement_item("Excel", "preferred"),
                requirement_item("Tableros de indicadores", "preferred"),
            ],
        },
        source_text=source_text,
    )

    assert flat["must_have"] == []
    assert flat["should_have"] == []
    nice = fold(flat["nice_to_have"])
    for expected in ("tms", "wms", "excel", "tableros de indicadores"):
        assert expected in nice
    assert_flat_matches_nested_requirements(normalized, flat)


def test_soft_parent_cue_inherits_across_y_list_for_analytics_tools():
    source_text = "Se valorará experiencia con GA4 y Looker Studio."
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item("GA4", "preferred"),
                requirement_item("Looker Studio", "preferred"),
            ],
        },
        source_text=source_text,
    )

    assert flat["must_have"] == []
    assert flat["should_have"] == []
    nice = fold(flat["nice_to_have"])
    assert "ga4" in nice
    assert "looker studio" in nice
    assert_flat_matches_nested_requirements(normalized, flat)


def test_soft_parent_cue_inherits_to_libreta_and_vehiculo_plural_phrase():
    source_text = "Libreta y vehículo serán valorables."
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item("Libreta", "preferred"),
                requirement_item("Vehículo", "preferred"),
            ],
        },
        source_text=source_text,
    )

    assert flat["must_have"] == []
    assert flat["should_have"] == []
    nice = fold(flat["nice_to_have"])
    assert "libreta" in nice
    assert "vehiculo" in nice
    assert_flat_matches_nested_requirements(normalized, flat)


def test_hard_parent_cue_inherits_to_every_comma_list_sibling():
    source_text = "Debe manejar métricas, calidad, ausentismo, turnos y coaching."
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item("Métricas", "preferred"),
                requirement_item("Calidad", "preferred"),
                requirement_item("Ausentismo", "preferred"),
                requirement_item("Turnos", "preferred"),
                requirement_item("Coaching", "preferred"),
            ],
        },
        source_text=source_text,
    )

    assert flat["should_have"] == []
    must = fold(flat["must_have"])
    for expected in ("metricas", "calidad", "ausentismo", "turnos", "coaching"):
        assert expected in must
    assert_flat_matches_nested_requirements(normalized, flat)


def test_hard_parent_cue_preserves_dependent_con_fragment():
    source_text = (
        "Es excluyente experiencia en RRHH generalista, con exposición a conflictos laborales "
        "y gestión de personas en operación."
    )
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item("Experiencia en RRHH generalista", "preferred"),
                requirement_item("Exposición a conflictos laborales", "preferred"),
            ],
        },
        source_text=source_text,
    )

    assert flat["should_have"] == []
    must = fold(flat["must_have"])
    assert "experiencia en rrhh generalista" in must
    assert "conflictos laborales" in must
    assert "gestion de personas en operacion" in must
    assert_flat_matches_nested_requirements(normalized, flat)


def test_debe_manejar_alternative_tool_list_is_must_have():
    source_text = "Debe manejar Adobe y/o Figma con criterio visual sólido."
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item("Adobe y/o Figma", "preferred", source_text=source_text),
            ],
        },
        source_text=source_text,
    )

    assert flat["should_have"] == []
    assert "adobe y/o figma" in fold(flat["must_have"])
    assert_flat_matches_nested_requirements(normalized, flat)


def test_sibling_can_override_parent_cue_with_explicit_local_soft_modifier():
    source_text = "Debe manejar métricas, calidad y Excel valorable."
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Métricas"),
                requirement_item("Calidad"),
                requirement_item("Excel", source_text="Excel valorable"),
            ],
        },
        source_text=source_text,
    )

    assert "metricas" in fold(flat["must_have"])
    assert "calidad" in fold(flat["must_have"])
    assert "excel" not in fold(flat["must_have"] + flat["should_have"])
    assert "excel" in fold(flat["nice_to_have"])
    assert_flat_matches_nested_requirements(normalized, flat)


def test_local_valorable_overrides_later_conditional_debe_clause():
    source_text = "Libreta de conducir será valorable si debe recorrer servicios."
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Libreta de conducir", source_text=source_text),
            ],
        },
        source_text=source_text,
    )

    assert flat["must_have"] == []
    assert flat["should_have"] == []
    assert flat["nice_to_have"] == ["Libreta de conducir"]
    assert flat["credentials"]["required"] == []
    assert flat["credentials"]["preferred"] == []
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_084_sales_requirement_not_duplicated_when_inmobiliarias_is_preferred_context():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item(
                    "Perfil comercial fuerte y experiencia en ventas",
                    source_text="Es excluyente perfil comercial fuerte y experiencia en ventas",
                ),
            ],
            "should_have": [
                requirement_item(
                    "Experiencia en ventas",
                    "preferred",
                    source_text="idealmente inmobiliarias",
                ),
                requirement_item(
                    "Experiencia inmobiliaria",
                    "preferred",
                    source_text="idealmente inmobiliarias",
                ),
            ],
        }
    )

    assert flat["must_have"] == ["Perfil comercial fuerte y experiencia en ventas"]
    assert flat["should_have"] == ["Experiencia inmobiliaria"]
    assert fold(flat["must_have"] + flat["should_have"]).count("experiencia en ventas") == 1
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_098_hard_excluyente_context_applies_to_comma_split_components():
    source_text = (
        "Es excluyente experiencia gestionando franquiciados, estándares operativos, "
        "auditorías, capacitación y seguimiento comercial."
    )
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item(
                    "Capacitación y seguimiento comercial",
                    "preferred",
                    source_text=source_text,
                ),
            ],
        },
        source_text=source_text,
    )

    assert "capacitacion y seguimiento comercial" in fold(flat["must_have"])
    assert "capacitacion y seguimiento comercial" not in fold(flat["should_have"])
    assert_flat_matches_nested_requirements(normalized, flat)


def test_alternative_healthcare_commercial_experience_stays_one_composite_requirement():
    phrase = "experiencia comercial en salud, laboratorios, equipamiento médico, dispositivos médicos o servicios vinculados al sector"
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia comercial en salud", source_text=phrase),
                requirement_item("Laboratorios", source_text=phrase),
                requirement_item("Equipamiento médico", source_text=phrase),
                requirement_item("Dispositivos médicos", source_text=phrase),
                requirement_item("Servicios vinculados al sector", source_text=phrase),
            ],
        }
    )

    assert flat["must_have"] == [
        "Experiencia comercial en salud, laboratorios, equipamiento médico, dispositivos médicos o servicios vinculados al sector"
    ]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_alternative_regulated_industry_list_stays_one_composite_requirement():
    phrase = "laboratorio, industria farmacéutica, alimentos, química o ambiente regulado"
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Laboratorio", source_text=phrase),
                requirement_item("Industria farmacéutica", source_text=phrase),
                requirement_item("Alimentos", source_text=phrase),
                requirement_item("Química", source_text=phrase),
                requirement_item("Ambiente regulado", source_text=phrase),
            ],
        }
    )

    assert flat["must_have"] == ["Laboratorio, industria farmacéutica, alimentos, química o ambiente regulado"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_alternative_telecom_equipment_phrase_stays_one_composite_requirement():
    phrase = "fibra óptica o equipos de telecomunicaciones"
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Fibra óptica", source_text=phrase),
                requirement_item("Equipos de telecomunicaciones", source_text=phrase),
            ],
        }
    )

    assert flat["must_have"] == ["Fibra óptica o equipos de telecomunicaciones"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_unrelated_must_have_requirements_remain_separate():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia comercial B2B"),
                requirement_item("Manejo de CRM"),
            ],
        }
    )

    assert flat["must_have"] == ["Experiencia comercial B2B", "Manejo de CRM"]
    assert_flat_matches_nested_requirements(normalized, flat)


@pytest.mark.parametrize(
    ("base", "preferred", "expected"),
    [
        (
            "Inglés para clientes internacionales",
            "Inglés valorable para clientes internacionales",
            "Inglés valorable para clientes internacionales",
        ),
        (
            "Certificaciones del rubro",
            "Certificaciones del rubro serán valorables",
            "Certificaciones del rubro serán valorables",
        ),
    ],
)
def test_near_duplicate_requirements_prefer_complete_phrase_with_importance_cue(base, preferred, expected):
    normalized, flat = normalize_and_flatten(
        {
            "should_have": [
                requirement_item(base, "preferred"),
            ],
            "nice_to_have": [
                requirement_item(preferred, "nice_to_have"),
            ],
        }
    )

    combined = flat["should_have"] + flat["nice_to_have"]
    assert combined == [expected]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_033_near_duplicate_qa_experience_keeps_single_hard_requirement():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia excluyente diseñando casos de prueba"),
                requirement_item("Experiencia diseñando casos de prueba"),
            ],
        }
    )

    assert flat["must_have"] == ["Experiencia excluyente diseñando casos de prueba"]
    assert fold(flat["must_have"]).count("disenando casos de prueba") == 1
    assert_flat_matches_nested_requirements(normalized, flat)


def test_component_duplicate_base_tecnica_keeps_more_complete_phrase():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Base técnica comprobable en redes"),
                requirement_item("Base técnica en redes"),
            ],
        }
    )

    assert flat["must_have"] == ["Base técnica comprobable en redes"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_001_component_and_larger_management_requirement_collapses_to_larger_phrase():
    larger = (
        "Haber ocupado posiciones gerenciales o de jefatura durante al menos 5 años "
        "trabajando con contratos comerciales"
    )
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Haber ocupado posiciones gerenciales o de jefatura durante al menos 5 años"),
                requirement_item(larger),
            ],
        }
    )

    assert flat["must_have"] == [larger]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_busqueda_006_trailing_component_duplicate_collapses_to_larger_phrase():
    larger = (
        "Haber trabajado en logística de distribución o transporte, "
        "con contacto directo con choferes y clientes"
    )
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item(larger),
                requirement_item("Con contacto directo con choferes y clientes"),
            ],
        }
    )

    assert flat["must_have"] == [larger]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_blocker_component_and_aggregate_duplicates_collapse_to_larger_blocker():
    normalized, flat = normalize_and_flatten(
        {
            "blockers": [
                "No avanzar perfiles sin experiencia corporativa",
                "No avanzar perfiles sin experiencia corporativa ni perfiles junior",
            ],
        }
    )

    assert flat["blockers"] == ["No avanzar perfiles sin experiencia corporativa y perfiles junior"]
    assert normalized["requirements"]["blockers"] == flat["blockers"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_blocker_duplicate_with_and_without_no_avanzar_prefers_prefixed_blocker():
    normalized, flat = normalize_and_flatten(
        {
            "blockers": [
                "Sin experiencia documentada en calidad",
                "No avanzar perfiles sin experiencia documentada en calidad",
            ],
        }
    )

    assert flat["blockers"] == ["No avanzar perfiles sin experiencia documentada en calidad"]
    assert normalized["requirements"]["blockers"] == flat["blockers"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_alternative_certification_aggregate_removes_component_duplicates():
    aggregate = "Security+, Cisco, Microsoft o similares"
    normalized, flat = normalize_and_flatten(
        {
            "nice_to_have": [
                requirement_item("Certificación Security+", "nice_to_have"),
                requirement_item("Certificación Cisco", "nice_to_have"),
                requirement_item("Certificación Microsoft", "nice_to_have"),
                requirement_item(aggregate, "nice_to_have"),
            ],
        }
    )

    assert flat["nice_to_have"] == [aggregate]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_redundant_aggregate_requirement_is_removed_when_clean_independent_components_exist():
    aggregate = "Perfil comercial fuerte y experiencia en ventas"
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Perfil comercial fuerte"),
                requirement_item("Experiencia en ventas"),
                requirement_item(aggregate),
            ],
        }
    )

    assert flat["must_have"] == ["Perfil comercial fuerte", "Experiencia en ventas"]
    assert_flat_matches_nested_requirements(normalized, flat)


def test_flat_top_level_fields_and_nested_requirements_stay_synchronized_after_normalization():
    normalized, flat = normalize_and_flatten(
        {
            "must_have": [
                requirement_item("Experiencia comercial B2B excluyente"),
            ],
            "should_have": [
                requirement_item("Deseable CRM", "preferred"),
            ],
            "nice_to_have": [
                requirement_item("Inglés será un plus", "nice_to_have"),
            ],
            "credentials": [
                requirement_item("Título habilitante", "must_have"),
                requirement_item("Libreta de conducir suma", "nice_to_have"),
            ],
            "blockers": [
                "No avanzar perfiles sin experiencia comercial",
            ],
        }
    )

    assert_flat_matches_nested_requirements(normalized, flat)
