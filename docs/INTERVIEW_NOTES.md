# Interview Notes: Answer Sheet and Pre-Search Checklist

Two sections. **The twelve questions** is the answer sheet for the technical
interview (prepared 2026-09-17). **The pre-search checklist** below it answers
the PRD's Appendix, one section per heading, as built and measured through
2026-09-17. Both were brought up to the submission state on 2026-09-20 (tag
`week1-final`; the deployed runtime is `478f432`); the "Deployed today versus
planned" table between them stays as the record of 2026-09-17. Each answer
names where the evidence lives. Numbers come from the eval results in
`evals/results/` unless a source is named. Where something is deferred, not
measured, or not implemented, it says so.

## The Twelve Questions

The PRD's own wording for these twelve is not in this repository — no PRD file
exists in the tree — so the questions below are reconstructed from the four
themes the PRD's p.10 "Interview Preparation" section names (the audit, the
architecture, the evaluation, production thinking), three each. The two
phrasings that do survive in the repo, "What did you find when you ran it?"
and "What did you find? What would you add next?", are used verbatim
(both are quoted in `docs/FINAL_SUBMISSION_TODOS.md`). Every answer ends with
an `Evidence:` pointer that resolves to real content in this tree.

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

Evidence: `ARCHITECTURE.md` "Open Items" item 9; `AUDIT.md` remediation table, row SEC-MEDIUM-504; `infra/digitalocean/main.tf:67-82`.

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
answering with a status of ok, empty, partial, or unavailable; since the
batched gateway (2026-09-19) a turn's tools travel as one or two gateway
requests, each with a 2 s timeout. Every request re-checks the live session,
the conversation binding and the squad restriction, and every tool in it gets
its own section-ACL check and an OpenEMR audit row *before* any data leaves —
if that insert fails, the tool returns `unavailable` instead of records. When
the records are headed to the model, the batch also writes a
`copilot-model-disclosure` row naming the provider and the model first, and
returns nothing if it cannot. One thing I will not overstate: the gateway's
parameter check is a hand-written allowlist plus format checks that mirror the
exported JSON Schemas, not validation against the schema files. Schema-file
validation is planned, and the docblock at `ToolRegistry.php:37` still claims
otherwise.

Evidence: `interface/modules/custom_modules/oe-module-copilot/src/Gateway/BatchRunner.php:54-64`; `interface/modules/custom_modules/oe-module-copilot/public/gateway/tools.php:103-118`; `interface/modules/custom_modules/oe-module-copilot/src/Gateway/Tools/ToolRegistry.php:37-54`.

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
model's prose summary is replaced by the first verified claims, restated word
for word, whenever anything was withheld. The safety property therefore belongs to the verifier, not to
the model: a weaker model raises the withheld and repair rates without making
what is displayed less true.

Evidence: `agent/app/verifier.py:111-121`; `docs/adr/0006-verification-strategy.md:26-81`.

### The evaluation

**Q7. How do you know it works — what does the suite actually assert?**

48 YAML cases: 38 run live against the real deployment, driving the real
login, chart open, session, ticket and turn handshake as different users, and
10 run offline through pytest node ids. All 48 were in the release run
(`0f11642`, three attempts per live case) and in the single pass at the
deployed tree (`4d2a9fd`); 15 are a golden smoke tier and 4 are a holdout
tier excluded from filtered runs. The assertions are deterministic — HTTP
status, authorization outcome, evidence status per tool, claim types and
matchers for planted findings, citation resolution, limitations, verifier
outcome, latency — and no model-graded score enters the pass rate. Thirteen
release gates sit on top of the cases; the blocking ones are golden-set
integrity, authorization leakage, unsupported displayed claim, explicit
uncertainty recall, safe degradation, healthy-stack tool failures, citation
resolution, latency p95 and error rate. Two gates deliberately refuse to
pass: citation correctness and time to first useful evidence report NOT
MEASURED in every run. Cost per verified turn did the same until 2026-09-17;
it is now judged against the $0.0223 projection ($0.0104 in the release run,
PASS) and reads NOT CONFIGURED only for a run with no model-backed turn.

Evidence: `evals/run.py:648-710`; `evals/results/2026-09-20T051146Z-0f11642.md:8-23`.

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

The release run (2026-09-20, commit `0f11642`, `--repeat 3`) was taken while
`c37b9e6` was deployed — the two runtime trees are byte-identical — and
executed all 48 cases, the 38 live ones three times each. It passed 123 of
124 attempts, with every blocking gate PASS: golden set 29 of 29 attempts,
citations 615 of 615 resolved, no unsupported displayed claim, zero 5xx,
model-backed p95 15.8 s against the 30 s warn line, $0.0104 per model-backed
turn. The single failure is `CONF-DUP-NAMES-C2-001`, a holdout
case that passed the other two attempts: on one attempt the summary called a
duplicate medication a duplicate rather than a possible one, which the
verifier's hedging lexicon caught. Flakiness stays confined to model wording —
`MISS-AUTHOR-J-001`, `CONF-NOTE-VS-LIST-N-001` and now this one have each
flipped run to run, and the golden case `INJ-NOTE-O-001` flipped once in a
golden-only smoke run (`evals/results/2026-09-20T032913Z-23e197e.md`: a
claim's text matched the case's forbidden `no allergies` pattern) and has
passed all seven attempts since — while no deterministic assertion has ever
flipped on an unchanged deployment. The scorecard, not the pass count, is the
signal I read: over 126 model-backed turns, 12.7% needed a repair round, 1.1%
of statements were withheld, 4.25 claims and 1.56 model calls per turn, 293
in / 897 out / 4,413 cache-read tokens.

The deployed tree moved after that run: four runtime commits for Slack alert
delivery and the tool-failure counter (`e466b9d`, `dbf5372`, `0471178`,
`478f432`; only `dbf5372` touches the turn path). `478f432` is what is live,
so a full single pass was taken at that tree (`4d2a9fd`, runtime identical to
it): 48 of 48, every blocking gate PASS, citations 206 of 206, p95 20.0 s,
$0.0113 per model-backed turn, no 5xx. The three-attempt stability evidence
is therefore one counter fix behind the running code; the single pass is at
it.

The run before the release run is the one worth telling. At `6c787bd` it
failed `ISO-RECENT-PATIENT-RESUME-001` three times out of three, which turned
out to be a half-applied timezone putting two clocks in one column and
silently breaking conversation resume. Nothing errored; only the suite
noticed.

Evidence: `evals/results/2026-09-20T051146Z-0f11642.md`,
`evals/results/2026-09-20T064022Z-4d2a9fd.md`, and the baseline comparison
`evals/results/2026-09-20T051146Z-0f11642-vs-a4a5856.md`: p95 24.1 s to
15.8 s, task success 95% to 100%, cost $0.0127 to $0.0104.

### Production thinking

**Q10. What happens at 300 users?**

300 physicians on the usage model in `AI_COST_ANALYSIS.md` (20 visits a day,
one UC-01 turn plus one follow-up per visit, 22 working days) is 12,000 turns
a day; spread flat across an 8-hour clinic at that document's 17 s per turn,
that is about 7 concurrent turns — but appointments are slot-aligned, so an
hour's worth compresses into the few minutes after the hour and the realistic
peak is about 60 concurrent turns (1,500 turns x 17 s / ~420 s). This Droplet
does not survive that, and that is measured, not argued. The 2026-09-18 load
test on the live host finished 10 of 10 users with a real-model turn p95 of
45.0 s and 2 errors in 20 turns; at 50 users 31 of 50 finished and 90% of tool
calls came back unavailable. The `--fault model` control, with zero model
calls, broke the same way, which puts the wall in OpenEMR's Apache/PHP and
MariaDB — each at or above one full core of the box's two, with Apache never
near its 250 prefork workers — and not in the agent, whose CPU never passed
54%. Batching a turn's tools into one or two gateway requests (2026-09-19,
measured on a throwaway Droplet of the same size) made 10 users clean — every
turn complete, no tool unavailable, turn p95 24.8 s — and did not move the
onset, which is still between 10 and 15 users (37% of tool calls unavailable
at 15). So the first fix at 300 users is OpenEMR capacity, not agent
replicas: the tier comparison measured a `c-4` (4 dedicated vCPU, $84/mo)
finishing 60 of 60 concurrent users with no tool unavailable and a turn p95
of 32.2 s, still over the 30 s line, and horizontal OpenEMR nodes are priced
in §2 below and not built. The agent has its own, later ceiling, and three
process facts in the code set it: a single uvicorn worker with no `--workers`
flag; no process-wide turn semaphore or queue, so nothing in the agent bounds
concurrent turns (the per-turn 6-wide semaphore went away with batching); and
a LangGraph checkpointer that is an `AsyncSqliteSaver` over a file in a local
state directory, in WAL mode since 2026-09-18. That SQLite file is exactly why
the answer is never `--workers N` — a second worker in the same container
would contend on it — so scaling is a second agent container behind the edge
with a shared checkpointer, which is a Week 2 change rather than a flag. Still
not measured: any concurrent load since follow-ups went to low effort and the
brief moved to chart open, which starts a first turn on every eligible chart
open rather than on a click; and a run with realistic think time and
slot-aligned bursts instead of the driver's ramp.

Evidence: `agent/Dockerfile:31`; `agent/app/graph/nodes.py:209-226`; `agent/app/state_store.py:61-63` and `agent/app/main.py:43-53`; `docs/audit/evidence/performance/load-test-2026-09-18.md`, `baseline-2026-09-18.md`, `batched-gateway-2026-09-19.md` and `droplet-tier-comparison-2026-09-18.md`; `AI_COST_ANALYSIS.md` "Usage model (assumption)".

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
detector, not a better prompt. The case passed all three attempts in the
2026-09-20 release run and the single pass after it, which changes nothing:
it is still model recall, the detector is still not built, and a case that
has flipped once will flip again.

Evidence: `evals/cases/CONF-NOTE-VS-LIST-N-001.yaml:5-7`; `evals/results/2026-09-17T024919Z-a4a5856.md:123`.

**Q12. How would you operate this — monitoring, alerting, rollback, cost?**

One correlation id runs through the panel, the gateway, the OpenEMR audit row,
the agent logs, the metrics and the trace, and the agent's own logs are
PHI-free JSON. Traces go to Langfuse Cloud. The code default is a client-side
mask that replaces every payload with a digest; the demo deployment turns
content capture on (`COPILOT_TRACE_CONTENT=1`, ADR-0007 amendment 2026-09-19),
so its traces carry prompts, the evidence pack and answers — defensible only
because every patient on that box is synthetic, and a deployment with real PHI
keeps the default. `/metrics` is a Prometheus-style endpoint and
`agent/app/alerts.py` evaluates the three PRD alerts over two samples of it;
on the live host the `alerts` compose service runs it every 300 s and pages a
Slack channel through a webhook held as a Docker file secret. That path was
proven end to end on 2026-09-20, and proving it found two defects (see the
known gaps below). Rollback is redeploying the previous commit with the same
script and needs no data migration because the co-pilot is read-only. It was
rehearsed end to end on a throwaway Droplet on 2026-09-18 — clean deploy,
rollback to tag `week1`, roll forward, `backup.sh`, `restore.sh`, destroy —
and two Droplet snapshots exist, but no `backup.sh` run against the live host
is recorded, nothing is scheduled, and the whole deployment is a single
Droplet and therefore one failure domain. Cost is bounded by token caps (20K
per turn, 60K per conversation) and a daily 2,000,000-token halt that routes
every further turn to the deterministic fallback; the measured $0.0104 per
model-backed turn in the release run ($0.0113 in the single pass at the
deployed tree) sits below the $0.0223 projection basis, which has been the
configured gate since 2026-09-17 (`evals/run.py` `cost_gate()`: PASS at or
under $0.0223, PASS (warn) to $0.0446 with risk acceptance in the report,
FAIL and blocking above; NOT CONFIGURED only for a run with no model-backed
turn). What triggers spend changed with module 0.5.0: the UC-01 brief is
prepared when a chart opens, not when someone clicks, so an unread brief is
about $0.011 of model spend plus its audit rows. The module default,
`visit_today`, limits that to charts with a visit today; the demo box runs
`always`.

Evidence: `agent/app/alerts.py:1-24`; `docs/operations/alerts.md` "Delivery" and "Running the job"; `docs/audit/evidence/observability/alerts-slack-2026-09-20.log`; `docs/deployment/digitalocean.md` "Rehearsal Runbook"; `evals/run.py:158`, `:623`; `AI_COST_ANALYSIS.md` "Part B"; `docs/operations/usage-funnel.md`.

### Coding workflow

The repository is the process. Every decision that constrains later work is an
ADR (seven so far), and every agent session starts from `AGENTS.md`, which
carries the hard gates: do not implement the AI layer until the audit is
complete, trace every capability to a use case in `USERS.md`, and never
describe a planned safeguard as implemented. The order was audit, then
`USERS.md`, then the architecture and the ADRs, then the module gateway, then
the agent, then the evals — the AI layer was gated on the audit being
finished, not on a feeling that the codebase was understood. Work lands in
small conventional commits (81 at `0fba313` on 2026-09-17, 167 at
`week1-final`), and every push runs the fast deterministic checks in
`.gitlab-ci.yml`: whitespace, `php -l` over the module, `caddy validate`,
`docker compose config`, the pytest suite (91 cases on 2026-09-17, 145 at
`week1-final`), the contract drift check and the offline eval subset; from
2026-09-17 to 2026-09-20 a push to `main` also deployed to the Droplet
(`deploy:production`) and smoke-checked it (`verify:smoke`); `deploy:production`
is manual since, so a push alone no longer deploys, though `verify:smoke`
still runs on every push. The live suite is a manual job so a push
never spends model budget by itself. The standing rule is
evals-before-tuning — no change to the prompt, the model id, the effort
setting or the verifier lexicon without a baseline run, the change, a second
run and an `evals/compare.py` diff — and a case is added for every discovered
bug and every cohort defect. What the workflow does not yet include is the
review step: one error-analysis journal of 20 traces is sampled and committed,
and all 20 First-issue fields are still blank.

Evidence: `AGENTS.md` "Hard Gates"; `.gitlab-ci.yml:10-135`; `evals/README.md` "Error Analysis" (the committed journal, 0 of 20 reviewed).

## Deployed today versus planned (2026-09-17)

What is actually running on the Droplet at the time of the interview, against
what is written down but not built. "Planned" here means planned — nothing in
the right-hand column is implemented.

**What moved by 2026-09-20.** The table is the record of 2026-09-17 and is not
rewritten. Since then: the `alerts` service runs on the host every 300 s and
pages a Slack channel through a file-secret webhook, which makes ten Compose
file secrets; rollback, roll forward, `backup.sh` and `restore.sh` were
rehearsed on a throwaway Droplet on 2026-09-18 and two Droplet snapshots
exist; the 10- and 50-user load tests ran on 2026-09-18; `/ready` reports
`tracer` `ok` on the Droplet; the cost gate reads $0.0104 at the release run;
and `CONF-NOTE-VS-LIST-N-001` passed three of three in the release run while
remaining model recall. Still as the table says: no egress restriction, no
OpenEMR audit row for agent-level denials, and an unreviewed journal. The
current list is the next section.

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
| Verification pass/fail panel | **Counter and scores since 2026-09-17; panels built 2026-09-18, after this table was written.** `/metrics` exposes `copilot_verification_total{outcome}` and every `copilot.turn` trace carries the `verification_passed` and `turn_error` scores; the 2026-09-16 nine-panel set had neither verification outcome nor error rate | Re-render the committed panel evidence, which predates the two panels | `agent/app/turn_outcome.py`; `agent/app/telemetry.py` (`finish_turn_trace`); `docs/operations/langfuse-dashboard.md` |
| Cost gate | **Configured 2026-09-17.** PASS at or under $0.0223 per model-backed turn, PASS (warn) to $0.0446 with risk acceptance, FAIL above; $0.0127 measured at `a4a5856` | A cost alert on daily spend ($14 warn, $42 page) is still manual from `/metrics` | `evals/run.py:146`, `:593`; `AI_COST_ANALYSIS.md` Part B |
| Agent-level denials | Counted in `/metrics` (`copilot_denials_total{reason}`) and in the agent's logs only. They never reach the gateway, so **they leave no OpenEMR audit row**; gateway-level denials do | An audit path for denials rejected at the agent API | `ARCHITECTURE.md` "Open Items" item 9; `agent/app/api.py:49`, `:57` |
| `CONF-NOTE-VS-LIST-N-001` | **Missed** in the 2026-09-17 run: the model did not raise the planted note-versus-list conflict. Non-blocking task-success gate, 95%, PASS | A deterministic note-versus-list conflict detector | `evals/results/2026-09-17T024919Z-a4a5856.md:19`, `:123` |
| Error-analysis journal | **Unreviewed.** 20 traces across 14 patients are sampled and committed; all 20 First-issue and Notes fields are blank | Fill all 20, run the report, commit the issue list | `evals/error_analysis/2026-09-16T190727Z-journal.md:23`; `evals/README.md:197-199` |

## Known gaps at submission (2026-09-20)

Written for both AI interviews. If an evaluator finds one of these, it should
already be on this list; nothing here is discovered on camera.

**Measured on an older tree.** The load tests, the CPU and memory baselines,
and the droplet-tier comparison all ran 2026-09-18. Three performance changes
landed after them: the batched gateway, follow-up turns at low effort, and the
brief prepared on chart open. The batched gateway got its own before/after and
ceiling sweep on 2026-09-19, on a throwaway Droplet of the same size (onset
still between 10 and 15 users); nothing concurrent has been measured since the
other two, and nothing on the live host since 2026-09-18. The bottleneck they
identified — OpenEMR's Apache/PHP and MariaDB CPU, not the agent — is
structural and unchanged, but the absolute per-level numbers predate those
changes. The serial eval latency is current; the concurrent numbers are not.

**The committed dashboard renders are two panels behind the dashboard.**
Verification pass/fail rate and turn error rate are widgets on the Langfuse
dashboard (built 2026-09-18, seen drawing data 2026-09-20) over the scores
`verification_passed` and `turn_error`, which are emitted on every turn —
8,709 scores on the project as of 2026-09-20. The panel renders committed
under `docs/audit/evidence/observability/` are the nine-panel set from
2026-09-16 and show neither. Langfuse Cloud exposes no widget API; the widget
fields are recorded in `docs/operations/langfuse-dashboard.md`.

**Release run, and the tree that moved after it.**
`evals/results/2026-09-20T051146Z-0f11642.md` was taken while `c37b9e6` was
deployed (the two runtime trees are byte-identical): 48 cases x 3 attempts,
124 attempts in all because the 10 offline cases run once, 123 passed, every
blocking gate PASS, golden 29/29 attempts, citations 615/615 resolved,
model-backed p95 15.8 s, $0.0104 per turn, no 5xx. One miss,
`CONF-DUP-NAMES-C2-001`, flaky at 2 of 3 and in the holdout tier: on one
attempt the summary called a duplicate medication a duplicate rather than a
possible one, which the hedging lexicon caught. Two gates read NOT MEASURED
by design (below). Against the a4a5856 baseline
(`evals/results/2026-09-20T051146Z-0f11642-vs-a4a5856.md`): p95 24.1 s to
15.8 s, task success 95% to 100%, cost $0.0127 to $0.0104, and
`CONF-NOTE-VS-LIST-N-001` FAIL to pass. Four runtime commits then landed and
were deployed for the alert work below (`e466b9d`, `dbf5372`, `0471178`,
`478f432`; only `dbf5372` touches the turn path). `478f432` is what is live,
the tag `week1-final` differs from it only in docs and eval results, and
`evals/results/2026-09-20T064022Z-4d2a9fd.md` is the full single pass at that
tree: 48 of 48, every blocking gate PASS, citations 206/206, p95 20.0 s,
$0.0113 per turn, no 5xx. So the three-attempt stability evidence is one
counter fix behind the running code, and the single pass is at it. The image
digests, the Droplet snapshot and the edge re-probe recorded on 2026-09-20
also predate that last deploy and were not re-taken; the Caddyfile did not
change in it. One more thing an evaluator can find in `evals/results/`: the
golden case `INJ-NOTE-O-001` failed once, in a golden-only smoke run
(`2026-09-20T032913Z-23e197e.md`, a claim's text matched the case's forbidden
`no allergies` pattern), and has passed all seven attempts since. That is
model wording inside a tier described as having none.

**The deployment runs UTC, and that is a limitation, not a preference.** A
clinic needs its own day: `BriefPolicy` asks "is this patient being seen
today", and in UTC an evening chart open in Pacific is already asking about
tomorrow. We set the clinic timezone on 2026-09-19 and reverted it the same
night. The reason is the interesting part. OpenEMR re-points the MySQL
session at PHP's offset on every connect, so setting `TZ` on `openemr` and
`agent` and not on `database` made application writes resolve in PDT while
every row already in the table stayed UTC — one `datetime` column, two
clocks, seven hours apart. `findResumable` orders by `last_turn_at DESC`, so a stale
conversation outranked the one just created and resume returned the wrong
transcript; `isIdle` read the old rows as future-dated and never retired
them. Nothing errored. The eval suite caught it
(`ISO-RECENT-PATIENT-RESUME-001`, three failures of three, having passed at
`f4f69ab4`), which is the argument for the suite in one sentence. Doing it
properly means the timezone on every container that touches a date plus a
migration of rows written on the old clock; doing it partially is worse than
UTC. The revert removed `TZ` from the compose file and nothing else: the
entrypoint's `configure_timezone()` is still there, dormant while `TZ` is
unset, and `BriefPolicy` still takes PHP's day rather than the database's.
The conversation table was truncated (a dump was taken first) and the cohort
re-seeded on one clock. Two residues were left in place and written down
rather than scrubbed: roughly three hours of OpenEMR audit rows, written
between the 18:45 PDT deploy and the 21:33 PDT revert, are stamped about seven
hours early among UTC neighbours — deleting audit rows to tidy a seam is not a
trade this project should make — and the agent's SQLite volume still holds
checkpoints for the truncated conversations, unreachable and unswept. Full
write-up: `docs/audit/evidence/performance/brief-on-open-2026-09-20.md` §10.

**The brief on chart open spends before anyone asks.** Since module 0.5.0 the
panel starts the UC-01 brief itself when a chart finishes loading, through the
same path as a click: session and CSRF, per-turn ticket, delegation token,
per-tool section ACL, audit before data, verifier. `BriefPolicy` decides
server-side. The module default is `visit_today` — only a chart with a
non-cancelled appointment today — and an unknown value fails closed to `off`;
the demo box overrides to `always` so a grader sees the brief on any day, and
no mode prepares one for a break-glass login or a role with no clinical
section. What it costs: an unread brief is about $0.011 of model spend (the
live-suite average per model-backed turn; a brief-specific cost is not
measured) plus its `copilot-tool-read` rows and two `copilot-model-disclosure`
rows. `/metrics` counts `brief_started` against `drawer_open` so the waste can
be read, but those counters are in-process, reset on every deploy, are fed by
an unauthenticated endpoint, and no real-session numbers exist. What the
physician waits for was measured once (`evals/brief_latency.py`, 12 briefs on
four charts): the brief is ready at p50 13.4 s and p95 17.5 s, so at a 10 s
reading lag the wait is p50 3.4 s and p95 7.5 s against 12.7 s and 16.9 s for
the click flow. The lag is a parameter, not an observation — no physician
session was timed — and the run was not repeated at the deployed tree. One
flaw is written down and not patched: a restored transcript draws the brief as
a question the physician never typed. Evidence:
`docs/adr/0003-integration-point-module-gateway.md` (amendment 2026-09-19),
`docs/audit/evidence/performance/brief-on-open-2026-09-20.md`,
`docs/audit/evidence/performance/brief-latency-2026-09-19.md`,
`docs/operations/usage-funnel.md`.

**The demo deployment sends trace content to Langfuse.** The code default
masks every trace payload to a digest. The demo compose file sets
`COPILOT_TRACE_CONTENT=1`, so each `plan`, `narrate` and `repair` generation
carries its prompt, the evidence pack and the raw output, and the turn carries
the question and the rendered answer. It was turned on because digest-only
traces could not explain why 19 of 79 summaries were being replaced, and it is
defensible only because the box holds 26 synthetic patients; ADR-0007's
2026-09-19 amendment states the assumption as an assumption, and there is
still no BAA. With real PHI the default stays. Where this file says traces
carry digests, read "by default".

**The alerts page a Slack channel, and proving that found two defects.** The
three PRD alerts were evaluated every 300 s and written to stdout, which meant
a page at 3am reached nobody. Wiring the webhook was meant to be a five-minute
job. Driving five faulted turns at the deployment showed `/metrics` had no
`medications` row at all: the batched-gateway optimisation
(`046b96e`) resolves fault-injected and invalid-params tools locally and
skipped the counter increment, so the tool-failure alert's numerator was
structurally zero and it could not fire. That is not just a test gap —
`invalid_params` is a real production failure, the model emitting a parameter
the contract rejects, and it was invisible to the alert built to catch it. The
2026-09-18 page predates batching, which is exactly why the alert looked
healthy. Fixed, then the first real delivery returned
`"webhook_delivered": false` because Slack rejects a body without `text`.
Fixed too. Both pages now land in the channel with exact denominators.
Evidence: `docs/audit/evidence/observability/alerts-slack-2026-09-20.log`. The
lesson I would state to a CTO: an alert you have never seen fire end to end is
a hypothesis, not a control. The other half is in the same file: the manual
live suite on 2026-09-20 (pipeline 24351, job 79057, 761 s) ran without a
page. One thing to know when reading that channel: a fault-injected tool
counts toward the rate, and fault injection is on for the demo box, so an eval
run with several fault cases in one window can legitimately page there.

**Two gates read NOT MEASURED, by design, not by omission.** Citation
correctness needs gold source ids per case — the runner can prove every
citation resolves to a retrieved record (and does, on every run), but not that
it is the *right* record; that is the Week 2 gold-source-id plan. Time to first
useful evidence needs the SSE path, and the runner uses non-streaming turns.
Both are stated as NOT MEASURED in every report rather than being quietly
folded into a pass.

**Still true from the audit, and accepted for Week 1.** Patient isolation
equals OpenEMR's, which is none beyond role; ours rests on the gateway's
per-tool checks. Delegation tickets are not single-use — one is valid for 90
seconds and outlives logout by at most that. The 24-hour conversation purge is
a design target: `ConversationRepository::sweep()` exists with no caller.
Egress from the agent container is unrestricted; the risk acceptance is in
`AUDIT.md` §9. The hostname is still the disposable `sslip.io` one. There are
no executed BAAs, and no real PHI has ever been in the system.

**Repository.** GitLab is the system of record. The public GitHub fork exists
so the PRD's "forked from OpenEMR" requirement points at a real fork; both
carry the same commits and tags at submission. Pipeline 24351 ran green on
`4985e52`, one docs-only commit before the one `week1-final` points at, and
its live-suite output is a CI artifact, not a file under `evals/results/`.

## The Pre-Search Checklist

The PRD Appendix checklist, one section per heading, as built and measured
through 2026-09-17, with the items that moved brought up to 2026-09-20 and
dated where they were.

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
  latest `--repeat 3` scorecard 2026-09-20
  (`evals/results/2026-09-20T051146Z-0f11642.md`, 126 model-backed turns):
  p50 8.2 s, p95 15.8 s, p99 20.6 s; first turns p95 18.6 s, follow-ups p95
  11.2 s. The single pass at the deployed tree
  (`evals/results/2026-09-20T064022Z-4d2a9fd.md`) reads p95 20.0 s. On
  2026-09-17 (`a4a5856`) the same figures were 12.5 s, 24.1 s and 30.7 s,
  first turns 16.0 s, follow-ups 29.7 s. Since module 0.5.0 the first turn
  starts when the chart opens, so the physician waits only for what is left
  of it: measured once over 12 briefs, p95 7.5 s at a 10 s reading lag, the
  lag being a parameter and not an observation
  (`docs/audit/evidence/performance/brief-latency-2026-09-19.md`).
  Time to first useful evidence is **not measured**: the eval runner uses
  non-streaming turns, so the SSE path is never timed and the gate reports NOT
  MEASURED. The streamed `evidence` event is emitted after the retrieve node,
  and the retrieve node measures about 1 s in traces, but that is a node
  timing, not a measured time to first paint.
- **Concurrency.** One 2 vCPU / 4 GB Droplet; one uvicorn process, no
  `--workers`. Since 2026-09-19 a turn's tools go to the gateway as one or
  two batched requests, and the 6-wide per-turn `asyncio.Semaphore` went away
  with the per-tool calls; there is no process-wide turn semaphore, so
  nothing in the agent bounds concurrent turns. One model call per node. Load
  tests at 10 and 50 concurrent users ran on 2026-09-18 (the web-tier bullet
  below, and Q10).
- **Cost constraints.** 20K tokens per turn, 60K per conversation, and a daily
  token halt that routes to the deterministic fallback (`agent/app/budget.py`,
  ADR-0004). Measured $0.0104 to $0.0118 per model-backed turn at list price
  with prompt caching across the full runs of 2026-09-19 and 2026-09-20
  ($0.012 to $0.014 on 2026-09-16 and 2026-09-17; eval scorecards).
- **OpenEMR web tier — a separate axis from the agent above, now measured by
  the M4 load test (2026-09-18).** An earlier version of this note theorized
  an unset PHP-FPM `pm.max_children` pool as the cause of the
  operator-observed failure between 5 and 10 concurrent users. **That theory
  is disproven**: a live check of the `openemr` container found `mod_php`
  under Apache prefork (`MaxRequestWorkers=250`), not PHP-FPM at all, and the
  load test never pushed the Apache process count anywhere near that limit
  before CPU saturated. Confirmed cause: `openemr` and `database` each
  independently peak at or above 100% of a full vCPU core on the Droplet's
  two cores well before any worker-count ceiling matters. Full detail in
  `ARCHITECTURE.md` "Latency and Scale" and
  `docs/audit/evidence/performance/`.
  - **Same-box mitigation: none left to try.** No FPM pool to raise — the
    constraint is raw CPU. The one same-box lever that existed (batching the
    co-pilot's own tool-gateway calls, which had been repeating OpenEMR's
    ~1,045-query bootstrap up to six times per turn) shipped and was measured
    2026-09-19: it lowered CPU peaks at 10 users but did not move the
    failure onset, still between 10 and 15 concurrent users. Detail in the
    clinic-size estimate below.
  - **Horizontal option, priced, not built.** Load balancer + N
    `docker/binary` app nodes + managed MySQL + managed Valkey (externalizing
    PHP sessions, which are container-local today) + one shared NFS node for
    `sites/documents` (also container-local today). Unlike the disproven
    FPM theory above, horizontal OpenEMR nodes are a real answer to the
    now-confirmed CPU-bound constraint — N nodes is approximately N× the
    CPU/SQL-processing budget the load tests measured, an axis those tests
    never tried (they only varied single-Droplet size; see the droplet-tier
    comparison below). DigitalOcean list pricing checked 2026-09-18:
    ≈$107/mo (2 lean app nodes, single non-HA DB/Valkey) to ≈$177/mo (3
    nodes, right-sized DB, still no failover) to ≈$277/mo (4 nodes plus
    DB/Valkey standbys), against the current single-Droplet $24/mo
    (`infra/digitalocean/variables.tf:13-16`). Not implemented, not
    load-tested, no ADR — a brainstormed answer to "how would you scale
    this," not a plan committed in `infra/`.
  - **Extending the same topology to the agent tier, diagrammed, not
    built.**

    ![Horizontally scalable OpenEMR + agent architecture: an edge load balancer routes to an independently scalable OpenEMR app tier and agent tier, sharing MySQL, Redis/Valkey, and NFS storage](../diagrams/horizontal-scaling-openemr-agent.svg)

    Both tiers scale by adding nodes behind the same edge (Caddy already
    splits `/` to OpenEMR and `/copilot-api/*` to the agent); the agent's
    gateway calls still land in-process inside whichever OpenEMR node picks
    them up (ADR-0003), and it never touches MySQL directly. One important
    caveat the M4 finding puts on this diagram: **adding agent replicas
    would not move today's measured ceiling** — the confirmed bottleneck is
    OpenEMR/MariaDB CPU, and `agent` CPU never exceeded 54% peak even under
    real load (`ARCHITECTURE.md` "Latency and Scale"). Agent horizontal
    scaling answers a different question — how many simultaneous
    conversations the agent itself can hold once OpenEMR isn't the wall —
    and it needs one change with no working precedent yet: swapping
    `AsyncSqliteSaver` (a local file, one writer; still process-local after
    the 2026-09-18 WAL fix) for a shared, multi-writer checkpointer. The
    repo's own stated direction for that is Postgres, not Redis
    (`ARCHITECTURE.md` "Latency and Scale"; deferred to Week 2,
    `docs/WEEK2_HANDOFF.md`) — the diagram draws one shared Redis/Valkey box
    for both OpenEMR sessions and agent state for simplicity; read the
    agent's edge of that box as "a shared external store," not a commitment
    to Redis specifically.
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
    - **Today, prod `s-2vcpu-4gb`, partly fixed 2026-09-19
      (`docs/audit/evidence/performance/batched-gateway-2026-09-19.md`).** No
      config-tunable worker pool to raise — the constraint is raw CPU. The
      co-pilot's own tool-gateway traffic turned out to be a meaningful part
      of that CPU load (each of a turn's up-to-six tool calls repeated
      OpenEMR's ~1,045-query bootstrap); batching those into one or two
      gateway requests per turn measurably helped *at* the previously-tested
      10-user level (status share 85% -> 100% clean, both `openemr` and
      `database` CPU peaks dropped from over one full vCPU core to under it)
      but did **not** raise the ceiling itself — re-measured onset is between
      10 and 15 concurrent users, CPU pegged around 125-136% per container
      from 15 through 50. Estimated safe zone: still **roughly a 1-2 provider
      practice** — this number hasn't materially changed, because batching
      removes redundant bootstrap work, not the real per-tool SQL fetch work
      that two vCPUs were always going to struggle to serve past low double
      digits of concurrent turns.
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
  before data leaves, carrying the correlation id, and since 2026-09-19 a
  batch whose records go to the model also writes a `copilot-model-disclosure`
  row first (provider, model, tools, record count, never content) and returns
  nothing if it cannot
  (`docs/audit/evidence/compliance/04-model-disclosure-rows-2026-09-19.md`);
  the agent logs are PHI-free JSON; traces are masked to digests by default
  (ADR-0007), with content capture turned on for the synthetic-only demo box
  (its 2026-09-19 amendment). Denials rejected at the agent API never reach
  the gateway and so leave no OpenEMR audit row — they exist only in
  `/metrics` and the agent logs (`ARCHITECTURE.md` "Open Items" item 9;
  `agent/app/api.py:50`, `:58`). `AUDIT.md` §5 maps
  observations to HIPAA provisions, but no BAA has been executed with the
  model provider and none has been reviewed — the executive summary says
  "No executed BAAs" and §3 says "The BAA remains assumed, not reviewed". No
  HIPAA compliance is claimed.

### 4. Team and skill constraints

- **Agent frameworks.** LangGraph was chosen from day one so Weeks 2 and 3
  (supervisor and workers, ingestion, retrieval) extend the graph instead of
  replacing a hand-rolled loop (`docs/PROJECT_PLAN.md`).
- **Domain experience.** Primary-care workflow written down first
  (`USERS.md`) and checked against OpenEMR's real data shapes in a two-day
  audit (`AUDIT.md`) before any agent code; the clinician interview is still
  open (`USERS.md` "Validation Work").
- **Eval and testing.** Comfortable enough to write the suite ourselves: 48
  YAML cases (15 of them a golden tier, 4 a holdout tier; all 48 in the two
  latest full runs), a runner that drives the real login and chart handshake,
  pytest for the offline invariants. No eval framework (see §9).

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
  2 s timeout on each batched gateway request. The agent never touches the
  database (AGENTS.md hard gate).

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
- **Cost per query.** $0.0104 measured per model-backed turn in the release
  run (`0f11642`), $0.0113 in the single pass at the deployed tree
  (`4d2a9fd`) and $0.0127 on 2026-09-17 (`a4a5856`), against the $0.0223
  projection basis in `AI_COST_ANALYSIS.md` Part B, the configured gate since
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
  mask so nothing but digests leaves the box by default. The demo box runs
  with content capture on (`COPILOT_TRACE_CONTENT=1`, the 2026-09-19
  amendment), which is for synthetic patients only.
- **Metrics that matter.** Nine panels on the "Clinical Co-Pilot" dashboard
  cover the PRD's request count, latency p50/p95, token usage, cost, tool
  calls, tool failures, repair count (via generations by name) and an
  ERROR-level observation count
  (`docs/operations/langfuse-dashboard.md`, "Panels and the PRD metric each
  covers"). The PRD's other two dashboard minimums, verification pass/fail
  rate and turn error *rate*, are two further panels over trace scores; the
  ERROR-level panel alone counts observations and divides by nothing. Since
  2026-09-17 the inputs exist: every `copilot.turn` trace carries the `verification_passed`
  and `turn_error` scores
  (`agent/app/telemetry.py` `finish_turn_trace`) and `/metrics` exposes
  `copilot_verification_total{outcome}` beside
  `copilot_verifier_rejections_total` (`agent/app/metrics.py:131-136`); the
  two panels over the scores were built in the Langfuse UI on 2026-09-18
  (`docs/operations/langfuse-dashboard.md`). Since 2026-09-19 `/metrics`
  also carries the usage funnel
  (`copilot_panel_events_total{event}` for `chart_open`, `brief_started` and
  `drawer_open`), which is how an unread brief gets counted
  (`docs/operations/usage-funnel.md`); the counters reset on every deploy.
- **Real-time monitoring.** Prometheus-style `/metrics` on the agent, and
  `agent/app/alerts.py`, which evaluates the three PRD alerts against the
  thresholds in `KEY_METRICS.md` over two samples. On the live host the
  `alerts` compose service runs it every 300 s
  (`infra/digitalocean/runtime/compose.yaml`) and delivers to a Slack channel
  through a webhook read from a Docker file secret; delivery was proven on
  2026-09-20 (`docs/audit/evidence/observability/alerts-slack-2026-09-20.log`).
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
  is recorded in `docs/SUBMISSION_CHECKLIST.md`, and so is the last one for
  Week 1: pipeline 24351 on `4985e52` (ref `week1-final`, 2026-09-20), all
  seven jobs green including the manual live suite. The golden tier
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
  `partial`; the model's prose summary is replaced by the first verified
  claims, restated word for word, when anything was withheld (ADR-0006 §7).
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
  a bounded allowlist of the seven tools
  (`agent/app/graph/nodes.py:265-266`) and whose parameters are re-checked at
  the gateway; out-of-scope requests (other patients, schedule, general
  medicine, dosing) are refused as a limitation, not answered. An
  `interpretation` claim type lets the model state a reading the physician
  can correct.
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
  `:80`). A CSP on the module's assets is **planned** (SEC-MED-003); no CSP
  header is set today.
- **Data leakage.** Authorization is parity with the chart (ADR-0002): the
  gateway checks the same ACLs OpenEMR does before any tool returns data; a
  patient switch closes the conversation at the ticket stage; a patient id in
  tool params is rejected by the gateway's hand-written parameter allowlist,
  which mirrors the exported JSON Schemas but does not validate against the
  schema files (`ToolRegistry.php:37-54`; `AUTH-FORGED-PID-001`). Traces carry
  digests only by default (the demo box captures content, see the known gaps
  above); logs are PHI-free.
- **API key management.** Docker secrets on the host, files with mode 600 on
  the workstation, never in the repository, environment dumps, Terraform
  state, or shell history; the runner token follows the same pattern.
- **Audit logging.** One OpenEMR audit row per gateway call with user,
  patient, tool, and correlation id, written before data leaves; if the insert
  fails the tool returns `unavailable` rather than records
  (`src/Gateway/BatchRunner.php:54-64`). Since 2026-09-19 a retrieval whose
  records go to the model also writes a `copilot-model-disclosure` row before
  they leave (`public/gateway/tools.php:103-118`): one per batch, so two for a
  UC-01 first turn; its fail-closed branch has not been exercised on the
  deployment. Gateway-level denials are audited with
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
  `agent/tests/`, counted 2026-09-17 at `0fba313`; 145 at `week1-final`,
  2026-09-20); PHP lint and a recorded-response contract test for the tools.
- **Integration.** The turn graph with recorded gateway fixtures and a
  scripted model; the live eval suite drives login, chart open, session,
  ticket, and turn against the deployment as different users; the Bruno
  collection (22 requests, 45 assertions) covers the HTTP contract. The
  recorded 21/21 runs predate the 22nd request, `06 Brief on chart open`.
- **Adversarial.** Authorization cases (front office, squad restriction,
  tampered and stale tickets, forged pid, patient switch), injection,
  altered facts, fabricated sources, advice wording, budget exhaustion.
- **Regression.** One case per discovered bug (the `activity=0` with no end
  date conflict, DQ-HIGH-002; paraphrased advice slipping past the lexicon,
  `CIT-PARAPHRASE-ADVICE-001`) and one per cohort defect; results versioned
  per commit in `evals/results/` with a compare script and `--repeat` for
  flakiness. Two model-recall cases flip run to run — `MISS-AUTHOR-J-001`
  (runs `1ddf824`, `69560f05`, `1fda51b`) and `CONF-NOTE-VS-LIST-N-001` (run
  `a4a5856`) — and both sit under the non-blocking task-success gate. Two
  more have flipped on wording since: the holdout case
  `CONF-DUP-NAMES-C2-001` (runs `12cd849a`, `0f11642`) and, once, the golden
  case `INJ-NOTE-O-001` (the golden-only smoke run `23e197e`). No
  deterministic assertion has flipped on an unchanged deployment; the one
  that failed there, `ISO-RECENT-PATIENT-RESUME-001` at `695acfa` and
  `6c787bd`, was the split-clock regression and passes again from `c37b9e6`
  (the 12/14 golden run at `7b7022b` was the 2026-09-18 rehearsal Droplet
  before its model key was pushed, not the live host).

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
  (`infra/digitalocean/main.tf:67-82`). A second $6 Droplet runs CI.
- **CI/CD.** Lints, contract schema check, agent tests, and the offline evals
  on every push. Deployment is the same script either way
  (`infra/digitalocean/deploy.sh`): from 2026-09-17 to 2026-09-20 a push to
  `main` ran it from CI (`deploy:production`, then `verify:smoke`), an owner
  decision to deploy continuously once the early submission was in;
  `deploy:production` is manual since 2026-09-20 so a docs-only push stops
  redeploying the Droplet. The live suite stays a manual job, so it
  exercises whatever is currently live, not necessarily the commit just
  deployed (`.gitlab-ci.yml:73-135`).
- **Monitoring and alerting.** Langfuse dashboard (nine panels), `/health`,
  `/metrics`, and `/ready`. `/ready` really probes the gateway (`ping.php`)
  and the LLM (`models.retrieve`), and since 2026-09-17 the tracer too
  (`GET /api/public/projects` on the Langfuse host with basic auth and a 5 s
  timeout, `agent/app/readiness.py:81-100`; all five dependencies read `ok`
  on the Droplet on 2026-09-20). The panel itself probes `/health`, not
  `/ready` (`copilot.js:717`). Alerts have page and warn thresholds; on the
  live host the `alerts` compose service
  (`infra/digitalocean/runtime/compose.yaml`, `--interval 300`) evaluates
  them every 300 s and delivers pages to Slack through a file-secret webhook
  (`docs/operations/alerts.md` "Delivery").
- **Rollback.** Images are built from the repository at a commit; rolling
  back is redeploying the previous commit with the same script. The database
  is untouched by the co-pilot (read-only), so rollback has no data migration
  step. Never rehearsed as of 2026-09-17; **rehearsed end to end on
  2026-09-18** on a throwaway Droplet, the live host never touched
  (`docs/deployment/digitalocean.md` `## Rehearsal Runbook`, timing table:
  `backup.sh` 15 s, rollback to tag `week1` 2m36s, roll forward 1m13s,
  `restore.sh` about 3m19s, and the restore was shown to restore rather than
  no-op). The live host has two Droplet snapshots (`week1-final-2026-09-18`,
  `week1-final-2026-09-20`, the second taken before the last alerts deploy);
  no `backup.sh` run against it is recorded and nothing is scheduled
  (`## Backup and Restore`).

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
   quality (withheld rate, replaced summaries) but not safety, which is
   exactly what the scorecard measures.
3. **JSON-as-text over grammar-constrained output** (ADR-0004). Defense:
   measured 45 s or more with constrained decoding versus 5 to 9 s as text,
   with the contract still enforced after parsing and one re-ask on
   malformed output; malformed rate is visible in the traces.
