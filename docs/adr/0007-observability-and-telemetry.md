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

### Status notes (2026-09-16, implementation as built; the decision text above is unchanged)

- Traces (`agent/app/telemetry.py`): one root span `copilot.turn` per turn
  with session id = conversation id, a `generation` observation per model
  call (`plan`, `narrate`, `repair`) carrying usage and cost, and since
  commit `74a1bf6` one `tool`-type observation per gateway call carrying
  status, reason, record count, truncation flag, and gateway latency. Since
  2026-09-17 every turn trace also carries the scores `verification_passed`
  (1.0 for `passed`, 0.0 for `partial` or `failed_closed`, absent when the
  verifier did not run) and `turn_error` (1.0 for a failed or timed-out
  turn) plus the `verification` outcome in its metadata (`finish_turn_trace`
  in `agent/app/telemetry.py`, computed once in `agent/app/turn_outcome.py`
  and shared with the response and `copilot_verification_total{outcome}`);
  the generation and tool observations take the turn's correlation id and
  every telemetry warning logs it. The observation context managers also
  re-raise the body's own exception unchanged; before that day they turned
  it into `RuntimeError`, which bypassed the graph's `except ModelError`
  fallback for real provider failures.
  The `mask` function is passed to the Langfuse client at construction;
  the startup guard that exists is the refusal to run when any LangSmith
  tracing variable is set (`FORBIDDEN_ENV`). Dashboard panels:
  `docs/operations/langfuse-dashboard.md`.
- Alerts (decision 6): the three PRD alerts are implemented as pure
  functions in `agent/app/alerts.py` with the `KEY_METRICS.md` thresholds,
  run by `python -m app.alerts` (`agent/app/alerts_cli.py`; optional
  `--webhook`, `--ready-url`, `--interval`), and covered by
  `agent/tests/test_alerts.py`. Since 2026-09-17 it is scheduled by the
  `alerts` service in `infra/digitalocean/runtime/compose.yaml`
  (`--interval 300`, agent image, state on the `agent_state` volume), on the
  host from the M3 deploy; the runbook's cron line is superseded.
- `/ready` reports the tracer dependency as `reachable` (both key files
  present and `GET /api/public/projects` on the Langfuse host answering 200
  under basic auth within 5 s), `http_<code>`, the httpx error class, or
  `not_configured` (`agent/app/readiness.py`, since 2026-09-17). That is a
  live reachability probe rather than the exporter's last-success age
  decision 6 planned; the SDK does not expose that age, and the probe
  answers the same question.
- Of the Verification items below: the correlation eval exists
  (`OBS-CORRELATION-001`; walkthrough in
  `docs/operations/correlation-id-walkthrough.md`) and the alert evals
  exist (`test_alerts.py`). No automated export-grep eval for fixture PHI
  exists yet; the PHI-free read-backs of 2026-09-15 and 2026-09-16 were
  manual (API and UI). No tracer-down eval exists: the `X-Copilot-Fault`
  value `tracer` is listed in `settings.py` but no graph node acts on it
  (only `model`, `tool:<name>`, and `budget` change behavior). The tracer's
  failure path is exercised by
  `agent/tests/test_telemetry.py::test_observation_failure_logs_the_correlation_id`
  (client construction failing: the observation degrades to a no-op and the
  warning carries the correlation id) and by
  `agent/tests/test_health.py::test_ready_is_503_when_tracer_unreachable`; no
  eval blocks the exporter endpoint during a live turn, so the Verification
  item below is still open.

### Amendment (2026-09-19): content capture mode

Revisit trigger 3 fired: error analysis of the 2026-09-18 sessions found 19 of
79 turns had the model's narrative replaced by the count-only summary, and
neither the rejected text nor the reason was visible anywhere an operator
could read it without shell access to the Droplet. Digest-only traces cannot
feed error analysis or eval data.

- **Decision.** A setting `COPILOT_TRACE_CONTENT` (`settings.trace_content`)
  selects between two modes. Off, the code default, is decision 2 as written:
  the mask is installed and no prompt, response, or record text leaves the
  process. On, the mask is not installed and each `plan`, `narrate`, and
  `repair` generation carries its system prompt, messages (evidence pack and
  question), and raw model output; the turn span and the trace carry the
  question, the rendered answer, the model's own summary, accepted and
  rejected claims, and the summary-replacement reason.
- **Assumption, stated as one.** Content mode is permitted only where the
  tracer is inside the compliance boundary: self-hosted next to OpenEMR, or a
  BAA-covered region (Langfuse offers one at `hipaa.cloud.langfuse.com`, Pro
  plan, signed BAA). For this challenge the hosted project in use is assumed
  to meet that bar, in the same way the LLM provider's BAA is assumed
  (`docs/audit/compliance.md`, "Important disclaimers"); the deployment holds synthetic patients
  only, so no PHI reaches the tracer either way. Moving to a covered tracer is
  configuration (`COPILOT_LANGFUSE_HOST` and keys), not code. The demo compose
  file sets the mode on; `COPILOT_TRACE_CONTENT=0` restores decision 2.
- **What the assumption does not cover.** Access to the tracer project,
  retention, and audit logging of trace reads are the operator's to provide
  (Langfuse audit logs are Enterprise-only; the open-source edition keeps
  data indefinitely). Eval data promoted from traces into this public
  repository must stay synthetic.
- **Fixed in both modes** (commit `49f1637`): the SDK runs metadata through the
  same mask as payloads, so the end-of-turn totals had been digested and were
  unreadable; an allowlist (`METADATA_KEYS`, enum-shaped values only) now lets
  them through. `span.update_trace` does not exist in langfuse 4.x and its
  `AttributeError` was swallowed; trace name, session, and tags now go through
  `propagate_attributes`. New on every trace: the `summary_model_kept` score,
  the `summary_replaced` rule name, and a `prompt_version` hash on each
  generation.
- **Exception text in masked mode (found and fixed 2026-09-19).** The SDK's
  mask covers input, output, and metadata only. Exception text left through
  two other channels: the LangChain handler's `status_message`, and the
  OpenTelemetry status description and `exception` event written when a span
  is closed with the exception. A gateway or contract error that quotes record
  text would have reached the tracer. In masked mode the handler now reports
  the exception class only (`_callback_handler`), and observations are closed
  clean and marked `ERROR` with the class name (`_close_on_error`); the body's
  exception still reaches the caller unchanged. Content mode keeps full error
  text. Verified against the real SDK with an in-memory exporter
  (`test_exception_text_never_reaches_the_exporter_in_masked_mode`; the same
  scenario with the fix bypassed exports the text 8 times). That test is also
  the first export-grep check this ADR's Verification section asked for, and
  the contract test for the SDK surface the module relies on, including the
  private `_get_error_level_and_status_message`.

### Status note (2026-09-20): alert delivery

Decision 6 said the alert job "emits `alert` log events plus a webhook". Until
commit `e466b9d` the evaluator had a `--webhook` flag and the deployment passed
nothing to it, so a page reached only `docker compose logs alerts`.

- **Delivery.** The `alerts` service now runs with `--webhook-file
  /run/secrets/slack_alert_webhook` and `--webhook-channel`. The receiver is a
  Slack incoming webhook held as a Docker file secret (`slack_alert_webhook`,
  pushed by `push-secrets.sh`, never in the repository): a webhook URL is a
  credential, and an argv value is visible to `docker inspect` and every
  process listing on the host. The file is read every cycle, so an absent or
  empty file means log-only, not a crash, and supplying it needs no restart.
  The payload is a one-line `text` summary followed by the alert record
  (commit `0471178`; Slack rejects a body without `text` or `blocks`), plus a
  best-effort `channel` (commit `478f432`; honoured only by legacy
  custom-integration webhooks). The record is counters, gauges, and fixed
  message templates, so the PHI-free rule of decision 2 holds for this
  channel in either trace mode.
- **What proving it found.** Five fault-injected turns on the deployment
  showed the tool-failure alert could not fire: since the batched gateway,
  tools the agent answers without a gateway call (`fault_injected`,
  `invalid_params`) skipped the `copilot_tool_calls_total` increment, so the
  alert's numerator was structurally zero. Fixed in `dbf5372` with a graph
  regression test. Both tool-failure rules then fired and delivered
  (`webhook_delivered` true), and the full live suite of pipeline 24351 ran
  761 s without a page.
  `docs/audit/evidence/observability/alerts-slack-2026-09-20.log`; runbook
  `docs/operations/alerts.md`, "Delivery".
- Of the Verification items below, "Alert evals" is now also exercised end to
  end for the tool-failure alert; no such record exists for the latency and
  error-rate alerts, which `agent/tests/test_alerts.py` covers.

## Verification

- **Observed 2026-09-15 on the deployment:** one Langfuse trace per turn
  (`copilot.turn`, session id = conversation id, correlation id in
  metadata) holding the eight node spans in order, a generation span per
  model call with model id, input/output/cache tokens, per-call cost, and
  latency (a UC-01 turn: $0.033, 17.1 s), and every input and output
  replaced by a digest. A read-back of the trace found none of the fixture
  names, values, or note text. Two integration facts learned: the Langfuse
  v4 LangChain handler takes no trace name or metadata arguments (they go in
  the run config), and generation spans nest only when the agent opens the
  turn's root span itself.
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
