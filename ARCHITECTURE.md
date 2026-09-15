# Clinical Co-Pilot Architecture

## High-Level Architecture Summary

> **Hard-gate placeholder:** Replace this block with an approximately 500-word
> summary after `AUDIT.md` is complete. It should explain the user workflow,
> component boundaries, authorization model, data flow, verification design,
> failure behavior, observability, deployment shape, major tradeoffs, and known
> limitations. The summary must reflect audit evidence rather than simply repeat
> the pre-audit hypothesis below.

## Status

The audit is complete and owner-reviewed (2026-09-14). This document remains
the pre-audit hypothesis until it is revised against `AUDIT.md` §8 ("How the
Audit Changed the Agent Plan"). Facts the audit has already established are
marked **Audit note** below. Do not represent planned controls as implemented.

## Goals and Constraints

- Support the use cases defined in `USERS.md` inside the existing patient chart.
- Keep patient-specific data within the authenticated and authorized request
  scope.
- Ensure all factual claims are attributable and verified before display.
- Return useful evidence within the physician's short preparation window.
- Degrade safely when OpenEMR, a tool, the model, or observability is impaired.
- Use demo data only during this project.

## Context and Components

### OpenEMR module

Candidate integration: a custom module using existing patient-demographics or
page-heading render events. It owns the chat interface, displays citations and
verification state, and receives active-user/patient context from OpenEMR.

### Clinical-data gateway

An OpenEMR-side boundary that authenticates the current session, validates the
active patient, applies ACL checks for every tool call, emits audit events, and
returns minimum-necessary typed data. It is the only agent component allowed to
access OpenEMR clinical services.

**Audit note:**
- OpenEMR has no patient-level authorization (SEC-HIGH-001, confirmed live),
  and its services enforce no ACL (ARCH-HIGH-002). The gateway must make the
  authorization decision itself on every tool call; nothing below it will.
- The session `pid` is a single mutable value set before authorization
  (SEC-HIGH-002). Treat it as a request, and bind each conversation to
  (site, user, pid) server-side.
- Decided (ADR-0002): **parity with the chart.** The gateway binds each
  conversation to the open chart, re-runs the chart's section ACLs per tool,
  denies break-glass, audits every read, and never lets the model choose a
  patient. Isolation therefore equals OpenEMR's, stated as a limitation; a
  stricter care-relationship policy is designed and deferred.
- Decided (ADR-0003): **in-process module gateway** plus a separate agent
  service with its own header-authenticated HTTP API, joined by a short-lived
  delegation token. SMART on FHIR is the deferred product-grade integration.
  The identity and authorization TODOs below are resolved by those two
  records and will be folded into this document in the audit-driven revision.

### Agent service

A separately deployable orchestration service with strict request/tool schemas,
conversation state, bounded tool selection, structured LLM output, retries, and
timeouts. It receives neither database credentials nor unrestricted patient
access.

**Audit note:**
- Apache prefork with a 60 s PHP limit cannot host model calls
  (ARCH-MEDIUM-006), so orchestration runs outside PHP.
- Do not use the OAuth password grant or system scopes (SEC-MED-005). A
  service token would discard user identity.

### Verification layer

A deterministic post-generation boundary that resolves every claim's source
IDs against the retrieved evidence, validates relevant value/date/unit fields,
enforces domain policies, and withholds unsupported output.

### Observability stack

Structured logs, metrics, and traces joined by one correlation ID. It must show
request count, errors, p50/p95 latency, tool calls/failures, retries, in-flight or
queue depth, verification pass/fail, tokens, and cost without placing raw PHI in
ordinary operational telemetry.

## Request Flow

TODO: Add a sequence diagram showing authentication, authorization, parallel
retrieval, LLM generation, verification, rendering, audit logging, and failure
branches.

## Identity, Authorization, and Trust Boundaries

- TODO: Document the exact OpenEMR session and ACL APIs used.
- TODO: Define short-lived delegation claims and validation.
- TODO: Define patient-context locking across multi-turn follow-ups.
- TODO: Define denial and break-glass behavior.
- TODO: Prove unauthorized requests do not invoke tools or the LLM.

## Canonical Contracts

- TODO: Select the source-of-truth schema technology.
- TODO: Define conversation request/response and error envelopes.
- TODO: Define every tool input/output schema.
- TODO: Generate downstream types rather than maintaining parallel hand-written
  contracts.
- TODO: Define versioning and backward-compatibility policy.

## Data Retrieval and Tool Design

Candidate read-only tools:

| Tool | OpenEMR service candidate (audit-verified behavior) | Use cases | Key failure states (audit finding) |
| --- | --- | --- | --- |
| Get encounter timeline | `EncounterService::getEncountersForPatientByPid`, `ClinicalNotesService::getClinicalNotesForPatient` (Clinical Notes form only) | UC-01, UC-02, UC-03 | No prior encounter (DQ-CRITICAL-001); empty note author (DQ-MEDIUM-008); zero-dates (DQ-MEDIUM-006) |
| Get medications | `PrescriptionService` (UNION of `prescriptions` and `lists`/`lists_medication`), `MedicationPatientIssueService` | UC-01, UC-03 | Two unlinked, conflicting sources (DQ-HIGH-003); `activity` vs `enddate` status conflict (DQ-HIGH-002); option-id dose fields (DQ-MEDIUM-010) |
| Get problems | `ConditionService` (returns one row per linked encounter; dedupe by `condition_uuid`), `PatientIssuesService::getActiveIssues` | UC-01, UC-03 | Duplicate rows (DQ-MEDIUM-014); NULL `begdate` (DQ-HIGH-004); ICD-9/uncoded text (DQ-HIGH-005) |
| Get allergies | `AllergyIntoleranceService` plus the `lists_touch` review marker | UC-01 | "Not documented" vs "reviewed, none" (DQ-MEDIUM-007); missing reaction/severity |
| Get lab observations | `ProcedureService::search()` with a `puuid` token (verified on synthetic data). **Not** `ProcedureService::getAll()`, which emits invalid SQL (PERF-MED-001). `ObservationLabService` not yet exercised | UC-01, UC-02 | Text/qualified values, missing unit/range/flag, corrected results (DQ-MEDIUM-009) |
| Get patient context | `PatientService::findByPid` | All | Wrong patient; no patient-level authorization in OpenEMR (SEC-HIGH-001) |

**Audit note:** raw service output for a five-year synthetic patient is about
169 KB, roughly 42K tokens (PERF-MED-005). Tools must project fields, apply a
time window, cap rows, and report truncation.

Each tool must define its authorization requirement, latency budget, timeout,
retry safety, source-reference format, audit event, and user-visible degradation
behavior.

## Conversation State

- TODO: Define storage, retention, encryption, and deletion.
- TODO: Bind state to authenticated user, site, patient, and conversation.
- TODO: Prevent follow-up messages from silently switching patient context.
- TODO: Define context-window and summarization limits.

## Verification Design

Every generated response should use a schema similar to:

- `claims[]`: concise display text plus typed facts and `source_ids[]`.
- `sources[]`: immutable references to records retrieved for this request.
- `limitations[]`: missing, conflicting, stale, or unavailable evidence.
- `verification`: machine-produced outcome, rejected claims, and policy rules.

The verifier—not the model—decides whether a claim can be displayed as fact.
TODO: Specify exact matching rules, supported domain constraints, retry/repair
behavior, and what remains vulnerable to semantic misinterpretation.

## Failure and Degradation Matrix

| Failure | Planned behavior | Must never happen |
| --- | --- | --- |
| Unauthorized patient/tool | Return a generic denial and audit it before retrieval | Sending patient data or request text to the LLM |
| One clinical tool times out | Return a marked partial response listing the unavailable source | Presenting omitted data as absence |
| LLM unavailable | Return a deterministic sourced summary where possible | Fabricating a normal response |
| Invalid structured model output | Validate, retry once if safe, then fall back | Rendering unvalidated text |
| Verification rejects a claim | Remove/withhold it and expose the limitation | Letting the model override verification |
| Observability unavailable | Preserve clinical response if safe; buffer minimal redacted operational data | Blocking care solely for analytics or leaking PHI into fallback logs |
| OpenEMR/database unavailable | `/ready` fails and UI displays dependency error | Claiming there are no records |

## Latency and Scale

- TODO: Allocate latency budgets across authorization, tools, model, verification,
  and rendering.
- TODO: Define safe parallel tool execution and concurrency limits.
- TODO: Define cache isolation and invalidation before enabling caching.
- TODO: Add measured 10- and 50-user baselines and scaling implications.

**Audit note** (`docs/audit/performance.md`):
- Measured single-request baselines: clinical services 1–25 ms in-process,
  including a 5-year synthetic chart; dashboard render ≈360 ms and ≈1,045 SQL
  statements; public FHIR `metadata` p95 ≈1 s.
- Proposed budget: gateway ≤50 ms, tool fan-out ≤300 ms, LLM ≤4 s,
  verification ≤150 ms.

## Deployment and Operations

- The accepted smoke-test baseline is recorded in
  [`docs/adr/0001-ephemeral-single-droplet-baseline.md`](docs/adr/0001-ephemeral-single-droplet-baseline.md):
  one DigitalOcean Droplet runs Caddy, OpenEMR, and MariaDB with Caddy as the
  only public application boundary and MariaDB on an internal network.
- Deployment credentials are generated on the host and kept out of cloud-init,
  Terraform state, and version control. The development-only services and
  credentials are absent from this stack.
- TODO: Replace the upstream baseline image with a pinned project image.
- TODO: Validate owned-domain TLS, database persistence, backup, restore,
  migration, and rollback against the completed audit.
- TODO: Define `/health` and meaningful `/ready` dependency semantics.
- TODO: Link alert definitions and the on-call runbook.

**Audit note:** the upstream image publicly serves private keys and the dev
compose file (SEC-HIGH-500, confirmed live), containers are unhardened, and the
DB root password sits in the web process environment (SEC-MEDIUM-503).
OpenEMR `readyz` is unusable as a readiness gate (SEC-MED-007). See
`docs/deployment/digitalocean.md`, "Before the Evaluator Deployment".

## Privacy and Compliance

- TODO: Create the PHI data-flow inventory.
- TODO: Document BAA assumptions for every third-party processor.
- TODO: Define audit events, retention, access review, incident response, and
  deletion behavior.
- TODO: State why the demo is not authorization for real clinical use.

**Audit note:** `docs/audit/compliance.md` already contains:
- the PHI data-flow inventory (§4);
- BAA implications, including that an LLM BAA does not cover hosted
  LangSmith/Langfuse (§4);
- proposed `copilot-*` audit events (§5);
- retention, breach-notification, and deletion procedures, demo vs real (§2, §6).

## Evaluation Strategy

See `evals/README.md`. Architecture changes must add or update tests for the
boundary, invariant, or regression risk they introduce.

## Decisions and Tradeoffs

Record accepted decisions under `docs/adr/` and link them here. At minimum,
defend module placement, data access boundary, agent framework, model choice,
state storage, verification approach, observability stack, and deployment model.

## Known Limitations

TODO: Maintain an honest list of unsupported clinical questions, unverified data
types, terminology limitations, residual model risk, and operational gaps.
