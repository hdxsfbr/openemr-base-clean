# ADR-0004: Agent Runtime (LangGraph), Canonical Contracts, and Model

- **Status:** Accepted 2026-09-15 (owner chose LangGraph from the start on
  2026-09-14 after reviewing the Weeks 1–3 syllabus; approved with
  ADR-0005..0007 on 2026-09-15)
- **Date:** 2026-09-14
- **Owners:** Andre Batista (agent service)
- **Related requirements:** PRD "Agentic Chatbot" (multi-turn, tool
  invocation), "canonical API/event/schema contracts" (Pydantic, Zod, or
  equivalent as the source of truth), "runnable API collection", AI cost
  analysis. `AGENTS.md`: strict canonical schemas, generated downstream
  types, small dependency surface. `AUDIT.md` ARCH-MEDIUM-006, PERF-MED-005.
  Syllabus Weeks 2–3: supervisor and two workers on a graph, checkpointing,
  human-in-the-loop nodes, PR-blocking eval CI, adversarial platform against
  this co-pilot.
- **Related use cases:** UC-01..03; CAP-01, CAP-02, CAP-04, CAP-07, CAP-08.
- **Related decisions:** ADR-0003 (agent service outside PHP), ADR-0005
  (state and checkpointing), ADR-0006 (verification), ADR-0007
  (observability).

## Context

The agent service must run outside PHP (ARCH-MEDIUM-006), expose a
header-authenticated HTTP API, define strict schemas as the contract of
record, and orchestrate a bounded tool loop with structured output that a
deterministic verifier can check. The Week 1 need is a single agent with a
handful of steps. The syllabus makes Week 2 a supervisor with two workers on
an explicit graph with checkpointing and human-in-the-loop nodes, gated by
eval CI, and Week 3 an adversarial platform that drives this co-pilot
headlessly. "Good architecture compounds; technical debt costs double." A
hand-written loop in Week 1 would be ported in Week 2 alongside multimodal
ingestion and RAG. Payload size drives latency and cost (about 42K raw
tokens for a five-year chart), so context assembly must be deterministic and
cache-friendly regardless of orchestration.

## Decision

1. **Runtime:** Python 3.12, FastAPI, Pydantic v2, **LangGraph** for the
   turn graph, the official `anthropic` SDK called directly from nodes,
   `httpx` for gateway calls, `langgraph-checkpoint-sqlite` for state
   (ADR-0005), OpenTelemetry SDK (ADR-0007). No LangChain model wrappers,
   chains, or agents: nodes are plain Python functions; timeouts, retries,
   structured output, and prompt caching live in our code.
2. **Graph (Week 1, single agent).** Nodes: `authorize` (token, budget,
   fault flags), `classify` (UC-01 first turn or follow-up), `plan` (fixed
   plan, or a model call that selects tools with `strict` schemas),
   `retrieve` (parallel gateway calls; emits the evidence event), `narrate`
   (model call with structured output bound to `TurnClaims`), `verify`
   (deterministic), `repair` (one model call with rejections), `render`
   (assemble `TurnResponse`, emit events). Conditional edges: `plan` to
   `retrieve` at most 3 rounds and 8 tool calls per turn; `narrate` failure
   or budget exhaustion to `render` with the deterministic brief (CAP-08);
   `verify` with rejections and no repair yet to `repair`, otherwise to
   `render`. Per-turn wall clock 12 s enforced around the graph run. No
   interrupts in Week 1; the human-in-the-loop node arrives with Week 2.
3. **Contracts:** Pydantic models in `agent/contracts/` are the single
   source of truth; the graph state schema is built from them. A build step
   exports JSON Schema to `contracts/schema/`; the PHP gateway validates
   requests and responses with `opis/json-schema`; TypeScript types for the
   module JS and the Bruno assertions are generated from the same files;
   tool definitions for the model derive from the same models with
   `strict: true`. No hand-written parallel definitions.
4. **Model:** `claude-opus-5` in code, adaptive thinking, `output_config.effort`
   `low` for the fixed-shape first-turn narration and `medium` for
   tool-selecting follow-ups; prompt caching on the stable system prompt and
   evidence-pack prefix. **Measured 2026-09-15** on the UC-01 evidence pack
   (about 1,150 tokens): Opus 5 narrates in 15 to 17 s, Sonnet 5 in about
   10.5 s, with comparable verifier acceptance (8/10 vs 6/7). Neither meets
   the 8 s complete-response budget yet; the deployment runs
   `COPILOT_MODEL_ID=claude-sonnet-5` as an explicit environment setting
   until the owner confirms or reverts. **Output format:** claims are
   returned as JSON text and validated by the agent (`app/model_output.py`);
   the grammar-constrained `output_config.format` path was measured at 45 s
   or a timeout even for a two-claim schema and is not used.
   Retry once on 429 or 5xx with jitter; none on timeout. A small circuit
   breaker around the model client (open after 3 consecutive failures for
   60 s) routes turns to the deterministic fallback. Sonnet 5 is measured as
   the alternative in `AI_COST_ANALYSIS.md`; any model change is recorded
   here.
5. **Budgets as graph state:** per-turn token cap (20K) and per-conversation
   cap (60K) checked in `authorize`; a process-wide daily spend counter with
   a halt flag; exhaustion routes to the deterministic fallback with the
   limitation `model_budget_exhausted` (Week 3 cost-amplification defense).
6. **Week 2 extension path (designed, not built):** the supervisor becomes
   the parent graph; the Week 1 turn graph and the two workers (document,
   evidence) are subgraphs; the checkpointer, correlation scheme, contracts,
   verifier, and evals are unchanged. Writes need a separate ADR
   (`AGENTS.md`).

## Alternatives Considered

### Hand-written tool loop on the Anthropic SDK (the earlier draft of this ADR)

- Benefits: about 200 lines; no orchestration dependency; every branch in
  our code.
- Costs and risks: Week 2 requires an explicit graph with checkpointing and
  interrupts, so the loop would be ported in the same week as ingestion,
  RAG, and CI; the interview story for Week 2 would be "we rewrote it".
- Reason rejected: the syllabus makes the graph a known requirement, and
  the explainability concern is answered by keeping nodes plain and the
  model layer ours.

### LangChain agents or `create_react_agent`

- Costs and risks: model wrappers hide retry and structured-output
  semantics; prompt formats not under our control; LangSmith tracing defaults
  that capture PHI.
- Reason rejected: we use LangGraph for state and edges only.

### Anthropic Managed Agents

- Reason rejected: PHI would transit an Anthropic-hosted workspace and the
  gateway calls would leave our boundary; compliance requires the data path
  to stay inside our boundary except the model call.

### Model cascade (Haiku for tool selection, Opus for narration)

- Reason deferred: measure one model at tuned effort first; decide in
  `AI_COST_ANALYSIS.md`.

## Consequences

### Positive

- The Week 1 graph is the Week 2 subgraph; no orchestration rewrite.
- Every node, edge, and routing decision is visible in the trace, which is
  what the interview and the Week 3 attacker both need.
- Checkpointing, streaming of node events, and later interrupts are native.
- Structured output plus strict tools give the verifier typed inputs.

### Negative and residual risk

- Two more dependencies (`langgraph`, `langgraph-checkpoint-sqlite`), pinned.
- The checkpointer persists graph state; raw tool records must be kept out
  of state (ADR-0005) or PHI at rest grows.
- LangSmith auto-tracing must never be enabled; guarded by config and an
  eval (ADR-0007).
- Opus-tier pricing per turn remains the cost driver.

## Verification

- Graph tests: each conditional edge exercised (round limit, budget
  exhaustion, model failure, verifier rejection, repair once).
- Contract tests: exported schema validates recorded tool and turn
  responses; a schema change without a version bump fails CI.
- Trace shows node order and per-node latency for one correlation ID.
- Cost and latency per turn type summarized in `AI_COST_ANALYSIS.md`.

## Revisit Triggers

- Week 2 PRD (supervisor and workers, ingestion, RAG): extend, do not
  replace.
- Cost analysis shows Opus-tier pricing breaks the 10K-user projection.
- LangGraph's checkpoint or streaming semantics conflict with the PHI-at-rest
  or telemetry rules.
