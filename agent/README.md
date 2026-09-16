# Co-Pilot Agent Service

The separate service from ADR-0003 and ADR-0004: co-pilot HTTP API, LangGraph
turn graph, deterministic verifier, checkpointed state, PHI-free telemetry.
It holds no database credentials and no OpenEMR session. Layout under `app/`:

- `api.py`: `POST /v1/conversations/{id}/turns` (JSON, or server-sent events
  `evidence`, `progress`, `claims`, `done`, `error` when `Accept:
  text/event-stream`), `GET` and `DELETE /v1/conversations/{id}`; delegation
  token in `X-Copilot-Token` (or `Authorization: Bearer`), 10 turns per
  minute per conversation. `main.py` adds `/health`, `/ready`, `/metrics`,
  the correlation-ID middleware, and structured JSON logs (`logging_setup.py`).
- `graph/`: the eight-node LangGraph turn graph (`build.py`: authorize,
  classify, plan, retrieve, narrate, verify, repair, render; `nodes.py`,
  `state.py`). `pack_limitations` in `nodes.py` emits the deterministic
  limitation lines for field-level absences; `narrate` is skipped when every
  clinical section is denied or unavailable.
- `verifier.py`: source resolution, typed fact checks, domain rules, the
  `FORBIDDEN` advice/inference lexicon (widened to paraphrases 2026-09-16),
  the summary gate, and the suggestion filter.
- `contracts/`: Pydantic contracts (`CONTRACT_VERSION` 1.2.0); `python -m
  app.contracts.export` writes `contracts/schema/*.json`, `--check` fails on
  drift (run in CI).
- `model.py` (Anthropic SDK, circuit breaker, one retry on 429/5xx, strict
  tool schemas), `evidence.py` (evidence pack), `budget.py` (per-turn,
  per-conversation, and daily token budgets), `readiness.py`, `metrics.py`
  (Prometheus text), `alerts.py` and `alerts_cli.py` (the three PRD alerts
  over `/metrics`), `telemetry.py` (Langfuse callback handler with the PHI
  mask, a tool-type observation per gateway call), `state_store.py` (SQLite
  checkpointer path, per-turn record cache).

`pytest` runs 60 tests under `tests/` (API, contracts, graph, health,
alerts); the offline eval cases in `evals/cases/` delegate to these pytest
node ids (`evals/README.md`).

```bash
cd agent
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
uvicorn app.main:app --port 8080
```

Configuration is by environment (see `app/settings.py`). Secrets are files,
never environment values. For a local run against the dev stack, point the
agent at the same files the deployment uses (`~/.config/agentforge/`) and at
the dev stack's gateway:

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
