# Co-Pilot Agent Service

The separate service from ADR-0003 and ADR-0004: co-pilot HTTP API, LangGraph
turn graph, deterministic verifier, checkpointed state, telemetry that is
PHI-free by default. It holds no database credentials and no OpenEMR session.
Version 0.3.0 (`app/__init__.py` and `pyproject.toml`; `/health` and `/ready`
report it). Layout under `app/`:

- `api.py`: `POST /v1/conversations/{id}/turns` (JSON, or server-sent events
  `evidence`, `progress`, `claims`, `done`, `error` when `Accept:
  text/event-stream`), `GET` and `DELETE /v1/conversations/{id}`; delegation
  token in `X-Copilot-Token` (or `Authorization: Bearer`), 10 turns per
  minute per conversation (429 `rate_limited`). The token goes into the
  per-turn cache, never into graph state, so it is never checkpointed.
  `main.py` adds `/health` (liveness, version, uptime; the chart panel's
  `?panel=chart_open`, `brief_started` or `drawer_open` feeds the usage
  funnel counters, any other value is ignored), `/ready` (gateway ping,
  `models.retrieve`, a `GET /api/public/projects` probe of the Langfuse host,
  delegation secret, writable state dir; the three network checks run
  concurrently; cached for `ready_cache_seconds`), `/metrics`, the
  correlation-ID middleware, and structured JSON logs (`logging_setup.py`).
- `graph/`: the eight-node LangGraph turn graph (`build.py`: authorize,
  classify, plan, retrieve, narrate, verify, repair, render; `nodes.py`,
  `state.py`). `pack_limitations` in `nodes.py` emits the deterministic
  limitation lines for field-level absences; `narrate` is skipped when every
  clinical section is denied or unavailable. `retrieve` sends each batch of
  tools as one gateway request (`_call_batch`; a UC-01 first turn is two
  batches) and, when the records will go to the model, declares the provider
  and model id on it so the module writes its `copilot-model-disclosure`
  audit row before returning them. A blank plan parameter becomes null and
  one that still fails its contract is dropped (`_clean_params`); a tool the
  node answers itself (`fault_injected`, `invalid_params`) is still counted
  in `copilot_tool_calls_total`. `plan` skips its model call when the
  question is one of the agent's own suggestion constants (`KNOWN_PLANS`).
- `verifier.py`: source resolution, typed fact checks, domain rules, the
  `FORBIDDEN` advice/inference lexicon (widened to paraphrases 2026-09-16),
  the summary gate (dates and numbers must match a verified claim, reasons
  `ungrounded_date` and `ungrounded_number`; ADR-0006 decision 7 as amended
  2026-09-19), the deterministic fallback summary, and the suggestion filter.
- `contracts/`: Pydantic contracts (`CONTRACT_VERSION` 1.2.0); `python -m
  app.contracts.export` writes `contracts/schema/*.json`, `--check` fails on
  drift (run in CI).
- `model.py` (Anthropic SDK, circuit breaker, one retry on 429/5xx, strict
  tool schemas), `model_output.py` (the model-facing output schema: one
  malformed claim costs that claim, not the turn), `gateway_client.py` (the
  tool gateway client, single and batched; a failure becomes an `unavailable`
  envelope, never an empty one), `delegation.py` (per-turn delegation token
  check), `evidence.py` (evidence pack), `budget.py` (per-turn,
  per-conversation, and daily token budgets), `readiness.py`, `metrics.py`
  (Prometheus text: request, turn, denial, tool call with a bounded `reason`
  label, verification outcome, verifier rejection and token counters, the
  usage funnel `copilot_panel_events_total` and
  `copilot_conversation_first_turn_total` (`docs/operations/usage-funnel.md`),
  `copilot_in_flight` for every HTTP request and `copilot_turns_in_flight` for
  turns inside the graph or the SSE stream, the 5-minute
  `copilot_turn_latency_ms` p50/p95/p99 gauges; all in-process, so they reset
  on a restart), `turn_outcome.py` (the one verification-outcome computation
  shared by the response, the counter, and the trace scores), `alerts.py` and
  `alerts_cli.py` (the three PRD alerts over `/metrics`; `forbidden` is
  excluded from the tool-failure numerator, not the denominator; run as
  `python -m app.alerts`, see below), `telemetry.py` (Langfuse callback
  handler; the PHI mask is installed unless `COPILOT_TRACE_CONTENT` is on,
  ADR-0007 amendment 2026-09-19, and in masked mode an exception reaches the
  trace as its class name only; a tool-type observation per gateway call; the
  `verification_passed`, `turn_error` and `summary_model_kept` scores on the
  turn trace; every warning carrying the correlation id), `state_store.py`
  (SQLite checkpointer path, per-turn record and token caches).

`pytest` runs 145 tests under `tests/` as of 2026-09-20 (API, contracts,
graph, health, alerts, model output, the summary gate and fallback, telemetry
including the tracer-on branch of every observation against a fake `langfuse`
module, and `test_controls.py` for the checkpoint content, the circuit
breaker, and the LangSmith guard); the offline eval cases in
`evals/cases/` delegate to these pytest node ids (`evals/README.md`).

Dependencies are pinned. `pyproject.toml` carries the lower bounds;
`requirements.lock` is the exact set from the running container's
`pip freeze` (Python 3.12.14 in `python:3.12-slim`; the header records the
read-only command that generated it). `Dockerfile` and the CI agent jobs
install `-r requirements.lock` first and then the package with
`pip install --no-deps .`, so no runtime dependency can resolve newer on a
rebuild with `--pull`. The build backend (`setuptools>=69` in
`pyproject.toml`) is not in the lock: `pip freeze` omits it and pip's
isolated build environment fetches it fresh at image build time. After
changing a dependency, regenerate the lock from the container and commit
both files. A fresh venv from the lock passes the suite on host
Python 3.13 too, but the container's 3.12 is the version of record.

```bash
cd agent
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock && pip install --no-deps -e . && pip install -c requirements.lock '.[dev]'
pytest
uvicorn app.main:app --port 8080
```

Configuration is by environment (see `app/settings.py`; every field is read
as `COPILOT_<FIELD>`). Secrets are files, never environment values. The
settings, their code defaults, and what the demo Droplet's
`infra/digitalocean/runtime/compose.yaml` sets instead:

For the planned OpenRouter PDF extraction work (GitLab #50–#55), the
owner-provided local development key is at
`~/.config/agentforge/openrouter_api_key` on this machine. This path is not
yet wired into `app/settings.py` or Compose; #51 adds that integration. Read
the key from a file secret at runtime. Never print, log, or commit its value.

| Variable | Code default | Notes |
| --- | --- | --- |
| `COPILOT_GATEWAY_BASE_URL`, `COPILOT_GATEWAY_PING_URL` | the module gateway at `http://openemr:80/...` | internal network, never through the edge |
| `COPILOT_GATEWAY_TIMEOUT_SECONDS` | `2.0` | per gateway request, so per batch |
| `COPILOT_ANTHROPIC_API_KEY_FILE`, `COPILOT_ANTHROPIC_WORKSPACE_ID_FILE`, `COPILOT_DELEGATION_SECRET_FILE`, `COPILOT_LANGFUSE_PUBLIC_KEY_FILE`, `COPILOT_LANGFUSE_SECRET_KEY_FILE` | `/run/secrets/<name>` | file secrets; an absent file reads as not configured |
| `COPILOT_LANGFUSE_HOST` | `https://us.cloud.langfuse.com` | |
| `COPILOT_TRACE_CONTENT` | `false` (digest mask installed) | demo compose: `1`, full exchanges on the traces, synthetic patients only (ADR-0007 amendment 2026-09-19) |
| `COPILOT_MODEL_PROVIDER`, `COPILOT_MODEL_ID` | `anthropic`, `claude-sonnet-5` | both named in the module's `copilot-model-disclosure` row |
| `COPILOT_PLAN_MODEL_ID`, `COPILOT_PLAN_MODEL_SUPPORTS_EFFORT` | unset, `true` | plan-call override; 2026-09-18 experiment, not adopted |
| `COPILOT_EFFORT_FIRST_TURN`, `COPILOT_EFFORT_FOLLOWUP` | `low`, `low` | follow-up was `medium` until 2026-09-19; also the effort of the plan call and of a follow-up's repair round |
| `COPILOT_MODEL_TIMEOUT_SECONDS` | `30.0` | |
| `COPILOT_MAX_OUTPUT_TOKENS` | `3200` | narrate and repair cap; `1800` until 2026-09-19; thinking tokens count toward it |
| `COPILOT_MAX_PLAN_ROUNDS` | `1` | `3` until 2026-09-18 (ADR-0004 amendment; the bound is written inside decision 2, and the status line and code comments call it decision 5); demo compose also sets `1` |
| `COPILOT_MAX_TOOL_CALLS_PER_TURN` | `8` | |
| `COPILOT_TURN_WALL_CLOCK_SECONDS` | `45.0` | past it a non-streaming turn answers 504 `dependency_unavailable`; a repair round runs only if it can still finish inside it |
| `COPILOT_TOKENS_PER_TURN`, `COPILOT_TOKENS_PER_CONVERSATION`, `COPILOT_DAILY_TOKEN_HALT` | `20000`, `60000`, `2000000` | the daily count is in-process and keyed on the UTC day |
| `COPILOT_TURNS_PER_MINUTE` | `10` | per conversation |
| `COPILOT_EVIDENCE_PACK_MAX_CHARS` | `48000` | about 12K tokens |
| `COPILOT_CONVERSATION_IDLE_MINUTES` | `30` | declared, but nothing under `app/` reads it; the module retires idle conversations (`ConversationRepository::IDLE_MINUTES`) |
| `COPILOT_STATE_DIR` | `/var/lib/copilot` | checkpointer; on the Droplet the alerts job keeps its state file on the same volume |
| `COPILOT_READY_CACHE_SECONDS` | `30.0` | |
| `COPILOT_FAULT_INJECTION` | `false` | demo compose: `1`, honors `X-Copilot-Fault` (`model`, `tool:<name>`, `budget`) for the collection's failure examples and the eval fault cases |

The alerts job is the same package: `python -m app.alerts --url <metrics URL>
[--ready-url URL] [--state FILE] [--interval SECONDS] [--webhook URL]
[--webhook-file FILE] [--webhook-channel '#name'] [--timeout 10]`. One JSON
line per alert, a heartbeat line when none; one-shot exit codes 0, 2 (a page
fired), 1 (metrics not fetched). `--webhook-file` is read every cycle and an
absent or empty file falls back to `--webhook`, and with neither there is no
delivery; the Droplet's `alerts` service passes
`/run/secrets/slack_alert_webhook` (a Docker file secret, since a Slack
webhook URL is a credential) and `--webhook-channel`, which only legacy
custom-integration webhooks honor. The POST body is one JSON object: a
one-line `text` summary, the alert record's fields, and `channel` when set.
Thresholds and delivery: `docs/operations/alerts.md`; the 2026-09-20 Slack
delivery evidence:
`docs/audit/evidence/observability/alerts-slack-2026-09-20.log`.

For a local run against the dev stack, point the agent at the same files the
deployment uses (`~/.config/agentforge/`) and at the dev stack's gateway:

```bash
COPILOT_GATEWAY_BASE_URL=http://localhost:8300/interface/modules/custom_modules/oe-module-copilot/public/gateway \
COPILOT_GATEWAY_PING_URL=http://localhost:8300/interface/modules/custom_modules/oe-module-copilot/public/gateway/ping.php \
COPILOT_ANTHROPIC_API_KEY_FILE=$HOME/.config/agentforge/anthropic_api_key \
COPILOT_LANGFUSE_PUBLIC_KEY_FILE=$HOME/.config/agentforge/langfuse_public_key \
COPILOT_LANGFUSE_SECRET_KEY_FILE=$HOME/.config/agentforge/langfuse_secret_key \
COPILOT_DELEGATION_SECRET_FILE=/tmp/copilot-dev-delegation-secret \
COPILOT_STATE_DIR=/tmp/copilot-dev-state COPILOT_FAULT_INJECTION=1 \
uvicorn app.main:app --port 18080
```

The dev delegation secret is the one the module generated at
`sites/default/documents/copilot/delegation_secret` inside the dev container;
copy it to the path above.
