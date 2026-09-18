"""Turn outcome helpers shared by the API response, `/metrics`, and the trace
scores. ADR-0006 defines the verification outcomes and ADR-0007 puts the
verification pass/fail rate and the error rate in the dashboard minimum; one
computation here means the response, the counter, and the score cannot
disagree with each other."""

from __future__ import annotations

from typing import Any, Mapping

# Closed label set for copilot_verification_total{outcome} and the trace score.
VERIFICATION_OUTCOMES = ("not_run", "failed_closed", "partial", "passed")
# Turn statuses that count as an error for the `turn_error` score; `timeout` is
# the API's own status for a turn that exceeded its wall clock (never a graph
# status), and a missing status means the turn never rendered.
ERROR_STATUSES = frozenset({"failed", "timeout"})


def verification_outcome(state: Mapping[str, Any]) -> str:
    """`not_run` when the model never produced claims and nothing failed (a
    denial, or a deterministic-only path); `failed_closed` when narration
    failed on a turn that has no deterministic brief (anything but the UC-01
    first turn); `partial` when the verifier withheld a claim; else `passed`."""
    if state.get("raw_claims") is None and not state.get("narrate_error"):
        return "not_run"
    if state.get("narrate_error") and state.get("turn_type") != "uc01_first":
        return "failed_closed"
    return "partial" if state.get("rejected") else "passed"


def turn_error(state: Mapping[str, Any]) -> bool:
    """True for a failed or timed-out turn; a denial is not an error."""
    return str(state.get("status") or "failed") in ERROR_STATUSES
