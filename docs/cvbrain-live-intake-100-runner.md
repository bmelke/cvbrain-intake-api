# CVBrain Live Intake 100-Case Runner

This runner verifies realistic HR/RRHH intake language against the live CVBrain
Job Intake API. It sends only the text inside each `BUSQUEDA_###` block as
`source_text`; block markers, fixture headers, comments, and role hints are not
included in API payloads.

## Files

- Fixture:
  `tests/fixtures/live_intake/cvbrain_100_busquedas_hr_realistas_sin_role_hint.txt`
- Runner:
  `scripts/run_live_intake_fixture.py`

## Cloud Shell Setup

```bash
PROJECT="cvbrain"
SERVICE="cvbrain-intake-api-staging"
REGION="us-east1"

export CVBRAIN_STAGING_URL="$(gcloud run services describe "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --format='value(status.url)')"

export CVBRAIN_KEY="$(gcloud secrets versions access latest \
  --secret=cvbrain-intake-api-key \
  --project "$PROJECT")"

echo "URL=$CVBRAIN_STAGING_URL"
echo "KEY_LENGTH=$(printf %s "$CVBRAIN_KEY" | wc -c)"
```

Do not print the API key itself.

## Run

```bash
python3 scripts/run_live_intake_fixture.py \
  --input tests/fixtures/live_intake/cvbrain_100_busquedas_hr_realistas_sin_role_hint.txt \
  --out /tmp/cvbrain-intake-100-$(date +%Y%m%d-%H%M%S)
```

The runner reads `CVBRAIN_STAGING_URL` and then `CVBRAIN_KEY` or
`CVBRAIN_INTAKE_API_KEY` from the environment when CLI flags are omitted.

## Output

The output directory contains:

- `requests/BUSQUEDA_###.request.json`
- `responses/BUSQUEDA_###.response.json`
- `summary.json`
- `summary.csv`
- `failures.md`

Do not commit `/tmp` outputs. Review responses before sharing externally; live
API outputs are verification artifacts and may contain recruiter request text.

## Classification

The runner marks hard technical or contract issues as `FAIL_*`, populated but
review-worthy outputs as `WARN`, and clean cases as `PASS`.

Hard failures include non-200 responses, invalid JSON, `ok:false`,
`ai_schema_validation_failed`, `ai_provider_error`, unexpected non-OpenAI engine
in live AI mode, fallback usage in live AI mode, empty core output, obvious
orphan requirement fragments, weak modifiers promoted above `nice_to_have`, and
hard modifiers demoted below `must_have` or blocker.

Warnings include search-readiness warnings, low confidence, generated recruiter
questions, and English role titles that may deserve manual review.
