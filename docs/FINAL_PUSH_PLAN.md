# Final Push Plan: orchestration spec for agents

Machine-readable plan for carrying the Week 1 final submission from HEAD
`e1dd331` (tag `week1`) to submitted by Sunday 2026-09-20 08:00 PT.

**This document is the approved design.** The understanding and design
phases are already done: the findings are in
[FINAL_SUBMISSION_TODOS.md](FINAL_SUBMISSION_TODOS.md), the audit is in
[AUDIT.md](../AUDIT.md), and the decisions are in
[docs/adr/](adr/). An orchestrator using the `task-to-production` skill
**skips Phase 0 and Phase 1 and starts at Phase 2** (plan into
workstreams, implement, verify). Do not re-run a design judge panel. Do
not re-audit the codebase.

## How to run this

```
Read docs/FINAL_PUSH_PLAN.md and orchestrate it. Start at MILESTONE M1.
Use the task-to-production skill from Phase 2 onward. Stop at every
STOP gate and wait for me.
```

The orchestrator should track every task with TaskCreate/TaskUpdate so
progress is visible outside the run.

**Working branch, superseded 2026-09-17.** M1 and M2 happened on
`week1-final-push` as planned below and reached `main` through
[!2](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/merge_requests/2),
merged the same day at the owner's decision, not at M5. Rationale: the early
submission is already graded, so the risk this section was written to avoid
(a reviewer opening `main` mid-week and seeing unfinished work) no longer
applies, and the owner wants to deploy continuously rather than save
everything for one push on Sunday. **From here, `main` is the working
branch.** New work commits (or small MRs, either is fine) directly against
`main`; there is no new per-milestone branch. Treat every "on the branch" /
"at M5, merge to main" instruction below as historical description of how
M1-M2 actually happened, not as an instruction to repeat. Invariant 4 is
amended to match (see below). M3-M5 still apply as milestones, just against
`main` instead of a side branch, and the M5 tag/submission steps (freeze,
release run, tag `week1-final`) are unaffected by this change.

---

## 1. Hard invariants (never violate, no exceptions)

These come from `AGENTS.md`, the ADRs, and owner decisions. An agent that
breaks one has failed its task even if its tests pass.

1. **Never modify OpenEMR core.** No fixes to `aclCheckIssue`, `readyz`
   routing, prefork sizing, bundled dependencies, or anything outside
   `interface/modules/custom_modules/oe-module-copilot/`, `agent/`,
   `evals/`, `infra/`, `contracts/`, `docs/`, and the root markdown
   deliverables. OpenEMR defects are documented, not repaired.
2. **Never re-litigate ADR-0002 (parity authorization), ADR-0003
   (in-process module gateway), ADR-0004 (LangGraph, Sonnet 5).** SMART on
   FHIR, care-relationship authorization, and alternative runtimes are
   settled and deferred.
3. **Evals before tuning.** No change to the prompt, model id, effort
   setting, planning rounds, or verifier lexicon during this push. If one
   is ever proposed, it requires a baseline `--repeat 2` run, the change, a
   second `--repeat 2` run, and `evals/compare.py` output. There is no time
   for that before Sunday, so the answer is no.
4. **Amended 2026-09-17: `infra/digitalocean/deploy.sh` against `137.184.4.22`
   now runs unattended in CI on every push to `main`** (`.gitlab-ci.yml`
   `deploy:production`, stage `deploy`), at the owner's explicit decision,
   for the same reason the branch model above changed. **Everything else in
   this invariant is unchanged and still human-gated:** `tf.sh apply`,
   `destroy.sh`, `smoke-cycle.sh`, and `push-secrets.sh` run by a human, not
   CI. Agents prepare those; humans run them. The CI deploy job's SSH access
   is a dedicated key (`DEPLOY_SSH_PRIVATE_KEY`, a protected file-type CI/CD
   variable) authorized only for the `deployer` user's `authorized_keys` on
   that one Droplet; the CI runner's static IP needs adding to
   `allowed_ssh_cidrs` in `terraform.tfvars` and applying, which is a
   `tf.sh apply` and therefore still the owner's step.
5. **Never spend model budget against the deployment without approval.**
   Live eval runs, load tests, and the release run are human-gated.
6. **Never print or commit a secret.** Do not run `git remote -v` (the
   `gitlab` URL embeds a write token). Do not `cat` anything under
   `/opt/agentforge/secrets` into a transcript that will be shared. Secrets
   live in `~/.config/agentforge/` (mode 600) and as Docker secrets.
7. **Never claim a control is implemented when it is not.** If a task
   cannot be completed, write the limitation instead and say so. A false
   claim in a doc is worse than a missing feature.
8. **Synthetic data only.** The cohort is `af-cohort-v1`. No real patient
   data anywhere, including fixtures, journals, screenshots, and logs.

---

## 2. The shared-document protocol (this is what makes parallelism safe)

Nearly every task wants to edit `KEY_METRICS.md`, `ARCHITECTURE.md`,
`README_AGENT_FORGE.md`, `docs/REQUIREMENTS_TRACEABILITY.md`, and
`docs/SUBMISSION_CHECKLIST.md`. Parallel agents editing those files will
conflict and clobber each other.

**Rule: only the stream that owns a file may edit it.** Every other
stream writes a delta instead.

- A stream that needs a change in a file it does not own appends to
  `docs/_pending/<stream-id>.md` (create the directory; it is gitignored
  via a `.gitignore` entry the first stream adds).
- Delta format, one block per change:

  ```
  ### FILE: KEY_METRICS.md
  ANCHOR: the unique current sentence or heading to locate the edit
  CURRENT: what it says now (short quote)
  REPLACE WITH: the exact replacement text
  EVIDENCE: file:line or command output proving the new text is true
  STREAM: WS-AGENT / task A3
  ```

- At each milestone, a single **doc-apply pass** (one agent, no
  parallelism) reads every `docs/_pending/*.md`, applies the blocks,
  deletes the consumed files, and commits. This is the only writer to
  shared docs.

**Exclusive ownership map.** Files not listed belong to no stream and
require an explicit note before editing.

| Path | Owner |
|---|---|
| `agent/app/**`, `agent/tests/**`, `agent/Dockerfile`, `agent/pyproject.toml`, `agent/requirements.lock`, `agent/README.md` | WS-AGENT |
| `evals/run.py`, `evals/compare.py`, `evals/README.md`, `evals/cases/**` | WS-EVAL |
| `evals/load/**`, `docs/audit/scripts/droplet-stats.sh` | WS-LOAD |
| `infra/**`, `docs/deployment/digitalocean.md` | WS-INFRA |
| `docs/INTERVIEW_NOTES.md`, `docs/INTERVIEW_FEEDBACK.md`, `docs/DEMO_SCRIPT.md`, `docs/SOCIAL_POST.md`, `docs/WEEK2_HANDOFF.md` | WS-CONTENT |
| `KEY_METRICS.md`, `ARCHITECTURE.md`, `AUDIT.md`, `README.md`, `README_AGENT_FORGE.md`, `SETUP.md`, `AI_COST_ANALYSIS.md`, `USERS.md`, `docs/SUBMISSION_CHECKLIST.md`, `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/PROJECT_PLAN.md`, `docs/adr/**`, `docs/operations/**`, `docs/PRIOR_COHORT_LESSONS.md` | WS-DOCS (doc-apply pass only) |
| `docs/audit/evidence/**` | the stream that produced the evidence |

---

## 3. Workstreams

| ID | Name | Milestone | Parallel-safe with | Human-gated steps |
|---|---|---|---|---|
| WS-DOCS | Truth pass and doc-apply passes | M1, M2, M4, M5 | runs alone at each pass | none |
| WS-CONTENT | Interview, demo, social, handoff | M1 (answer sheet), M2 (rest) | all | recording, publishing |
| WS-AGENT | Agent service code and tests | M2 | WS-EVAL, WS-LOAD, WS-INFRA, WS-CONTENT | dependency pin needs read-only SSH |
| WS-EVAL | Eval harness and cases | M2 | WS-AGENT, WS-LOAD, WS-INFRA, WS-CONTENT | live case verification |
| WS-LOAD | Load driver and sampler | M2 build, M4 run | WS-AGENT, WS-EVAL, WS-INFRA, WS-CONTENT | running it (spend) |
| WS-INFRA | Compose, scripts, backup, rehearsal | M2 build, M3/M4 run | WS-AGENT, WS-EVAL, WS-LOAD, WS-CONTENT | deploy, rehearsal Droplet |
| WS-HUMAN | Owner-only deliverables | all | n/a | all of it |

---

## MILESTONE M1 — Documents tell the truth (Thursday, before 12:00 PT)

**Why first.** The technical interview is at 12:00 PT. About thirty
statements across the docs are contradicted by the code, and the twelve
PRD interview questions have no written answer. Both are read during the
interview. Nothing functional changes in this milestone, so it is safe to
run while the deployment is untouched.

**Run in parallel: WS-DOCS-TRUTH and WS-CONTENT-INTERVIEW.**

### WS-DOCS-TRUTH (one agent, owns all shared docs)

Apply rows 1 to 6 and 8 to 18 of the refresh table in
[FINAL_SUBMISSION_TODOS.md](FINAL_SUBMISSION_TODOS.md#doc-refresh-at-the-final-commit).
Skip rows 7 and 19 (WS-CONTENT owns `docs/INTERVIEW_NOTES.md`).

Each row names the file, the current text, and the correct fact. Verify
the correct fact against the code before writing it; the table is a
finding, not gospel. Tasks:

- **D1** Latest-run statements point at `evals/results/2026-09-17T024919Z-a4a5856.md`
  (45 ran, 44 passed, all blocking gates PASS, Golden set 14/14, citations
  177/177, p95 24.1 s, $0.0127 per turn).
- **D2** Name both recall-flaky cases (`MISS-AUTHOR-J-001`,
  `CONF-NOTE-VS-LIST-N-001`), not just the first.
- **D3** Report count: eleven reports at HEAD, not nine.
- **D4** `README_AGENT_FORGE.md:54`: AF-DQ-N's conflict claim is model
  recall, missed once; AF-DQ-A2's amlodipine conflict is the deterministic
  example.
- **D5** Checklist repairs: the `[HAHAHA]` marker at line 119, the missing
  commit at 105, the stale screenshot clause at 64, the "GitHub not kept in
  sync" claim at 8-15 (both remotes are at `e1dd331` with tag `week1`).
- **D6** Deployed-version statements: commit `e1dd331`, tag `week1`
  (runtime directories unchanged since `831e1d8`), not `v0.2.0-slice`.
  `c7253ed` is the tag object, not a commit; do not write it.
- **D8 to D18** The claims the code contradicts: no CSP, ViewEvent not
  dispatched, no parity LimitationKind, `sweep()` not `purge()` and
  retention is a design target, no `unsupported_principal` reason,
  hand-written param allowlist not JSON Schema validation, HIPAA row
  understated, `/ready` tracer check is presence-only and the panel probes
  `/health`, two isolation invariants untested, no source registry, no
  PSR-3 gateway log line, stale "Open Items" title, fault injection on by
  default, Clinical Notes only, `/metrics` public by choice.

**Acceptance:**
```bash
git diff --stat                       # docs only, no code files
grep -rn "HAHAHA" docs/               # no hits
grep -rn "no full run on the 45-case" --include='*.md' .   # no hits
grep -rn "v0.2.0-slice.*live\|purge()\|unsupported_principal" --include='*.md' . | grep -v evals/results  # no hits
```

### WS-CONTENT-INTERVIEW (one agent, owns the interview docs)

- **C1** Write the twelve-question answer sheet as a new top section of
  `docs/INTERVIEW_NOTES.md`: PRD p.10 asks three questions each on the
  audit, the architecture, the evaluation, and production thinking. Each
  answer is three to five sentences with an `Evidence:` file:line pointer.
  Include the 300-user derivation (about 60 concurrent turns and about 140
  gateway calls against a 6-wide semaphore in one uvicorn process with a
  SQLite checkpointer in a local state dir, so scale is a second agent
  container with a shared checkpointer, never `--workers N`), one committed
  worst failure mode, and a "coding workflow" paragraph.
- **C2** Add a dated "deployed today versus planned" table covering: edge
  allowlist, file secrets, `/ready` presence-only tracer check, alerts run
  on demand, no rollback rehearsal, no backups, no egress restriction, no
  load test, no verification pass/fail panel, cost gate NOT CONFIGURED,
  agent-level denials without an OpenEMR audit row, the
  `CONF-NOTE-VS-LIST-N-001` miss, journal unreviewed.
- **C3** Fix the four overclaims in the same file: "streams in about 1 s"
  (TTFE is NOT MEASURED), the alerts job in present tense, rollback stated
  as established, cost "acceptable against the projection" with no
  threshold set.
- **C4** Create `docs/INTERVIEW_FEEDBACK.md` with the disposition rule at
  the top and an empty table (question, answer given, gap admitted,
  disposition, evidence).

**Acceptance:** all twelve questions have an answer and an `Evidence:`
pointer; no sentence in `docs/INTERVIEW_NOTES.md` claims a control the
code does not implement.

### 🛑 STOP — M1 gate

Tell the owner: done, what changed, anything the refresh table got wrong.

**What the owner does by hand:**
1. Read the twelve answers. They are the interview script.
2. Skim `KEY_METRICS.md` "Current status" and the
   `README_AGENT_FORGE.md` status table. Do they match the a4a5856 run?
3. Confirm `docs/SUBMISSION_CHECKLIST.md` has no joke markers.
4. Go to the 12:00 PT interview. Fill `docs/INTERVIEW_FEEDBACK.md`
   within an hour afterward.

**Owner-only, same day:** record the early-submission AI video interview.
Hard stop 19:59 PT Thursday. The email from `support@rs.gauntletai.com`
arrived 2026-09-17 02:59 UTC and is unread.

---

## MILESTONE M2 — Code and harness ready, nothing deployed (Thursday pm and Friday)

**Run in parallel: WS-AGENT, WS-EVAL, WS-LOAD, WS-INFRA, WS-CONTENT.**
Every stream owns a disjoint file set, so no worktree isolation is
needed. Shared-doc changes go to `docs/_pending/<stream>.md`.

### WS-AGENT (owns `agent/**`)

- **A1 (P0)** Make `/ready` probe the tracer. `agent/app/readiness.py:73-76`
  returns `configured` when the two key files are non-empty and sends no
  request; the PRD requires the observability backend be reachable. Make
  `check_tracer` async, keep `not_configured` when a key is absent,
  otherwise `GET {langfuse_host}/api/public/projects` with basic auth and a
  5 s timeout: 200 is reachable, another status is `http_<code>`, an
  `httpx.HTTPError` is its class name. Gather the three async checks. Add
  `test_ready_is_503_when_tracer_unreachable` pointing `langfuse_host` at
  `http://127.0.0.1:9`.
- **A2** Add `copilot_turns_in_flight`. `agent/app/main.py:62-69`
  increments `metrics.in_flight` for every HTTP request including the 30 s
  healthcheck and `/metrics` scrapes, so it is not the queue depth the PRD
  asks for. Add a separate gauge incremented around `graph.ainvoke` and the
  SSE generator, decremented in `finally`. Test that hitting `/health`
  leaves it at 0.
- **A3** Export the verification outcome. `agent/app/api.py:110-115`
  computes `Verification.outcome` and discards it. Add
  `copilot_verification_total{outcome}` to `/metrics` and
  `score_trace("verification_passed")` plus `score_trace("turn_error")` in
  `finish_turn_trace`. The PRD names verification pass/fail rate and error
  rate in the dashboard minimum; neither exists on the nine Langfuse
  panels.
- **A4** Put the correlation id on the three log calls that lack it:
  `agent/app/telemetry.py:146`, `:165`, `agent/app/model.py:265`. Pass it
  explicitly as an argument. Do not introduce a ContextVar and do not touch
  the PHP `error_log` calls; both are deferred to Week 2.
- **A5** Label tool calls with a reason and stop counting authorization
  denials as tool failures. `agent/app/alerts.py:20-23` counts `forbidden`
  toward the tool-failure rate; in the a4a5856 run 6 of the 7 `unavailable`
  results were `forbidden` from `AUTH-FRONTDESK-001`, which would page
  during a front-desk demo. Emit
  `copilot_tool_calls_total{tool,status,reason}` with a bounded reason set
  and exclude `forbidden` in `evaluate_tool_failure_rate`. Test that six
  forbidden among forty do not warn.
- **A6** Pin dependencies. `agent/pyproject.toml` has lower bounds only and
  `start.sh` rebuilds with `--pull` on every deploy, so ADR-0004's "pinned"
  claim is hollow. Generate the lock from the running container (read-only
  SSH, ask the owner to run it if SSH is unavailable):
  `ssh deployer@137.184.4.22 'cd /opt/agentforge && docker compose exec -T agent pip freeze' | grep -v '^agentforge-copilot-agent' > agent/requirements.lock`.
  Dockerfile installs `-r requirements.lock` then `pip install --no-deps .`;
  `.gitlab-ci.yml` matches. Verify a fresh venv from the lock passes.
- **A7** Add the tests for controls the docs already cite: checkpoint
  content (no verbatim note body, no raw-record key shapes, no delegation
  token in any channel after a UC-01 turn and a follow-up on the af-dq-a2
  fixtures; do not assert lab values or doses are absent, verified claims
  carry them by design), the 429 rate limit with `turns_per_minute = 2`,
  the circuit breaker opening after three failures and closing after the
  cooldown, and `guard_environment()` raising on `LANGSMITH_TRACING=1`.
  If the checkpoint test finds a raw record shape, that is an ADR-0005
  breach: stop and report it, do not paper over it.

**Acceptance:**
```bash
cd agent && .venv/bin/python -m pytest -q          # was 60 tests, expect more
.venv/bin/python -m app.contracts.export --check
cd .. && agent/.venv/bin/python evals/run.py --offline-only
```
Plus `docs/_pending/WS-AGENT.md` with deltas for `ARCHITECTURE.md`,
`KEY_METRICS.md`, ADR-0004, ADR-0007, the traceability matrix, and the
checklist.

### WS-EVAL (owns `evals/run.py`, `evals/cases/**`, `evals/README.md`)

- **E1 (must land before the release run)** Wire the cost gate.
  `evals/run.py` hard-codes the "Cost per verified turn" row as
  NOT CONFIGURED. Add `COST_PER_TURN_PROJECTION_USD = 0.0223` beside
  `PRICE_PER_MTOK` and make it a real gate: PASS at or under $0.0223, warn
  between one and two times with risk acceptance, block above $0.0446,
  NOT CONFIGURED only when there are no model-backed turns. Emit a delta
  explaining in `AI_COST_ANALYSIS.md` why the basis is $0.0223 while the
  eval mix measures $0.0127 (four post-deploy turns at about 1,950 output
  tokens versus about 1,170 in the eval mix; no setting changed between
  them), and defining the daily budget from the 2,000,000-token halt
  (about 1,100 turns, about $14 per day warn, $42 page).
- **E2** Decide the `CONF-NOTE-VS-LIST-N-001` matcher. In a4a5856 the
  conflict claim was verified and cited both tables but its text lacked
  "atorvastatin", so only the claim-text regex failed while the turn-level
  check passed; 11 of 12 recorded runs pass the strict matcher. Either keep
  the assertion and record the miss as a wording miss, or replace
  `text: atorvastatin` with `kind: note_vs_list` in `claims_include`
  keeping `type: conflict`, `tables_all`, and the turn-level drug-name
  check. Record the choice in the case `risk:` line and `evals/README.md`.
  Never loosen silently.
- **E3 (only if under two hours)** Add `ISO-FRESH-REPEAT-001` (AF-DQ-C,
  fresh conversation carries no history, `text_must_not_match` on "as I
  mentioned earlier" phrasings) and `ISO-TWO-USERS-001` (an `as_user:`
  step opening a second session as `physician`, then a ticket carrying the
  first user's conversation id expecting 403 or 404). `ARCHITECTURE.md:482-487`
  calls both invariants tested with no case behind them. If the harness
  change exceeds two hours, stop and emit a delta listing them under
  `evals/README.md` "Not automated in Week 1".

**Acceptance:** `evals/run.py --offline-only` and `--golden-only` parse and
run; the gate table shows a real cost state; every new case has the
required metadata and a `risk:` line; no case file is half-finished
(`manifest()` globs every YAML, so a broken case turns the gate table
NOT RUN and blocks).

### WS-LOAD (owns `evals/load/**`, `docs/audit/scripts/droplet-stats.sh`)

Build only. Running is M4 and human-gated.

- **L1 (P0)** `evals/load/run_load.py`: asyncio plus `httpx.AsyncClient`,
  no new dependency. Port the six-step handshake from the `Session` class
  in `evals/run.py`. Each virtual user logs in as `audit-physician` or
  `physician`, opens AF-DQ-A2 (900001), AF-DQ-N (900018) or AF-HEAVY
  (900023), and times chart open, `session.php`, start, mint, the UC-01
  turn, mint, one follow-up. Flags: `--users`, `--label`, `--fault model`
  (capacity without provider limits), about 30 s ramp. At 1 and 10 users
  also send the first turn with `Accept: text/event-stream` and record time
  to the `event: evidence` frame. Write
  `evals/load/results/<UTC>-<sha>.json` with a fixed schema: per level and
  scenario p50/p95/p99 for chart open, ticket and turn; error rate split by
  5xx, 504, 429 and transport; denials; status share complete, partial,
  fallback, failed; tool `unavailable` counts by reason from
  `copilot_tool_calls_total` deltas.
- **L2** `docs/audit/scripts/droplet-stats.sh`: read-only over SSH, 5 s
  samples to CSV. `docker stats --no-stream` for openemr, database, agent
  and caddy; `docker top <openemr> | grep -c httpd` against the 250 prefork
  cap; `SHOW GLOBAL STATUS LIKE 'Threads_connected'`; host `free -m` (no
  swap is configured); `/metrics` at the start and end of each level.
- **L3** Write the expected-failure note into the script's docstring: 50
  users times `tool_concurrency` 6 is up to 300 concurrent gateway requests
  against 250 prefork workers with a 2.0 s timeout, so the likely 50-user
  failure is `partial` turns rather than 5xx, and provider 429s open the
  breaker for 60 s and convert turns to fallback. These are results to
  record, not bugs to fix during the window.

**Acceptance:** `--users 2` smoke against the deployment (human-approved,
about $0.05) produces a valid results JSON; the sampler writes a CSV.

### WS-INFRA (owns `infra/**`, `docs/deployment/digitalocean.md`)

- **I1** Add an `alerts` service to `infra/digitalocean/runtime/compose.yaml`:
  `image: agentforge/copilot-agent:local`, command
  `python -m app.alerts --url http://agent:8080/metrics --ready-url http://agent:8080/ready --state /var/lib/copilot/alerts-state.json --interval 300`,
  the `agent_state` volume, the `frontend` network,
  `restart: unless-stopped`, and `healthcheck: {disable: true}`. The
  disable is mandatory: the inherited Dockerfile HEALTHCHECK would stall
  `docker compose up --wait` in `start.sh`. The alert rules and 26 tests
  already exist; nothing schedules them.
- **I2** Make `infra/digitalocean/runtime/start.sh` recover and fail
  loudly. After the existing `up --detach --wait`, add
  `docker compose up --detach --wait --wait-timeout 120 caddy`, then a
  `docker compose ps` check that exits non-zero unless database, openemr,
  agent, caddy and alerts are running, then a retry loop (six attempts, 10 s
  apart) on `curl --fail https://${public_hostname}/meta/health/livez`. Add
  an `x-logging` anchor (`json-file`, `max-size: 10m`, `max-file: 3`) to
  every service; container logs are unbounded on a host up since 2026-09-15.
- **I3** Write `infra/digitalocean/backup.sh` and `restore.sh`. Backup over
  SSH: `mariadb-dump --single-transaction` of the openemr database, a tar
  of the `openemr_sites` and `agent_state` volumes, a tar of
  `/opt/agentforge/secrets` and `.env`, streamed into one timestamped
  archive encrypted with `age` or `gpg --symmetric` under
  `~/.config/agentforge/backups/`, never into the repo. Restore: stop
  openemr and agent, untar secrets and `.env`, load the dump, untar the
  volumes, `up -d --wait`. Document that the demo password is generated on
  the host, so losing `/opt/agentforge/secrets` orphans the database volume
  and changes `DEMO_PASSWORD`.
- **I4** Write the rehearsal runbook into `docs/deployment/digitalocean.md`
  as exact commands: a throwaway SSH key, a `rehearsal` Terraform
  workspace with `-var project_name=agentforge-rehearsal`, deploy,
  demo-seed, `--golden-only` against the rehearsal host, rollback by
  deploying tag `week1` from `git worktree add /tmp/rb week1`, roll forward
  to HEAD, `restore.sh`, then destroy the same day. State in bold that the
  default workspace and `137.184.4.22` are never touched, and that
  `smoke-cycle.sh` and a default-workspace `tf.sh apply` both target the
  live Droplet. Execution is M3/M4 and human-gated.

**Acceptance:**
```bash
cd infra/digitalocean/runtime && PUBLIC_HOSTNAME=x TLS_EMAIL=y docker compose --env-file /dev/null config --quiet   # the verbatim `config --quiet` exits 1: compose.yaml requires PUBLIC_HOSTNAME/TLS_EMAIL and the runtime .env is gitignored
bash -n start.sh && bash -n ../backup.sh && bash -n ../restore.sh
```

### WS-CONTENT (owns the content docs)

- **X1** Revise `docs/DEMO_SCRIPT.md` for the final video with numeric
  placeholders: a "since the early submission" opener, then replace the
  closing rows with the eval report at the final commit (10 s), load
  results at 10 and 50 users with p50/p95/p99, error rate and the
  CPU/memory baseline (15 s), one alert rule and the alerts service output
  (10 s), the rollback rehearsal in one sentence (5 s), and the cost line
  with the gate's real state (10 s). Cut the dosing refusal beat. Keep the
  commit and tag on screen. The script must not claim numbers that do not
  exist yet; placeholders stay visible as `<pending M4>`.
- **X2** Draft `docs/SOCIAL_POST.md` in LinkedIn and X versions: the hook
  ("90 seconds between patient rooms"), what it is (read-only co-pilot
  inside OpenEMR, every statement cites a chart record, a deterministic
  verifier checks each claim), three or four numbers, one audit lesson (the
  fail-open ACL helper the gateway bypasses), links to the public GitHub
  fork and the final video, tagging @GauntletAI. The X version is under 280
  characters. The lab GitLab is login-only, so never link it publicly.
- **X3** Write `docs/WEEK2_HANDOFF.md`: read-first order; a seams table
  honest about what is code and what is prose (`SourceRef.id` is an int,
  reserved claim types are a comment, there is no source registry, there is
  no `actions/` directory); the compare.py baseline; residuals (fault
  injection on by default on the demo host, no checkpoint sweeper, the
  daily halt counts input plus output only, langchain is present only for
  the Langfuse callback, the Langfuse v2 API migration is due 2026-11-16);
  the two deferred experiments (a deterministic note-versus-list conflict
  line in `pack_limitations`, a one-planning-round cap for follow-ups) each
  with the baseline-change-compare protocol; operational state by file name
  only, never values. One page is enough if time is short.
- **X4** Pre-write the egress risk-acceptance paragraph as a delta so
  Saturday's decision flips one sentence: what code execution in the agent
  would gain (model and tracer keys, the evidence pack) against the
  compensating controls (file secrets only in that container, no database
  route, deny-by-default edge, PHI-free telemetry, the 2M-token daily halt,
  a disposable Droplet). Also draft the dated "after grading" rotation
  checklist for `docs/deployment/digitalocean.md`.

### Doc-apply pass (one agent, after the five streams finish)

Read every `docs/_pending/*.md`, verify each `EVIDENCE:` line still holds,
apply the blocks to the shared docs, delete the consumed pending files,
and report any delta that conflicts with another or with the code.

### 🛑 STOP — M2 gate

**Machine verification, all must pass before the owner is asked:**
```bash
cd agent && .venv/bin/python -m pytest -q && .venv/bin/python -m app.contracts.export --check
cd .. && agent/.venv/bin/python evals/run.py --offline-only
cd infra/digitalocean/runtime && PUBLIC_HOSTNAME=x TLS_EMAIL=y docker compose --env-file /dev/null config --quiet   # the verbatim `config --quiet` exits 1: compose.yaml requires PUBLIC_HOSTNAME/TLS_EMAIL and the runtime .env is gitignored
cd ../../.. && git status --short && git diff --stat
ls docs/_pending/ 2>/dev/null   # must be empty or absent
```

**What the owner does by hand:**
1. Read the full diff. Nothing outside the owned file sets; no prompt,
   model, or verifier change.
2. Run the agent tests and the offline evals once, personally.
3. Decide: approve the single deploy, or send items back.

Nothing has touched the deployment yet. This is the last cheap stopping
point.

---

## MILESTONE M3 — Deployed once and verified (Friday)

Human runs the deploy. Agents prepare the commands, watch the output, and
verify afterward.

1. Owner confirms the SSH allowlist matches the current public IP
   (`curl -s https://api.ipify.org` against `infra/digitalocean/terraform.tfvars`;
   if it differs, `tf.sh apply` where the plan shows only the firewall).
2. Owner runs `infra/digitalocean/deploy.sh 137.184.4.22 openemr-137-184-4-22.sslip.io <tls-email>`.
   Do not rerun `demo-seed`. Keep the Caddy-stuck-in-Created recovery
   command at hand until I2 is proven.
3. Agent verification, in order:
   ```bash
   infra/digitalocean/smoke.sh
   curl -s https://openemr-137-184-4-22.sslip.io/copilot-api/ready | jq   # tracer now "reachable"
   cd docs/api-collection && bru run --env deployed --env-var DEMO_PASSWORD="$DEMO_PASSWORD"   # 21/21
   cd ../.. && DEMO_PASSWORD="$DEMO_PASSWORD" agent/.venv/bin/python evals/run.py --golden-only
   ssh deployer@137.184.4.22 'cd /opt/agentforge && docker compose logs --tail 5 alerts'      # heartbeat
   ```
4. Agent smoke-tests the load driver at `--users 2` (about $0.05).

### 🛑 STOP — M3 gate

**What the owner does by hand:**
1. Open the panel on AF-DQ-A2 as `audit-physician`, run a starter
   question, click a citation, confirm it opens the record.
2. Open Langfuse and confirm the two new panels (verification pass rate,
   turn error rate) draw data.
3. Confirm `/copilot-api/ready` reports the tracer as reachable, and that
   stopping the tracer key would flip it (or trust the test).

If anything is wrong here, the rollback is redeploying tag `week1` from a
worktree. Do that rather than hot-fixing forward under time pressure.

---

## MILESTONE M4 — Production evidence captured (Saturday)

Order matters: rehearsal and backup first so the host can be restored,
then the snapshot, then the load runs, then the egress decision by noon.

1. **Snapshot first (owner).**
   `doctl compute droplet-action snapshot $(./tf.sh output -raw droplet_id) --snapshot-name week1-final-2026-09-19`,
   and copy both `terraform.tfstate` files plus `terraform.tfvars` to
   `~/.config/agentforge/tfstate/<date>/` at mode 600.
2. **Rehearsal (owner runs, agent watches).** The I4 runbook on a throwaway
   Droplet: clean deploy, rollback to tag `week1`, roll forward, restore
   from backup, `--golden-only` on the rehearsal host, then destroy the
   same day. Agent records each step's wall-clock time into the runbook.
3. **Load tests (owner approves spend, agent drives).** A five-minute idle
   baseline with the sampler, then `--users 10` and `--users 50` with the
   real model (about 20 and 100 model-backed turns, roughly $0.25 and
   $1.30; read `copilot_tokens_total` first because the daily halt counter
   is process-local), then both levels again with `--fault model`. Check
   `/ready` and `docker compose ps` after each level. Never during an eval
   run or the demo. Never resize the Droplet or change `tool_concurrency`
   as a reaction inside the window: record and move on.
4. **Baselines (agent).** Write
   `docs/audit/evidence/performance/load-test-2026-09-19.md` and
   `baseline-2026-09-19.md` with per level and scenario: mean and peak CPU
   per container, peak memory, host free-memory low-water mark, peak httpd
   count, peak `Threads_connected`, turns per minute, p50/p95/p99, error
   rate, status share. Commit the CSVs and the JSON. Report the status
   share beside latency: latency is gamed by falling back early.
5. **Interpretation (agent, delta).** Write the worker-count and
   Droplet-size decision into `ARCHITECTURE.md` "Latency and Scale": one
   asyncio process per node because the limiter, metrics, breaker, daily
   halt and SQLite checkpointer are all process-local, so scale is by
   nodes. Resize only if the host actually swaps or saturates, and only
   before the release run so the baseline matches the final host.
6. **Egress decision by noon (owner).** Default is to paste X4's risk
   acceptance. Build the DOCKER-USER rules only if they were proven on the
   rehearsal Droplet on Friday. Never build them first on the graded host.
7. **Alerts rehearsal (agent).** Five `X-Copilot-Fault: tool:medications`
   turns and one `model` turn; commit the PHI-free output as
   `docs/audit/evidence/observability/alerts-rehearsal-2026-09-19.log`.
8. **Cost completion (agent).** Fill the per-tier architectural-changes
   table in `AI_COST_ANALYSIS.md` (tier, what breaks first, change, cost
   effect) grounded in code, fold in the measured concurrency, and replace
   "scales linearly" with "linear until the tier levers apply".
9. **Doc-apply pass** for everything above.

### 🛑 STOP — M4 gate

**What the owner does by hand:**
1. Read the load and baseline numbers. Do they support or contradict the
   30 s p95 threshold in `KEY_METRICS.md`? Confirm or revise it explicitly;
   loosening a latency threshold needs a written risk acceptance, and
   loosening a safety gate is never allowed.
2. Confirm the rehearsal actually rolled back and restored, with timings.
3. Confirm no claim anywhere asserts evidence that did not materialize.

---

## MILESTONE M5 — Freeze, release run, submit (Saturday 18:00 PT through Sunday)

1. **Code freeze 18:00 PT.** After this, nothing touching the gateway,
   verifier, prompt, model, or eval assertions merges. Docs only.
2. **Deploy the frozen tree (owner).** `git status --porcelain` empty,
   `git worktree add /tmp/final <frozen-sha>`, deploy from there.
3. **Release run (owner approves, agent drives), start by 19:00 PT.**
   ```bash
   DEMO_PASSWORD=... agent/.venv/bin/python evals/run.py --repeat 3 --label "week1-final release run"
   agent/.venv/bin/python evals/compare.py evals/results/2026-09-17T024919Z-a4a5856.json evals/results/<final>.json > evals/results/<final>-vs-a4a5856.md
   ```
   About 36 minutes and about $1.65. **If a blocking gate fails: roll back
   to tag `week1` and submit the early agent with the new evidence and an
   honest limitations list. Never edit an assertion to make it pass. Never
   hot-fix on Sunday.**
4. **Record the deployed identity (agent).** Commit, results file, and
   `docker compose images` digests into `docs/deployment/digitalocean.md`,
   `README.md`, `SETUP.md`, `ARCHITECTURE.md`.
5. **Edge probe (agent).** `deploy.sh` re-copies the Caddyfile, so rerun
   `docs/audit/scripts/cloud-probe.sh` and commit it as
   `cloud-probe-2026-09-19-final.txt`.
6. **Final doc pass part 2 (agent).** Refresh table rows 19 to 30: every
   "target 2026-09-19" and "planned" passage gets the report path and real
   numbers, or the same sentence everywhere ("not done for Week 1;
   residual risk, see AUDIT.md §9") with no future date. Refresh
   `AI_COST_ANALYSIS.md` Part A (66 project commits at HEAD, both Droplets'
   hours, about $6.20 of eval model spend across the scorecards). Walk the
   202 "2026-09-16" status lines outside `evals/results` and update each or
   append "unchanged as of 2026-09-20". Trim the `AUDIT.md` executive
   summary from 635 words toward 550 by moving status sentences into
   section 7, removing no finding.
7. **Merge to `main`, then tag and push (owner).** In this order, because
   the submission form names GitLab `main` and the checklist calls it the
   system of record:
   1. Run the secret scan from checklist :95-98 while still on the branch.
   2. `git push gitlab week1-final-push && git push origin week1-final-push`.
      Push the branch as early as Friday, not at the freeze, so its pipeline
      is green well before Sunday. **If the manual `test:evals-live` job
      fails immediately with an empty `DEMO_PASSWORD`, that variable is
      marked protected in GitLab and is exposed only to protected branches.
      Either mark `week1-final-push` protected or unprotect the variable;
      do not paste the password into the job.**
   3. Open the merge request to `main` on
      `labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean`,
      title it "Week 1 final submission", and merge it yourself. The web UI
      needs no token; the API route needs the renewed api-scope PAT.
   4. `git checkout main && git pull` so local `main` carries the merge.
   5. `git tag -a week1-final -m "Week 1 final submission; deployed tree = <frozen-sha>, differs only in docs and results"`
      on `main`, then `git push gitlab main --tags && git push origin main --tags`.
   6. Confirm with `git ls-remote --heads --tags gitlab` and the same for
      `origin` that both carry the identical `main` and `week1-final`.
   Do not submit the form until step 6 is clean; a reviewer opening `main`
   must see the final work, not `e1dd331`.

### Owner-only, not delegable

| When | What |
|---|---|
| Thu by 19:59 PT | Early-submission AI video interview |
| Thu after the interview | Fill `docs/INTERVIEW_FEEDBACK.md` |
| Thu or Fri | Review the 20-trace error-analysis journal by hand (`evals/review_ui.py`); finding the issue is explicitly not delegable |
| Sat evening | Record the final demo video, 3 to 5 minutes, after the release run |
| Sat night or Sun 06:00 PT | Publish the social post with the 20 to 30 s clip |
| Sun 06:30 PT | Rerun the checklist: `--golden-only`, the phone check, and `git ls-remote --heads --tags` on both remotes showing the merge request landed and `main` carries the `week1-final` tag |
| Sun 08:00 PT | Submit the form: live URL, repo URL, video, social post, `audit-physician` plus password |
| Sun afternoon | Final AI video interview within 24 hours of submitting |

---

## 4. Cut order when time runs short

Cut in this order and write one sentence per cut item under
`evals/README.md` "Not automated in Week 1" or in Known Limitations:

1. WS-EVAL E3 (the two isolation cases) and any WS-CONTENT item beyond X1
   and X2.
2. WS-AGENT A7 beyond the checkpoint-content test.
3. The egress build (paste the risk acceptance instead).
4. `docs/WEEK2_HANDOFF.md` shrinks to a one-page stub.

**Never cut:** the M1 truth pass, the early AI interview, A1, A6, I2, the
rehearsal in its minimum form (rollback to tag `week1`), E1 before the
release run, the load tests and baselines, the 18:00 PT freeze, the
release run, the demo, the social post, and submitting by 08:00 PT.

## 5. Reporting

At every STOP, report in this shape: what landed, what the verification
commands printed, what was cut and why, what the owner must check by hand,
and any finding that contradicts
[FINAL_SUBMISSION_TODOS.md](FINAL_SUBMISSION_TODOS.md) or a doc. Never
report a task complete without the command output that proves it.
