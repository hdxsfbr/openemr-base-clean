# Langfuse Dashboard: Clinical Co-Pilot

Project "My Project" in Andre's Organization on Langfuse Cloud US
(`https://us.cloud.langfuse.com`). The dashboard named **Clinical Co-Pilot**
holds the PRD's operational panels; the Langfuse-maintained Agent, Latency,
Cost, and Usage dashboards complement it. Built 2026-09-16 with the
Langfuse Assistant from the descriptions below; anyone with project access
can rebuild it the same way. Two first drafts were replaced on review: a
combined p50/p95 widget and a combined input/output token widget each drew
a single line (the chart renderer collapses two metrics), so they became
separate widgets; a "traces with errors" widget filtered on trace level
and never fired, so it became an observation-level error count.

Renders of the nine panels as of 2026-09-16, plus one full trace export,
are committed for evaluators without project access under
`docs/audit/evidence/observability/`.

## Panels and the PRD metric each covers

| Panel | Definition | PRD metric |
| --- | --- | --- |
| copilot.turn traces over time | Count of traces named `copilot.turn` per hour | Requests |
| copilot.turn latency p50 | p50 latency of `copilot.turn` traces over time | p50 latency |
| copilot.turn latency p95 | p95 latency of `copilot.turn` traces over time | p95 latency |
| Total model cost over time | Sum of model cost per time bucket | Cost |
| Tokens by usage type over time | Token usage grouped by usage type (input, output, cache read) per time bucket | Tokens |
| Generations by name over time | Count of GENERATION observations grouped by name (`plan`, `narrate`, `repair`) | Retry count: every `repair` is one verifier-driven retry |
| Tool calls by name over time | Count of TOOL observations grouped by name (`encounters`, `problems`, `medications`, `allergies`, `lab_results`, `clinical_notes`, `patient_context`) | Tool calls |
| Tool errors by name | TOOL observations with level ERROR grouped by name | Tool failures |
| ERROR-level observations over time | Count of observations of any type with level ERROR, grouped by observation type | Errors (a model call that fails and a tool that returns `unavailable` both land here) |
| Verification pass rate (**to build**) | Average of the trace score `verification_passed` over `copilot.turn` traces per time bucket (scores emitted since 2026-09-17 by `finish_turn_trace`; absent on turns where the verifier did not run) | Verification pass/fail rate — not yet on the dashboard |
| Turn error rate (**to build**) | Average of the trace score `turn_error` over `copilot.turn` traces per time bucket (1.0 for a failed or timed-out turn) | Error rate — not yet on the dashboard; `/metrics` `copilot_requests_total{status="5xx"}` is the alert-job source |

### The two panels still to build

These are the last two of the PRD's dashboard minimum (p.8, "verification
pass/fail rate" and "error rate"). Everything they need already exists; only
the two widgets are missing, and Langfuse Cloud exposes no widget API, so
they are built in the UI.

Verified 2026-09-20 against `GET /api/public/v2/scores`: 8,709 scores are
recorded on the project, and a 50-score sample carried `verification_passed`
and `turn_error` on `copilot.turn` traces. Both panels will have history the
moment they are created — they are not waiting on new traffic.

For each: **Dashboards → Clinical Co-Pilot → Add widget**, then

| Field | Verification pass rate | Turn error rate |
| --- | --- | --- |
| View | Scores | Scores |
| Metric | `value`, aggregation Average | `value`, aggregation Average |
| Filter | Score Name = `verification_passed` | Score Name = `turn_error` |
| Breakdown | none | none |
| Chart | Line chart over time | Line chart over time |
| Name | Verification pass rate | Turn error rate |

Read the first as "fraction of turns whose verifier passed" (1.0 is all
passed) and the second as "fraction of turns that errored" (0.0 is none).
After saving both, re-render the panel set into
`docs/audit/evidence/observability/` so the committed evidence matches the
live dashboard, and strike the two "**to build**" rows above.

The Langfuse Agent Dashboard adds p95 latency per tool and observation
types; the Latency dashboard adds p95 by trace name and by model.

## What a trace carries

- One trace per turn named `copilot.turn`, session id = conversation id,
  tags `copilot` plus the turn type (`uc01_first` or `followup`; set in
  `agent/app/telemetry.py`), metadata `correlation_id`, `conversation_id`,
  and `turn_type`, plus PHI-free totals (`status`, `claims`, `withheld`,
  `tool_calls`, `timings_ms`, `usage`) attached when the turn finishes.
- Nested observations: the graph nodes (`authorize`, `classify`,
  `retrieve`, `plan`, `narrate`, `verify`, `repair`, `render`) as chains,
  one GENERATION per model call with token usage and cost, and one TOOL
  observation per gateway call with status, reason, record count,
  truncation flag, and gateway latency. LangGraph's conditional edges
  appear as `router` chains; they are noise and can be filtered out with
  `name != router`.
- Every input and output is replaced by a digest (`{"digest": true, keys,
  bytes}`) by the client-side mask (ADR-0007). No claim text, record text,
  names, or identifiers reach Langfuse. Verified by reading traces back
  through the API and in the UI on 2026-09-16.

## Project state noted on 2026-09-16

- Langfuse shows an "Action required" notice for the v4 API migration due
  2026-11-16. The SDK in use (langfuse 4.15, OpenTelemetry-based) is
  reported as v4-compatible for spans: they are exported to
  `POST /api/public/otel/v1/traces` (`langfuse/_client/span_processor.py:123`).
  No eval script needs migrating: `grep -rn "api/public" evals/` returns
  nothing. **Three migration targets remain before 2026-11-16.** (1) Added
  2026-09-17 with the `verification_passed` and `turn_error` trace scores:
  `finish_turn_trace` calls `score_trace` on every turn
  (`agent/app/telemetry.py:164,191-192`), and langfuse 4.15.3 posts scores
  through `LangfuseSpan.score_trace` -> `create_score` -> `add_score_task`
  -> `ScoreIngestionConsumer` -> `POST /api/public/ingestion`
  (`langfuse/_utils/request.py:59`), the v3 ingestion endpoint the SDK itself
  marks "removed on November 16, 2026" (`langfuse/api/ingestion/client.py:32`);
  bump the SDK to a release whose score path no longer posts there and confirm
  the two scores still arrive on a `copilot.turn` trace. (2) The runnable
  trace-lookup curl in `docs/operations/correlation-id-walkthrough.md:50`
  (`GET /api/public/traces?limit=50`) and (3) the one-off export that produced
  the committed trace evidence,
  `docs/audit/evidence/observability/langfuse-trace-921f44e1-copilot-turn.md:3`
  (`GET /api/public/traces/<id>`): re-check both against the v4 API and update
  the walkthrough; the exported evidence file is a historical artifact and only
  its cited endpoint needs a note.
- Six root-level traces named `plan`, `narrate`, and `repair` exist from
  2026-09-15 23:14 to 23:15 (the first streamed turns after that deploy).
  Every later turn nests correctly; they are a one-off and can be ignored
  or deleted.
- The Agent Dashboard's "Total Tool Calls" card counts model-issued tool
  calls on generations, which the agent does not annotate; the TOOL
  observation panels are the authoritative tool metrics here.

## Reading a turn from the panel

Copy the `ref` shown under an answer (for example `75a29aa756c7985f.1`),
open Tracing, and search the metadata for it, or follow
`docs/operations/correlation-id-walkthrough.md` for the API route.
