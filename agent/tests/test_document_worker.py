"""Hard process boundary for the durable extraction lease."""

from __future__ import annotations

from threading import Event

from app.document_worker import LEASE_DEADLINE_SECONDS, run_isolated_once


class _FakeProcess:
    def __init__(self, *, exit_after_join: bool) -> None:
        self.exit_after_join = exit_after_join
        self.alive = True
        self.started = False
        self.terminated = False
        self.killed = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> None:
        if self.exit_after_join:
            self.alive = False

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False

    def kill(self) -> None:
        self.killed = True
        self.alive = False


def test_isolated_runner_terminates_a_hung_child_at_the_lease_deadline() -> None:
    process = _FakeProcess(exit_after_join=False)
    moments = iter((10.0, 10.0 + LEASE_DEADLINE_SECONDS + 0.1))

    exceeded = run_isolated_once(
        Event(),
        process_factory=lambda **_: process,
        monotonic=lambda: next(moments),
    )

    assert exceeded is True
    assert process.started is True
    assert process.terminated is True


def test_isolated_runner_leaves_a_completed_child_untouched() -> None:
    process = _FakeProcess(exit_after_join=True)

    exceeded = run_isolated_once(
        Event(),
        process_factory=lambda **_: process,
        monotonic=lambda: 10.0,
    )

    assert exceeded is False
    assert process.started is True
    assert process.terminated is False
