# Interview Notes: Answer Sheet and Pre-Search Checklist

Two sections. **The twelve questions** is the answer sheet for the technical
interview (prepared 2026-09-17). **The pre-search checklist** below it answers
the PRD's Appendix, one section per heading, as built and measured through
2026-09-17. Each answer names where the evidence lives. Numbers come from the
eval results in `evals/results/` unless a source is named. Where something is
deferred, not measured, or not implemented, it says so.

## The Twelve Questions

The PRD's own wording for these twelve is not in this repository — no PRD file
exists in the tree — so the questions below are reconstructed from the four
themes the PRD's p.10 "Interview Preparation" section names (the audit, the
architecture, the evaluation, production thinking), three each. The two
phrasings that do survive in the repo, "What did you find when you ran it?"
and "What did you find? What would you add next?", are used verbatim
(`docs/FINAL_SUBMISSION_TODOS.md:122`, `:165`). Every answer ends with an
`Evidence:` pointer that resolves to real content in this tree.

### The audit

**Q1. What did you find when you audited OpenEMR?**

Five findings, and the first one determined the whole design: OpenEMR
authorizes by role and by chart section, never by patient. `AclMain::aclCheckCore`
takes no patient argument, only 4 of 310 classes under `src/Services/`
reference it and none of those are clinical, and the one patient hook,
`checkUserHasAccessToPatient()`, is a `return true` stub used during SMART
launch binding. We proved it live rather than reading it: accounts in
Physicians and Clinicians opened two unrelated charts and got HTTP 200 on all
twelve clinical sections, while Front Office got 403 on the issue lists — so
section ACL works and patient-level ACL does not exist. The other four
findings were the data (the stock demo data cannot support the use case and
contradicts itself), services that fail silently, an audit log the co-pilot
would bypass, and a deployment edge that forwarded every path.

Evidence: `AUDIT.md` security findings table, row SEC-HIGH-001; `docs/audit/evidence/security/live-cross-patient-test.md`.

**Q2. Which finding changed the architecture, and what did you do about it?**

The absence of patient-level authorization. We could not inherit "may this
user see this patient" from the host, so ADR-0002 chose parity: the co-pilot
shows exactly what the user could see by clicking, the conversation is bound
server-side to (site, user, pid), the chart's own section ACLs and squad check
are re-run on every tool call, the model never picks a patient, and the
limitation — isolation equals OpenEMR's — is written down rather than papered
over. That decision is also why the gateway is in-process inside an OpenEMR
module (ADR-0003): it is the only place where the session and the ACLs both
exist. It paid for itself within a day. The first live role test caught
`AclMain::aclCheckIssue()` failing open when the issue-type table is not
loaded at page scope — true in the gateway's session-less request — so Front
Office briefly received problems and allergies through the co-pilot; it was
closed the same day by reading `issue_types.aco_spec` directly and failing
closed.

Evidence: `AUDIT.md` §8, the `aclCheckIssue()` fail-open paragraph; `docs/adr/0002-patient-scope-authorization.md`.

**Q3. What did the audit leave unresolved — what would you add next?**

Three things, and I will not claim any of them as done. Agent-level denials (a
missing, tampered, or mismatched delegation token rejected at the agent API)
are counted in `/metrics` and written to the agent's logs, but they never
reach the gateway, so they leave no OpenEMR audit row; gateway-level denials
do. `ViewEvent` dispatch — the hook ADR-0002 describes as the way the co-pilot
would inherit any future upstream patient filter — is designed and not
implemented; there is no reference to it in the module. And the agent's egress
is still unrestricted: the Terraform firewall allows all outbound TCP, UDP and
ICMP, so "egress limited to the LLM and tracing endpoints" is a plan, not a
control.

Evidence: `ARCHITECTURE.md` "Open Items" item 9; `AUDIT.md` remediation table, row SEC-MEDIUM-504; `infra/digitalocean/main.tf:54-70`.

### The architecture

**Q4. Why this architecture — one agent, LangGraph, this model?**

One agent, one LangGraph turn graph with eight nodes: authorize, classify,
plan, retrieve, narrate, verify, repair, render. LangGraph was chosen on day
one (ADR-0004) so that Week 2's supervisor-and-workers shape extends the graph
instead of replacing a hand-rolled loop, and so conversation state is a
checkpoint rather than something I maintain by hand. Multi-agent is deferred
until there is a second responsibility worth a worker; today there is not. The
model is Claude Sonnet 5 through the Anthropic SDK, chosen on measured latency
after Opus 5 was tried first, and structured output is JSON-as-text validated
by a Pydantic contract because grammar-constrained decoding measured 45 s or
more per call.

Evidence: `agent/app/graph/build.py:11-32`; `docs/adr/0004-agent-runtime-contracts-and-model.md`.

**Q5. Where is the trust boundary, and how does the agent get data?**

The agent never touches the database and never issues SQL. It calls seven
typed tools over one in-process gateway inside an OpenEMR custom module, each
with a 2 s timeout and a status of ok, empty, partial, or unavailable. Every
call re-checks the live session, the conversation binding, the chart's section
ACLs and the squad restriction, and writes an OpenEMR audit row *before* any
data leaves — if that insert fails, the tool returns `unavailable` instead of
records. One thing I will not overstate: the gateway's parameter check is a
hand-written allowlist plus format checks that mirror the exported JSON
Schemas, not validation against the schema files. Schema-file validation is
planned, and the docblock at `ToolRegistry.php:37` still claims otherwise.

Evidence: `interface/modules/custom_modules/oe-module-copilot/public/gateway/tools.php:64-76`; `interface/modules/custom_modules/oe-module-copilot/src/Gateway/Tools/ToolRegistry.php:37-54`.

**Q6. How do you stop the model from displaying something untrue?**

A deterministic verifier runs between the model and the browser, and the model
cannot grade, approve, or bypass it. Every displayed patient-specific
statement is a typed claim — nine claim types plus `interpretation` — citing a
record retrieved in the same turn through the same authorization as the chart;
the verifier checks source existence, field-level fact match per claim type,
window membership for changes, a forbidden-language lexicon (no advice, no
causation), and permits an absence claim only after a successful retrieval of
that section. A rejected claim is withheld, the turn's status becomes
`partial`, one repair round runs with the specific rejection reasons, and the
model's prose summary is replaced by a count-only summary whenever anything
was withheld. The safety property therefore belongs to the verifier, not to
the model: a weaker model raises the withheld and repair rates without making
what is displayed less true.

Evidence: `agent/app/verifier.py:98-120`; `docs/adr/0006-verification-strategy.md:26-81`.

### The evaluation

**Q7. How do you know it works — what does the suite actually assert?**

46 YAML cases (45 in the latest recorded run, `a4a5856`; `ISO-FRESH-REPEAT-001` was added 2026-09-17 and has not run yet) run against the real deployment, driving the real login, chart
open, session, ticket and turn handshake as different users; 14 are a golden
smoke tier and 4 are a holdout tier excluded from filtered runs. The
assertions are deterministic — HTTP status, authorization outcome, evidence
status per tool, claim types and matchers for planted findings, citation
resolution, limitations, verifier outcome, latency — and no model-graded score
enters the pass rate. Thirteen release gates sit on top of the cases; the
blocking ones are golden-set integrity, authorization leakage, unsupported
displayed claim, explicit uncertainty recall, safe degradation, healthy-stack
tool failures, citation resolution, latency p95 and error rate. Three gates
deliberately refuse to pass by default: citation correctness and time to first
useful evidence report NOT MEASURED, and cost per verified turn reports NOT
CONFIGURED.

Evidence: `evals/run.py:635-648`; `evals/results/2026-09-17T024919Z-a4a5856.md:8-23`.

**Q8. What is your ground truth?**

A deterministic synthetic cohort, `af-cohort-v1`: 26 fictional patients, one
per catalogued OpenEMR data defect, seeded by a committed PHP script, so the
required behaviour for each patient is known before the case is written. It
exists because the stock demo data cannot support the use case — three
patients, one 2014 encounter each, zero lab results, three placeholder notes,
every onset date empty — and because Synthea output has no fixed seed and is
not reproducible as a fixture. Recorded gateway responses from the same cohort
double as pytest fixtures, so the offline tests and the live suite share one
contract. No real patient data is used anywhere in this project.

Evidence: `evals/fixtures/cohort/README.md`; `evals/fixtures/cohort/seed_cohort.php`.

**Q9. What did you find when you ran it?**

The latest full run (2026-09-17, commit `a4a5856`) executed all 45 cases and
passed 44, with every blocking gate PASS: golden set 14 of 14, citations 177
of 177 resolved, no unsupported displayed claim, zero 5xx, model-backed p95
24.1 s against the 30 s warn line, $0.0127 per model-backed turn. The single
failure is `CONF-NOTE-VS-LIST-N-001` under the non-blocking task-success gate
at 95%: the model did not raise a planted note-versus-list medication
conflict. Flakiness is confined to model recall — two cases have flipped run
to run, `MISS-AUTHOR-J-001` and `CONF-NOTE-VS-LIST-N-001` — while every
deterministic assertion has passed every time. The scorecard, not the pass
count, is the signal I read: 32.5% of turns needed a repair round, 2.6% of
statements were withheld, 3.75 claims and 2.33 model calls per turn.

Evidence: `evals/results/2026-09-17T024919Z-a4a5856.md:3`, `:8-23`, `:26-53`, `:80-94`, `:123`.

### Production thinking

**Q10. What happens at 300 users?**

300 physicians on the usage model in `AI_COST_ANALYSIS.md` (20 visits a day,
one UC-01 turn plus one follow-up per visit, 22 working days) is 12,000 turns
a day; spread flat across an 8-hour clinic at that document's 17 s per turn,
that is about 7 concurrent turns — but appointments are slot-aligned, so an
hour's worth compresses into the few minutes after the hour and the realistic
peak is about 60 concurrent turns (1,500 turns x 17 s / ~420 s). Taking UC-01
first turns as roughly a third of the peak mix, and each first turn issuing
seven gateway calls (one `encounters` call, then six tools fanned out), that
peak puts about 140 calls into the in-process module gateway at once, each
with a 2 s timeout, against Apache prefork's 250 workers; the eval suite's
55/45 first-to-follow-up mix would push the same burst nearer 210. Three
process facts decide what happens next, and all three are in the code: the
agent runs a single uvicorn worker with no `--workers` flag, the 6-wide
`asyncio.Semaphore` is constructed *inside* the retrieve node per turn so it
bounds fan-out within one turn and not across turns (there is no process-wide
turn semaphore), and the LangGraph checkpointer is an `AsyncSqliteSaver` over
a file in a local state directory. That SQLite file is exactly why the answer
is never `--workers N` — a second worker in the same container would contend
on it — so scaling is a second agent container behind the edge with a shared
checkpointer, which is a Week 2 change rather than a flag. None of this is
measured yet: the load driver (`evals/load/run_load.py`, 43 offline tests) and
the Droplet sampler (`docs/audit/scripts/droplet-stats.sh`) were built
2026-09-17 and have not been run; the 10- and 50-user runs are the M4 step,
human-gated.

Evidence: `agent/Dockerfile:25`; `agent/app/graph/nodes.py:138` with `agent/app/settings.py:19`; `agent/app/state_store.py:61-63` and `agent/app/main.py:43-48`; `AI_COST_ANALYSIS.md:141-171`; `evals/load/run_load.py`.

**Q11. What is your worst failure mode?**

Silent omission, and it is committed rather than argued about. The verifier is
a false-positive control only: it can prove that everything shown is
supported, and it cannot notice something the model never said. The concrete
case is `CONF-NOTE-VS-LIST-N-001` — a note says atorvastatin was stopped while
the medication list still calls it active — and the case file states plainly
that no deterministic detector for a note contradicting the list exists, so
raising that conflict is model recall. In the 2026-09-17 run the model did not
raise it, and the turn still rendered as a clean, fully cited, complete answer
with nothing flagged; the physician would have had no signal that a conflict
existed. That is the worst thing this system does today, it sits under a
non-blocking gate by design, and the fix is a deterministic note-versus-list
detector, not a better prompt.

Evidence: `evals/cases/CONF-NOTE-VS-LIST-N-001.yaml:5-7`; `evals/results/2026-09-17T024919Z-a4a5856.md:123`.

**Q12. How would you operate this — monitoring, alerting, rollback, cost?**

One correlation id runs through the panel, the gateway, the OpenEMR audit row,
the agent logs, the metrics and the trace; traces go to Langfuse Cloud through
a client-side mask that replaces every payload with a digest, and the agent's
own logs are PHI-free JSON. `/metrics` is a Prometheus-style endpoint and
`agent/app/alerts.py` evaluates the three PRD alerts over two samples of it —
on the live host still run on demand; the `alerts` compose service
(`--interval 300`, in the tree since 2026-09-17) reaches the host at the M3
deploy. Rollback is redeploying
the previous commit with the same script and needs no data migration because
the co-pilot is read-only, but it has never been rehearsed, there are no
backups, and the whole deployment is a single Droplet and therefore one
failure domain. Cost is bounded by token caps (20K per turn, 60K per
conversation) and a daily 2,000,000-token halt that routes every further turn
to the deterministic fallback; the measured $0.0127 per model-backed turn sits
below the $0.0223 projection basis, which has been the configured gate since
2026-09-17 (`evals/run.py` `cost_gate()`: PASS at or under $0.0223, PASS
(warn) to $0.0446 with risk acceptance in the report, FAIL and blocking
above; NOT CONFIGURED only for a run with no model-backed turn).

Evidence: `agent/app/alerts.py:1-24`; `docs/operations/alerts.md:203-233`; `evals/run.py:146`, `:593`; `AI_COST_ANALYSIS.md:63`.

### Coding workflow

The repository is the process. Every decision that constrains later work is an
ADR (seven so far), and every agent session starts from `AGENTS.md`, which
carries the hard gates: do not implement the AI layer until the audit is
complete, trace every capability to a use case in `USERS.md`, and never
describe a planned safeguard as implemented. The order was audit, then
`USERS.md`, then the architecture and the ADRs, then the module gateway, then
the agent, then the evals — the AI layer was gated on the audit being
finished, not on a feeling that the codebase was understood. Work lands in
small conventional commits (81 at `0fba313`), and every push runs the
fast deterministic checks in `.gitlab-ci.yml`: whitespace, `php -l` over the
module, `caddy validate`, `docker compose config`, the 91 pytest cases, the
contract drift check and the offline eval subset; the live suite is a manual
job so a push never spends model budget by itself. The standing rule is
evals-before-tuning — no change to the prompt, the model id, the effort
setting or the verifier lexicon without a baseline run, the change, a second
run and an `evals/compare.py` diff — and a case is added for every discovered
bug and every cohort defect. What the workflow does not yet include is the
review step: one error-analysis journal of 20 traces is sampled and committed,
and all 20 First-issue fields are still blank.

Evidence: `AGENTS.md:28-36`; `.gitlab-ci.yml:8-66`; `evals/README.md:197-199`.

## Deployed today versus planned (2026-09-17)

What is actually running on the Droplet at the time of the interview, against
what is written down but not built. "Planned" here means planned — nothing in
the right-hand column is implemented.

| Control | Deployed today (2026-09-17) | Planned / gap | Evidence |
| --- | --- | --- | --- |
| Edge path allowlist | Deployed. Caddy denies by default; only OpenEMR application paths, `/copilot-api/*` and `/meta/health/livez` are routed, and the module's `gateway/` and `bin/` paths return 404 from the edge | — | `infra/digitalocean/runtime/Caddyfile:22-40` |
| Secrets | Deployed as Compose file secrets (nine), mounted only into the containers that need them; no key in an image or an environment dump | Docker Swarm / KMS-managed secrets | `infra/digitalocean/runtime/compose.yaml:237-256` |
| `/ready` tracer check | A real probe since 2026-09-17: `GET /api/public/projects` on the Langfuse host with basic auth and a 5 s timeout; `reachable` on 200, `http_<code>` or the httpx error class otherwise, and either fails readiness; the three network checks run concurrently. Verified offline only until the M3 deploy | `tracer: reachable` observed on the Droplet | `agent/app/readiness.py:81-100`; `agent/tests/test_health.py::test_ready_is_503_when_tracer_unreachable` |
| Alerts | On the live host today: run on demand by hand. In the tree since 2026-09-17: the `alerts` compose service (`python -m app.alerts ... --interval 300`, agent image, state on the `agent_state` volume, health check disabled), on the host from the M3 deploy | Webhook delivery to a pager; the service only logs | `infra/digitalocean/runtime/compose.yaml` (services: `database`, `openemr`, `copilot-setup`, `demo-seed`, `agent`, `alerts`, `caddy`) |
| Rollback | Procedure only: redeploy tag `week1` from `git worktree add /tmp/rb week1` with the same `deploy.sh`, no data migration because the co-pilot is read-only | **Never rehearsed.** The rehearsal runbook (throwaway Droplet in a `rehearsal` Terraform workspace; the live Droplet excluded by construction) is written and is the M4 step, with an empty timing table until it runs | `docs/deployment/digitalocean.md`, "Rehearsal Runbook" |
| Backups | **None taken.** Droplet backups are disabled; `infra/digitalocean/backup.sh` (encrypted archive of the database dump, two volumes, secrets and `.env`) and `restore.sh` exist since 2026-09-17 and have not been run against a host | First backup and a restore on the rehearsal Droplet (M4); the Droplet snapshot before the load tests | `infra/digitalocean/backup.sh`, `restore.sh`; `docs/deployment/digitalocean.md`, "Backup and Restore" |
| Egress restriction | **None.** The firewall allows all outbound TCP, UDP and ICMP | Egress limited to the LLM and tracing endpoints, plus a blocked-egress test | `infra/digitalocean/main.tf:54-70`; `AUDIT.md` remediation table, row SEC-MEDIUM-504 |
| Load test | **Driver and sampler built 2026-09-17, no run yet.** `evals/load/run_load.py` (43 offline tests) and `docs/audit/scripts/droplet-stats.sh` exist; no 10- or 50-user measurement yet; the runs are M4, human-gated | 10- and 50-user runs with p50/p95/p99, error rate and peak CPU/memory | `evals/load/run_load.py` (results schema in the module docstring); `evals/load/test_run_load.py` (43 tests, `pytest --collect-only -q`); `docs/audit/scripts/droplet-stats.sh`; `docs/audit/INTERVIEW_NOTES.md:130-131` (the audit's "not measured" note) |
| Verification pass/fail panel | **Counter and scores since 2026-09-17, panels not built.** `/metrics` exposes `copilot_verification_total{outcome}` and every `copilot.turn` trace carries the `verification_passed` and `turn_error` scores; the dashboard's nine panels still have neither verification outcome nor error rate | The two panels over the scores in the Langfuse UI (owner action) | `agent/app/turn_outcome.py`; `agent/app/telemetry.py` (`finish_turn_trace`); `docs/operations/langfuse-dashboard.md` |
| Cost gate | **Configured 2026-09-17.** PASS at or under $0.0223 per model-backed turn, PASS (warn) to $0.0446 with risk acceptance, FAIL above; $0.0127 measured at `a4a5856` | A cost alert on daily spend ($14 warn, $42 page) is still manual from `/metrics` | `evals/run.py:146`, `:593`; `AI_COST_ANALYSIS.md` Part B |
| Agent-level denials | Counted in `/metrics` (`copilot_denials_total{reason}`) and in the agent's logs only. They never reach the gateway, so **they leave no OpenEMR audit row**; gateway-level denials do | An audit path for denials rejected at the agent API | `ARCHITECTURE.md` "Open Items" item 9; `agent/app/api.py:49`, `:57` |
| `CONF-NOTE-VS-LIST-N-001` | **Missed** in the 2026-09-17 run: the model did not raise the planted note-versus-list conflict. Non-blocking task-success gate, 95%, PASS | A deterministic note-versus-list conflict detector | `evals/results/2026-09-17T024919Z-a4a5856.md:19`, `:123` |
| Error-analysis journal | **Unreviewed.** 20 traces across 14 patients are sampled and committed; all 20 First-issue and Notes fields are blank | Fill all 20, run the report, commit the issue list | `evals/error_analysis/2026-09-16T190727Z-journal.md:23`; `evals/README.md:197-199` |

## The Pre-Search Checklist

The PRD Appendix checklist, one section per heading, as built and measured
through 2026-09-17.

## Phase 1: Define Your Constraints

### 1. Domain selection

- **Use cases.** Three, all for one primary-care physician in the 90 seconds
  before a visit, on one open chart (`USERS.md`): UC-01 what changed since
  the last visit; UC-02 which abnormal results have no later result or
  documented follow-up; UC-03 what the chart says about why a medication is
  listed. Follow-up questions stay inside the same chart and window. Rejected
  or deferred: schedule sweeps, cross-patient questions, documentation
  drafting, anything that writes (`USERS.md` "Rejected and Deferred").
- **Verification requirements.** Every displayed patient-specific fact is a
  typed claim citing a record retrieved this turn, checked field by field by
  a deterministic verifier before anything renders (ADR-0006). Absence,
  conflict, undated, unavailable, and truncated states are stated explicitly,
  never flattened. No diagnosis, treatment, dosing, adherence, interaction,
  or causal statements.
- **Data sources.** OpenEMR's own tables, read through OpenEMR's service
  layer inside a custom module: encounters, problem list, medications (list
  and prescriptions), allergies, lab results, clinical notes, patient
  context. No external sources in Week 1 (`ARCHITECTURE.md` "Tools").

### 2. Scale and performance

- **Query volume.** Sized for 20 patients per physician per day, a few
  turns per patient; single clinic. `AI_COST_ANALYSIS.md` projects 100, 1K,
  10K, and 100K users on the measured token mix.
- **Latency.** Complete verified response p95 under 30 s for the early
  submission, owner-accepted 2026-09-15 with an 8 s design goal
  (`KEY_METRICS.md`). Measured on the deployment across the full eval runs,
  latest scorecard 2026-09-17 (`evals/results/2026-09-17T024919Z-a4a5856.md`):
  model-backed turns p50 12.5 s, p95 24.1 s, p99 30.7 s; first turns p95
  16.0 s, follow-ups p95 29.7 s.
  Time to first useful evidence is **not measured**: the eval runner uses
  non-streaming turns, so the SSE path is never timed and the gate reports NOT
  MEASURED. The streamed `evidence` event is emitted after the retrieve node,
  and the retrieve node measures about 1 s in traces, but that is a node
  timing, not a measured time to first paint.
- **Concurrency.** One 2 vCPU / 4 GB Droplet; one uvicorn process, no
  `--workers`. Tool fan-out inside a turn is bounded by a 6-wide
  `asyncio.Semaphore` created per turn in the retrieve node; there is no
  process-wide turn semaphore, so the bound does not apply across concurrent
  turns. One model call per node. Load tests at 10 and 50 concurrent users
  have not been run: the driver and sampler were built 2026-09-17 and the
  runs are M4, human-gated.
- **Cost constraints.** 20K tokens per turn, 60K per conversation, and a daily
  token halt that routes to the deterministic fallback (`agent/app/budget.py`,
  ADR-0004). Measured $0.012 to $0.014 per model-backed turn at list price
  with prompt caching (eval scorecards).
- **OpenEMR web tier — a separate axis from the agent above, not yet load
  tested.** The deployed `openemr` container is the official
  `openemr/openemr:8.1.1` image, built from `docker/release/` (Alpine,
  PHP-FPM behind Apache via FastCGI proxy, `docker/release/openemr.conf:213`).
  Nothing in `docker/release/` sets `pm.max_children` (absent from the whole
  directory), so the pool runs on Alpine's packaged php-fpm default — commonly
  a small fixed worker count, though this has not been confirmed by reading
  the live container's `/usr/local/etc/php-fpm.d/www.conf` or by a load test
  that isolates FPM queuing (503/504s, workers pegged) from CPU saturation
  (slow but successful responses). That gap is a plausible, **unverified**
  explanation for the operator-observed step-function failure between 5 and
  10 concurrent users on the production Droplet. `docker/binary/` is the
  variant OpenEMR itself documents for this
  (`docker/binary/php-fpm.d/www.conf`: `pm.max_children = 50`;
  `docker/binary/README.md:168-189`: "Horizontal Scaling ... Kubernetes,
  Docker Swarm").
  - **Same-box mitigation, untested.** Raise `pm.max_children` / tune OPcache
    on the current `s-2vcpu-4gb` Droplet before spending anything on new
    infrastructure. Idle-container RSS is ~333 MiB
    (`docs/audit/performance.md:237`), well under the 512 MB per-worker
    `memory_limit`, so RAM headroom exists on paper; the 2 vCPUs remain a real
    ceiling for simultaneously *rendering* requests, since `PERF-MED-002`
    (`docs/audit/performance.md:73`) already found the patient dashboard
    costs ≈1,045 SQL statements and is CPU-bound, not I/O-bound. Needs a load
    test to turn "should help" into a number.
  - **Horizontal option, priced, not built.** Load balancer + N
    `docker/binary` app nodes + managed MySQL + managed Valkey (externalizing
    PHP sessions, which are container-local today) + one shared NFS node for
    `sites/documents` (also container-local today). DigitalOcean list pricing
    checked 2026-09-18: ≈$107/mo (2 lean app nodes, single non-HA DB/Valkey)
    to ≈$177/mo (3 nodes, right-sized DB, still no failover) to ≈$277/mo
    (4 nodes plus DB/Valkey standbys), against the current single-Droplet
    $24/mo (`infra/digitalocean/variables.tf:13-16`). Not implemented, not
    load-tested, no ADR — a brainstormed answer to "how would you scale
    this," not a plan committed in `infra/`.
  - **Multi-cloud comparison, same topology, priced, not built.** Same shape
    (LB + N app nodes + managed MySQL + managed Redis/Valkey + shared NFS for
    `sites/documents`) repriced on AWS, Azure, and GCP list pricing checked
    2026-09-18, to have an answer ready for "wouldn't a bigger cloud be
    cheaper" before it's asked. DigitalOcean is not the outlier here — it
    lands mid-pack, and is cheapest of the four at the HA tier:

    | Tier | DigitalOcean | AWS | Azure | GCP |
    | --- | --- | --- | --- | --- |
    | Lean (2 app nodes, no HA) | $107 | $77 | $119 | $102 |
    | Balanced (3 app nodes) | $177 | $192 | $164 | $226 |
    | HA (4 nodes + DB/cache standby) | $277 | $291 | $248 | $370 |

    AWS wins the lean tier on EFS's pure pay-per-GB pricing (no minimum) and
    tiny RDS/ElastiCache SKUs; Azure wins once sized up, since its Flexible
    Server MySQL and Premium Files NFS scale more gently than AWS's or GCP's
    equivalents. GCP is the outlier, and it is two specific pricing floors,
    not a general "GCP costs more": Memorystore for Redis has no tier under
    1 GB (≈$36/mo for what is a few MB of session data), and Filestore's
    cheapest tier has a 1 TB minimum (≈$164/mo alone) — wrong-sized for a
    `sites/documents` share this small, so the GCP column substitutes a
    self-managed NFS box, the same workaround this design already uses on
    every provider for that reason. Several DB/cache line items are
    extrapolated from a confirmed unit rate rather than a quoted price for
    that exact SKU (RDS/Azure MySQL 2vCPU/4GB tiers; GCP Cloud SQL via
    Google's own published `$30.11/vCPU + $5.11/GB` formula, cross-checked
    against Google's worked 4vCPU/15GB example). Two omissions matter more
    than the table: none of this includes committed-use/reserved-instance
    discounts, which the three hyperscalers offer (typically 30-50% off
    compute/DB on a 1-3yr term) and DigitalOcean largely does not; and none
    of it includes egress, where DigitalOcean bundles materially more free
    outbound transfer per Droplet than the per-GB charges the other three
    apply past a small free tier. Same status as the DigitalOcean figures
    above: not implemented, not load-tested, no ADR.
  - **Clinic-size back-of-envelope, now partly measured
    (`docs/audit/evidence/performance/droplet-tier-comparison-2026-09-18.md`).**
    Translates measured throughput into "how big a clinic" using Little's Law
    (`L = λ × W`) plus a peak/busy-hour concentration factor — the same
    reasoning Q10 already applies to the agent (appointments compress into
    slot-aligned bursts), applied here to raw OpenEMR page requests. An
    earlier version of this estimate assumed an FPM worker pool capping
    simultaneity at ~5 in-flight requests; that premise is **disproven** — a
    live check of the `openemr` container found `mod_php` under Apache
    prefork (`MaxRequestWorkers=250`), not `php-fpm` at all, and the M4 load
    test never got the Apache process count above 54-68 even while CPU was
    already saturated, confirming the worker pool was never the real wall.
    The actual constraint, confirmed directly by container CPU data, is
    OpenEMR's Apache/PHP and MariaDB layer saturating CPU — both peak at or
    above 100% of a full vCPU core well before any worker-pool limit is
    reached, on every Droplet tier tested (see below).
    - **Today, prod `s-2vcpu-4gb`, unfixed.** No config-tunable worker pool
      to raise — the constraint is raw CPU. M4's own bracket data: clean
      through roughly 5-10 concurrent users, hard degradation by 50 (31/50
      VUs completed, 90% of tool-gateway calls unavailable). Estimated safe
      zone: **roughly a 1-2 provider practice**, consistent with the
      operator-observed failure between 5 and 10 concurrent users — this
      number hasn't changed, because it was never actually about FPM.
    - **Measured, three bigger/different Droplet tiers, 2026-09-18.** Real
      load tests (not modeled) against `s-4vcpu-8gb` ($48/mo, 4 shared vCPU),
      `c-2` ($42/mo, 2 **dedicated** vCPU — prod's own core count, no
      CPU-credit throttling), and `c-4` ($84/mo, 4 dedicated vCPU), each via
      a throwaway rehearsal Droplet, replace the old modeled "~2.8 req/s
      working budget" with throughput measured directly from real-model load
      test traffic (method: OpenEMR-facing requests per second at each
      tier's last-100%-VU-completion level — see the linked document):

      | Tier | Measured throughput | Clinic size (25-50 req/encounter, 2-3 visits/hr, 3x-5x peak, formula unchanged) |
      | --- | --- | --- |
      | `s-4vcpu-8gb` ($48/mo) | 4.39 req/s | ~21-to-105 providers |
      | `c-2` ($42/mo, dedicated) | 4.35 req/s | ~21-to-104 providers |
      | `c-4` ($84/mo, dedicated) | 7.34 req/s | ~35-to-176 providers |

      using `providers = throughput ÷ (req/encounter × visits/hr ×
      peak-factor ÷ 3600)` at each end of the assumption range, same formula
      and same other assumptions as before. Headline finding: `c-2`, at
      prod's own core count but dedicated (non-burstable) CPU, matched or
      beat the 4-vCPU shared-core tier — CPU-credit throttling on the
      Basic/shared-CPU family, not just core count, is part of what limits
      prod specifically. `c-4` is the standout: roughly 6-10x prod's clean
      concurrent-user ceiling for 3.5x the monthly cost.
    - **Caveat, same as everywhere else in this section.** Requests per
      encounter and the peak concentration factor are still *assumptions*,
      not observations — only the throughput term is now measured, and only
      for the three new tiers, not prod itself (out of scope for that
      session; prod was never touched). Turn p95 still busts the 30 s budget
      on every tier tested, including the best one, so this section answers
      "how many concurrent users the box can serve," not "how many providers
      get a response inside budget" — those are different, both-open
      questions. The rigorous next step is still a load test with realistic
      think-time and slot-aligned burst timing rather than the driver's
      current ramped-burst pattern.

### 3. Reliability requirements

- **Cost of a wrong answer.** A fluent unsupported clinical claim is the
  central failure: a physician may act on it. Hence the verifier fails closed,
  and a displayed unsupported claim is treated as a verifier defect, not a
  model one (`KEY_METRICS.md`).
- **Non-negotiable verification.** Source existence, field-level fact match
  per claim type, window membership for changes, lexicon (no advice, no
  causation), absence only after a successful retrieval of that section,
  summary shown only when every claim verified and every number is grounded
  (ADR-0006 §1 to §7).
- **Human in the loop.** The physician is the only actor; the co-pilot is
  read-only, cannot write to the chart, and every claim links to the record
  so the human checks the source in one click. No autonomous actions exist.
- **Audit and compliance.** Every gateway call writes an OpenEMR audit row
  before data leaves, carrying the correlation id; the agent logs are
  PHI-free JSON; traces are masked to digests (ADR-0007). Denials rejected at
  the agent API never reach the gateway and so leave no OpenEMR audit row —
  they exist only in `/metrics` and the agent logs (`ARCHITECTURE.md` "Open
  Items" item 9; `agent/app/api.py:49`, `:57`). `AUDIT.md` §5 maps
  observations to HIPAA provisions, but no BAA has been executed with the
  model provider and none has been reviewed — the executive summary says
  "There are no executed BAAs" and §3 says "The BAA remains assumed, not
  reviewed". No HIPAA compliance is claimed.

### 4. Team and skill constraints

- **Agent frameworks.** LangGraph was chosen from day one so Weeks 2 and 3
  (supervisor and workers, ingestion, retrieval) extend the graph instead of
  replacing a hand-rolled loop (`docs/PROJECT_PLAN.md`).
- **Domain experience.** Primary-care workflow written down first
  (`USERS.md`) and checked against OpenEMR's real data shapes in a two-day
  audit (`AUDIT.md`) before any agent code; the clinician interview is still
  open (`USERS.md` "Validation Work").
- **Eval and testing.** Comfortable enough to write the suite ourselves: 46
  YAML cases (14 of them a golden tier, 4 a holdout tier; 45 in the latest
  recorded run), a runner that
  drives the real login and chart handshake, pytest for the offline
  invariants. No eval framework (see §9).

## Phase 2: Architecture Discovery

### 5. Agent framework selection

- **Single or multi-agent.** Single agent, one LangGraph turn graph:
  authorize, classify, plan or retrieve, narrate, verify, repair, render
  (`agent/app/graph/`). Multi-agent is deferred to Week 2 when there is a
  second responsibility worth a worker.
- **State.** Per-turn state is reset on every invocation; conversation state
  (history, token totals, closed flag) lives in a LangGraph checkpoint keyed
  by conversation id. Raw records never enter state; the evidence pack is held
  per turn in a store keyed by turn id (ADR-0005).
- **Tool integration.** Seven tools behind one in-process gateway in the
  OpenEMR module, each with a typed contract exported to JSON Schema
  (`contracts/schema/`), a status of ok, empty, partial, or unavailable, and a
  2 s timeout. The agent never touches the database (AGENTS.md hard gate).

### 6. LLM selection

- **Provider.** Claude Sonnet 5 through the Anthropic SDK (ADR-0004), chosen
  on measured latency after Opus 5 was tried first. Provider-neutral swap
  points exist (the model port) but no second provider is wired.
- **Structured output.** JSON-as-text validated by our Pydantic contract,
  with one re-ask on malformed output. The grammar-constrained structured
  output path measured 45 s or more per call and was dropped
  (`agent/app/model.py`).
- **Context window.** Evidence packs are capped in characters and per-tool
  record limits (labs 50, notes 20) with a `truncated` flag; a five-year
  synthetic chart (`AF-HEAVY`) is in every eval run to keep this honest.
- **Cost per query.** $0.0127 measured per model-backed turn in the latest
  run (`a4a5856`), against the $0.0223 projection basis in
  `AI_COST_ANALYSIS.md` Part B, which has been the configured gate since
  2026-09-17 (`evals/run.py` `COST_PER_TURN_PROJECTION_USD`, `cost_gate()`):
  PASS at or under $0.0223, PASS (warn) to $0.0446 with risk acceptance in
  the report, FAIL and blocking above; NOT CONFIGURED only for a run with no
  model-backed turn. The run judges the cost as well as reporting it.

### 7. Tool design

- **Tools.** encounters, problems, medications, allergies, lab_results,
  clinical_notes, patient_context (`ARCHITECTURE.md` "Tools"). Each
  normalizes OpenEMR's defects: clinical dates with precision and basis,
  absence states distinguished, text-valued labs quoted, orphans omitted, and
  a medication whose `lists` row and `prescriptions` row disagree carries a
  `status_conflict` flag instead of a status (`MedicationsTool.php:62-76`).
  That deterministic flag covers list-versus-prescription disagreement only;
  a note contradicting the list is not detected deterministically (see §11).
- **External APIs.** Only the model provider and the tracing backend. No
  third-party clinical APIs.
- **Mock vs real data.** Real OpenEMR, with a deterministic synthetic cohort
  of 26 fictional patients, one per catalogued data defect
  (`evals/fixtures/cohort/`). Recorded tool responses serve as pytest
  fixtures so offline tests share the contract.
- **Error handling per tool.** A failed or denied tool returns `unavailable`
  with a reason; the section is marked unavailable in the answer, no absence
  can be claimed for it, and the rest of the brief still renders (ADR-0006
  §5, `TOOL-OUTAGE-LABS-001`).

### 8. Observability strategy

- **Choice.** Langfuse Cloud (ADR-0007): OpenTelemetry-based SDK, session
  and metadata support, a hobby tier that covers a clinic, and a client-side
  mask so nothing but digests leaves the box.
- **Metrics that matter.** Nine panels on the "Clinical Co-Pilot" dashboard
  cover the PRD's request count, latency p50/p95, token usage, cost, tool
  calls, tool failures, repair count (via generations by name) and an
  ERROR-level observation count
  (`docs/operations/langfuse-dashboard.md:18-33`). Two PRD dashboard minimums
  are **not** on it as panels: verification pass/fail rate and turn error
  *rate*. The error panel counts ERROR-level observations; nothing divides
  that count by turns, so the dashboard shows error volume and not an error
  rate. Since 2026-09-17 the inputs exist: every `copilot.turn` trace carries
  the `verification_passed` and `turn_error` scores
  (`agent/app/telemetry.py` `finish_turn_trace`) and `/metrics` exposes
  `copilot_verification_total{outcome}` beside
  `copilot_verifier_rejections_total` (`agent/app/metrics.py:109-114`); the
  two panels over the scores are an owner action in the Langfuse UI (M3),
  not built.
- **Real-time monitoring.** Prometheus-style `/metrics` on the agent, and
  `agent/app/alerts.py`, which evaluates the three PRD alerts against the
  thresholds in `KEY_METRICS.md` over two samples. On the live host it is
  **run on demand**; the `alerts` compose service (every 300 s,
  `infra/digitalocean/runtime/compose.yaml`, in the tree since 2026-09-17)
  reaches the host at the M3 deploy.
- **Cost tracking.** Token usage and model cost per generation in every
  trace; per-turn usage in the API response; cost per turn in every eval
  scorecard.

### 9. Eval approach

- **Correctness.** Deterministic assertions on the real system: HTTP status,
  authorization outcome, evidence status per tool, claim types and matchers
  for planted findings, citation resolution, limitations, verifier outcome,
  latency. No model-graded scores in the pass rate (`evals/README.md`).
- **Ground truth.** The synthetic cohort: every defect is planted, so the
  required behavior per patient is known in advance and written into the
  case.
- **Automated vs human.** Automated for everything above; the clinician
  rubric (`USERS.md`) is human-scored and kept in a separate field, never
  aggregated with the deterministic pass rate.
- **CI integration.** The offline subset (verifier and graph invariants via
  pytest) runs on every push in `.gitlab-ci.yml`; the live suite is the
  manual job `test:evals-live`, which needs the deployment and the masked
  `DEMO_PASSWORD` variable and attaches its results as a 90-day artifact, so
  a push never spends model budget by itself. A dedicated runner Droplet was
  provisioned on 2026-09-16 because the lab GitLab had none
  (`docs/deployment/digitalocean.md` "CI Runner"); the first green pipeline
  is recorded in `docs/SUBMISSION_CHECKLIST.md`. The golden tier
  (`--golden-only`) is the fast smoke run; the holdout tier is excluded from
  filtered runs unless `--include-holdout` (`evals/README.md`).

### 10. Verification design

- **Claims that must be verified.** All of them. Nine claim types
  (`change_event`, `medication_status`, `problem_status`, `lab_result`,
  `lab_comparison`, `documented_reference`, `absence`, `conflict`,
  `undated`) plus `interpretation`, each with the facts its rule checks
  (`ARCHITECTURE.md` "Verification Design"). The scope is every claim the
  model *makes*: the verifier is a false-positive control and cannot detect a
  finding the model omitted (see §11 and the worst-failure-mode answer above).
- **Fact-checking sources.** The evidence pack retrieved in the same turn,
  through the same authorization as the chart. Nothing outside it counts.
- **Confidence thresholds.** None: verification is binary per claim. A
  rejected claim is withheld and counted; the answer's status becomes
  `partial`; the model's prose summary is replaced by a count-only summary
  when anything was withheld (ADR-0006 §7).
- **Escalation.** A withheld claim triggers one repair round with the
  specific rejection reasons; after that it stays withheld. Model or budget
  failure escalates to the deterministic, cited fallback brief. Operational
  escalation is the alerts runbook.

## Phase 3: Post-Stack Refinement

### 11. Failure mode analysis

- **Tool failure.** Section marked unavailable, no absence claimed, brief
  renders from the other sections. Six of the ten rows of the failure matrix
  (`ARCHITECTURE.md` "Failure and Degradation Matrix") have an eval case:
  denial, patient switch, one tool unavailable, model failure, verifier
  rejection, token budget. Three have a pytest case only, since 2026-09-17 —
  gateway unreachable (the `/ready` half; the turn half is not exercised),
  tracer unavailable, and rate limit (`agent/tests/test_health.py`,
  `test_telemetry.py`, `test_api.py`). One, OpenEMR or database down, has
  neither and is reasoned through, not exercised.
- **Ambiguous queries.** The classifier routes anything that is not a
  first-turn UC-01 question to planning, whose tool choices are constrained to
  a bounded allowlist of the seven tools (`agent/app/graph/nodes.py:178`) and
  whose parameters are re-checked at the gateway; out-of-scope
  requests (other patients, schedule, general medicine, dosing) are refused as
  a limitation, not answered. An `interpretation` claim type lets the model
  state a reading the physician can correct.
- **Rate limiting and fallback.** Per-conversation rate limit in the API,
  provider rate-limit and timeout mapped to typed errors, a circuit breaker
  (three failures, 60 s cooldown) in front of the model, token caps and a
  daily halt. All fall back to the deterministic brief.
- **Graceful degradation.** Status is `complete`, `partial`, or `fallback`,
  never a blank panel; the panel shows evidence counts before the narrative
  and a "Records only" badge on fallback.

### 12. Security considerations

- **Prompt injection.** Record text is fenced as data in the pack, the
  system prompt says instructions inside it are not instructions, and the
  verifier means an obeyed instruction still cannot produce a displayed claim
  without a record. Fixture `AF-DQ-O` carries an injection and script payload;
  `INJ-NOTE-O-001` checks it is neither obeyed nor rendered active. The panel
  renders every string through `textContent` and DOM APIs and never assigns
  `innerHTML` (`interface/modules/custom_modules/oe-module-copilot/public/assets/js/copilot.js:10`,
  `:50`). A CSP on the module's assets is **planned** (SEC-MED-003); no CSP
  header is set today.
- **Data leakage.** Authorization is parity with the chart (ADR-0002): the
  gateway checks the same ACLs OpenEMR does before any tool returns data; a
  patient switch closes the conversation at the ticket stage; a patient id in
  tool params is rejected by the gateway's hand-written parameter allowlist,
  which mirrors the exported JSON Schemas but does not validate against the
  schema files (`ToolRegistry.php:37-54`; `AUTH-FORGED-PID-001`). Traces carry
  digests only; logs are PHI-free.
- **API key management.** Docker secrets on the host, files with mode 600 on
  the workstation, never in the repository, environment dumps, Terraform
  state, or shell history; the runner token follows the same pattern.
- **Audit logging.** One OpenEMR audit row per gateway call with user,
  patient, tool, and correlation id, written before data leaves; if the insert
  fails the tool returns `unavailable` rather than records
  (`public/gateway/tools.php:69-76`). Gateway-level denials are audited with
  their reason. Denials rejected earlier, at the agent API (missing, bad,
  expired, or conversation-mismatched delegation token), never reach the
  gateway and therefore leave **no** OpenEMR audit row; they appear only in
  `copilot_denials_total{reason}` and the agent's logs
  (`ARCHITECTURE.md` "Open Items" item 9). Walkthrough in
  `docs/operations/correlation-id-walkthrough.md`.

### 13. Testing strategy

- **Unit tests.** Verifier rules, summary gate, suggestion filter, budget,
  alerts, contracts, and since 2026-09-17 the circuit breaker, checkpoint
  content and telemetry re-raise controls (91 pytest cases collected in
  `agent/tests/`, counted 2026-09-17 at `0fba313`); PHP lint and a
  recorded-response contract test for the tools.
- **Integration.** The turn graph with recorded gateway fixtures and a
  scripted model; the live eval suite drives login, chart open, session,
  ticket, and turn against the deployment as different users; the Bruno
  collection (21 requests, 41 assertions) covers the HTTP contract.
- **Adversarial.** Authorization cases (front office, squad restriction,
  tampered and stale tickets, forged pid, patient switch), injection,
  altered facts, fabricated sources, advice wording, budget exhaustion.
- **Regression.** One case per discovered bug (the `activity=0` with no end
  date conflict, DQ-HIGH-002; paraphrased advice slipping past the lexicon,
  `CIT-PARAPHRASE-ADVICE-001`) and one per cohort defect; results versioned
  per commit in `evals/results/` with a compare script and `--repeat` for
  flakiness. Two model-recall cases flip run to run — `MISS-AUTHOR-J-001`
  (runs `1ddf824`, `69560f05`) and `CONF-NOTE-VS-LIST-N-001` (run `a4a5856`)
  — and both sit under the non-blocking task-success gate; every
  deterministic assertion has passed in every run.

### 14. Open source planning

- **Release.** The whole repository: the OpenEMR module, the agent, the
  contracts, the eval suite and cohort, the infrastructure, and the
  documentation.
- **Licensing.** OpenEMR is GPL-3.0; the module and the agent are declared
  GPL-3.0-only (`agent/pyproject.toml`) so nothing in the tree is under a
  conflicting license. No proprietary dependencies; the model provider is a
  service, not a bundled component.
- **Documentation.** `README_AGENT_FORGE.md` for evaluators, `SETUP.md`,
  `ARCHITECTURE.md`, seven ADRs, the audit, the glossary, runbooks under
  `docs/operations/`, and the eval README.
- **Community.** Deferred past Week 1; the social post is a final-submission
  item. The likely first contribution upstream is the cohort seed and the
  data-quality findings, which stand on their own.

### 15. Deployment and operations

- **Hosting.** One DigitalOcean Droplet behind Caddy with automatic TLS,
  Docker Compose, secrets as Compose file secrets, Terraform for the host and
  firewall (`docs/deployment/digitalocean.md`, ADR-0001). Caddy denies by
  default: only OpenEMR application paths, `/copilot-api/*` and
  `/meta/health/livez` are routed, and the module's `gateway/` and `bin/`
  paths 404 from the edge (`Caddyfile:22-40`). Outbound traffic is **not**
  restricted — the firewall allows all outbound TCP, UDP and ICMP
  (`infra/digitalocean/main.tf:54-70`). A second $6 Droplet runs CI.
- **CI/CD.** Lints, contract schema check, agent tests, and the offline evals
  on every push; deployment is a scripted step run by the owner after the
  live suite and the Bruno collection pass (`infra/digitalocean/deploy.sh`).
- **Monitoring and alerting.** Langfuse dashboard (nine panels), `/health`,
  `/metrics`, and `/ready`. `/ready` really probes the gateway (`ping.php`)
  and the LLM (`models.retrieve`), and since 2026-09-17 the tracer too
  (`GET /api/public/projects` on the Langfuse host with basic auth and a 5 s
  timeout, `agent/app/readiness.py:81-100`; verified offline until the M3
  deploy). The panel itself probes `/health`,
  not `/ready` (`copilot.js:485`). Alerts have page and warn thresholds; on
  the live host today they are run on demand, not on a schedule; in the tree
  the `alerts` compose service (`infra/digitalocean/runtime/compose.yaml`,
  `--interval 300`, since 2026-09-17) schedules them every 300 s from the M3
  deploy.
- **Rollback.** Images are built from the repository at a commit; rolling
  back is redeploying the previous commit with the same script. The database
  is untouched by the co-pilot (read-only), so rollback has no data migration
  step. **This has never been rehearsed** — the procedure is written
  (`docs/deployment/digitalocean.md` `## Failure and Recovery`; "tested
  backup/restore and rollback" is still listed under "Documented, not changed
  here" in `## Before the Evaluator Deployment`), and the rehearsal runbook
  (`## Rehearsal Runbook`, throwaway Droplet, live host never touched) has an
  empty timing table until it runs (M4) — and there are no backups: none has
  been taken; `backup.sh` and `restore.sh` exist since 2026-09-17 and neither
  has been run against a host (`## Backup and Restore`).

### 16. Iteration planning

- **User feedback.** Clinician interview with the question list in
  `USERS.md`; the follow-up suggestions shown in the panel double as a signal
  of what physicians ask next.
- **Eval-driven cycle.** Baseline run, change, run, compare with
  `evals/compare.py`; the scorecard (withheld rate, repair rate, summary
  basis, cost, latency by turn type, near-miss hedge-language rate) is the
  quality signal, pass count alone is not. Any model, prompt, effort, or
  planning experiment follows this. Unscripted questions go through a manual
  error-analysis journal (`evals/error_analysis.py`, reviewed in
  `evals/review_ui.py`); recurring issues become new cases. The first journal
  (20 turns, 14 patients, sampled 2026-09-16) has not been reviewed yet.
- **Prioritization.** P0 / P1 lists in `docs/PROJECT_PLAN.md`, tied to the
  release gates in `KEY_METRICS.md`; safety gates never trade against
  latency or cost.
- **Long-term maintenance.** Contracts are versioned (1.2.0) and exported
  with a CI drift check; ADRs record every deferred alternative (SMART on
  FHIR, care-relationship authorization, structured output) with the trigger
  that would reopen it.

## Three decisions evaluators will probe

1. **Parity authorization instead of a care-relationship rule** (ADR-0002).
   Defense: the co-pilot can never show more than the chart shows, the rule
   is testable ("could this user open this in the chart?"), and the stricter
   policy is written down with its trigger. Evidence: nine authorization
   cases, and an OpenEMR audit row on every gateway-level denial (denials
   rejected at the agent API are counted and logged but produce no OpenEMR
   audit row).
2. **Deterministic verifier before display** (ADR-0006). Defense: the
   safety property does not depend on the model; a weaker model degrades
   quality (withheld rate, count-only summaries) but not safety, which is
   exactly what the scorecard measures.
3. **JSON-as-text over grammar-constrained output** (ADR-0004). Defense:
   measured 45 s or more with constrained decoding versus 5 to 9 s as text,
   with the contract still enforced after parsing and one re-ask on
   malformed output; malformed rate is visible in the traces.
