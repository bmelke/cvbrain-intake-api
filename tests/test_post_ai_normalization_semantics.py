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
