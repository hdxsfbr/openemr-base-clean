# ADR-0014: Week 2 operational budgets and single-Droplet deployment

- **Status:** Accepted 2026-09-21 (owner approval)
- **Date:** 2026-09-21
- **Owners:** Andre Batista (Week 2 operations, privacy, and deployment)
- **Related requirements:** Week 2 PRD observability and cost tracking, deployed
  core flow, PHI-safe logs, cost/latency report, and inspectable worker
  handoffs. `AGENTS.md`: safe failure, one correlation ID, bounded dependencies,
  reproducible evidence, and no raw PHI in ordinary telemetry.
- **Related use cases:** UC-01 and UC-02; document extraction and bounded
  guideline evidence in the pre-visit workflow.
- **Related decisions:** ADR-0001 (single-Droplet baseline), ADR-0004 (model and
  budgets), ADR-0005 (state retention), ADR-0007 (telemetry), ADR-0009
  (extraction bounds), ADR-0010 (retrieval), ADR-0011 (document records), and
  ADR-0013 (supervisor and worker handoffs).

## Context

Week 2 adds a 95-second document job, retained OCR evidence, approximately
484 MiB of local retrieval-process RSS, and CPU inference to a Week 1 host
whose OpenEMR and MariaDB services already degrade between 10 and 15
concurrent turns. The existing deployment also has controls that are suitable
only for its synthetic-data demo: content traces and fault injection default
on, the 24-hour checkpoint purge is not scheduled, tracer failure makes the
whole service unready despite telemetry being non-blocking, and the process-
local token halt omits planning and cache-write usage. Those observations are
not evidence that the Week 2 controls below are implemented.

## Decision

1. The normative operational contract is
   [`docs/specs/week2-operational-budgets.md`](../specs/week2-operational-budgets.md).
   It fixes the PHI-safe audit/event fields, trace and metric topology,
   correlation rules, retention, latency and cost gates, capability readiness,
   degradation behavior, storage limits, deployment shape, and report evidence.
2. Week 2 remains on one host but moves to a DigitalOcean `c-4`: four dedicated
   vCPUs, 8 GiB RAM, and 50 GB disk. OpenEMR, MariaDB, chat/supervisor,
   extraction, retrieval, alerts, and Caddy remain isolated services. Extraction
   concurrency is one and retrieval concurrency is two. No Redis, additional
   database, or self-hosted tracer is added.
3. Operational telemetry is PHI-free by default and cannot block a clinical
   response. OpenEMR audit rows retain the patient-bearing access trail;
   ordinary logs, metrics, traces, handoffs, and checkpoints exclude raw
   documents, OCR, values, excerpts, questions, prompts, and answers. Content
   tracing and fault injection are prohibited outside an explicitly synthetic
   demo.
4. Readiness is capability-scoped. Core authorization, state, gateway, contract,
   and verifier failures make the service unready. Model, document, guideline,
   tracer, and alert dependencies report independent readiness and invoke their
   typed safe-degradation behavior; tracer failure never makes core readiness
   fail.
5. The accepted latency gates retain the 30-second complete-turn target and
   45-second release block, add a 90-second extraction p95 under the existing
   95-second cap, and require guideline retrieval p95 at or below 1.5 seconds
   under a two-second hard deadline. The exact component gates are normative in
   the supporting specification.
6. Chat retains its `$0.0223` target and `$0.0446` release block. Extraction
   targets p95 at or below `$0.10` and is capped at `$0.15` per document. A
   restart-safe combined dollar ledger warns at `$14` and refuses new model
   spend at `$20` per UTC day. It accounts for every model path and token class;
   the existing process-local token counter is not sufficient.
7. Source records and immutable OCR/review evidence follow the OpenEMR record
   lifecycle. Transient renders and crops are deleted at completion or by a
   one-hour crash sweeper; conversations and checkpoints are deleted 24 hours
   after close. Each source permits at most three immutable extraction versions
   and each version must fit the stricter OCR/storage envelope in the supporting
   specification. Existing versions are never deleted to admit another.
8. None of these choices is considered implemented or release-ready until the
   co-located deployment, privacy, degradation, cost, storage, and latency
   evidence required by the supporting specification passes.

## Alternatives Considered

### Keep the shared 2-vCPU / 4-GiB host

Rejected because it is already CPU-bound before adding OCR and local retrieval,
and the retrieval benchmark reaches the two-second deadline at ten workers on
a much larger workstation.

### Make every dependency part of one readiness bit

Rejected because it turns a tracer outage into a clinical outage and prevents
the already-designed deterministic fallback and lane-specific limitations.

### Retain content traces for easier debugging

Rejected as the operational default because prompts, evidence, OCR, and answers
are sensitive. Synthetic fixtures and explicit synthetic-only content capture
remain available for error analysis.

### Keep token-only, process-local spend controls

Rejected because they omit billing classes and model paths, reset on restart,
and cannot enforce one limit across chat and extraction workers.

## Consequences

- The c-4 costs more than the current demo host and has less disk than the
  current shared-CPU tier, so disk budgets and cleanup are release controls.
- One host remains one failure domain. The chosen topology buys measured CPU
  headroom without adding a distributed queue or database during the sprint.
- Capability readiness preserves useful safe paths during partial outages but
  requires the UI and supervisor to present each unavailable capability
  explicitly.
- Immutable evidence and the three-version limit preserve provenance at the
  cost of refusing a fourth extraction rather than silently overwriting or
  deleting history.
- The dollar halt requires pre-call reservation and durable settlement; a
  post-call metric alone cannot prevent overspend.

## Verification

The cost/latency report must contain every artifact listed in the normative
specification, including cold/warm and mixed-load measurements on the chosen
host, component CPU/RSS/disk effects, all token billing classes, privacy canary
scans, correlation reconstruction, retention sweeps, and injected readiness and
degradation failures. Results must label every statement as observed, inferred,
or planned.
