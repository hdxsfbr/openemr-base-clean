# Week 2 Handoff (one-page stub, 2026-09-17)

The long form is Week 2 work (plan cut rule 4). Every claim was checked on 2026-09-17 against
the working tree (HEAD `66a6711` plus the M2 streams' uncommitted edits); a `file:line` is the
proof. No number below is one that does not exist yet.

## Read first, in this order

1. `README_AGENT_FORGE.md` (what is deployed, credentials by name, limits), then `SETUP.md`.
2. `ARCHITECTURE.md` and `docs/adr/` 0002 to 0007: settled decisions; do not re-litigate.
3. `AUDIT.md` section 9 Residual Risk, then `KEY_METRICS.md` (gates) and `evals/README.md`.
4. `agent/README.md`, `docs/operations/alerts.md`, `docs/deployment/digitalocean.md`.
5. `docs/FINAL_PUSH_PLAN.md` section 1: the eight invariants still apply in Week 2.

## Seams: what is code and what is prose

| Seam | Prose says | Code is | Evidence |
| --- | --- | --- | --- |
| `SourceRef.id` | `SourceId` is a URI open to `document:` and `guideline:` schemes | `id: int = Field(ge=0)`, `table: str`, `uuid: str \| None`; the URI is a separate `source_id` field. A page- or chunk-addressed source needs a new shape | `agent/app/contracts/common.py:57-64`; `ARCHITECTURE.md:444-446` |
| Reserved claim types | Week 2 adds `document_extract`, `guideline_reference` with fact types and verifier rules | A comment; no validator, no verifier rule | `agent/app/contracts/turns.py:26`; `common.py:15-16`; `ARCHITECTURE.md:441-443` |
| Source registry | "A registry keyed by URI prefix is the Week 2 extension point" | None. `grep -rn -i registry agent/app/` returns nothing; resolution is the flat `EvidencePack.records` dict | `agent/app/evidence.py:60`; `ARCHITECTURE.md:449-450, 515-516` |
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
  (`agent/pyproject.toml:19`). `agent/requirements.lock` (WS-AGENT A6, untracked at `66a6711`) pins
  `langchain==1.4.1` and `langfuse==4.15.4`, one patch ahead of the `agent/.venv` install (1.4.0, 4.15.3).
- **Langfuse 2026-11-16 removal: a watch item, not a migration.** `langfuse` 4.15.3 in `agent/.venv`
  (`site-packages/` paths below) marks two families "removed on November 16, 2026" on Langfuse Cloud:
  v3 ingestion, replaced by OTel `POST /api/public/otel/v1/traces` (`langfuse/api/ingestion/client.py:32`),
  and the legacy `observations_v1`/`metrics_v1` reads (`langfuse/api/legacy/observations_v1/client.py:31`,
  `langfuse/api/legacy/metrics_v1/client.py:28`), replaced by `/api/public/v2/...`
  (`langfuse/_client/client.py:468-474`, which carries no date). This project is on neither: the SDK
  exports spans to the OTel endpoint (`langfuse/_client/span_processor.py:123`) and
  `grep -rn 'ingestion\|observations_v1\|metrics_v1' agent/app/` is empty. Bump the SDK once before
  that date and re-run the A1 tracer probe.

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
  (a `docs/_pending/WS-CONTENT.md` delta until the M2 doc-apply pass lands it).
