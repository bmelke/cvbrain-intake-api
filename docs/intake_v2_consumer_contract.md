# CVBrain Intake API V2 Consumer Contract

WordPress must call the CVBrain API server-side only and render response safely. WordPress must not contain AI/domain interpretation and must not call OpenAI directly. This is the consumer contract for future TrabajoAca consumers of CVBrain Intake API V2. CVBrain is the semantic brain. TrabajoAca/WordPress/UI only consume and render CVBrain API responses; they do not add semantic intelligence.

This document is operational and contractual only. It does not authorize WordPress implementation. WordPress adapter work requires a later separate gate.

## Endpoints And Auth

Consumers use only these CVBrain Intake API V2 endpoints:

- `GET /intake/v2/status`
- `POST /intake/v2/analyze` accepts JSON with non-empty `source_text`; `source_language` must be explicit. The explicit value may be a known language code/name or `auto`. When `source_language` is `auto`, CVBrain AI determines the source language from `source_text`; the consumer must not infer source_language in PHP. The consumer must not correct grammar in PHP and must not classify, normalize, map, or reinterpret job/domain content before sending.

Consumers send V2 authentication with:

- `X-CVBrain-V2-API-Key`

The `X-CVBrain-V2-API-Key` value is server-side only. It must never be exposed in browser JavaScript, public HTML, logs, analytics, or client-side config. Use a clearly marked placeholder such as `<server-side-v2-api-key>` in documentation and tests, never a real API key or real token.

For V2, these legacy or alternate auth names must not be used as fallback:

- `X-CVBrain-API-Key`
- `X-TrabajoAca-API-Key`
- `Authorization: Bearer`

Each legacy or Bearer auth option above is listed only to say it must not be used as fallback for V2.

## Analyze Request

`POST /intake/v2/analyze` accepts a JSON body with:

- `source_text`
- `source_language`

`source_text` must be non-empty. `source_language` must be explicit. Consumers may send `source_language` as `auto` so CVBrain AI determines the source language from `source_text`. The consumer must not infer source_language in PHP. The consumer must not correct grammar, spelling, punctuation, accents, typos, titles, licenses, credentials, locations, numbers, or domain wording in PHP. The consumer must not classify, normalize, map, or reinterpret job/domain content before sending.

The consumer passes the recruiter input as source text, represented only by a placeholder such as `<source text from recruiter input>` in documentation. Do not include real job descriptions, CV data, recruiter data, company names, email addresses, phone numbers, addresses, live CMS data, real site data, production records, private operational content, or semantic expected outputs.

## Request Limits

Consumers must precheck mechanical request limits before sending:

- request body `<= 262144` bytes
- `source_text <= 50000` characters

If the request body limit or `source_text` limit is exceeded, the consumer should avoid sending the request when possible and handle `413` too large safely if CVBrain returns it.

## Success Response

Successful responses use the public response envelope with schema version:

- `cvbrain_intake_v2_public_response`

Top-level success fields include:

- `ok`
- `status`
- `schema_version`
- `display_plan`
- `metadata`

Consumers should render safe response and display fields from `display_plan` and `metadata`. Consumers must not reinterpret semantic output from `display_plan`, must not remap it into local semantic categories, and must not derive new meaning from CVBrain-owned text.

`display_plan` is the recruiter-facing Search Brief contract. Consumers render these CVBrain-owned sections separately:

- `comparison_basis`: what CVBrain will use to compare CVs.
- `must_have_criteria`: explicit hard requirements preserved by CVBrain.
- `nice_to_have_criteria`: preferred or appreciated items preserved by CVBrain.
- `questions_for_recruiter`: recruiter/company questions, including experience clarification for the most relevant missing dimensions and not every possible question, kept separate from criteria; consumers must not infer must-have or nice-to-have criteria, must not generate missing criteria, and PHP/WordPress must not classify experience from these questions.
- `missing_information_or_blockers`: missing information or blocker signals.
- `search_readiness`: search recommendation/readiness values from CVBrain, including the AI-owned `recommendation_summary` human-readable recruiter-facing text.
- `recommended_next_steps`: safe next-step guidance from CVBrain-owned readiness data, rendered from the AI-owned `recommended_next_steps` human-readable recruiter-facing list.

Consumers must render criteria and questions separately. Consumers must not infer must-have or nice-to-have criteria from `questions_for_recruiter`, must not generate missing criteria themselves, and must not move questions into criteria. CVBrain owns semantic interpretation.

Consumers may render `search_readiness` to show whether search is recommended with the current information, possible but should be clarified, or not recommended yet because key information is missing. Consumers render `recommendation_summary` as AI-owned human-readable recruiter-facing readiness text and may render `recommended_next_steps` as AI-owned human-readable recruiter-facing next steps. Consumers must not generate search readiness, recommendation summaries, or recommended next steps themselves.


## Global Vague-Experience Clarification

Experience clarification is AI-owned by CVBrain. Vague experience requirements are a global intake-risk pattern, not a role-specific exception. When source text mentions experience, background, track record, prior similar roles, hands-on work, domain exposure, or experience with tools, tasks, people, industries, volumes, clients, payroll, operations, sales, logistics, or other work scopes without enough definition, CVBrain should ask the most relevant missing clarification questions and not every possible question.

The global vague-experience clarification dimensions are duration/time, similarity, depth, scale/volume, recency, evidence, and criticality. CVBrain may ask how much time is expected, what roles/tasks/industries/contexts count as similar, whether the candidate must lead/supervise/own/execute/assist/advise, what scale or volume matters, whether the experience must be recent, what evidence validates it, and whether it is required, excluding, preferred, or helpful.

Consumers render those CVBrain-owned questions in `questions_for_recruiter`. Consumers must keep experience questions separate from criteria, must not move questions into must-have or nice-to-have criteria, and must not generate criteria from missing experience details. Experience clarification must not be classified in PHP, WordPress, or other consumers; consumers must not classify experience, infer duration, infer similarity, infer depth, infer scale, infer recency, infer evidence, infer criticality, or add keyword dictionaries/fallback semantic logic.

Soft-skill assessment boundary: traits such as confiable, responsable, pulcro, proactivo, ordenado, autónomo, or comprometido may be rendered if CVBrain includes them, and CVBrain may ask what observable behaviors or evidence matter. The recruiter/team owns assessment technique; consumers must not invent interview technique or make the hiring company choose a technique.

Protected traits: age, sex, gender, and similar protected traits must not become criteria. If source text says those traits are not relevant, consumers should render only CVBrain's safe public output and must not create protected-trait criteria.

Contractual/business baseline: when absent and relevant, CVBrain may ask recruiter/company questions about salary, contract mode, schedule, availability, location/work modality, start date, and similar business conditions. Consumers render those questions only; they must not answer or infer them.

## Safe Error And Unavailable Handling

Consumers must handle these statuses safely:

- `400` request validation: show a safe request validation state.
- `401` unauthorized: show a safe unauthorized state.
- `413` too large: show a safe too large state.
- `503` unavailable: treat as retry/degraded unavailable state.

Do not expose secrets. Do not expose raw source text. Do not expose prompt text. Do not expose provider payload or provider output. Do not expose raw exception text.

## Semantic Ownership Boundary

CVBrain is the semantic brain. TrabajoAca/WordPress/UI only consume and render.

Forbidden consumer behavior:

- No role/title interpretation in WordPress/PHP.
- No license interpretation in WordPress/PHP.
- No credential interpretation in WordPress/PHP.
- No blocker interpretation in WordPress/PHP.
- No required/preferred/nice-to-have interpretation in WordPress/PHP.
- No source_language inference in WordPress/PHP.
- No grammar correction in WordPress/PHP.
- No domain phrase mapping in WordPress/PHP.
- No hardcoded title/role dictionaries in WordPress/PHP.
- No fallback semantic logic in WordPress/PHP.
- No direct OpenAI calls in WordPress/PHP.
- No provider execution logic in WordPress/PHP.

## Security And Logging

Consumers must not log, store, or expose raw source_text, raw source text, prompts, provider payloads, provider raw output, or raw exceptions. Consumers must not log, store, or expose:

- V2 API key
- auth headers
- raw source_text
- prompts
- provider payloads
- provider raw output
- raw exceptions
- OpenAI keys
- model/env values

Consumers may log only safe operational metadata that does not include secrets, auth material, source content, prompts, provider payloads, provider raw output, raw exception text, OpenAI keys, or model/env values.

## WordPress Adapter Boundary

This doc does not authorize WordPress implementation. WordPress adapter work requires a later separate gate.

WordPress must call CVBrain API server-side only. WordPress must render response safely. WordPress must not contain AI/domain interpretation. WordPress must not call OpenAI directly.

WordPress adapter work must not add role/title interpretation, license interpretation, credential interpretation, blocker interpretation, required/preferred/nice-to-have interpretation, source_language inference, grammar correction, domain phrase mapping, hardcoded title/role dictionaries, fallback semantic logic, direct OpenAI calls, or provider execution logic.

## Staging And Live Smoke Separation

Live smoke is separate from consumer integration. No default live smoke. No consumer-triggered live smoke. No WordPress-triggered live smoke.

Staging analyze smoke does not authorize adapter work. Staging analyze smoke is only a separate, explicitly approved operational check and does not authorize WordPress adapter work, UI changes, production data usage, live smoke by default, or consumer-triggered live smoke.

## Secret And Data Safety

Do not include literal secrets, realistic secret examples, real API keys, real tokens, provider credentials, auth header values, source documents, provider payloads, provider output, or raw exceptions in consumer docs, tests, logs, or examples.

Safe placeholders are allowed only when clearly placeholders:

- `<server-side-v2-api-key>`
- `<source text from recruiter input>`
