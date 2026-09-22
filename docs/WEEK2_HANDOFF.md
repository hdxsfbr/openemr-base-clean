# Week 2 implementation handoff

**Status:** Local implementation seams are substantially complete on branch
`codex/week2-implementation` as of 2026-09-21, but the mandatory runtime is not
complete. Production extraction/OCR/storage and source-view adapters are not
wired into FastAPI startup; `document_ready` remains false and source review
fails closed. Deployment, protected-branch configuration, an owner-approved
full baseline, and live browser/load/rollback evidence also remain open.

Start with
[`docs/specs/week2-integrated-implementation-plan.md`](specs/week2-integrated-implementation-plan.md).
It is the authoritative execution sequence and evidence handoff from the
completed Wayfinder map. It reconciles ADR-0008 through ADR-0015, maps every
capability to `USERS.md` UC-01 through UC-03, UC-05, and UC-06, maps the Week 2
PRD into `docs/REQUIREMENTS_TRACEABILITY.md`, and defines the exact
`W2_ARCHITECTURE.md` outline and implementation-ticket dependencies.

The locally implemented core seams are intentionally narrow: two document types, the PRD-named
intake-extractor and evidence-retriever workers behind a deterministic
supervisor, the approved bounded guideline corpus/retriever, closed source and
citation contracts, source-grounded review UI, 55 golden and 90 total
retained eval cases, candidate-matched blocking GitLab CI, and the accepted
single-host operational budgets. The model and agent remain unable to write;
only an explicit authorized physician UI action may promote a fully reviewed
document into immutable module-owned records.

Treat local seams, runtime integration, and external release evidence
separately. C7 runtime wiring and C8 external enforcement remain partial; do
not mark deployment, protected CI, load, rollback, or browser evidence complete
until the listed artifacts exist. `W2_ARCHITECTURE.md` remains a synthesis of
accepted decisions, not a place to silently choose different ones.

## Week 1 baseline inherited by Week 2

The baseline below was first written as a Week 2 stub. Every claim was checked
on 2026-09-17 against the working tree (HEAD `0fba313`; M2 round 1 committed in
`16a5d34..7197ed6`, re-checked in round 2); a `file:line` is the proof. It was
re-checked on 2026-09-20 at tag `week1-final` (`ebaae17`): every code
`file:line` below was re-pointed to that tree, and `ARCHITECTURE.md` is cited by
section because its lines moved. These observations remain inherited
constraints; the accepted integration plan replaces the stub's speculative
Week 2 seams.

## Read first, in this order

1. `README_AGENT_FORGE.md` (what is deployed, credentials by name, limits), then `SETUP.md`.
2. `ARCHITECTURE.md` and `docs/adr/` 0002 to 0007: settled decisions; do not re-litigate. Read
   the dated amendments too: 0003 (batched gateway, brief on chart open), 0004 (plan rounds),
   0006 (summary grounding, the disclosure event), 0007 (content capture).
3. `AUDIT.md` section 9 Residual Risk, then `KEY_METRICS.md` (gates) and `evals/README.md`.
4. `agent/README.md`, `docs/operations/alerts.md`, `docs/operations/usage-funnel.md`,
   `docs/deployment/digitalocean.md`.
5. `docs/FINAL_PUSH_PLAN.md` section 1: the eight invariants still apply in Week 2.

## State at handoff (2026-09-20): what changed after this stub was written

- **What is running.** Commit `478f432` is live at `https://openemr-137-184-4-22.sslip.io`; tag
  `week1-final` (`ebaae17`) differs from it only in docs and eval results (`git diff 478f432
  week1-final -- agent interface/modules/custom_modules/oe-module-copilot infra` is empty). Agent
  `/health` reports 0.3.0 (`agent/app/__init__.py:3`); the module is `Bootstrap::VERSION` 0.5.0
  (`src/Bootstrap.php:33`), served as `module_version` by `public/api/session.php:37`. The module's
  `version.php` and `info.txt` were never bumped and still say 0.1.0. **A push to `main` can
  deploy to that Droplet** (`.gitlab-ci.yml:85-99`, `deploy:production`, then `verify:smoke`) --
  automatic 2026-09-17 to 2026-09-20, manual since.
- **Brief on chart open (module 0.5.0, ADR-0003 amendment 2026-09-19).** The panel starts the
  UC-01 brief itself when a chart finishes loading, through the same path as a click; no new
  endpoint or authorization. `BriefPolicy::mode()` (`src/BriefPolicy.php:45-62`): unset means
  `visit_today`, an unknown value fails closed to `off`; the demo compose file overrides to
  `always` (`infra/digitalocean/runtime/compose.yaml:79`), so the comment at `BriefPolicy.php:49`
  about the compose default is stale. No brief for a break-glass login or a role with no clinical
  section. An unread brief is about $0.011 (the live-suite average per model-backed turn, not a
  brief-specific measurement) plus its audit rows; `copilot_panel_events_total{event}` counts
  `brief_started` against `drawer_open` (`docs/operations/usage-funnel.md`), in-process, reset on
  every deploy, no real-session numbers yet. Physician wait, measured once with
  `evals/brief_latency.py`: brief ready at p50 13.4 s / p95 17.5 s over 12 briefs; the reading lag
  is a parameter (`docs/audit/evidence/performance/brief-latency-2026-09-19.md`). Known flaw, not
  patched: a restored transcript draws the brief as a question the physician typed
  (`docs/audit/evidence/performance/brief-on-open-2026-09-20.md` section 6).
- **Batched gateway and the disclosure audit (2026-09-19).** A turn's tools go to `tools.php` as one
  or two batched requests (`agent/app/graph/nodes.py:209-247`, `src/Gateway/BatchRunner.php`); a
  batch-level timeout marks every tool in it `unavailable`. When the records will go to the model
  the agent declares `{provider, model}` (`nodes.py:160-166`) and the module writes a
  `copilot-model-disclosure` row before returning them, or returns none
  (`public/gateway/tools.php:103-118`): one row per batch, so two for a UC-01 first turn. The
  fail-closed branch has not been exercised on the deployment
  (`docs/audit/evidence/compliance/04-model-disclosure-rows-2026-09-19.md`).
- **Alerts deliver to Slack (2026-09-20).** The compose `alerts` service runs `python -m app.alerts`
  (which hands off to `agent/app/alerts_cli.py` `main`) with `--interval 300`, `--webhook-file
  /run/secrets/slack_alert_webhook` and a best-effort `--webhook-channel`
  (`infra/digitalocean/runtime/compose.yaml:227-262`). Proving it found two defects, both fixed:
  locally resolved tool failures (`fault_injected`, `invalid_params`) were not counted (`dbf5372`),
  and Slack rejects a body without `text` (`0471178`). Evidence:
  `docs/audit/evidence/observability/alerts-slack-2026-09-20.log`.
- **Clock: every container runs UTC, on purpose, and it is a limitation.** A clinic timezone was set
  on some services and not others on 2026-09-19 (`a6bb7b2`, `449c664`) and reverted the same night
  (`c37b9e6`, compose only): it put two clocks in one `datetime` column and broke conversation
  resume without an error (`ISO-RECENT-PATIENT-RESUME-001`, 3 of 3 at `6c787bd`). Doing it
  properly is `TZ` on `openemr`, `database`, `demo-seed`, `copilot-setup` and `agent` together plus
  a row migration. Residue left in place: roughly three hours of OpenEMR `log` rows (18:45 to 21:33
  PDT, 2026-09-19) stamped about seven hours early; orphaned checkpoints on the `agent_state`
  volume for the conversations truncated out of `copilot_conversation`; `configure_timezone()`
  dormant in `infra/digitalocean/runtime/openemr-entrypoint.sh`; `BriefPolicy` reading PHP's day,
  not `CURDATE()`. The cohort's appointments sit on the seeder's anchor day (`DEMO_ANCHOR`), so
  under `visit_today` the brief stops firing for the cohort once that day passes; the demo box
  runs `always` for that reason. Write-up:
  `docs/audit/evidence/performance/brief-on-open-2026-09-20.md` section 10.
- **Trace content.** `trace_content` defaults to `False` (`agent/app/settings.py:31`); the demo
  compose file sets `COPILOT_TRACE_CONTENT` to 1 (`compose.yaml:194`), so that box sends prompts,
  the evidence pack and answers to Langfuse. Synthetic patients only; ADR-0007 amendment 2026-09-19.
- **Settings that moved.** `max_plan_rounds` 3 to 1 (`settings.py:61`, 2026-09-18),
  `effort_followup` medium to low (`:50`, 2026-09-19), `max_output_tokens` 1,800 to 3,200 (`:57`,
  2026-09-19); `KNOWN_PLANS` (`nodes.py:53`) skips the plan call for the agent's own five suggested
  questions.

## Seams: what is code and what is prose

| Seam | Prose says | Code is | Evidence |
| --- | --- | --- | --- |
| `SourceRef.id` | `SourceId` is a URI open to `document:` and `guideline:` schemes | `id: int = Field(ge=0)`, `table: str`, `uuid: str \| None`; the URI is a separate `source_id` field. A page- or chunk-addressed source needs a new shape | `agent/app/contracts/common.py:13-20` (the reserved `document:`/`guideline:` URI schemes and the `SourceId` pattern), `:57-64` (`SourceRef`); `ARCHITECTURE.md` "Canonical Contracts", the `SourceId` bullet |
| Reserved claim types | Week 2 adds `document_extract`, `guideline_reference` with fact types and verifier rules | A comment; no validator, no verifier rule | `agent/app/contracts/turns.py:26` (the only reserved-claim-type comment in `agent/`: `grep -rn document_extract agent/` returns that line alone); `ARCHITECTURE.md` "Canonical Contracts", the claim-type bullet |
| Source registry | "A registry keyed by URI prefix is the Week 2 extension point" | None. `grep -rn -i registry agent/app/` returns nothing; resolution is the flat `EvidencePack.records` dict | `agent/app/evidence.py:60`; `ARCHITECTURE.md` "Canonical Contracts" and "Verification Design" ("Source resolution") |
| `actions/` | "a reserved, empty `actions/` class for writes" | No such directory in `agent/` or the module (`find ... -iname 'actions*'` is empty); `AGENTS.md` requires an ADR before any write | `ARCHITECTURE.md` "Tools" ("Endpoint classes"); `ls module/src/Gateway/` shows seven classes (`BatchRunner.php` is the 2026-09-19 addition) and one subdirectory, `Tools/`, no `actions/` |

## Eval baseline for `evals/compare.py`

Baseline: `evals/results/2026-09-20T051146Z-0f11642.json`, the M5 release run (`--repeat 3`: 48
cases, 124 attempts, 123 passed, Golden 29/29 attempts over 15 cases, holdout 11/12 attempts over
4 cases, citations 615/615, p95 15.8 s, $0.0104 per model-backed turn over 126 such turns; the
miss is `CONF-DUP-NAMES-C2-001`, holdout, one attempt of three, hedging wording). Compare with
`agent/.venv/bin/python evals/compare.py evals/results/2026-09-20T051146Z-0f11642.json evals/results/<candidate>.json`.
It was taken while `c37b9e6` was deployed (runtime trees byte-identical). The deployed tree then
moved to `478f432` (Slack delivery and the tool-failure counter; only `dbf5372` touches the turn
path), and `evals/results/2026-09-20T064022Z-4d2a9fd.json` is the full single pass at that tree:
48/48, Golden 15/15, holdout 4/4, citations 206/206, p95 20.0 s, $0.0113 over 42 model-backed
turns. Use it when the candidate is a single pass, and do not mix the two scorecards.
Older baseline, 2026-09-17: `evals/results/2026-09-17T024919Z-a4a5856.json` (45 cases, 44 passed,
Golden 14/14, citations 177/177, p95 24.1 s, $0.0127 per model-backed turn as printed, $0.0139
after the 2026-09-17 pricing fix in `evals/README.md`; the miss is `CONF-NOTE-VS-LIST-N-001`,
model recall). Its diff against the release run is committed:
`evals/results/2026-09-20T051146Z-0f11642-vs-a4a5856.md`.

## Residuals (verified, not fixed)

- **Fault injection is on by default on the demo host.**
  `COPILOT_FAULT_INJECTION: ${COPILOT_FAULT_INJECTION:-1}`
  (`infra/digitalocean/runtime/compose.yaml:189`) overrides `fault_injection: bool = False`
  (`agent/app/settings.py:78`), so `X-Copilot-Fault` is honored on the graded deployment. Since
  `dbf5372` a fault-injected tool counts toward the tool-failure alert, so an eval run with several
  fault cases in one window can page the Slack channel from that host.
- **No checkpoint sweeper.** `AsyncSqliteSaver` is the checkpointer (`agent/app/main.py:43-53`, WAL
  since 2026-09-18); the only delete path is `drop_pack` for the 120 s evidence-pack TTL
  (`agent/app/state_store.py:17,38`). The 24 h purge is marked planned (`ARCHITECTURE.md` "Status
  and Rules"); on the module side `ConversationRepository::sweep()` exists with no caller
  (`src/Conversation/ConversationRepository.php:115`). Since the 2026-09-20 truncation the volume
  also holds checkpoints for conversations that no longer exist.
- **The daily halt counts input plus output only.** `Usage.total` is
  `input_tokens + output_tokens` (`agent/app/model.py:129-131`), added at
  `agent/app/graph/nodes.py:288,318`; cache reads (4,759 per turn in a4a5856, 4,413 in the release
  run) are not counted; the 2,000,000 limit (`settings.py:66`) is process-local and keyed on the UTC
  day (`agent/app/budget.py:13-38`).
- **`langchain` is present only for the Langfuse callback.** The single import is
  `from langfuse.langchain import CallbackHandler` (`agent/app/telemetry.py:135`); `langchain>=1.0`
  (`agent/pyproject.toml:19`), beside `langfuse>=4.15,<5` (`:18`). `agent/requirements.lock`
  (WS-AGENT A6, committed in `16a5d34`) pins `langchain==1.4.1` and `langfuse==4.15.4`, one patch
  ahead of the `agent/.venv` install (1.4.0, 4.15.3).
- **Langfuse 2026-11-16 removal: a migration item, not a watch item.** `langfuse` 4.15.3 in `agent/.venv`
  (`site-packages/` paths below) marks two families "removed on November 16, 2026" on Langfuse Cloud:
  v3 ingestion, replaced by OTel `POST /api/public/otel/v1/traces` (`langfuse/api/ingestion/client.py:32`),
  and the legacy `observations_v1`/`metrics_v1` reads (`langfuse/api/legacy/observations_v1/client.py:31`,
  `langfuse/api/legacy/metrics_v1/client.py:28`), replaced by `/api/public/v2/...`
  (`langfuse/_client/client.py:468-474`, which carries no date). Spans go over OTel
  (`langfuse/_client/span_processor.py:123`); the A3 trace scores do not. `finish_turn_trace` calls
  `score_trace` on every turn (`agent/app/telemetry.py:289,318-322`; three scores since 2026-09-19,
  `summary_model_kept` being the third) and the SDK routes it
  `LangfuseSpan.score_trace` -> `create_score` (`_client/span.py:468`) -> `add_score_task`
  (`_client/client.py:2051`, queued at `_client/resource_manager.py:527`) -> `ScoreIngestionConsumer`
  `batch_post` (`_task_manager/score_ingestion_consumer.py:183`) -> `POST /api/public/ingestion`
  (`_utils/request.py:59`), the family being removed; `grep -rn ingestion agent/app/` is empty only
  because the call lives in the SDK. Before that date: bump `langfuse` (`agent/pyproject.toml`,
  `agent/requirements.lock`) to a release whose score path no longer posts there (re-check
  `_utils/request.py` after the bump), confirm in the Langfuse UI that `verification_passed`,
  `turn_error` and `summary_model_kept` still land on a `copilot.turn` trace, and re-run the A1
  tracer probe.

- **Agent egress is unrestricted (SEC-MEDIUM-504), accepted for Week 1.**
  `main.tf`'s Cloud Firewall outbound rules allow all TCP/UDP/ICMP to
  `0.0.0.0/0`, and it operates on the Droplet's single public IP, not
  per-container — it cannot distinguish the agent container's traffic from
  any other. The Docker-network isolation is already correct (agent on
  `frontend` only, no route to `database`, `compose.yaml:205-206`); what's
  missing is restricting the agent's *outbound* reach to just Anthropic's
  API and `https://us.cloud.langfuse.com`. M4 step 6 (2026-09-18) decided
  to accept this risk for Week 1 rather than build it under grading-week
  time pressure — full reasoning and compensating controls in `AUDIT.md`
  section 9 (SEC-MEDIUM-504). **Week 2 task:** a `DOCKER-USER` iptables
  rule set, proven on a throwaway Droplet first, never built first on the
  graded host. A naive IP allowlist is the wrong mechanism — Anthropic and
  Langfuse sit behind anycast CDN IPs that can shift, so a static allowlist
  can silently start dropping legitimate traffic later with no code change
  to explain why. Prefer an SNI-filtering forward proxy (filters on the
  TLS SNI hostname, sent in cleartext before encryption, so it doesn't care
  which IP the name currently resolves to) — but that adds a new single
  point of failure of its own (the proxy itself), so it needs the same
  throwaway-Droplet proof-out before touching the live host.

## Deferred experiments (never without the protocol)

Protocol, every time: `evals/run.py --repeat 2 --label "baseline <sha>"`, the change,
`evals/run.py --repeat 2 --label "<experiment>"`, then `evals/compare.py <baseline>.json <candidate>.json`.
Blocking gates stay PASS; `--include-holdout` only for the final check; about $0.47 per single pass
(`4d2a9fd` run total; $1.32 for the `--repeat 3` release run; $0.51 at a4a5856) and 12 min
(`.gitlab-ci.yml:116-117`). On the demo host a run with fault cases can page Slack (Residuals).

1. **Deterministic note-versus-list conflict line in `pack_limitations`**
   (`agent/app/graph/nodes.py:403`). Today `note_vs_list` exists only as a
   prompt-instructed `conflict.kind` (`agent/app/model.py:44`) written into a free string
   (`agent/app/contracts/turns.py:47`); the deterministic conflict lines cover the status
   flag (`nodes.py:420-421`) and list-versus-prescriptions (`nodes.py:437-449`). Target:
   `CONF-NOTE-VS-LIST-N-001` stops depending on model wording. Still open: the case passed 3 of 3
   in the release run and 1 of 1 at `4d2a9fd`, on model recall alone.
2. **One planning round for follow-ups.** Done 2026-09-18 under the protocol (`e2cd633`):
   `max_plan_rounds: int = 1` (`agent/app/settings.py:61`, compose `COPILOT_MAX_PLAN_ROUNDS`
   default 1) gates the follow-up loop at `nodes.py:238`. Follow-up p95 28.9 s to 12.4 s, p95 over
   all turns 27.5 s to 18.0 s, cost per turn $0.0133 to $0.0103, 45/46 to 46/46
   (`docs/audit/evidence/performance/model-experiments-2026-09-18.md`; ADR-0004 amended). In
   a4a5856, before it, follow-up p95 was 29.7 s against 16.0 s for first turns; in the release run
   it is 11.2 s against 18.6 s.

Also adopted under the protocol on 2026-09-19, so not to be redone blind: follow-ups at `low`
effort (`f4f69ab`, `docs/audit/evidence/performance/followup-effort-2026-09-19.md`), the
physician-facing summary prompt (`2013fbd`,
`docs/audit/evidence/quality/narrative-quality-2026-09-19.md`) and the known-plan table
(`089ef2b`, `docs/audit/evidence/performance/known-plans-2026-09-19.md`, saving not yet measured
live). Tried and not adopted: routing the plan call to Haiku 4.5 (the model-experiments file). The
holdout miss `CONF-DUP-NAMES-C2-001` was deliberately not tuned on.

## Operational state, by file name only (never values)

- Droplet `/opt/agentforge/secrets/`: `mysql_root_password`, `mysql_password`,
  `openemr_admin_password`, `copilot_delegation_secret`, `demo_user_password` (generated
  by `runtime/start.sh:33-37`); `anthropic_api_key`, `anthropic_workspace_id`,
  `langfuse_public_key`, `langfuse_secret_key`, `slack_alert_webhook` (pushed by
  `infra/digitalocean/push-secrets.sh`; the webhook since 2026-09-20, ten file secrets in all);
  `/opt/agentforge/.env`; agent volume `/var/lib/copilot` (checkpoints, `alerts-state.json`).
- Operator `~/.config/agentforge/`: `do.env`, the five pushed secrets above,
  `gitlab_runner_token`, `gitlab_pat`, `git-credentials`, `backups/`, `tfstate/<date>/`;
  repo-local, git-ignored: `infra/digitalocean/terraform.tfvars`, `terraform.tfstate*`.
- DigitalOcean: Droplet snapshots `week1-final-2026-09-18` and `week1-final-2026-09-20` (the
  second predates the last alerts deploy); a CI runner Droplet beside the live one.
- GitLab project: masked CI variable `DEMO_PASSWORD`; `COPILOT_EVAL_BASE_URL`
  (`.gitlab-ci.yml:125-126`); protected `DEPLOY_SSH_PRIVATE_KEY` (file type) and `TLS_EMAIL` for
  `deploy:production` (`.gitlab-ci.yml:73-99`); runner #222.
- Rotation after grading: the dated checklist in `docs/deployment/digitalocean.md`
  ("After grading: credential rotation (dated checklist)" under `## Failure and Recovery`, landed in `58f4098`).
  The Slack alert webhook was added to it on 2026-09-20.
