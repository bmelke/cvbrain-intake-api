# CVBrain Intake API

CVBrain Intake API is the standalone analyzer service used by the TrabajoAca Job Intake preview flow.

- Product: CVBrain
- Service: cvbrain-intake-api
- Dev Cloud Run service: cvbrain-intake-api-dev
- Dev URL: https://cvbrain-intake-api-dev-4680101523.us-east1.run.app

The service currently uses deterministic parsing only. It does not use OpenAI and does not connect to a database.

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

With API key protection enabled:

```bash
CVBRAIN_INTAKE_API_KEY=local-test-key uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Tests

```bash
pytest
```

Full local check:

```bash
./scripts/check.sh
```

The check runs:

```bash
python3 -m py_compile app/main.py
pytest
```

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

Staging should require an API key:

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

Prefer a secret manager integration before using staging with broader access.

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
