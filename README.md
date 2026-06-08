# CVBrain Intake API

CVBrain Intake API is the standalone analyzer service used by the TrabajoAca Job Intake preview flow.

- Product: CVBrain
- Service: cvbrain-intake-api
- Dev Cloud Run service: cvbrain-intake-api-dev
- Dev URL: https://cvbrain-intake-api-dev-4680101523.us-east1.run.app

The service defaults to deterministic parsing. Optional OpenAI Structured Output extraction is available only when explicitly enabled with environment variables. The service does not connect to a database.

## Endpoints

- `GET /health`
- `POST /api/job-intake/analyze`

`/health` is public.

`/api/job-intake/analyze` is public only when `CVBRAIN_INTAKE_API_KEY` is not set. When `CVBRAIN_INTAKE_API_KEY` is set, requests must include either:

- `X-CVBrain-API-Key`
- `X-TrabajoAca-API-Key`

## Privacy

The current dev endpoint is public. Do not send real PII, real recruiter files, raw candidate data, candidate names, emails, phones, addresses, or private notes to the dev endpoint.

Staging and production must set `CVBRAIN_INTAKE_API_KEY`.

OpenAI extraction is only for job-intake interpretation. It must not rank candidates, choose candidates, replace manual search, or introduce candidate data.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Local Run

Without API key, useful for local development:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Deterministic mode is the default and does not require `OPENAI_API_KEY`:

```bash
CVBRAIN_EXTRACTOR_MODE=deterministic uvicorn app.main:app --host 127.0.0.1 --port 8000
```

With API key protection enabled:

```bash
CVBRAIN_INTAKE_API_KEY=local-test-key uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Tests

```bash
pytest
```

Tests use mocked providers and make no real OpenAI calls. `OPENAI_API_KEY` is not required for tests.

Full local check:

```bash
./scripts/check.sh
```

The check runs:

```bash
python3 -m py_compile app/main.py
pytest
```

## Extractor Modes

`POST /api/job-intake/analyze` always returns the current flat compatibility fields. Optional metadata may include `engine`, `fallback_used`, `ai_model`, and `job_intelligence` when AI extraction succeeds.

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `CVBRAIN_EXTRACTOR_MODE` | `deterministic` | `deterministic`, `auto`, or `ai`. |
| `OPENAI_API_KEY` | unset | Required only when AI is actually used. |
| `CVBRAIN_OPENAI_MODEL` | unset | Required for AI mode. Auto mode uses AI only when both key and model are set. |
| `CVBRAIN_AI_TIMEOUT_SECONDS` | `20` | OpenAI client timeout. |
| `CVBRAIN_AI_FALLBACK_ENABLED` | `true` | Fall back to deterministic output on AI failure. |
| `CVBRAIN_AI_STRICT_SCHEMA_ENABLED` | `true` | Request strict Structured Output schema where supported. |
| `CVBRAIN_AI_MAX_INPUT_CHARS` | `12000` | Conservative input limit for AI mode. |
| `CVBRAIN_AI_MAX_OUTPUT_TOKENS` | `4096` | Conservative output token limit for AI mode. |
| `CVBRAIN_LOG_AI_METADATA` | `false` | Reserved for non-sensitive operational metadata only. |
| `CVBRAIN_STORE_RAW_AI_OUTPUT` | `false` | Raw AI output must not be stored by default. |

Mode behavior:

- `deterministic`: always uses the deterministic parser. No OpenAI key or model is required.
- `auto`: uses OpenAI only when both `OPENAI_API_KEY` and `CVBRAIN_OPENAI_MODEL` are configured; otherwise deterministic.
- `ai`: attempts OpenAI Structured Output extraction. Missing key/model, invalid JSON, schema failure, timeout, or provider error falls back to deterministic when fallback is enabled, or returns a clean `ok=false` flat response when fallback is disabled.

AI output target:

```text
OpenAI Structured Output -> CVBrain Job Intelligence v1 validation -> flat compatibility mapping
```

The top-level response remains backward-compatible for WordPress. `job_intelligence` is additive and present only after successful AI validation.

## Curl Examples

Health:

```bash
curl -sS https://cvbrain-intake-api-dev-4680101523.us-east1.run.app/health
```

Analyze without API key, for local/dev only when `CVBRAIN_INTAKE_API_KEY` is unset:

```bash
curl -sS http://127.0.0.1:8000/api/job-intake/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "source_text": "Account Manager Semi Senior con experiencia en dispositivos medicos. Minima de 3 anos.",
    "source_filename": "",
    "source_mime_type": "text/plain",
    "recruiter_notes": "",
    "locale": "es-UY"
  }'
```

Analyze with API key:

```bash
curl -sS http://127.0.0.1:8000/api/job-intake/analyze \
  -H 'Content-Type: application/json' \
  -H 'X-CVBrain-API-Key: local-test-key' \
  -d '{
    "source_text": "Account Manager Semi Senior con experiencia en dispositivos medicos. Minima de 3 anos.",
    "source_filename": "",
    "source_mime_type": "text/plain",
    "recruiter_notes": "",
    "locale": "es-UY"
  }'
```

The `X-TrabajoAca-API-Key` header is also accepted for WordPress integration.

## WordPress Configuration

For TrabajoAca staging/local preview, configure the WordPress Job Intake plugin with:

```php
define( 'TRABAJOACA_JOB_INTAKE_API_BASE_URL', 'https://cvbrain-intake-api-dev-4680101523.us-east1.run.app' );
```

The WordPress staging flags still belong in staging/local configuration only. Do not enable production defaults from this repo.

## Cloud Run Deploy

Use the appropriate service name and API key settings per environment. Do not commit API keys.

### Dev

Dev is currently public and should receive sanitized test content only:

```bash
gcloud run deploy cvbrain-intake-api-dev \
  --source . \
  --region us-east1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 20 \
  --timeout 60 \
  --min-instances 0 \
  --max-instances 1
```

### Staging

Staging should require an API key. For deterministic staging:

```bash
gcloud run deploy cvbrain-intake-api-staging \
  --source . \
  --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars CVBRAIN_INTAKE_API_KEY=REPLACE_WITH_SECRET_VALUE \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 20 \
  --timeout 60 \
  --min-instances 0 \
  --max-instances 1
```

For AI staging, document and configure secrets; do not commit them:

```bash
gcloud run deploy cvbrain-intake-api-staging \
  --source . \
  --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars CVBRAIN_EXTRACTOR_MODE=ai,CVBRAIN_AI_FALLBACK_ENABLED=true,CVBRAIN_AI_STRICT_SCHEMA_ENABLED=true,CVBRAIN_OPENAI_MODEL=REPLACE_WITH_APPROVED_MODEL \
  --set-secrets OPENAI_API_KEY=OPENAI_API_KEY:latest,CVBRAIN_INTAKE_API_KEY=CVBRAIN_INTAKE_API_KEY:latest \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 10 \
  --timeout 60 \
  --min-instances 0 \
  --max-instances 2
```

Prefer Secret Manager integration before using staging with broader access.

### Production

Production must require an API key:

```bash
gcloud run deploy cvbrain-intake-api \
  --source . \
  --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars CVBRAIN_INTAKE_API_KEY=REPLACE_WITH_SECRET_VALUE \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 20 \
  --timeout 60 \
  --min-instances 0 \
  --max-instances 1
```

Do not send real PII to staging or production until the privacy review approves the intake workflow.
