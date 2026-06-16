# CVBrain Product Migration Plan

Date: 2026-06-16

Status: migration note. This document does not move infrastructure, create a new repo, deploy production, change keys, change Cloud Run config, modify WordPress, touch Super CV, add a database, or change runtime behavior.

## Purpose

The current standalone screen at:

```text
https://staging2.trabajoaca.com/cvbrain-intake/
```

is a staging bridge. It proves the product direction but is not the final hosting model.

The long-term direction is a CVBrain-owned product surface that is independent of TrabajoAca WordPress.

## Temporary Assets

Current staging2 directory:

```text
~/www/staging2.trabajoaca.com/public_html/cvbrain-intake/
```

Temporary files:

```text
index.php
assets/cvbrain-intake.css
assets/cvbrain-intake.js
api/analyze.php
```

These files should eventually move out of the TrabajoAca staging web root.

## Possible Future Repository

Options:

1. add a frontend app inside `cvbrain-intake-api` under a clear directory such as `web/`.
2. create a separate repository such as `cvbrain-intake-web`.
3. create a broader CVBrain monorepo if future ATS features include intake, review, authentication, and search workflows.

Recommended next step:

- separate `cvbrain-intake-web` once the UI needs auth, user sessions, design system, deployments, and non-staging environments.

## Possible Domain or Subdomain

Future hosting options:

- `https://intake.cvbrain.ai/`
- `https://app.cvbrain.ai/`
- `https://cvbrain.trabajoaca.com/` for transitional staging.
- Cloud Run custom domain for staging and production.

Use a CVBrain-owned domain/subdomain for product identity. Avoid making the long-term UI look like TrabajoAca unless the client is explicitly embedding CVBrain.

## Required Config

The future UI/proxy needs:

- `CVBRAIN_API_BASE_URL`
- `CVBRAIN_INTAKE_API_KEY` or an equivalent service credential.
- environment name: local/staging/prod.
- allowed origins/CORS strategy if browser calls are ever direct.
- request timeout matching long AI extraction.
- logging/monitoring configuration.

Secrets must be environment-managed, not committed.

## API Key Strategy

Current staging bridge:

- browser calls local `api/analyze.php`.
- `api/analyze.php` reads server-side key.
- browser never sees the key.

Future product:

- browser should authenticate to the product app, not directly to the CVBrain API key.
- backend-for-frontend or server-side route should call CVBrain API.
- API keys should rotate per environment.
- external platform clients should receive their own scoped credentials.
- logs must never print raw keys.

## Auth and Rate Limit Strategy

Staging bridge:

- simple nonce/cookie.
- simple per-IP temp-file rate limit.
- noindex.

Future product should add:

- user authentication.
- organization/account boundaries.
- per-user and per-organization rate limits.
- abuse monitoring.
- request size limits.
- CAPTCHA or WAF if public sign-in is exposed.
- audit logs without raw source text unless approved.
- privacy controls for uploaded documents.

## What Must Move

From staging2:

- `index.php` UI structure.
- CSS visual direction.
- JS display rendering pattern.
- server-side proxy behavior.
- noindex/rate-limit/auth lessons.

Into CVBrain-owned product:

- rendering of `display_plan`.
- friendly errors.
- long-input loading copy.
- source input form.
- example-loader behavior.
- secure server-side API call.

What should not move as-is:

- dependency on WordPress constants.
- temporary PHP proxy implementation.
- staging2 path assumptions.
- simple temp-file rate limit as production control.

## Migration Steps

1. Choose repository and hosting target.
2. Create environment-specific config for API base URL and credentials.
3. Rebuild the screen as a CVBrain-owned app or service.
4. Implement auth and production-grade rate limiting.
5. Render `display_plan` only.
6. Add e2e tests for short/long input, missing plan, no secret exposure, and no raw JSON.
7. Deploy staging.
8. Compare staging2 bridge versus new CVBrain surface.
9. Freeze staging2 bridge or redirect it.
10. Remove temporary staging2 directory after sign-off.

## Rollback During Migration

If the future CVBrain-hosted screen fails, keep the staging2 bridge until replacement is verified.

Current staging2 rollback command:

```bash
ssh trabajoaca 'rm -rf /home/u2088-ujxgrfoyqrdu/www/staging2.trabajoaca.com/public_html/cvbrain-intake'
```

Do not remove the bridge until a replacement URL and rollback path are documented.

## Non-Goals

- No production deploy from this note.
- No key rotation from this note.
- No WordPress cleanup from this note.
- No candidate search integration.
- No database migration.
- No ATS account system implementation.
