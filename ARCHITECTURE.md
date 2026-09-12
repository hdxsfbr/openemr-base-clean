# Clinical Co-Pilot Architecture

## High-Level Architecture Summary

> **Hard-gate placeholder:** Replace this block with an approximately 500-word
> summary after `AUDIT.md` is complete. It should explain the user workflow,
> component boundaries, authorization model, data flow, verification design,
> failure behavior, observability, deployment shape, major tradeoffs, and known
> limitations. The summary must reflect audit evidence rather than simply repeat
> the pre-audit hypothesis below.

## Status

This document is an architecture hypothesis until the audit is completed and
the decisions are recorded. Do not represent planned controls as implemented.

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

### Agent service

A separately deployable orchestration service with strict request/tool schemas,
conversation state, bounded tool selection, structured LLM output, retries, and
timeouts. It receives neither database credentials nor unrestricted patient
access.

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

| Tool | OpenEMR service candidate | Use cases | Key failure states |
| --- | --- | --- | --- |
| Get encounter timeline | `EncounterService`, `ClinicalNotesService` | UC-01, UC-02, UC-03 | No prior encounter, unavailable note, malformed date |
| Get medications | `MedicationPatientIssueService` | UC-01, UC-03 | Conflicting status, missing dates, free-text name |
| Get problems | `ConditionService`, `PatientIssuesService` | UC-01, UC-03 | Duplicate/inactive issue, uncoded text |
| Get allergies | `AllergyIntoleranceService` | UC-01 | Missing reaction/status |
| Get lab observations | `ObservationLabService`, `ObservationService` | UC-01, UC-02 | Missing range/unit, incompatible units |
| Get patient context | `PatientService` | All | Wrong patient, insufficient ACL |

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

## Deployment and Operations

- TODO: Define TLS ingress, public/private services, network policy, secrets,
  database persistence, backup, restore, migration, and rollback.
- TODO: Keep development-only services and credentials out of the public stack.
- TODO: Define `/health` and meaningful `/ready` dependency semantics.
- TODO: Link alert definitions and the on-call runbook.

## Privacy and Compliance

- TODO: Create the PHI data-flow inventory.
- TODO: Document BAA assumptions for every third-party processor.
- TODO: Define audit events, retention, access review, incident response, and
  deletion behavior.
- TODO: State why the demo is not authorization for real clinical use.

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
