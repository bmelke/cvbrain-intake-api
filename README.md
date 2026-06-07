# CVBrain Intake API

CVBrain Intake API is the standalone analyzer service used by the Job Intake flow.

Endpoints:

- GET /health
- POST /api/job-intake/analyze

## Local run

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.main:app --host 127.0.0.1 --port 8000

## Cloud Run dev deploy

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
