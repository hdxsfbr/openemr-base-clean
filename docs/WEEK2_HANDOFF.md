# Week 2 Handoff (one-page stub, 2026-09-17)

The long form is Week 2 work (plan cut rule 4). Every claim was checked on 2026-09-17 against
the working tree (HEAD `0fba313`; M2 round 1 committed in `16a5d34..7197ed6`, re-checked in
round 2); a `file:line` is the proof. No number below is one that does not exist yet.

## Read first, in this order

1. `README_AGENT_FORGE.md` (what is deployed, credentials by name, limits), then `SETUP.md`.
2. `ARCHITECTURE.md` and `docs/adr/` 0002 to 0007: settled decisions; do not re-litigate.
3. `AUDIT.md` section 9 Residual Risk, then `KEY_METRICS.md` (gates) and `evals/README.md`.
4. `agent/README.md`, `docs/operations/alerts.md`, `docs/deployment/digitalocean.md`.
5. `docs/FINAL_PUSH_PLAN.md` section 1: the eight invariants still apply in Week 2.

## Seams: what is code and what is prose

| Seam | Prose says | Code is | Evidence |
| --- | --- | --- | --- |
| `SourceRef.id` | `SourceId` is a URI open to `document:` and `guideline:` schemes | `id: int = Field(ge=0)`, `table: str`, `uuid: str \| None`; the URI is a separate `source_id` field. A page- or chunk-addressed source needs a new shape | `agent/app/contracts/common.py:13-20` (the reserved `document:`/`guideline:` URI schemes and the `SourceId` pattern), `:57-64` (`SourceRef`); `ARCHITECTURE.md:446-448` |
| Reserved claim types | Week 2 adds `document_extract`, `guideline_reference` with fact types and verifier rules | A comment; no validator, no verifier rule | `agent/app/contracts/turns.py:26` (the only reserved-claim-type comment in `agent/`: `grep -rn document_extract agent/` returns that line alone); `ARCHITECTURE.md:443-445` |
| Source registry | "A registry keyed by URI prefix is the Week 2 extension point" | None. `grep -rn -i registry agent/app/` returns nothing; resolution is the flat `EvidencePack.records` dict | `agent/app/evidence.py:60`; `ARCHITECTURE.md:449-452, 531-533` |
| `actions/` | "a reserved, empty `actions/` class for writes" | No such directory in `agent/` or the module (`find ... -iname 'actions*'` is empty); `AGENTS.md` requires an ADR before any write | `ARCHITECTURE.md:299-303`; `ls module/src/Gateway/` shows six classes and one subdirectory, `Tools/`, no `actions/` |

## Eval baseline for `evals/compare.py`

Baseline: `evals/results/2026-09-17T024919Z-a4a5856.json` (45 cases, 44 passed, Golden
14/14, citations 177/177, p95 24.1 s, $0.0127 per model-backed turn; the miss is
`CONF-NOTE-VS-LIST-N-001`, model recall). Compare with
`agent/.venv/bin/python evals/compare.py evals/results/2026-09-17T024919Z-a4a5856.json evals/results/<candidate>.json`.
The M5 release run (`--repeat 3`) supersedes it once it exists; its file name is `<pending M5>`.

## Residuals (verified, not fixed)

- **Fault injection is on by default on the demo host.**
  `COPILOT_FAULT_INJECTION: ${COPILOT_FAULT_INJECTION:-1}`
  (`infra/digitalocean/runtime/compose.yaml:156`) overrides `fault_injection: bool = False`
  (`agent/app/settings.py:55`), so `X-Copilot-Fault` is honored on the graded deployment.
- **No checkpoint sweeper.** `AsyncSqliteSaver` is the checkpointer (`agent/app/main.py:43-48`); the
  only delete path is `drop_pack` for the 120 s evidence-pack TTL (`agent/app/state_store.py:17,38`).
  The 24 h purge is marked planned (`ARCHITECTURE.md:80-81`).
- **The daily halt counts input plus output only.** `Usage.total` is
  `input_tokens + output_tokens` (`agent/app/model.py:124-125`), added at
  `agent/app/graph/nodes.py:205,235`; cache reads (4,759 per turn in a4a5856) are not
  counted; the 2,000,000 limit (`settings.py:43`) is process-local (`agent/app/budget.py:38`).
- **`langchain` is present only for the Langfuse callback.** The single import is
  `from langfuse.langchain import CallbackHandler` (`agent/app/telemetry.py:74`); `langchain>=1.0`
  (`agent/pyproject.toml:19`). `agent/requirements.lock` (WS-AGENT A6, committed in `16a5d34`) pins
  `langchain==1.4.1` and `langfuse==4.15.4`, one patch ahead of the `agent/.venv` install (1.4.0, 4.15.3).
- **Langfuse 2026-11-16 removal: a migration item, not a watch item.** `langfuse` 4.15.3 in `agent/.venv`
  (`site-packages/` paths below) marks two families "removed on November 16, 2026" on Langfuse Cloud:
  v3 ingestion, replaced by OTel `POST /api/public/otel/v1/traces` (`langfuse/api/ingestion/client.py:32`),
  and the legacy `observations_v1`/`metrics_v1` reads (`langfuse/api/legacy/observations_v1/client.py:31`,
  `langfuse/api/legacy/metrics_v1/client.py:28`), replaced by `/api/public/v2/...`
  (`langfuse/_client/client.py:468-474`, which carries no date). Spans go over OTel
  (`langfuse/_client/span_processor.py:123`); the A3 trace scores do not. `finish_turn_trace` calls
  `score_trace` on every turn (`agent/app/telemetry.py:164,191-192`) and the SDK routes it
  `LangfuseSpan.score_trace` -> `create_score` (`_client/span.py:468`) -> `add_score_task`
  (`_client/client.py:2051`, queued at `_client/resource_manager.py:527`) -> `ScoreIngestionConsumer`
  `batch_post` (`_task_manager/score_ingestion_consumer.py:183`) -> `POST /api/public/ingestion`
  (`_utils/request.py:59`), the family being removed; `grep -rn ingestion agent/app/` is empty only
  because the call lives in the SDK. Before that date: bump `langfuse` (`agent/pyproject.toml`,
  `agent/requirements.lock`) to a release whose score path no longer posts there (re-check
  `_utils/request.py` after the bump), confirm in the Langfuse UI that `verification_passed` and
  `turn_error` still land on a `copilot.turn` trace, and re-run the A1 tracer probe.

- **Agent egress is unrestricted (SEC-MEDIUM-504), accepted for Week 1.**
  `main.tf`'s Cloud Firewall outbound rules allow all TCP/UDP/ICMP to
  `0.0.0.0/0`, and it operates on the Droplet's single public IP, not
  per-container — it cannot distinguish the agent container's traffic from
  any other. The Docker-network isolation is already correct (agent on
  `frontend` only, no route to `database`, `compose.yaml:167-168`); what's
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
Blocking gates stay PASS; `--include-holdout` only for the final check; about $0.51 (a4a5856) and 12 min (`.gitlab-ci.yml:71-72`) per pass.

1. **Deterministic note-versus-list conflict line in `pack_limitations`**
   (`agent/app/graph/nodes.py:319`). Today `note_vs_list` exists only as a
   prompt-instructed `conflict.kind` (`agent/app/model.py:43`) written into a free string
   (`agent/app/contracts/turns.py:47`); the deterministic conflict lines cover the status
   flag (`nodes.py:336-337`) and list-versus-prescriptions (`nodes.py:353-364`). Target:
   `CONF-NOTE-VS-LIST-N-001` stops depending on model wording.
2. **One planning round for follow-ups.** `max_plan_rounds: int = 3`
   (`agent/app/settings.py:38`) gates the follow-up loop at `nodes.py:159`. In a4a5856,
   follow-up p95 was 29.7 s against 16.0 s for first turns. Risk: fewer tools chained per
   follow-up; the multi-tool eval cases decide.

## Operational state, by file name only (never values)

- Droplet `/opt/agentforge/secrets/`: `mysql_root_password`, `mysql_password`,
  `openemr_admin_password`, `copilot_delegation_secret`, `demo_user_password` (generated
  by `runtime/start.sh:33-37`); `anthropic_api_key`, `anthropic_workspace_id`,
  `langfuse_public_key`, `langfuse_secret_key` (pushed by
  `infra/digitalocean/push-secrets.sh`); `/opt/agentforge/.env`; agent volume
  `/var/lib/copilot` (checkpoints, `alerts-state.json`).
- Operator `~/.config/agentforge/`: `do.env`, the four pushed secrets above,
  `gitlab_runner_token`, `gitlab_pat`, `git-credentials`, `backups/`, `tfstate/<date>/`;
  repo-local, git-ignored: `infra/digitalocean/terraform.tfvars`, `terraform.tfstate*`.
- GitLab project: masked CI variable `DEMO_PASSWORD`; `COPILOT_EVAL_BASE_URL`
  (`.gitlab-ci.yml:80-84`); runner #222.
- Rotation after grading: the dated checklist in `docs/deployment/digitalocean.md`
  ("After grading: credential rotation (dated checklist)" under `## Failure and Recovery`, landed in `58f4098`).
