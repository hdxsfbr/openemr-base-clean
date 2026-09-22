"""Process the internal, leased reviewed-document extraction queue.

This process has no HTTP listener and accepts no browser requests. It is run as
the separate ``extractor`` Compose service; every job originates at the module's
HMAC-authenticated internal gateway.
"""

from __future__ import annotations

import logging
import multiprocessing
import signal
import time
from threading import Event
from typing import Callable

from .document_runtime import ProductionAdapterError, build_document_queue_runner
from .logging_setup import configure_logging


LEASE_DEADLINE_SECONDS = 95.0


def _run_once() -> None:
    """Run one lease in a disposable child process.

    The child owns all source bytes, OCR buffers, and provider connections. A
    hard stop therefore also stops a hung native process or client thread.
    """
    try:
        runner = build_document_queue_runner()
    except ProductionAdapterError as exc:
        log = logging.getLogger("copilot.document_worker")
        log.error("document worker unavailable: %s", str(exc), extra={"component": "extractor"})
        return
    runner.run_once()


def run_isolated_once(
    stop: Event,
    *,
    process_factory: Callable[..., multiprocessing.Process] = multiprocessing.Process,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    """Return whether the child exceeded the module's 95-second lease wall."""
    process = process_factory(target=_run_once, name="copilot-document-lease")
    process.start()
    started = monotonic()
    while process.is_alive():
        if stop.is_set():
            process.terminate()
            process.join(timeout=1.0)
            return False
        remaining = LEASE_DEADLINE_SECONDS - (monotonic() - started)
        if remaining <= 0:
            process.terminate()
            process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
            return True
        process.join(timeout=min(0.25, remaining))
    return False


def main() -> int:
    configure_logging()
    log = logging.getLogger("copilot.document_worker")
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        timed_out = run_isolated_once(stop)
        if timed_out:
            log.warning("document worker lease exceeded", extra={"component": "extractor"})
        if not stop.is_set():
            stop.wait(0.25 if timed_out else 1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
