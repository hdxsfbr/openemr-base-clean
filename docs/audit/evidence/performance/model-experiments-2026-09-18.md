# Model and planning-loop experiments: what shipped and what didn't

Follow-up to `agent-perf-fix-2026-09-18.md`, same day. That doc fixed
agent-side latency under *load* (contention). This one is about per-turn
latency in the normal, uncontended case — the number `KEY_METRICS.md`'s 30 s
p95 target actually measures — using `evals/run.py` against the live
Droplet, one turn at a time, no concurrency.

## Methodology correction (own mistake, caught before it shipped)

The first attempt compared `evals/run.py --model claude-sonnet-5` against
`--model claude-haiku-4-5-20251001` and reported real-looking differences.
That comparison was invalid: `--model` only labels the report
(`evals/run.py:876`); it does not change which model the deployed agent
calls (`agent/app/api.py` has no per-request model override at all).
Confirmed directly on the live container both times:
`docker exec agentforge-openemr-agent-1 env | grep COPILOT_MODEL_ID` read
`claude-sonnet-5` throughout. The "Haiku 4.5" run was actually Sonnet 5
against itself — the observed differences were ordinary run-to-run
variance under an identical model, not a real Haiku effect. Not committed
anywhere before the mistake was caught; flagged here so the record is
honest about the false start.

## Baseline (both calls Sonnet 5, `max_plan_rounds=3`)

`evals/results/2026-09-18T201618Z-1fda51b.md`, commit `1fda51b` (after the
load-fix from `agent-perf-fix-2026-09-18.md`, before any of the changes
below): 45/46 passed (the one miss, `MISS-AUTHOR-J-001`, is a known-flaky
model-recall case, documented in `KEY_METRICS.md`). p50/p95/p99 11,748 /
27,543 / 30,538 ms; follow-up p95 28,886 ms; cost $0.0133/turn; status
share 88% complete / 12% partial.

## Experiment 1: `max_plan_rounds` 3 -> 1 — adopted

Closes the exact deferred experiment `docs/WEEK2_HANDOFF.md` already named
("One planning round for follow-ups ... the multi-tool eval cases decide").
Pure env toggle initially (`COPILOT_MAX_PLAN_ROUNDS`), except the variable
was never actually wired into `compose.yaml` — a real bug found in the
process: `docker compose` only substitutes `${VAR}` placeholders it finds
in the file, it does not pass host/`.env` variables into the container
implicitly. First attempt silently had no effect (container never
recreated, confirmed via `StartedAt`); fixed by adding
`COPILOT_MAX_PLAN_ROUNDS: ${COPILOT_MAX_PLAN_ROUNDS:-3}` to
`compose.yaml` (commit `61ed997`) before the real test.

Result (`evals/results/2026-09-18T210912Z-61ed997.md`): **46/46 passed**
(the previously-flaky case passed too), no blocking gates.

| Metric | Baseline (rounds=3) | rounds=1 | Change |
| --- | --- | --- | --- |
| Pass rate | 45/46 | 46/46 | better |
| Status complete / partial | 88% / 12% | 93% / 7% | better |
| Withheld statements | 3.6% | 1.8% | better |
| Model calls / turn | 2.19 | 1.64 | fewer |
| Cost / turn | $0.0133 | $0.0103 | **-23%** |
| Latency p50 (all turns) | 11,748 ms | 8,692 ms | -26% |
| **Latency p95 (all turns)** | 27,543 ms | **18,034 ms** | **-35%** |
| Latency p99 | 30,538 ms | 28,559 ms | -6% |
| **Follow-up p95** | 28,886 ms | **12,373 ms** | **-57%** |
| First-turn (`uc01_first`) p95 | 17,217 ms | 19,387 ms | flat (expected — `plan` never runs on first turns) |

The first-turn row is the control: `max_plan_rounds` only bounds the
`plan`->`retrieve` loop on follow-up turns, and first turns (which skip
`plan` entirely, going straight to the deterministic UC01 fetch) are
unaffected either way — confirming the effect is specifically the planning
loop, not something else moving. `ISO-FOLLOWUP-CHAIN-001` (the case
designed to test multi-turn tool chaining) still passed at rounds=1 — that
case chains across *conversation* turns via the checkpointer, a different
mechanism `max_plan_rounds` doesn't touch; what got trimmed is re-planning
*within* one turn, and a second round rarely earned its cost on this suite.

**Adopted as the new default** (`agent/app/settings.py`,
`infra/digitalocean/runtime/compose.yaml`: `3 -> 1`, ADR-0004 decision 5
amended). No quality regression found; every quality signal moved in the
same direction as latency and cost.

## Experiment 2: route `plan` to Haiku 4.5, keep `narrate` on Sonnet 5 — not adopted

Motivation: `classify` is pure regex (no model call), `plan` picks from a
fixed set of ~7 tools (bounded, structured), `narrate`/`repair` is
open-ended clinical synthesis under a strict verifier (ADR-0004's actual
safety boundary). The bounded decision looked like a natural candidate for
a smaller/faster model. Added `plan_model_id` (`agent/app/model.py`,
`agent/app/settings.py`, commit `3165aad`) — optional, defaults to `None`
(falls back to `model_id`, no behavior change unless set).

**First run failed for the wrong reason.** 32/46 passed, two blocking gates
(`Explicit uncertainty recall`, `Safe degradation`) FAIL. Root cause,
confirmed directly against the Anthropic API: `output_config.effort`
(adaptive thinking) is a Claude 5-family parameter and Haiku 4.5 rejects it
outright (`400 invalid_request_error: "This model does not support the
effort parameter"`). Every `plan` call 400'd, returned zero tool calls, and
the resulting recall failures across many follow-up turns had nothing to do
with Haiku's tool-selection judgment — the model was never actually asked.
Fixed with `plan_model_supports_effort` (default `True`; set `False`
alongside a non-Claude-5-family `plan_model_id`, commit `e931f12`),
verified directly against the API before redeploying (same request without
`output_config.effort` returns 200, `stop_reason: tool_use`).

**Second run (fix applied) is the real result.** 43/46 passed, blocking
gates: `Error rate` FAIL (one 504 on `CONF-DUP-NAMES-C2-001`'s second turn,
45,102 ms — the turn's own wall-clock ceiling), `Task success` FAIL (needs
risk acceptance: `CONF-DUP-NAMES-C2-001`, `CONF-NOTE-VS-LIST-N-001`,
`MISS-AUTHOR-J-001`). `MISS-AUTHOR-J-001` is the known-flaky case;
`CONF-NOTE-VS-LIST-N-001` is not — Sonnet 5 has passed it in every other
run this session, and it requires noticing a conflict across two specific
tables (`form_clinical_notes`, `lists`), a genuine tool-selection miss on
Haiku's part, not noise.

| Metric | Baseline (both Sonnet 5) | plan=Haiku 4.5, narrate=Sonnet 5 |
| --- | --- | --- |
| Pass rate | 45/46 | 43/46 |
| Blocking gates | none | Error rate FAIL, Task success FAIL |
| Latency p95 (model-backed) | 27,543 ms | 17,830 ms (**-35%**, real) |
| Cost / turn | $0.0133 | **$0.0155 (+16.5%, worse)** |
| Input tokens / turn | 581 | **2,516 (4.3x)** |
| Cache-read tokens / turn | 4,532 | **1,909 (less than half)** |

**The cost increase is the interesting finding, not just the gate
failures.** Anthropic's prompt cache is keyed to the specific model plus
prompt. Once `plan` and `narrate` call different models, they stop sharing
the cached system-prompt/evidence-pack prefix that made every other run in
this project cheap — input tokens quadrupled and cache reads dropped by
more than half in the same run. Haiku's lower per-token list price did not
come close to covering that; overall cost per turn went *up*. This is a
real, non-obvious architectural cost of per-node model-mixing that doesn't
show up until measured: splitting models across nodes that otherwise share
a prompt prefix breaks the caching that makes the whole system cheap.

**Not adopted.** The latency number was genuinely tempting (-35% p95,
matching the gain from the caching-aware framing that made it look like a
free win), but a blocking-gate failure exists precisely so a latency
number doesn't talk past a real regression — and there is one
(`CONF-NOTE-VS-LIST-N-001`), independent of the 504 (which may or may not
be systematic; not re-tested, since the recall miss alone is disqualifying
regardless). `plan_model_id` / `plan_model_supports_effort` stay in the
code as tested, documented, no-op-by-default infrastructure for a future
revisit — e.g. a same-family pairing that wouldn't fragment the cache, or
targeted work on the conflict-detection gap first.

## Full data

- Methodology-correction run (invalid, not committed):
  `/tmp/claude-1000/model-experiments/2026-09-18T204037Z-1fda51b.md`
  (scratch only, per `evals/run.py`'s own `--out-dir` convention for
  exploratory runs — `docs/WEEK2_HANDOFF.md`'s deferred-experiment
  protocol).
- Baseline: `evals/results/2026-09-18T201618Z-1fda51b.{json,md}` (committed).
- Adopted (`max_plan_rounds=1`): `evals/results/2026-09-18T210912Z-61ed997.{json,md}` (committed).
- Haiku `plan`, broken (effort 400s, not committed):
  `/tmp/claude-1000/model-experiments/2026-09-18T212021Z-61ed997.md`.
- Haiku `plan`, fixed, not adopted (not committed):
  `/tmp/claude-1000/model-experiments/2026-09-18T214024Z-e931f12.md`.

All live-host toggles were reverted immediately after each run
(`/opt/agentforge/.env` backed up before each edit, restored after); `/ready`
verified healthy before and after every deploy and every revert.
