# Status: `week1-final-push` — MILESTONE M2 (code and harness ready, nothing deployed)

Plan: [docs/FINAL_PUSH_PLAN.md](../FINAL_PUSH_PLAN.md), MILESTONE M2. Orchestrated
with the `task-to-production` skill from Phase 2; Phases 0 and 1 are the approved
plan document (do not re-audit, do not re-design). Live task tools
(`TaskCreate`/`TaskUpdate`) are absent in this session, so this file is the
durable record and the `/workflows` tree is the live one.

**Commit policy.** The orchestrator is the only committer. One commit per
workstream after the implement/verify workflow returns (file sets are disjoint,
so each commit is `git add <owned paths>`), one commit for the doc-apply pass,
and this file committed alone at every round boundary. Implementation agents
never run `git commit`.

**Started:** 2026-09-17 (Thursday evening PT), branch at `14dac2f`, tree clean,
60 agent tests, 45 eval cases.

| Workstream | Owner | Files owned | Acceptance criteria | Status |
|---|---|---|---|---|
| WS-AGENT: A1 tracer probe, A2 `copilot_turns_in_flight`, A3 verification outcome metric + trace scores, A4 correlation id on 3 log calls, A5 `reason` label and `forbidden` excluded from tool-failure rate, A6 `requirements.lock`, A7 control tests | WS-AGENT | `agent/app/**`, `agent/tests/**`, `agent/Dockerfile`, `agent/pyproject.toml`, `agent/requirements.lock`, `agent/README.md`; plus `.gitlab-ci.yml` for A6 only (unlisted in the plan's ownership map; granted here because A6 names it) | `cd agent && .venv/bin/python -m pytest -q` (more than 60 tests, all pass); `.venv/bin/python -m app.contracts.export --check`; `agent/.venv/bin/python evals/run.py --offline-only` passes; fresh venv from `requirements.lock` passes the suite; `docs/_pending/WS-AGENT.md` carries deltas for ARCHITECTURE.md, KEY_METRICS.md, ADR-0004, ADR-0007, the traceability matrix, the checklist | planned |
| WS-EVAL: E1 cost gate at $0.0223, E2 `CONF-NOTE-VS-LIST-N-001` matcher decision (evidence-driven), E3 `ISO-FRESH-REPEAT-001` only | WS-EVAL | `evals/run.py`, `evals/compare.py`, `evals/README.md`, `evals/cases/**` | `evals/run.py --offline-only` and `--golden-only` parse and run (golden needs a deployment and is human-gated: parse + `--help` + a dry manifest load are the M2 check); gate table shows a real cost state; every new case has the required metadata and a `risk:` line; `manifest()` loads every YAML | planned |
| WS-LOAD: L1 `run_load.py`, L2 `droplet-stats.sh`, L3 expected-failure docstring | WS-LOAD | `evals/load/**`, `docs/audit/scripts/droplet-stats.sh` | `python -m py_compile evals/load/run_load.py`; `run_load.py --help` lists `--users`, `--label`, `--fault`; `bash -n docs/audit/scripts/droplet-stats.sh`; results JSON schema documented in the module docstring. The `--users 2` smoke is M3 and human-gated | planned |
| WS-INFRA: I1 `alerts` service, I2 `start.sh` recovery + `x-logging`, I3 `backup.sh`/`restore.sh`, I4 rehearsal runbook | WS-INFRA | `infra/**`, `docs/deployment/digitalocean.md` | `cd infra/digitalocean/runtime && docker compose config --quiet`; `bash -n start.sh && bash -n ../backup.sh && bash -n ../restore.sh`; runbook states in bold that the default workspace and 137.184.4.22 are never touched | planned |
| WS-CONTENT: X1 demo script with `<pending M4>` placeholders, X2 social post, X3 Week-2 handoff (one-page stub), X4 egress risk acceptance + rotation checklist as deltas | WS-CONTENT | `docs/DEMO_SCRIPT.md`, `docs/SOCIAL_POST.md`, `docs/WEEK2_HANDOFF.md`, `docs/INTERVIEW_NOTES.md`, `docs/INTERVIEW_FEEDBACK.md` | No number in DEMO_SCRIPT.md that does not exist yet (placeholders visible); X version under 280 characters; no GitLab link; handoff seams table names what is code and what is prose; X4 blocks in `docs/_pending/WS-CONTENT.md` | planned |
| WS-DOCS: doc-apply pass (runs alone after the five streams), consuming every `docs/_pending/*.md` including the M1 leftovers | WS-DOCS (orchestrator-run, one agent) | `KEY_METRICS.md`, `ARCHITECTURE.md`, `AUDIT.md`, `README.md`, `README_AGENT_FORGE.md`, `SETUP.md`, `AI_COST_ANALYSIS.md`, `USERS.md`, `docs/SUBMISSION_CHECKLIST.md`, `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/PROJECT_PLAN.md`, `docs/adr/**`, `docs/operations/**`, `docs/PRIOR_COHORT_LESSONS.md`; this status file (orchestrator only) | Every `EVIDENCE:` line re-verified before its block is applied; `docs/_pending/` empty afterward; conflicts between deltas or with the code reported, not resolved silently | planned |

## Deferred

- **E3 `ISO-TWO-USERS-001`** — the harness has no `as_user:` step (`evals/run.py:407-452`
  builds one `Session` per case from `case["user"]`); a second concurrent session means
  dual ticket and conversation tracking through `check()`, past the plan's two-hour bar.
  Target: one line under `evals/README.md` "Not automated in Week 1" (WS-EVAL) and an
  `ARCHITECTURE.md` delta keeping "two users on the same patient" listed as untested.
- **X3 `docs/WEEK2_HANDOFF.md`** ships as the one-page stub the plan's cut rule 4
  allows (read-first order, seams table, residuals, the two deferred experiments by
  name with the baseline-change-compare protocol). The long form is Week 2 work.
- **A7 breaker test** is in scope; it is the first A7 item to drop if the clock bites,
  per cut rule 2. The checkpoint-content test is never cut.
- **M1 leftover delta** in `docs/_pending/WS-CONTENT.md` (an "Automated coverage today"
  sentence after the ARCHITECTURE.md failure matrix) was never applied by an M1
  doc-apply pass. It is recorded here because `docs/_pending/` is gitignored
  (`.gitignore:80`); the M2 doc-apply pass consumes it.
- **Human-gated, not attempted in M2:** the WS-LOAD `--users 2` smoke, the
  `--golden-only` live run, every deploy, rehearsal, and backup execution.

## Contradictions found in the inputs

1. **M1 doc-apply pass did not run as specified.** `docs/_pending/WS-DOCS.md` and
   `docs/_pending/WS-CONTENT.md` survived M1. Commit `aa4d19a` applied the two
   `docs/deployment/digitalocean.md` blocks and satisfied the `evals/README.md:14`
   block in a different form (an appended note at `:15-16`, the original line kept).
   Only the WS-CONTENT `ARCHITECTURE.md` block is unapplied.
2. **A3 names a function that does not exist.** The plan says to call
   `score_trace("verification_passed")` and `score_trace("turn_error")` in
   `finish_turn_trace`; nothing in `agent/` defines `score_trace`
   (`agent/app/telemetry.py` has `finish_turn_trace`, `generation`, `tool_observation`,
   `record_tool_result`). It must be written, not just called.
3. **E2's "deterministic" alternative is still model recall.** `kind: note_vs_list` is
   matchable (`evals/run.py:182-184`), but the value is prompt-instructed
   (`agent/app/model.py:43`) into a free-string field
   (`agent/app/contracts/turns.py:47`). Swapping the text regex for the kind field
   trades one model-produced assertion for another. The choice is to be made from
   `facts.kind` on the conflict claim across the recorded run JSONs, not from the
   plan's framing.
4. **A1 is two changes.** `agent/app/readiness.py:96-103` awaits its checks
   sequentially; "gather the three async checks" is a second change beyond making
   `check_tracer` async. Both are in scope.
5. **Isolation-invariant count.** The plan's M1 text says "two isolation invariants
   untested"; after M1, `ARCHITECTURE.md:498-503` correctly lists three (fresh-conversation
   repeat, two users on one patient, checkpoint content). A7's checkpoint-content test and
   E3's `ISO-FRESH-REPEAT-001` bring that to one, which stays deferred (above).

## Completeness

None yet. One dated bullet per round is appended here.
