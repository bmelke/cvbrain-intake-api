# CVBrain Standalone Staging Demo

Date: 2026-06-16

Status: staging-only documentation. This document describes the standalone demo currently hosted under the TrabajoAca staging2 web root. It does not deploy production, change API logic, modify WordPress, touch Super CV, change keys, or add persistence.

## Purpose

The standalone CVBrain demo gives recruiters a product-like CVBrain screen without entering WordPress admin or using TrabajoAca page styling.

Public staging URL:

```text
https://staging2.trabajoaca.com/cvbrain-intake/
```

The screen demonstrates CVBrain as an independent intake product:

1. recruiter pastes a search/job description.
2. the browser calls a local server-side proxy.
3. the proxy calls CVBrain Intake API with the API key server-side.
4. the browser renders only CVBrain `display_plan`.

## Current Directory

Staging2 path:

```text
~/www/staging2.trabajoaca.com/public_html/cvbrain-intake/
```

Current file layout:

```text
cvbrain-intake/
index.php
assets/
  cvbrain-intake.css
  cvbrain-intake.js
api/
  analyze.php
```

This directory is temporary staging infrastructure, not the final CVBrain product repository.

## Server-Side Proxy

Proxy:

```text
cvbrain-intake/api/analyze.php
```

Responsibilities:

- accept browser POST from the standalone screen.
- validate the page nonce/cookie.
- apply simple per-IP rate limiting.
- load server-side config from staging WordPress constants.
- call `POST /api/job-intake/analyze` on CVBrain.
- return only sanitized `display_plan` to the browser.

The proxy does not classify requirements, detect blockers, infer titles, build search concepts, or reconstruct intelligence if `display_plan` is missing.

If CVBrain does not return `display_plan`, the proxy returns:

```text
CVBrain no devolvió un plan de búsqueda normalizado.
```

## API Key Handling

The API key remains server-side.

Current config source:

- `TRABAJOACA_JOB_INTAKE_API_BASE_URL`
- `CVBRAIN_INTAKE_API_KEY`

The browser must never receive:

- `X-CVBrain-API-Key`
- `CVBRAIN_INTAKE_API_KEY`
- `TRABAJOACA_JOB_INTAKE_API_BASE_URL`
- raw env values

## Noindex and Rate Limit

The page includes:

```html
<meta name="robots" content="noindex,nofollow">
```

The proxy also sends:

```text
X-Robots-Tag: noindex, nofollow
```

Rate limiting is simple staging protection:

- per IP
- temporary file in server temp directory
- current limit: 20 requests per hour

This is acceptable for staging demo use. A future standalone CVBrain product should use stronger auth, abuse protection, and monitoring.

## UI Behavior

The page renders:

- title: `CVBrain`
- subtitle: `Interpretá una búsqueda laboral antes de mirar CVs`
- large textarea
- `Interpretar búsqueda` CTA
- `Limpiar` secondary action
- short and long sample buttons
- blocking loading overlay
- elapsed timer
- truthful stage animation

Stage labels:

- Preparando el texto recibido.
- Identificando rol, seniority, ubicación y modalidad.
- Separando responsabilidades de requisitos.
- Clasificando indispensables, preferidos y valorables.
- Detectando herramientas, industria, credenciales y experiencia.
- Detectando criterios de no avanzar.
- Identificando dudas o información faltante.
- Validando la estructura final.
- Preparando el plan de búsqueda para QVs/CVs.

The stage animation is not a live backend progress stream. It is copy for real process stages only.

## Rendered Fields

The browser renders only `display_plan` fields:

- `role_title`
- `seniority`
- `market`
- `location_modality`
- `summary` / `what_to_search`
- `must_have`
- `preferred`
- `nice_to_have`
- `blockers`
- `tie_breakers`
- `questions`
- `search_concepts`
- `readiness.label`
- `readiness.severity`

No raw JSON is shown by default.

## Known Limitations

- staging-only.
- no user accounts.
- no persistent sessions beyond a simple nonce/cookie.
- no production-grade WAF or abuse controls.
- no live progress endpoint.
- no candidate search.
- no result persistence.
- no raw debug UI.
- depends on staging2 server-side constants for API URL/key.

## Validation Checklist

Run after changes:

```bash
php -l ~/www/staging2.trabajoaca.com/public_html/cvbrain-intake/index.php
php -l ~/www/staging2.trabajoaca.com/public_html/cvbrain-intake/api/analyze.php
```

Manual checks:

- public URL renders without WordPress admin chrome.
- HTML/JS do not expose API key names or values.
- no raw JSON is visible.
- short input returns `display_plan`.
- long input returns `display_plan`.
- missing `display_plan` shows friendly error.
- Super CV files are untouched.

## Rollback

Because the directory did not exist before creation, rollback is removal:

```bash
ssh trabajoaca 'rm -rf /home/u2088-ujxgrfoyqrdu/www/staging2.trabajoaca.com/public_html/cvbrain-intake'
```

Backup marker:

```text
/home/u2088-ujxgrfoyqrdu/cvbrain-intake-standalone-backup-20260616-no-existing-dir.txt
```
