# Interview Notes: The Audit and the Decisions It Drove

Personal prep notes for the technical interview. Everything here is backed by
`AUDIT.md`, the detail docs in this folder, and the ADRs. Numbers were
re-verified against source and the database on 2026-09-14.

## The 30-second version

"We audited OpenEMR before writing any AI code. The finding that mattered:
OpenEMR authorizes by role and chart section, never by patient. We proved it
live: test accounts with no relationship to any patient opened arbitrary
charts, and each open was logged as a normal view. So the co-pilot cannot
inherit 'may this user see this patient' from the host. We decided to match
the chart exactly: bind every conversation to the open chart, re-run the
chart's permission checks per tool, audit every read, never let the model pick
a patient, and state plainly that isolation equals OpenEMR's. The other four
findings shaped the tool contracts: data that contradicts itself, services
that fail silently, an audit log the co-pilot would bypass, and a deployment
edge that forwarded every path."

## The five findings, in the order they affect the design

### 1. No patient-level authorization (SEC-HIGH-001 / ARCH-HIGH-003)

- **What:** `AclMain::aclCheckCore($section, $value, $user, ...)` has no
  patient argument. Only 4 of 310 classes under `src/Services/` reference it,
  none clinical. REST/FHIR tokens are checked for role, scope, and section.
  The one patient hook, `checkUserHasAccessToPatient()`, is a `return true`
  stub used only during SMART launch binding. The in-session local API sets
  `skipAuthorization`.
- **Proof:** `docs/audit/evidence/security/live-cross-patient-test.md`.
  Physicians and Clinicians groups: HTTP 200 and all 12 clinical sections for
  two unrelated patients. Front Office: demographics, and 403 on the issue
  lists (so section ACL does work, patient ACL does not).
- **Is this a bug?** No. It is OpenEMR's design: any clinician may need any
  chart, and the audit log is the control. The PRD's "physician has access
  to their own patients" and "resident may be supervised" describe concepts
  the host does not have. That is almost certainly the exam question.
- **What we did:** ADR-0002, parity. See "Key decisions" below.
- **Don't overclaim:** the API path is code-verified, not live-tested; the
  APIs are disabled on our deployment. The stub governs SMART launch binding
  only; the broader point is that clinician tokens have no patient filter at
  all.

### 2. The data cannot support the use case and contradicts itself (DQ-*)

- **What:** demo data is 3 patients, one 2014 encounter each, 0 lab results,
  3 placeholder SOAP notes ("Toe hurts"). Every problem, allergy, and
  medication has an empty onset date. Modification timestamps all record one
  install-time job. The single prescription is active in `prescriptions` and
  inactive in `lists`; the chart greys medications by `enddate` while
  `PrescriptionService` reports "stopped" by `activity`, so they disagree on
  the same row.
- **What we did:** tools normalize status and dates, flag conflicts, and
  return three absence states: documented / reviewed-none / not documented,
  plus "unavailable" for failures. Built `af-cohort-v1`, 26 deterministic
  synthetic patients that plant each defect (`evals/fixtures/cohort/`).
- **Why not `import-random-patients`?** Synthea output, no fixed seed, needs
  Java and internet in the container, not reproducible. Fine for load volume,
  useless as eval fixtures.

### 3. Silent failure below the agent (PERF-MED-001, DQ-MEDIUM-014)

- **What:** `ProcedureService::getAll()` has a dangling `LEFT JOIN` before
  `WHERE` (`ProcedureService.php:648`); REST `/api/procedure` is broken.
  `ConditionService` left-joins `issue_encounter` and returns one row per
  linked encounter: 26 rows for 7 conditions on the synthetic heavy patient.
- **What we did:** every tool returns `ok | empty | partial | unavailable`;
  dedupe by record identity; labs via `ProcedureService::search()`, which
  works. The verifier rejects "no X" unless retrieval reported `ok` or
  `empty`.
- **Line to use:** "'No labs documented' could mean a crashed query. That is
  the worst kind of hallucination because it is confidently absent."

### 4. Audit logging and telemetry (COMP-HIGH-001/002/004, COMP-MED-003)

- **What:** `audit_events_query` is off, so SELECTs are not logged and
  co-pilot reads would leave no trail unless we write one. Log integrity is
  `hash('sha3-512', ...)` over the row values, no key, stored in
  `log_comment_encrypt` next to the rows. `api_log_option` defaults to 2,
  "Full", which stores API response bodies (PHI) in the database. Hosted
  tracing (LangSmith etc.) would be a business associate with no BAA.
- **What we did:** the gateway writes a `copilot-*` audit event through
  `EventAuditLogger::newEvent()` before returning data. Telemetry carries
  IDs, counts, latency, tokens, cost, verification outcome only, or the
  tracer is self-hosted (Langfuse). Prompts and responses never go to
  ordinary logs.
  As built (2026-09-16): events are `copilot-session-start`,
  `copilot-tool-read`, `copilot-denied`, `copilot-session-end`; the tracer is
  hosted Langfuse with a client-side mask that digests every payload
  (ADR-0007), verified by read-back, not self-hosted. Model and verifier
  outcomes go to the trace and `/metrics`, not the OpenEMR log.
- **BAA answer:** the PRD lets us assume one with the LLM provider. Minimum
  necessary still applies: tools send projected, windowed fields, no direct
  identifiers where avoidable. An LLM BAA does not cover a tracing vendor.

### 5. Deployment exposure (SEC-HIGH-500/501/502)

- **What:** the official `openemr/openemr:8.1.1` image copies the whole
  repository into the web root. Our Caddy was `reverse_proxy openemr:80` with
  no path filter. Probe results: `docker/development-easy/docker-compose.yml`
  200, a dev MariaDB private key 200, a unit-test RSA key 200,
  `composer.lock` 200. Both pinned images have fixable Critical CVEs (8 and
  6).
- **Whose fault:** the served files are upstream fixtures; nothing we
  generated leaked (file secrets, internal DB network, generated passwords).
  The forwarding is ours. OpenEMR's own Apache config does deny
  `sites/*/documents`, so per-site OAuth keys were not exposed.
- **What we did:** deny-by-default Caddy path allowlist is P0 before any
  agent component or LLM key deploys. CVEs documented, not patched.
  Done 2026-09-15: the probe rerun shows every sensitive, API, and OAuth path
  at 404 (`evidence/security/cloud-probe-2026-09-15-allowlist.txt`); the
  co-pilot ships in a project image that adds only the module.
- **Ranking honesty:** this was #2 in an earlier draft on evidence strength.
  It moved to #5 because it changes a config file, not the design.

### Performance (not a top finding, but the number people ask about)

- Dashboard render: p50 ≈ 360 ms, 1,045 SQL statements, of which 431 are
  translation lookups, 104 layout, 112 phpGACL, 50 list labels. Clinical
  data is a small share. Barely changes with chart size (+3% for the 5-year
  synthetic patient).
- Services in-process: 1 to 25 ms per call, p95 ≤ 37 ms on the heavy
  patient.
- FHIR `metadata` on the Droplet: p50 689 ms, p95 ≈ 1 s. HTTP fan-out is
  expensive; in-process is not.
- Raw payload for the 5-year patient: 169 KB ≈ 42K tokens (bytes ÷ 4
  heuristic). **Context size, not OpenEMR, is the latency and cost driver.**
- Apache prefork, 60 s PHP limit: model calls cannot run inside PHP.
- Not measured: authenticated latency on the Droplet, 10/50-user load, p99,
  model latency, real tokenizer counts. Scheduled, not claimed.
- Update 2026-09-16: model latency and per-turn tokens are now measured on
  the deployment (Sonnet 5): p50 12.1 s, p95 27.6 s, p99 40.8 s over 120
  model-backed turns; 608 in / 1,170 out / 5,106 cache-read tokens and about
  $0.013 per turn (`evals/results/2026-09-16T073141Z-1ddf824.md`). The 30 s
  p95 is provisional (ADR-0004); the 8 s goal is tracked, not met. Still not
  measured: load at 10/50 users, authenticated dashboard latency.

## Key decisions and why

### Parity, not a stricter policy (ADR-0002)

- **Decision:** the co-pilot sees exactly what the user could see by
  clicking. Checks per tool call: live session; conversation bound to (site,
  user, pid); session pid equals conversation pid or the conversation closes;
  the chart's section ACL (`aclCheckCore`/`aclCheckIssue`); squad; not
  break-glass. One adapter builds an immutable `AuthorizedPatientContext`;
  tools never touch session, ACL, or a raw pid.
- **Why not stricter (schedule / encounter provider / care team):** it is
  stricter than the host, produces false denials for covering clinicians and
  nurses, depends on three data sources real sites keep badly, and costs
  about a week. It is fully designed in the ADR as the deferred alternative,
  so the seam exists.
- **Why it is still real work:** OpenEMR's services enforce nothing, so
  "defer to OpenEMR" without re-running its checks would be weaker than the
  chart, not equal to it.
- **Limitation, stated everywhere:** any clinician can summarize any chart.
  Bounded by one patient per conversation, no patient lookup tool, and an
  audit row per read.
- **Upstream drift:** we call the same ACL checks the chart pages make
  (`aclCheckCore`, `aclCheckAcoSpec` on `issue_types.aco_spec`, the squad
  check). Dispatching `ViewEvent` so a future patient filter applies to us is
  planned in ADR-0002 but **not implemented** as of 2026-09-16 (no reference
  in the module); say "planned", not "does".
- **What broke once:** `AclMain::aclCheckIssue()` returned true for every
  user in the session-less gateway request because the issue-type table is
  loaded at page scope. Front Office briefly received problems and allergies
  through the co-pilot on the first live role test (2026-09-15). Fixed the
  same day by reading `issue_types.aco_spec` directly and failing closed;
  `bin/acl_matrix.php` and `AUTH-FRONTDESK-001` are the regression checks.
  Good answer to "what did the parity decision cost you."

### In-process module gateway, SMART on FHIR deferred (ADR-0003)

- **Decision:** custom module renders the panel via
  `PatientDemographics\RenderEvent`; a module endpoint mints a short-lived
  delegation token bound to the conversation; a separate agent service
  exposes the HTTP API (what the Postman/Bruno collection drives) and calls
  back into module tool endpoints; tools run in-process and return typed,
  status-bearing records.
- **Why not SMART:** same authorization semantics (role, scope, section, no
  patient), so no isolation gain; APIs are disabled on the deployment and
  enabling them brings back permissive defaults; FHIR `metadata` p95 ≈ 1 s
  versus milliseconds in-process; FHIR coverage gaps for notes; eight
  configuration items must align before the first token (issuer URL, APIs
  on, client registration and approval, redirect URI, scopes, SMART app
  registration, per-site keys and TLS trust, refresh); the prior cohort lost
  days here.
- **When SMART wins:** a real product that must install on other OpenEMR
  sites without deploying a module, or on other EHRs. Standards-based,
  loosest coupling, automatic `api_log` trail, normalized FHIR resources.
  Say this out loud: "for a product, SMART is the right call; for a one-week
  embedded demo, it is the wrong trade."
- **Kept SMART-shaped:** `AuthorizedPatientContext` carries user, patient
  (pid and uuid), and sections mapped one-to-one to FHIR scopes. Under SMART
  the same object is built from `fhirUser`, launch `patient`, and granted
  scopes. Tools, agent, verifier, and evals do not change; tool bodies do.
- **PRD hint:** "embedded directly into OpenEMR", "integrate cleanly rather
  than bolt something on." No mention of SMART, FHIR, OAuth, or portability.
  The runnable API collection requirement means the agent needs a
  header-authenticated HTTP API either way.

### Documented, not fixed (AUDIT.md §7.3)

- We do not patch OpenEMR core, bump its dependencies, harden its container,
  or triage its 594 Semgrep results or 65 CSRF candidates. The audit plans
  the co-pilot. Each OpenEMR issue has three columns: why it stays, how the
  co-pilot is protected anyway, what a real deployment would need.
- Exception: our own deployment config (Caddy allowlist, image
  `.dockerignore`, agent secrets, APIs off) because the agent ships there.

### Synthetic cohort as a hard dependency

- Deterministic: fixed ids (pids 900001–900099, rows 9000001–9099999),
  fixed relative dates from an anchor, UUIDs assigned at insert so the
  table-wide backfill does not rewrite planted `modifydate` values (we hit
  this: identical loads had different checksums until fixed).
- Loaded on the deployment by a separate one-shot `demo-seed` job, never
  baked into the image, because the image must not contain `evals/`.

### PHI-free telemetry, self-hosted tracer preferred

- Access auditing goes to OpenEMR's audit log. Traces carry identifiers and
  metrics. Observability must not block care: buffer or drop spans on tracer
  failure, keep correlation-ID logs locally.

## Questions I expect, with short answers

- **"Is the `return true` stub really the API's patient check?"** Partly.
  The stub is real and ships in 8.1.1, but it only runs when a SMART launch
  binds a patient to a token. The larger truth: clinician tokens have no
  patient filter at all. Only role, scope, section.
- **"Isn't the deployment finding your own mistake?"** The served files and
  CVEs are upstream. Our edge forwarded every path, which is ours to fix and
  is fixed by the allowlist. None of our secrets leaked.
- **"Why not just trust OpenEMR's auth?"** We do, at the chart level. But its
  services enforce nothing, so the gateway has to re-run the chart's checks
  or the co-pilot would be weaker than the UI.
- **"Why not SMART on FHIR?"** Right for a product, wrong trade for this
  week: same isolation, slower calls, disabled API surface to reopen,
  coverage gaps, and an eight-item OAuth setup that cost the last cohort
  days. Seam kept so it can be swapped.
- **"What did you get wrong along the way?"** Overstated the stub as "the
  REST API's patient check"; corrected. Ranked deployment exposure #2 on
  evidence strength, moved to #5 on impact. Briefly committed to the stricter
  policy, then chose parity on review. Summary said "no notes"; there are
  three placeholder SOAP notes.
- **"What is unverified?"** Two-tab session test, squad-restricted live test,
  bearer-token request, CSRF triage, authenticated Droplet latency, load,
  model latency and cost, real data distributions, clinician validation of
  the workflow. (As of 2026-09-16: the squad case is live-tested through the
  gateway (`AUTH-SQUAD-001`), and model latency and cost are measured. Still
  open: browser two-tab test, `audit-nurse` role eval, break-glass eval,
  bearer-token request, CSRF triage, authenticated dashboard latency, load,
  real data distributions, clinician validation, `ViewEvent` dispatch, CSP on
  the panel, egress restriction.)
- **"Are you HIPAA compliant?"** No, and we say so. Demo system, synthetic
  data, no BAAs, no backups, no retention schedule, no tamper-evident audit
  sink. The audit lists what a real deployment would need.
- **"How did the audit change the plan?"** `AUDIT.md` §8, seven rows. The
  three biggest: authorization is our decision, not inherited; tools return
  normalized, status-bearing, deduplicated, windowed records; the co-pilot
  ships in our own image behind a deny-by-default edge.
- **"Why is performance not a top finding?"** Because OpenEMR is fast where
  we need it. The cost is page rendering (which we never do) and model
  context (which we control).

## Numbers to have ready

| Number | Meaning |
| --- | --- |
| 4 / 310 | service classes referencing `AclMain` / total under `src/Services/` |
| 12 | clinical sections rendered for unrelated patients by Physicians and Clinicians |
| 3 / 1 / 0 / 3 | demo patients / encounters each / lab results / placeholder notes |
| 26 for 7 | `ConditionService` rows for conditions on AF-HEAVY |
| 360 ms / 1,045 | dashboard p50 / SQL statements per load |
| 1–25 ms | in-process service call latency |
| ≈1 s | FHIR `metadata` p95 on the Droplet |
| 169 KB ≈ 42K tokens | raw 5-year chart payload |
| 8 / 6 | fixable Critical CVEs, OpenEMR and Caddy images |
| 26 | synthetic patients in `af-cohort-v1` |
| 60 s | PHP execution limit under Apache prefork |
| 45 / 44 | eval cases on disk (2026-09-16) / cases in the last recorded full runs |
| 27.6 s / $0.013 | p95 complete verified response / list-price cost per model-backed turn (run `1ddf824`, n=120) |

## Things not to say

- "OpenEMR has a security bug in authorization." It is a design, not a bug.
- "The API's patient check is a stub." Say "clinician tokens have no patient
  filter; the one hook is a stub used for SMART launch."
- "We secured OpenEMR." We designed around it and fixed our own edge.
- "We measured performance under load." We measured a baseline.
- "HIPAA compliant."

## Glossary pointer

EHR, PHI, BAA, FHIR, SMART, OAuth2, scope, ACL, squad, pid, break-glass,
Trivy, Semgrep, CVE, p95: one-line definitions are in `docs/GLOSSARY.md`.
