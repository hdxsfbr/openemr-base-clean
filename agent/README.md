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
never environment values: `ANTHROPIC_API_KEY_FILE`, `COPILOT_DELEGATION_SECRET_FILE`.
