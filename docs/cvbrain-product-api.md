# CVBrain Product and API Architecture

Date: 2026-06-16

Status: internal architecture documentation. This document does not change runtime behavior, WordPress behavior, Cloud Run configuration, database schema, candidate search, ranking, scoring, environment variables, keys, or production.

## Purpose

CVBrain is becoming a self-contained ATS/intake product. It interprets recruiter search text or job descriptions and returns normalized job-intake intelligence that can be used by multiple clients.

TrabajoAca is one current consumer of CVBrain. Future clients may include other ATS platforms, partner systems, internal recruiter tools, or a standalone CVBrain product screen.

## Product Boundary

CVBrain owns:

- AI extraction.
- deterministic and post-AI normalization.
- normalized JSON contracts.
- Job Intelligence fields.
- `display_plan` / recruiter-facing search plan.
- readiness, warnings, missing information, recruiter questions, blockers, and search concepts.

Clients own:

- collecting recruiter input.
- calling CVBrain securely.
- rendering the CVBrain response.
- escaping output.
- protecting API keys.
- deciding when to use the normalized search plan in downstream workflows.

Clients must not duplicate semantic cleanup, requirement classification, blocker detection, role-title interpretation, or search-concept construction.

## Current Endpoints

### `GET /health`

Public health endpoint.

Example response:

```json
{
  "ok": true,
  "service": "cvbrain-intake-api",
  "product": "CVBrain",
  "version": "0.1.0"
}
```

### `POST /api/job-intake/analyze`

Main recruiter-intake analysis endpoint.

When `CVBRAIN_INTAKE_API_KEY` is configured, callers must send one of:

- `X-CVBrain-API-Key`
- `X-TrabajoAca-API-Key`

`/health` remains public.

## Request Payload

```json
{
  "source_text": "Mutualista busca Responsable de Calidad Asistencial con auditorías clínicas e indicadores.",
  "source_filename": "",
  "source_mime_type": "text/plain",
  "recruiter_notes": "",
  "locale": "es-UY",
  "country_context": "UY",
  "candidate_market": "UY",
  "employer_market": "UY"
}
```

Field notes:

| Field | Required | Notes |
|---|---:|---|
| `source_text` | yes | Sanitized recruiter request or job description. Must not include candidate PII. |
| `source_filename` | no | Optional source filename. Do not send private filenames unless approved. |
| `source_mime_type` | no | Usually `text/plain` for direct text. |
| `recruiter_notes` | no | Optional untrusted context. |
| `locale` | recommended | Example: `es-UY`. |
| `country_context` | recommended | Example: `UY`. Helps prevent cross-country location leakage. |
| `candidate_market` | recommended | Market where candidates are searched. |
| `employer_market` | recommended | Employer/request market. |

## Response Structure

The API keeps the flat compatibility response for existing consumers and adds richer normalized fields.

Important top-level fields:

```json
{
  "ok": true,
  "version": "0.1.0",
  "role_title": "Responsable de Calidad Asistencial",
  "role_family": "",
  "summary": "...",
  "must_have": [],
  "should_have": [],
  "nice_to_have": [],
  "blockers": [],
  "credentials": {
    "required": [],
    "preferred": []
  },
  "experience": {
    "minimum_years": null,
    "seniority": ""
  },
  "location": {
    "raw": "",
    "normalized": "",
    "remote_allowed": null,
    "hybrid_allowed": null
  },
  "search_terms": [],
  "semantic_terms": [],
  "recruiter_questions": [],
  "warnings": [],
  "confidence": 0.74,
  "engine": "openai",
  "fallback_used": false,
  "job_intelligence": {},
  "display_plan": {}
}
```

`job_intelligence` is present after successful AI validation. It is the richer internal normalized schema.

`display_plan` is the preferred UI rendering contract for recruiter-facing screens.

## `display_plan` Contract

`display_plan` is UI-ready. A client may render it directly after escaping values.

Shape:

```json
{
  "role_title": "Responsable de Calidad Asistencial",
  "seniority": "",
  "market": "Uruguay",
  "location_modality": "",
  "summary": "...",
  "what_to_search": "...",
  "must_have": [],
  "preferred": [],
  "nice_to_have": [],
  "blockers": [],
  "tie_breakers": [],
  "questions": [],
  "search_concepts": [],
  "readiness": {
    "code": "usable_with_warnings",
    "label": "Usable con advertencias",
    "severity": "warning"
  }
}
```

Guarantees:

- no raw `search_readiness_*` tokens as display text.
- no `low_confidence:*` display tokens.
- no `ai_schema_*` or `ai_provider_*` display tokens.
- no metadata artifacts such as source-span placeholders.
- no missing placeholders as chips.
- no blocker phrases inside positive requirement buckets.
- duplicate requirements, questions, and concepts are collapsed by CVBrain.
- search concepts are short searchable concepts, not full lead sentences.
- country/market context is separated from actual location and modality.

Clients should treat missing or empty fields as display absence. Clients should not infer or rebuild missing intelligence.

## Client Responsibilities

Clients should:

- send recruiter text to CVBrain server-side.
- keep API keys server-side.
- render `display_plan` after escaping output.
- show friendly loading and error states.
- handle missing `display_plan` as an error or retry condition.
- keep candidate search/ranking as a separate downstream action.

Clients should not:

- classify must-have versus preferred requirements.
- detect blockers.
- infer role titles.
- dedupe semantic concepts beyond harmless visual duplicate suppression.
- construct search concepts.
- expose raw `job_intelligence` to non-technical users by default.
- expose API keys, env vars, raw provider responses, logs, or stack traces.
- use CVBrain to rank or choose candidates.

## TrabajoAca Today

TrabajoAca currently calls CVBrain from staging WordPress/standalone surfaces using server-side API calls. It should render `display_plan` and avoid duplicating semantic logic.

TrabajoAca search/ranking remains separate from intake. CVBrain can prepare a normalized search plan, but TrabajoAca/Super CV ranking/search remains responsible for candidate retrieval, ranking, and match explanations.

## Future External Client Use

Future clients can integrate through the same API:

1. collect recruiter text.
2. call `POST /api/job-intake/analyze` server-side.
3. render `display_plan`.
4. optionally store the normalized output according to their privacy policy.
5. optionally pass normalized search intent to their own search/ranking layer.

Each client must implement its own authentication, API-key storage, rate limiting, and privacy review. CVBrain should continue to own the intelligence contract so clients do not drift into inconsistent interpretations.

## Non-Goals

- Candidate ranking.
- Candidate scoring.
- Candidate search execution.
- Candidate data storage.
- Raw CV ingestion.
- Database writes.
- Client-specific UI semantics.
- Hardcoded one-off recruiter-case fixes.
