# ADR-0003: Integration Point — In-Process Module Gateway, SMART on FHIR Deferred

- **Status:** Accepted 2026-09-14
- **Status note (2026-09-16):** implemented as decided (module gateway and
  tools, agent service, delegation token: commits 83f33a6 and 948620f). The
  single token issued at panel render (§Decision 2) was refined into a
  per-turn ticket by ADR-0005 §2. Verification so far: the Bruno collection
  (`docs/api-collection/`, 21 requests, 41 assertions) passes against the
  deployed agent API as `audit-physician` (`docs/SUBMISSION_CHECKLIST.md`);
  gateway denials return 403 with a reason and a denial audit event
  (`Gateway/ContextBuilder.php`, `GatewayDenied`), and tampered or expired
  tokens are refused at the agent (`AUTH-TAMPER-001`, `AUTH-STALE-TICKET-001`);
  REST/FHIR remain unrouted at the edge
  (`docs/audit/evidence/security/cloud-probe-2026-09-15-allowlist.txt`); a
  single correlation id reconstructs a turn
  (`docs/operations/correlation-id-walkthrough.md`). Not yet measured: the
  tool fan-out p95 ≤ 300 ms on `AF-HEAVY` through the agent; `REG-HEAVY-001`
  bounds the whole turn at 45 s only, and per-tool gateway latency is
  recorded on Langfuse TOOL observations without a recorded p95.
- **Status note (2026-09-19):** `tools.php` now also accepts a batched
  request (`{"calls": [{"tool", "params"}, ...]}` → `{"results": [...]}`,
  `Gateway/BatchRunner.php`), so a turn's tool fan-out pays OpenEMR's
  `globals.php` bootstrap (translation/ACL/layout lookups, ~1,045 SQL
  statements measured per bootstrap, `docs/audit/performance.md`
  PERF-MED-002) once or twice per turn instead of once per tool — driven by
  `docs/audit/evidence/performance/droplet-tier-comparison-2026-09-18.md`
  finding the co-pilot's own tool-gateway traffic, not just staff chart
  opens, saturates OpenEMR CPU. The legacy single-tool `?tool=` request
  stays supported unchanged. Every check this ADR and ADR-0002 require —
  token verified once per request, context built once per request, and
  per-tool section ACL, audit-before-data, and run — still happens once per
  requested tool inside the batch loop; nothing is checked or audited once
  for the whole batch. Two consequences for this ADR's Verification section:
  the "six-tool fan-out p95 ≤ 300 ms" metric above is redefined as a batch
  p95 (still unmeasured); and per-tool gateway latency in Langfuse TOOL
  observations (`agent/app/graph/nodes.py`, `tool_observation`) now reports
  each tool's *outer* latency as roughly the shared batch's round-trip time,
  not that tool's own isolated network cost — each tool's own `latency_ms`
  in its envelope, timed inside PHP around just its `fetch()`, stays
  accurate. One accepted behavior change: a transport-level failure of the
  batch request (timeout, connection error) now marks every tool in that
  batch `unavailable` together, where previously only the one tool whose
  independent request failed would be affected — judged acceptable since
  the hop is internal-only (same docker network) and the actual common
  failure mode under load, OpenEMR/MariaDB timing out, stays isolated
  per-tool even inside a batch (`AbstractTool::run()`'s own catch).
- **Status note (2026-09-19, load-tested):** the accepted behavior change
  above was confirmed as the *dominant* real-world failure mode, not a
  theoretical edge case. Same-tier real-model load test at 15 concurrent
  users (`docs/audit/evidence/performance/batched-gateway-2026-09-19.md`):
  unavailable-tool counts by tool were `allergies`=8, `clinical_notes`=8,
  `lab_results`=8, `medications`=8, `problems`=8, `encounters`=2,
  `patient_context`=2 — an exact match to the two batch groups a first turn
  sends, meaning every failure was a whole-batch transport timeout, none an
  isolated per-tool fetch failure. The prediction two paragraphs up, that
  the common failure mode "stays isolated per-tool even inside a batch," did
  not hold at load; correlated within-batch failure is the actual common
  case once the Droplet's CPU is saturated (a batch takes long enough
  end-to-end to blow the client timeout before any individual tool's own
  exception path is ever reached). Still judged acceptable per the original
  reasoning — internal-only hop, tradeoff already named in Consequences —
  but the risk is real under load, not hypothetical.
- **Amended 2026-09-19 (brief on chart open, module 0.5.0):** the panel may
  now start the UC-01 brief itself as a chart finishes loading, instead of
  waiting to be clicked. *Why:* the first turn measured p50 9.2 s and p95
  24.8 s on the live suite (`evals/results/2026-09-19T230512Z-f4f69ab4.md`),
  and the moment this product is designed for is the 90 seconds between two
  visits (`USERS.md`); a quarter of that spent watching a spinner is the
  single worst thing about the panel. *What is unchanged:* the brief is the
  UC-01 starter question sent through the same path as a click — the user's
  session and CSRF, a per-turn ticket, the delegation token, the gateway's
  per-tool section ACL, audit-before-data, and the deterministic verifier.
  There is no new endpoint, no new authorization, and nothing the client
  asserts: `BriefPolicy` decides server-side and the panel obeys, the same
  way the agent's known-plan table matches on its own constants
  (`agent/app/graph/nodes.py`, `KNOWN_PLANS`). *What is changed:* retrieval,
  one model call, and the `copilot-tool-read` and `copilot-model-disclosure`
  audit rows now happen for a chart that was opened, where before they
  happened only for a chart that was asked about; `USERS.md`'s "nothing is
  retrieved before the click" holds only in mode `off`. The rows are still
  the physician's own read of a chart they opened, audited under their name.
  *Modes* (`COPILOT_BRIEF_ON_OPEN`, default `visit_today`): `off` restores the
  previous behaviour; `always` prepares a brief per chart open; `visit_today`
  prepares one only when the schedule shows a visit today for that patient.
  `visit_today` is the default because the brief exists for the 90 seconds
  before a visit, so a patient with no visit today is spend with no moment
  behind it; the cost is that it does nothing on a chart whose site has no
  schedule for today, including a cohort seeded at a past `DEMO_ANCHOR`, where
  `always` is the setting that shows the feature at all. No mode prepares a
  brief for a role the chart hides every clinical section from, or for a
  break-glass login, so front desk does not generate a denied turn per chart
  open. *Not an ADR-0002
  widening:* the only chart read is the one already open; the schedule
  question is "does this open chart have a visit today", never "which
  patients are on my schedule", so there is no patient lookup and no read of
  an unopened chart — the distinction `USERS.md` draws when it defers the
  UC-04 schedule sweep. *Residual risk:* spend on briefs nobody reads, which
  the funnel measures as `brief_started` against `drawer_open`
  (`docs/operations/usage-funnel.md`); a brief prepared at open and read
  minutes later is stale, so it carries the answer's own timestamp and the
  physician re-asks for the current state; and a page reload inside the
  brief's own 10-25 s window can pay for a second brief, which a 60-second
  per-tab guard narrows but does not close.
- **Date:** 2026-09-14
- **Owners:** Andre Batista (project owner)
- **Related requirements:** PRD "an AI agent embedded directly into OpenEMR";
  "integrate cleanly rather than bolt something on"; Stage 5 "where will your
  agent live, how will it access patient data, what are the authorization
  boundaries"; "export a runnable API collection covering the core agent
  endpoints"; separate `/health` and `/ready`; correlation IDs across service
  boundaries. `AGENTS.md`: the agent service never queries the database.
- **Related use cases:** UC-01, UC-02, UC-03 (`USERS.md`), all inside the
  open chart.
- **Related decisions:** ADR-0001 (single-Droplet deployment), ADR-0002
  (patient-scope authorization). `AUDIT.md` §3.4, §8 row 3;
  `docs/PRIOR_COHORT_LESSONS.md`.

## Context

The audit compared three ways for an agent to reach clinical data
(`AUDIT.md` §3.4): OpenEMR's internal PHP services called in-process, the
REST/FHIR HTTP API with OAuth2 tokens, and direct database access. Direct
access is forbidden by `AGENTS.md`. The remaining choice is between a custom
module that calls services in-process and a SMART on FHIR app that calls the
API with a per-user launch token.

Facts that bear on it:

- The REST/FHIR layer performs the same authorization the chart does (role,
  scope, section), no more. Neither route gives patient-level isolation
  (ADR-0002).
- REST and FHIR are disabled on the deployment. Enabling them reintroduces
  permissive defaults: self-registered clients auto-enabled, password grant
  on, full API logging with PHI response bodies (SEC-MED-005, COMP-HIGH-002).
- Latency: services answer in 1 to 25 ms in-process on a five-year synthetic
  chart; FHIR `metadata` was p95 about 1 s on the Droplet. A six-tool fan-out
  over HTTP is a material share of the latency budget (`AUDIT.md` §2).
- Coverage: the services reach every table the use cases need, including
  note forms and `pnotes`; FHIR exposes a subset, with clinical notes as
  `DocumentReference` only.
- Apache prefork with a 60 s PHP limit cannot host model calls
  (ARCH-MEDIUM-006); orchestration must run outside PHP either way.
- The previous cohort's largest time sink was OpenEMR's OAuth2 setup, a
  25-reply thread of 401s (`docs/PRIOR_COHORT_LESSONS.md`). SMART EHR launch
  needs roughly eight configuration items to align (issuer URL, APIs enabled,
  client registration and approval, redirect URI, scopes, SMART app
  registration, per-site signing keys and TLS trust, token refresh) before
  the first call succeeds.
- The PRD requires a runnable API collection: graders must drive the core
  agent endpoints from Postman or Bruno without reading source. The agent
  therefore needs its own HTTP API with header-token authentication under any
  architecture.
- Timeline: one week, educational project, single developer.

## Decision

**Build the co-pilot as an OpenEMR custom module plus a separate agent
service, with an in-process gateway as the only path to clinical data.
Defer SMART on FHIR as the product-grade integration.**

### Components and request path

1. **Module UI.** A custom module under
   `interface/modules/custom_modules/` renders the panel on the patient
   dashboard through `PatientDemographics\RenderEvent` (patient-scoped
   section hook, `AUDIT.md` §3.4). It runs under the clinician's session.
2. **Delegation.** On panel render, a module endpoint (session plus CSRF)
   creates a conversation bound to `(site, user, pid)` and issues a
   short-lived, signed **delegation token** carrying the conversation ID.
   The browser holds only this token for the agent API.
3. **Agent service.** A separately deployed container (outside PHP) exposes
   the co-pilot HTTP API: start conversation, send turn, get status,
   `/health`, `/ready`. Every request is authenticated by the delegation
   token in a header. This API is what the Postman/Bruno collection drives
   and what the dashboard measures. It holds the LLM key and nothing else.
4. **Gateway tool endpoints.** The agent calls back into the module's tool
   endpoints with the same delegation token. The gateway validates the
   token against the live session and conversation, builds the
   `AuthorizedPatientContext` (ADR-0002), writes the audit event, calls
   OpenEMR services in-process, normalizes, and returns typed records with a
   status. Tool schemas are the contract of record; the agent never sees a
   `pid`.
5. **Correlation.** One correlation ID is minted at the panel and carried
   through the module endpoint, agent API, tool calls, model calls,
   verifier, and audit events.

### Boundaries kept SMART-shaped

- `AuthorizedPatientContext` carries user, patient (pid and uuid), and
  allowed sections mapped one-to-one onto FHIR scopes. Under SMART the same
  object would be built from `fhirUser`, launch `patient`, and granted
  scopes; tools, agent, verifier, and evals would not change.
- Tool contracts are typed, versioned schemas independent of their
  implementation. Migrating a tool from `PrescriptionService` to
  `GET /fhir/MedicationRequest` changes its body, not its interface.

## Alternatives Considered

### SMART on FHIR EHR launch (the product-grade path)

- Benefits: no custom authorization code; standards-based; installable on
  any OpenEMR (enable APIs, register client, add to SMART apps list) and in
  principle on other SMART-capable EHRs; FHIR resources arrive normalized
  with coded statuses; `api_log` records every call automatically; loosest
  coupling to OpenEMR internals.
- Costs and risks: two to three days of OAuth configuration on the dev stack
  with bare 401/404 failures; re-enabling the API surface and hardening its
  defaults; HTTP latency per resource (FHIR `metadata` p95 ≈ 1 s on the
  Droplet); FHIR coverage gaps for notes and encounter forms; one-hour tokens
  and relaunch on patient switch; the launch-patient check is a stub, so
  isolation is unchanged; `api_log` stores PHI response bodies unless the
  site setting is changed.
- Reason deferred, not rejected: right architecture for a product that must
  install across sites or EHRs; wrong trade for a one-week embedded demo
  whose brief rewards embedding and a defended boundary, not portability.

### Agent service with a system-scoped API token

- Benefits: simplest client.
- Costs and risks: system scopes read every patient; the audit trail records
  the client, not the clinician; user identity is lost (SEC-MED-005).
- Reason rejected: violates "the system must know who is asking."

### Agent logic inside PHP

- Reason rejected: Apache prefork and the 60 s limit (ARCH-MEDIUM-006);
  model calls would hold workers.

### Direct database access from the agent

- Reason rejected: forbidden by `AGENTS.md`; no ACL, no audit, no patient
  binding.

## Consequences

### Positive

- User identity and the open patient come from the session with no second
  login and no OAuth plumbing.
- Millisecond tool latency leaves the budget to the model.
- The API surface stays disabled on the deployment; the only new public
  paths are the module endpoints and the agent API behind the Caddy
  allowlist.
- The agent API is a clean, header-authenticated HTTP service that the
  required Postman/Bruno collection and the dashboard can target directly.
- Full coverage of the tables the use cases need.

### Negative and residual risk

- **Bespoke, OpenEMR-only.** Installable on other OpenEMR sites as a module,
  not on other EHRs. Stated as a limitation.
- **Coupling to internals.** Three stable functions (`AclMain`,
  `PatientSessionUtil`, `EventAuditLogger`) plus the clinical service
  classes. Contained in the adapter and the tool layer; pinned by fixture
  tests so upstream change fails loudly.
- **We own the checks.** Services enforce nothing, so a forgotten ACL call
  is a leak the chart would not have (ADR-0002 §Negative).
- **Two hops instead of one.** Browser to agent to gateway. Mitigated by the
  delegation token and the correlation ID; measured in the load test.
- The delegation token is a new credential. Short-lived, bound to one
  conversation, validated against the live session on every gateway call,
  never stored in browser storage.

## Verification

- Postman/Bruno collection runs start-conversation, turn, and status against
  the deployed agent API with only a delegation token, and receives typed
  responses with correlation IDs.
- A gateway tool call without a valid delegation, or with one bound to
  another conversation or a closed session, returns 403 and writes only a
  denial event.
- Tool latency p95 ≤ 300 ms for the six-tool fan-out on `AF-HEAVY`
  (`AUDIT.md` §2 budget), measured through the agent, not in-process.
- `cloud-probe.sh` shows REST/FHIR still disabled and only allowlisted paths
  reachable after the module is deployed.
- One correlation ID reconstructs a full request from logs alone.

## Revisit Triggers

- A requirement to install the co-pilot on other OpenEMR sites without
  deploying a module, or on another EHR.
- Upstream FHIR coverage reaches the note and encounter-form types UC-01
  needs, and the OAuth configuration is scripted so the eight-item setup
  becomes repeatable.
- Tool latency through the gateway exceeds budget under load, making the
  in-process advantage moot.
- A real deployment, where the SMART path's standard audit trail and
  standards alignment outweigh the setup cost.
