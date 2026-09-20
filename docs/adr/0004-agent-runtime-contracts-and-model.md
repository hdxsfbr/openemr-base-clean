# ADR-0004: Agent Runtime (LangGraph), Canonical Contracts, and Model

- **Status:** Accepted 2026-09-15 (owner chose LangGraph from the start on
  2026-09-14 after reviewing the Weeks 1–3 syllabus; approved with
  ADR-0005..0007 on 2026-09-15; model amended to Sonnet 5 the same day on
  measured latency; decision 5's plan-round bound amended 2026-09-18,
  3 -> 1, on measured latency/cost/quality —
  `docs/audit/evidence/performance/model-experiments-2026-09-18.md`)
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
   `retrieve` at most 1 round (amended 2026-09-18 from 3: p95 down 35%, cost
   down 23%, 46/46 eval cases, quality signals improved, no case requiring a
   second round found — `docs/audit/evidence/performance/
   model-experiments-2026-09-18.md`) and 8 tool calls per turn; `narrate`
   failure or budget exhaustion to `render` with the deterministic brief (CAP-08);
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
4. **Model:** `claude-sonnet-5` (owner decision 2026-09-15), adaptive
   thinking, `output_config.effort` `low` for the fixed-shape first-turn
   narration and `medium` for tool-selecting follow-ups; prompt caching on
   the stable system prompt and evidence-pack prefix. **Measured 2026-09-15**
   on the UC-01 evidence pack (about 1,150 tokens): Opus 5 narrates in 15 to
   17 s, Sonnet 5 in about 10.5 s, with comparable verifier acceptance (8/10
   vs 6/7); the verifier, not the model, is the safety boundary, so the
   faster model was chosen. Opus 5 remains the measured alternative,
   selectable with `COPILOT_MODEL_ID`. The owner also accepted a provisional
   30 s complete-response target for the early submission
   (`KEY_METRICS.md`). **Output format:** claims are
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

### Opus 5 for narration

- Benefits: slightly higher verifier acceptance in the one measured sample.
- Costs and risks: 15 to 17 s per narration against 10.5 s, on a turn that
  already carries a planning call and a possible repair; 2.5 times the
  per-token price.
- Reason rejected (2026-09-15): latency is the user's constraint and the
  verifier is the safety boundary; kept selectable by environment.

### Model cascade (Haiku for tool selection, Sonnet for narration)

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
  Until 2026-09-17 "pinned" meant lower bounds in `agent/pyproject.toml`
  while `start.sh` rebuilt with `--pull`; now `agent/requirements.lock` (66
  exact versions from the running container's `pip freeze`, container Python
  3.12.14) is what `agent/Dockerfile` and the CI agent jobs install first,
  followed by `pip install --no-deps .`, so no runtime dependency can resolve
  newer on a rebuild. The build backend (`setuptools>=69` in
  `agent/pyproject.toml`) is not in the lock: `pip freeze` omits it and pip's
  isolated build environment fetches it fresh at image build time.
  Regenerate the lock from the container after any dependency change.
- The checkpointer persists graph state; raw tool records must be kept out
  of state (ADR-0005) or PHI at rest grows.
- LangSmith auto-tracing must never be enabled; guarded by config and an
  eval (ADR-0007).
- Opus-tier pricing per turn remains the cost driver.

### Status notes (2026-09-16, implementation as built; the decision text above is unchanged)

- Contracts live at `agent/app/contracts/` (not `agent/contracts/` as
  written); `CONTRACT_VERSION` is `1.2.0` (`common.py`), bumped on
  2026-09-16 for the `problem_status` claim type (ADR-0006). JSON Schema is
  exported to `contracts/schema/` by `python -m app.contracts.export`;
  `agent/tests/test_contracts.py` and the CI job `test:agent`
  (`--check`) fail on drift. The PHP gateway's `ToolRegistry::params()`
  does **not** read the schema files: it applies a hand-written key allowlist
  (`since`, `until`, `limit`, `cursor`, plus `term` for clinical notes and
  `analyte` for lab results) and hand-written format checks that mirror the
  exported schemas
  (`interface/modules/custom_modules/oe-module-copilot/src/Gateway/Tools/ToolRegistry.php:37`
  onward; the docblock there still claims schema validation). No
  `opis/json-schema` dependency is present in the module, and validating
  against `*_params.schema.json` is planned, not done
  (`ARCHITECTURE.md` states this correctly). No generated
  TypeScript types were found in the repository.
- Turn wall clock is 45 s (`turn_wall_clock_seconds`,
  `agent/app/settings.py`), not the 12 s in decision 2, matching the
  provisional 30 s p95 target in `KEY_METRICS.md`; a turn past it returns
  504. Plan rounds (3) and tool calls per turn (8) are as decided.
- Budgets (decision 5) are in `agent/app/budget.py`: 20K tokens per turn,
  60K per conversation, and a daily halt at `daily_token_halt` = 2,000,000
  tokens per UTC day, all routing to the deterministic fallback with
  `model_budget_exhausted`; `agent/tests/test_graph.py::test_budget_exhaustion_routes_to_deterministic_fallback`
  and eval case `MODEL-BUDGET-001` cover it.
- Model client (`agent/app/model.py`): one SDK retry (`max_retries=1`),
  circuit breaker opens after 3 consecutive failures for 60 s, as decided;
  covered since 2026-09-17 by
  `agent/tests/test_controls.py::test_circuit_breaker_opens_after_three_failures_and_closes_after_cooldown`
  and `::test_provider_connection_failures_trip_the_breaker_and_short_circuit_the_model`
  (three `APIConnectionError`s open it, the fourth call raises `circuit_open`
  without touching the SDK, a call after the cooldown goes through; time is
  controlled with `monkeypatch`).
- Cost and latency per turn type are now summarized per run by the eval
  scorecard (`evals/run.py`; latest `--repeat 3` run
  `evals/results/2026-09-20T051146Z-0f11642.md`: 48 cases x 3, 123 of 124
  attempts passed, every blocking gate PASS, $0.0104 list price per
  model-backed turn, p95 15.8 s over 126 model-backed turns; latest single
  pass, at the deployed runtime tree,
  `evals/results/2026-09-20T064022Z-4d2a9fd.md`: 48 of 48, $0.0113, p95 20.0 s
  over 42 model-backed turns) and rolled up in `AI_COST_ANALYSIS.md`. The
  `--repeat 3` run at `1ddf824` (p95 27.6 s over 120 model-backed turns) is
  kept as stability history.

### Status notes (2026-09-20, settings changed since the notes above; the decision text is unchanged)

- **Plan rounds are 1, not 3.** The 2026-09-16 note above ("Plan rounds (3)
  ... as decided") was true that day. `max_plan_rounds` has been 1 since
  commit `e2cd633` (2026-09-18), and the demo compose file sets
  `COPILOT_MAX_PLAN_ROUNDS` to 1 by default; the amendment is recorded in the
  status line and inside decision 2, where the bound lives (the status line
  and the code comments call it decision 5). Tool calls per turn are still 8.
- **Follow-ups run at effort `low`, not `medium`** (decision 4;
  `effort_followup`, commit `f4f69ab`, 2026-09-19; it also sets the effort of
  the `plan` call and of a follow-up's repair round). Fixture A/B, 14 turns
  per arm: 18.1 s -> 11.9 s and 1,788 -> 1,231 output tokens per follow-up,
  model summaries kept 10 vs 11, claims per turn 4.9 -> 3.9. Live suite at
  `low` against the run at `medium`
  (`evals/results/2026-09-19T230512Z-f4f69ab4.md` vs
  `2026-09-19T223524Z-12cd849a.md`): 48/48 vs 47/48, task success 100% in
  both, claims per turn 4.21 -> 4.10, follow-up p50 8.1 -> 7.2 s and p95
  12.3 -> 11.9 s, $0.0116 -> $0.0111 per model-backed turn. The risk to
  watch is recall, since `low` writes fewer claims;
  `COPILOT_EFFORT_FOLLOWUP=medium` restores the decision as written without a
  code change. `docs/audit/evidence/performance/followup-effort-2026-09-19.md`.
- **Narration output cap 1,800 -> 3,200 tokens** (`max_output_tokens`, commit
  `5d90982`, 2026-09-19). Adaptive-thinking tokens count toward the cap; at
  1,800, 10% of first-turn `narrate` calls stopped on `max_tokens` (Langfuse,
  2026-09-18/19), the re-ask ran a second full call, and the turn took 26 s
  instead of 9 s, which was the first-turn p95. 3,200 at the measured ~120
  output tokens per second still finishes inside `model_timeout_seconds`
  (30 s). `stop_reason` on each generation's metadata shows any new hit.
- **`plan` is skipped for the agent's own follow-ups** (`KNOWN_PLANS` in
  `agent/app/graph/nodes.py`, commit `089ef2b`, 2026-09-19). The five
  follow-ups the agent writes itself (two starter chips and the three
  deterministic suggestions) have fixed wording and chose the same tools in
  3 of 3 `plan` runs each (the medication question added `problems` in 1 of
  3, and the table takes the union), so a question that matches one of those
  constants after normalization retrieves from a table instead of paying the
  `plan` model call. There is no client flag: the match is on the agent's own
  constants, and model-written chips still go through `plan`. Expected saving
  about 2 s and one model call per such turn (Langfuse, 2026-09-18, 199
  follow-up turns: `plan` p50 2.0 s, p95 2.9 s); not measured live.
  `docs/audit/evidence/performance/known-plans-2026-09-19.md`.
- **Model output is parsed more tolerantly, still by our code** (decision 4,
  `app/model_output.py`). Since `f5fed01` (2026-09-19) a malformed claim (no
  text, unknown type, a number where a string belongs, a null container) is
  dropped instead of failing the whole output, and an over-long summary is
  cut at its last complete sentence; text that is not JSON is still refused.
  Since `bea1c00` (2026-09-19) a blank optional tool parameter from `plan`
  becomes a null and one that still fails its contract is dropped, which
  widens the retrieval; a call whose remaining parameters also fail is
  refused as `invalid_params` as before.

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
