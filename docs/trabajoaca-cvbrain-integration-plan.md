# TrabajoAca and CVBrain Integration Plan

Date: 2026-06-16

Status: internal integration plan. This document does not change WordPress, Super CV, CVBrain runtime behavior, database schema, candidate search, ranking, scoring, keys, staging configuration, or production.

## Direction

CVBrain is the intelligence provider. TrabajoAca is a client.

TrabajoAca should not own recruiter-intake semantics. It should call CVBrain and render the normalized response.

## Target Flow

```text
Recruiter text in TrabajoAca
  -> TrabajoAca server-side API call
  -> CVBrain /api/job-intake/analyze
  -> CVBrain normalized JSON + display_plan
  -> TrabajoAca renders display_plan
  -> later, recruiter explicitly triggers QV/CV search
  -> Super CV search/ranking handles candidate retrieval and ranking
```

## TrabajoAca Responsibilities

TrabajoAca should:

- collect recruiter text.
- optionally extract text from uploaded files before sending to CVBrain.
- send input to CVBrain server-side.
- keep API keys server-side.
- show loading, retry, and friendly error states.
- render `display_plan` after escaping output.
- preserve existing manual Super CV search.
- keep candidate search/ranking separate from intake.

TrabajoAca may:

- store or pass sanitized CVBrain output only after explicit product/privacy approval.
- map CVBrain normalized search intent into a Super CV preview search in a separate, explicit step.
- compare manual search versus CVBrain-generated query in preview/shadow mode.

## TrabajoAca Must Not Do

TrabajoAca should not:

- classify must-have, preferred, nice-to-have, or blockers.
- infer role titles.
- detect `no avanzar` or other blockers.
- clean semantic tokens from AI output.
- build search concepts.
- rewrite recruiter questions semantically.
- expose raw `job_intelligence` by default to non-technical users.
- expose raw OpenAI/provider logs.
- expose API keys, env vars, private config, candidate PII, or raw CV data.
- let intake directly rank or choose candidates.
- change Super CV ranking/search/scoring as part of intake rendering.

## Current TrabajoAca Consumption

Current staging surfaces include:

- WordPress Job Intake admin/prototype screens.
- standalone staging demo at `https://staging2.trabajoaca.com/cvbrain-intake/`.

The standalone demo is the preferred product-direction prototype because it treats CVBrain as the product and TrabajoAca as infrastructure only.

The previous WordPress UI can remain temporarily as a prototype, but future cleanup should simplify it to render CVBrain `display_plan` only.

## Search and Ranking Boundary

CVBrain intake output is search preparation, not candidate ranking.

CVBrain may return:

- role title.
- must-have/preferred/nice-to-have requirements.
- blockers.
- search concepts.
- normalized location/modality.
- recruiter questions.
- readiness.

Super CV / TrabajoAca search owns:

- candidate retrieval.
- ranking.
- scoring.
- match classes.
- recruiter-readable candidate explanations.
- safety and anti-discrimination checks for candidate search.
- benchmark preservation.

No intake change should silently replace manual search or alter current ranking.

## Future Implementation Steps

1. Update TrabajoAca Job Intake UI to prefer `display_plan`.
2. Remove duplicated semantic cleanup from WordPress UI code.
3. Keep API calls server-side.
4. Keep raw JSON/debug views restricted to admin/debug if still needed.
5. Add tests that WordPress does not reclassify requirements or reconstruct search concepts.
6. Add preview-only mapping from CVBrain normalized plan to Super CV query.
7. Only after review, allow explicit recruiter action to run QV/CV search.

## Done Criteria for TrabajoAca Cleanup

- WordPress renders `display_plan` directly.
- WordPress has no semantic classifier for intake display.
- WordPress does not infer blockers, titles, or search concepts.
- API key remains server-side.
- Super CV manual search behavior is unchanged.
- ranking/search/scoring files are untouched unless separately approved.
- no candidate PII is exposed or committed.
