"""Process the internal, leased reviewed-document extraction queue.

This process has no HTTP listener and accepts no browser requests. It is run as
the separate ``extractor`` Compose service; every job originates at the module's
HMAC-authenticated internal gateway.
"""

from __future__ import annotations

import logging
import signal
from threading import Event

from .document_runtime import ProductionAdapterError, build_document_queue_runner
from .logging_setup import configure_logging


def main() -> int:
    configure_logging()
    log = logging.getLogger("copilot.document_worker")
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        runner = build_document_queue_runner()
    except ProductionAdapterError as exc:
        # Missing credentials or local dependencies never permit a fallback
        # path for a patient document.
        log.error("document worker unavailable: %s", str(exc), extra={"component": "extractor"})
        return 1
    runner.run_forever(stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
