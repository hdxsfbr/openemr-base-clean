# Langfuse Dashboard: Clinical Co-Pilot

Project "My Project" in Andre's Organization on Langfuse Cloud US
(`https://us.cloud.langfuse.com`). The dashboard named **Clinical Co-Pilot**
holds the PRD's operational panels; the Langfuse-maintained Agent, Latency,
Cost, and Usage dashboards complement it. Built 2026-09-16 with the
Langfuse Assistant from the descriptions below; anyone with project access
can rebuild it the same way.

## Panels and the PRD metric each covers

| Panel | Definition | PRD metric |
| --- | --- | --- |
| copilot.turn traces over time | Count of traces named `copilot.turn` per hour | Requests |
| copilot.turn latency p50 / p95 | p50 and p95 latency of `copilot.turn` traces over time | p50 / p95 latency |
| Total model cost over time | Sum of model cost per time bucket | Cost |
| Input and output tokens over time | Token usage per time bucket | Tokens |
| Generations by name over time | Count of GENERATION observations grouped by name (`plan`, `narrate`, `repair`) | Retry count: every `repair` is one verifier-driven retry |
| Tool calls by name over time | Count of TOOL observations grouped by name (`encounters`, `problems`, `medications`, `allergies`, `lab_results`, `clinical_notes`, `patient_context`) | Tool calls |
| Tool errors by name | TOOL observations with level ERROR grouped by name | Tool failures |
| copilot.turn traces with errors over time | Distinct `copilot.turn` traces containing an ERROR-level observation | Errors |

The Langfuse Agent Dashboard adds p95 latency per tool and observation
types; the Latency dashboard adds p95 by trace name and by model.

## What a trace carries

- One trace per turn named `copilot.turn`, session id = conversation id,
  tags `copilot`, `turn`, metadata `correlation_id` and `conversation_id`.
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
  reported as v4-compatible; the remaining item is the public API calls made
  by the eval and verification scripts (`/api/public/traces`), which should
  move to the v2 endpoints before that date.
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
