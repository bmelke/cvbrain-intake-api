# CVBrain Fixture Evaluation Suite

Date: 2026-06-08

Status: fixture/test infrastructure for the CVBrain Job Intelligence design phase. This document and the accompanying fixtures do not add OpenAI, provider code, a database, runtime endpoint behavior changes, or candidate search behavior.

## Purpose

The fixture suite is the safety net for future deterministic extraction, AI structured extraction, location intelligence, and compatibility mapping. It captures what CVBrain must preserve before any AI-powered extraction is introduced.

The suite is AI-provider independent. Future OpenAI or other provider output must pass these same fixture expectations before staging.

## Fixture Folders

- `tests/fixtures/job_intelligence/`: sanitized recruiter-request fixtures and targeted expectations.
- `tests/fixtures/job_intelligence/expected/`: design notes for future Job Intelligence v1 expectations.
- `tests/fixtures/location_context/`: location-context case index for country and modality risks.
- `tests/fixtures/compatibility_mapping/`: required compatibility keys and product-boundary expectations.

## Fixture Format

Each job-intelligence fixture is JSON and contains:

```json
{
  "id": "uy_account_manager_medical_devices_montevideo_hybrid",
  "assertion_scope": "current_runtime_contract",
  "locale": "es-UY",
  "country_context": "UY",
  "candidate_market": "UY",
  "employer_market": "UY",
  "source_text": "sanitized recruiter request",
  "expected": {
    "job_title": "Account Manager Semi Senior",
    "seniority": "semi senior",
    "location": {
      "base": "Montevideo",
      "country_code": "UY",
      "hybrid_allowed": true,
      "remote_allowed": null
    },
    "industries": [],
    "must_have_contains": [],
    "should_have_contains": [],
    "nice_to_have_contains": [],
    "search_terms_include": [],
    "must_not_include": [],
    "warnings_include": [],
    "missing_information_include": []
  }
}
```

Tests use targeted assertions instead of full JSON equality. That keeps the fixtures stable while allowing the schema to evolve.

## Assertion Scopes

`current_runtime_contract` fixtures run against the current deterministic `/api/job-intake/analyze` endpoint.

`future_schema_expectation` fixtures document Job Intelligence v1 behavior that is not fully implemented yet, such as Argentina location normalization, country-context mismatch warnings, `hard_filter_candidate`, `hard_filter_approved`, source spans, and richer missing-information objects.

Do not fail the current runtime only because it lacks a future design field. Add or tighten runtime assertions only when the parser or mapper exists.

## Country and Location Testing Rules

Location is country-dependent and must be tested separately from generic text extraction.

Required guarantees:

- Uruguay/Montevideo input must not add Argentina, Buenos Aires, CABA, GBA, or AMBA.
- Argentina/CABA/GBA input must not add Uruguay, Montevideo, or Canelones.
- Cross-country conflict must preserve the source location and add a mismatch warning.
- Missing location must not default to Montevideo or Buenos Aires.
- Remote-only text must not infer a city.
- Hybrid-only text must not infer a city.
- Location hard filters require explicit wording and recruiter approval discipline.

## How to Add Sanitized Fixtures

1. Add a JSON file under `tests/fixtures/job_intelligence/`.
2. Use only synthetic recruiter text.
3. Set `assertion_scope` to `current_runtime_contract` only if the current deterministic parser should satisfy the assertions now.
4. Set `assertion_scope` to `future_schema_expectation` for v1/AI behavior that is not wired yet.
5. Add targeted `must_not_include` terms for country leakage and privacy risks.
6. Avoid full JSON snapshots.
7. Run `scripts/evaluate_fixtures.sh`.

## What Must Never Be Included

Fixtures, expected outputs, docs, and reports must not include:

- real candidate names
- candidate emails
- candidate phones
- addresses
- raw CV text
- private recruiter notes
- API keys
- provider keys
- private logs
- production secrets
- real candidate IDs

Extraction fixtures should describe job requirements only.

## Compatibility Mapping Coverage

The compatibility mapping fixtures document required keys and boundaries for:

- current flat CVBrain contract
- WordPress Review/Edit Draft rich shape
- Phase 2D Super CV mapping preview
- search-ready profile expectations
- shadow QA, comparison, and pilot review privacy boundaries

Candidate ranking remains Super CV-owned. `weight` remains extraction/search-priority guidance only.

## Preparing for AI Structured Extraction

Future AI extraction should emit or map into Job Intelligence v1 while preserving the current flat contract. Before staging, AI output must pass:

- all current runtime contract fixtures that are relevant to endpoint compatibility
- all future schema expectation fixtures once the schema/mappers exist
- location context tests
- compatibility mapping expectation tests
- privacy and secrets scans

The fixture suite should run before any staging pilot with AI enabled.

## Commands

Run the full fixture evaluation:

```bash
scripts/evaluate_fixtures.sh
```

Run the standard check:

```bash
scripts/check.sh
```

Both commands compile `app/main.py` and run `pytest`.

## Non-Goals

- No OpenAI implementation.
- No AI provider code.
- No database.
- No endpoint behavior change.
- No candidate search.
- No candidate result persistence.
- No real PII.
