"""Structured JSON logging. Never log request or response bodies, prompts, or records."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # "reason" is a bounded enum-like string (e.g. "http_400", "timeout",
        # "not_configured") set by openrouter_client.py's own failure logging --
        # never request/response content. Its absence from this whitelist meant
        # a real OpenRouter failure logged everything except the one field that
        # says why, which cost real diagnostic time chasing GitLab #55's schema
        # rejection (agent/app/openrouter_client.py:118,127).
        for key in ("correlation_id", "handoff_id", "path", "method", "status", "reason", "duration_ms", "component", "worker", "intent", "topic", "limitation", "candidate_count", "hit_count", "artifact_revision", "model_revision"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["error_class"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # uvicorn's access log would print raw paths with query strings; our middleware logs instead.
    logging.getLogger("uvicorn.access").disabled = True
