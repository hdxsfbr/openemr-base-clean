# ADR-0007: Observability and PHI-Free Telemetry

- **Status:** Accepted 2026-09-15 (owner approval)
- **Date:** 2026-09-14
- **Owners:** Andre Batista (agent service; module logging)
- **Related requirements:** PRD "Observability" (order of operations,
  step latency, tool failures, tokens and cost, from logs at any time);
  correlation ID across boundaries; real-time dashboard (requests, errors,
  p50/p95, tool calls, retries, verification pass/fail); three alerts;
  `/health` and `/ready`. `AUDIT.md` COMP-HIGH-004, COMP-MED-003,
  ARCH-MEDIUM-005; `docs/PRIOR_COHORT_LESSONS.md` (tracer rate limits).
- **Related use cases:** operational; supports every use case's latency
  and safety metrics in `KEY_METRICS.md`.
- **Related decisions:** ADR-0003 (correlation ID minted at the panel),
  ADR-0006 (verification outcomes).

## Context

Hosted tracers capture prompts and outputs by default, which would place PHI
with a vendor that has no BAA (COMP-HIGH-004). Self-hosting a current
Langfuse needs Postgres, ClickHouse, Redis, and object storage, more than a
4 GiB Droplet should carry beside OpenEMR and the agent. OpenEMR's audit log
is the right home for the access trail but the wrong tool for latency,
tokens, and cost. The PRD requires a dashboard and three alerts; the prior
cohort saw tracer rate limits stall requests.

## Decision

1. **Two channels with different content.** Access and security events go
   to OpenEMR's audit log via `EventAuditLogger::newEvent` (`copilot-*`
   events, identifiers only, `docs/audit/compliance.md` §5). Operational
   telemetry goes to OpenTelemetry spans and structured JSON logs.
2. **PHI-free by construction.** Integration is Langfuse's native LangGraph
   callback handler (one handler passed in the graph config), chosen on
   2026-09-15 over hand-rolled OpenTelemetry export for ease of integration.
   The Langfuse client is configured with a `mask` function that replaces
   every input and output payload with a PHI-free digest (record counts,
   source ids, status flags, claim ids, byte length), and trace metadata is
   limited to an allowlist: correlation and conversation ids, hashed user
   id, tool names, statuses, record counts, stage latencies, model id, token
   counts, cost, verification outcome and rule ids, error class. Prompts,
   responses, record text, names, and dates of birth never leave the
   process. An eval greps an export for fixture PHI on every release run,
   and a startup check refuses to run if the mask is not installed or if any
   LangSmith tracing variable is set.
3. **Backend.** A hosted Langfuse project (free tier for the week) for the
   real-time dashboard, acceptable because the traces are verifiably
   PHI-free (compliance §4 row 7). Self-hosted Langfuse is the
   real-deployment path. LangSmith was considered equally PRD-compliant and
   marginally easier to enable, but has a smaller free quota for the load
   tests and no self-hosting path outside an enterprise tier.
4. **Correlation.** `{conversation}.{turn}` minted by the module, carried in
   `X-Correlation-Id`, in every audit comment, span, log line, and response.
5. **Non-blocking.** Batch export with a bounded queue; drop on backpressure;
   never block or fail a turn on telemetry. Local JSON logs with the
   correlation ID are the reconstruction path when the tracer is down.
6. **Metrics and alerts.** The agent exposes `/metrics` (Prometheus text) on
   the internal network. A scheduled job in the agent container evaluates
   the three PRD alerts over 5-minute windows against the thresholds in
   `KEY_METRICS.md` and emits `alert` log events plus a webhook. `/ready`
   reports the exporter's last-success age as one of its dependencies.

## Alternatives Considered

### Self-hosted Langfuse on the Droplet

- Benefits: no third party at all.
- Costs and risks: memory and operational load beyond the 4 GiB baseline;
  another failure domain to explain.
- Reason deferred: real-deployment path; revisit if the Droplet grows.

### LangSmith or Langfuse with default capture

- Reason rejected: PHI to a vendor without a BAA (COMP-HIGH-004).

### Prometheus and Grafana only

- Benefits: light, self-hosted, native alerting.
- Costs and risks: no trace view of tool order and model calls, which the
  PRD asks to reconstruct; a second UI to build.
- Reason rejected as the primary; the `/metrics` endpoint keeps the door
  open.

## Consequences

### Positive

- The dashboard shows every PRD metric in real time without holding PHI.
- One correlation ID reconstructs a turn from logs alone, tracer or not.
- Care is never blocked by telemetry.

### Negative and residual risk

- Debugging a bad answer from traces alone is harder without prompt text;
  the eval suite and local reproduction with fixtures fill that gap.
- The allowlist is a control we must maintain; a new attribute added
  without review could leak. Mitigated by the export grep eval.
- The hosted tracer remains a third party; the claim is "PHI-free", not
  "covered by a BAA".

## Verification

- Export grep eval: no fixture names, values, or note text in any span.
- Correlation eval: a turn reconstructed from logs alone lists tool order,
  latencies, model calls, tokens, verification outcome.
- Tracer-down eval: exporter endpoint blocked, turn completes within budget.
- Alert evals: synthetic latency, error, and tool-failure bursts trigger the
  right alert with the documented threshold.

## Revisit Triggers

- The Droplet grows to a size that comfortably hosts Langfuse.
- A real deployment, where self-hosting or a BAA-covered vendor is required.
- A need to store prompt text for debugging (would require a BAA-covered,
  access-controlled store, not the tracer).
