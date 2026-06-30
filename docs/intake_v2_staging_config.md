# CVBrain Intake API V2 Staging Configuration

This document is the canonical guidance for CVBrain Intake API V2 staging configuration. It is operational configuration guidance only; it is not semantic interpretation, product behavior design, or approval to expose staging.

## Required V2 Runtime Configuration

Set exactly these required V2 runtime variables for staging:

- `CVBRAIN_INTAKE_V2_OPENAI_MODEL` must be configured explicitly for V2 provider construction.

```text
CVBRAIN_INTAKE_V2_API_KEY=<generated-v2-access-key>
CVBRAIN_INTAKE_V2_OPENAI_API_KEY=<secret-from-secret-manager>
CVBRAIN_INTAKE_V2_OPENAI_MODEL=<configured-v2-model>
```

- `CVBRAIN_INTAKE_V2_API_KEY` is the server-side V2 endpoint access key. Clients must send `X-CVBrain-V2-API-Key` with requests to the isolated V2 endpoint.
- `CVBRAIN_INTAKE_V2_OPENAI_API_KEY` must come from Secret Manager or secure runtime secret injection. Do not place the value in source files, command history, documentation examples, logs, or test fixtures.
- `CVBRAIN_INTAKE_V2_OPENAI_MODEL` must be configured explicitly for V2 provider construction. Choose an approved configured value for the staging runtime.

## Optional Manual Live Smoke

The optional live-smoke gate is:

```text
CVBRAIN_INTAKE_V2_ALLOW_LIVE_SMOKE=1
```

This flag is only for explicit manual live-smoke use. It is off by default. It must not run during normal tests, build, deploy, `/health`, `/intake/v2/status`, `/intake/v2/analyze`, WordPress, or default CI.

Do not run live smoke unless the gate is explicitly enabled for a manual preflight, the required V2 runtime configuration is present, and the run has separate approval.

## Legacy V1 Names - Do Not Use For V2

- Legacy V1 name `CVBRAIN_INTAKE_API_KEY`: do not use for V2.
- Legacy V1 name `OPENAI_API_KEY`: do not use for V2.
- Legacy V1 name `CVBRAIN_OPENAI_MODEL`: do not use for V2.

These names are listed only to prevent accidental substitution. They are not active V2 configuration instructions.

## Safe Staging Checklist

- Set the V2 server API key secret for `CVBRAIN_INTAKE_V2_API_KEY`.
- Set the V2 OpenAI API key secret for `CVBRAIN_INTAKE_V2_OPENAI_API_KEY`.
- Set the V2 OpenAI model value for `CVBRAIN_INTAKE_V2_OPENAI_MODEL`.
- Verify `/health` remains generic.
- Verify `GET /intake/v2/status` requires V2 auth.
- Verify `POST /intake/v2/analyze` requires V2 auth.
- Verify missing provider config returns safe 503 unavailable.
- Verify request, body, and source limits are active.
- Do not run live smoke unless explicitly gated.
- Do not deploy WordPress adapter yet.

## Push, Build, And Deploy Separation

This documentation gate does not authorize push, build, deploy, live OpenAI smoke, WordPress adapter work, or staging UI work.

Any push, build, deploy, live OpenAI smoke, WordPress adapter, or staging UI step requires a separate approved gate.

## Later Deployment Checks

Before any later staging exposure, run a separate deployment-readiness review that covers:

- Confirm V2 env vars are mapped into staging runtime.
- Confirm secrets are injected securely.
- Confirm build/deploy commands are run only after separate approval.
- Confirm branch, upstream, and push plan separately.

Do not include API keys, bearer tokens, OpenAI keys, prompts, provider payloads, provider outputs, raw exception text, or production/staging secret values in this document or in future staging reports.
