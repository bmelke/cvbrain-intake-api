# CVBrain AI Extractor Interface Design

Date: 2026-06-08

Status: architecture, docs, stubs, and tests only. This phase does not implement production OpenAI calls, add provider dependencies, add a database, store raw AI output, change `/api/job-intake/analyze` runtime behavior, remove deterministic extraction, reintroduce mock fixtures, add candidate ranking, add candidate data, or commit secrets/PII.

Baseline:

- `docs/cvbrain-fixture-evaluation-suite.md`
- WordPress reference: `docs/cvbrain-job-intelligence-field-inventory.md`
- WordPress reference: `docs/cvbrain-job-intelligence-schema-v1.md`
- WordPress reference: `docs/cvbrain-location-intelligence-design.md`
- WordPress reference: `docs/cvbrain-compatibility-mapping-v1.md`

## 1. Purpose

CVBrain needs AI for deeper recruiter-intake interpretation: nuanced requirement priority, Spanish hard/preferred indicators, role-family normalization, country-aware location handling, credentials, missing information, and recruiter questions. Deterministic extraction remains the safe default and fallback.

AI must only interpret recruiter/job-intake text. It must not rank candidates, search candidates, choose candidates, replace Super CV ranking, replace manual search, persist candidate data, or add candidate PII to extraction output.

The future AI extractor must produce CVBrain Job Intelligence v1, not only the old flat WordPress contract. CVBrain then derives:

1. the current flat compatibility contract,
2. WordPress rich draft compatibility,
3. Super CV mapping preview compatibility.

The fixture suite is the safety net before staging. Any future OpenAI implementation must pass fixture, location, compatibility, privacy, and no-leakage tests before it is connected to staging.

## 2. Extractor Architecture

Conceptual components:

| Component | Responsibility |
|---|---|
| `ExtractorRouter` | Selects deterministic or AI extraction based on environment and fallback policy. |
| `DeterministicExtractor` | Wraps the existing deterministic `analyze_text` parser. It remains the default. |
| `AIExtractorInterface` | Future provider-neutral interface for AI extraction. |
| `OpenAIExtractor` | Future implementation using OpenAI Structured Outputs. Not implemented in this phase. |
| `FallbackPolicy` | Decides deterministic fallback versus clean error on AI failure. |
| `JobIntelligenceValidator` | Future strict validator for CVBrain Job Intelligence v1. |
| `CompatibilityMapper` | Future mapper from Job Intelligence v1 to flat API, WordPress rich draft, and preview mapping outputs. |

Flow:

```text
source_text + locale + country_context
  ↓
ExtractorRouter
  ↓
AIExtractor or DeterministicExtractor
  ↓
Job Intelligence v1 validation
  ↓
flat compatibility mapping
  ↓
current /api/job-intake/analyze response
```

This phase adds dormant extractor stubs and tests only. The live FastAPI endpoint continues to call the existing deterministic parser directly.

## 3. Extractor Modes

Environment variable:

```text
CVBRAIN_EXTRACTOR_MODE
```

Allowed values:

- `deterministic`
- `ai`
- `auto`

Default:

```text
CVBRAIN_EXTRACTOR_MODE=deterministic
```

Mode behavior:

| Mode | Behavior |
|---|---|
| `deterministic` | Always use deterministic extraction. No OpenAI key is required. This remains the default. |
| `ai` | Use AI extraction. Requires `OPENAI_API_KEY`. If missing or failing, return clean error or deterministic fallback according to fallback settings. |
| `auto` | If `OPENAI_API_KEY` exists, attempt AI extraction. If not, use deterministic extraction. |

Unknown mode values should return a clean configuration error in future endpoint wiring.

## 4. Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `CVBRAIN_EXTRACTOR_MODE` | `deterministic` | Selects deterministic, AI, or auto routing. |
| `OPENAI_API_KEY` | unset | Future provider key supplied by environment/Secret Manager only. |
| `CVBRAIN_OPENAI_MODEL` | unset | Future model name. Should be explicitly configured for staging/prod. |
| `CVBRAIN_AI_TIMEOUT_SECONDS` | unset | Future provider request timeout. |
| `CVBRAIN_AI_FALLBACK_ENABLED` | `true` | If AI fails, fall back to deterministic extraction when enabled. |
| `CVBRAIN_AI_STRICT_SCHEMA_ENABLED` | `true` | Future strict Job Intelligence v1 validation. |
| `CVBRAIN_AI_MAX_INPUT_CHARS` | unset | Future source-text size guard. |
| `CVBRAIN_AI_MAX_OUTPUT_TOKENS` | unset | Future output-size guard. |
| `CVBRAIN_LOG_AI_METADATA` | `false` | Allows non-sensitive operational metadata only. |
| `CVBRAIN_STORE_RAW_AI_OUTPUT` | `false` | Raw AI output storage. Must remain false by default. |

Important defaults:

```text
CVBRAIN_EXTRACTOR_MODE=deterministic
CVBRAIN_AI_FALLBACK_ENABLED=true
CVBRAIN_AI_STRICT_SCHEMA_ENABLED=true
CVBRAIN_LOG_AI_METADATA=false
CVBRAIN_STORE_RAW_AI_OUTPUT=false
```

Rules:

- Raw AI output should not be stored by default.
- Raw recruiter text should not be logged.
- No API keys belong in the repo.
- Staging/prod secrets should use Secret Manager or equivalent deployment secrets.

## 5. AI Input Payload Design

Future AI extractor input:

```json
{
  "source_text": "...",
  "locale": "es-UY",
  "country_context": "UY",
  "candidate_market": "UY",
  "employer_market": "UY",
  "source_filename": "",
  "source_mime_type": "text/plain",
  "recruiter_notes": "",
  "schema_version": "cvbrain_job_intelligence_v1"
}
```

Rules:

- `country_context` is not optional for staging/prod once AI is enabled.
- If `country_context` is absent, derive only weakly from locale and add a warning.
- Preserve explicit source locations even when they conflict with country context.
- Treat recruiter notes as untrusted context.
- Do not log raw `source_text` or raw `recruiter_notes`.

## 6. Location-Aware AI Rules

Future AI system instructions must include:

- All job extraction is location-dependent.
- Interpret locations using `country_context`.
- Do not invent country.
- Do not invent city.
- Do not infer Buenos Aires, CABA, GBA, or AMBA unless source text says it or country context supports Argentina.
- Do not infer Montevideo or Canelones unless source text says it or country context supports Uruguay.
- If source text conflicts with context, preserve the source text and add `country_context_mismatch` warning.
- Do not convert CABA/GBA to Montevideo.
- Do not convert Montevideo to CABA/GBA.
- Do not infer remote, hybrid, or onsite unless explicit.
- Do not turn location into a hard filter unless explicit and approved by policy.

Location output must preserve source evidence and unsupported inferences so compatibility mappers can avoid country leakage.

## 7. AI Extraction Rules

Future AI system instructions must include:

- Extract only from source text and provided context.
- Do not invent salary.
- Do not invent compensation.
- Do not invent required degrees.
- Do not invent licenses.
- Do not invent certifications.
- Do not promote preferred or nice-to-have items to must-have.
- Preserve explicit versus inferred fields.
- Include confidence.
- Include source spans for important fields.
- Add missing information for absent but important fields.
- Add recruiter questions when ambiguous.
- Separate requirements from responsibilities.
- Separate hard requirements from preferred requirements.
- Separate search terms from evidence.
- Do not include candidate results.
- Do not include candidate PII.

AI output should be conservative: uncertainty becomes a warning, missing-information item, or recruiter question, not a fabricated requirement.

## 8. AI Output Target

The target output is CVBrain Job Intelligence v1, not only the old flat API contract.

The endpoint must still return current flat fields at top level for WordPress compatibility. Future response shape may be:

```json
{
  "ok": true,
  "version": "0.1.0",
  "role_title": "Account Manager Semi Senior",
  "must_have": [],
  "should_have": [],
  "nice_to_have": [],
  "location": {},
  "search_terms": [],
  "warnings": [],
  "confidence": 0.9,
  "engine": "openai",
  "fallback_used": false,
  "job_intelligence": {
    "schema_version": "cvbrain_job_intelligence_v1"
  }
}
```

Flat compatibility fields remain the WordPress-safe contract. `job_intelligence` is additive and must be feature-gated until validated.

## 9. Fallback Policy

If AI succeeds:

- `engine=openai`
- `fallback_used=false`
- validate Job Intelligence v1
- derive flat fields

If AI fails and fallback is enabled:

- `engine=deterministic`
- `fallback_used=true`
- warnings include `ai_fallback_used`
- include the specific AI failure warning code when safe
- do not return mock fixture data
- do not return stale sample data

If AI fails and fallback is disabled:

- `ok=false`
- return clean error/warning
- no partial hallucinated output
- keep flat compatibility shape when possible

Failure cases:

- missing API key
- timeout
- invalid JSON
- schema validation failure
- unsupported model response
- provider error
- input too large
- location guardrail violation

## 10. Structured Output Validation

Future OpenAI implementation should use Structured Outputs with strict JSON schema. The validator should enforce:

- required top-level sections
- no unknown critical fields unless explicitly allowed
- location object shape
- requirement object shape
- confidence range `0.0` through `1.0`
- no `hard_filter_approved=true` unless source/approval supports it
- no country leakage in fixture tests
- no candidate results in extraction schema
- no raw AI output in exportable response by default

Validation failure should trigger fallback or a clean error, depending on `CVBRAIN_AI_FALLBACK_ENABLED`.

## 11. Test Strategy

Interface/stub tests should make no real OpenAI calls. Required tests:

- deterministic mode routes to deterministic extractor
- auto mode without `OPENAI_API_KEY` routes to deterministic
- ai mode without `OPENAI_API_KEY` returns clean error or fallback according to policy
- fallback enabled adds `ai_fallback_used`
- fallback disabled returns `ok=false`
- AI payload includes locale, country context, candidate market, and employer market
- AI payload preserves source text but does not log it
- location context mismatch warning can be represented
- no network calls in tests
- fixture suite still passes

The current implementation adds dormant stubs under `app/extractors/` and isolated tests in `tests/test_extractor_router.py`.

## 12. Security and Privacy

Rules:

- No raw recruiter text in logs by default.
- No raw AI output stored by default.
- No secrets in repo.
- API keys only through environment or Secret Manager.
- Dev public endpoint must not receive real PII.
- Staging/prod require `CVBRAIN_INTAKE_API_KEY`.
- Candidate data is not part of extraction.
- Do not include candidate names, emails, phones, addresses, raw CV text, private candidate details, provider keys, or private logs in extraction outputs.

Operational metadata, if enabled later, must be non-sensitive: mode, engine, fallback status, schema version, model name, latency, and warning codes only.

## 13. Cloud Run Implications

Future staging service:

```text
cvbrain-intake-api-staging
```

Suggested staging env:

```text
CVBRAIN_EXTRACTOR_MODE=ai
CVBRAIN_AI_FALLBACK_ENABLED=true
CVBRAIN_AI_STRICT_SCHEMA_ENABLED=true
```

Required staging/prod secrets:

```text
OPENAI_API_KEY
CVBRAIN_INTAKE_API_KEY
```

Initial scaling:

- min instances `0`
- max instances `2`
- timeout `60`
- concurrency `10-20`

Dev service can remain deterministic or `auto` without OpenAI. Staging/prod should require API key protection before receiving any pilot traffic.

## 14. Migration Plan

Phase AI-0:

- docs/interface only

Phase AI-1:

- extractor interfaces/stubs/tests, no provider calls

Phase AI-2:

- mocked OpenAI structured output tests

Phase AI-3:

- optional OpenAI implementation behind env vars

Phase AI-4:

- staging Cloud Run with API key and OpenAI key

Phase AI-5:

- compare deterministic versus AI output on fixtures

Phase AI-6:

- connect staging2 WordPress to secured AI staging endpoint

Phase AI-7:

- pilot evaluation

Each phase must preserve the flat contract, deterministic fallback, fixture suite, location guardrails, privacy rules, and no-candidate-ranking boundary.

## Current Stub Files

This phase adds:

- `app/extractors/__init__.py`
- `app/extractors/base.py`
- `app/extractors/router.py`
- `app/extractors/deterministic.py`
- `app/extractors/ai_stub.py`
- `tests/test_extractor_router.py`

The stubs are not wired into `/api/job-intake/analyze`. Endpoint output remains deterministic and backward-compatible.
