# Co-Pilot Agent Service

The separate service from ADR-0003 and ADR-0004: co-pilot HTTP API, LangGraph
turn graph, deterministic verifier, checkpointed state, PHI-free telemetry.
This is the skeleton: `/health`, `/ready`, correlation-ID middleware, and
structured JSON logs. It holds no database credentials and no OpenEMR session.

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
