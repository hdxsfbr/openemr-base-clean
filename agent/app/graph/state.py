"""Graph state. Per-turn keys are reset by the API on every invocation; the
conversation keys (history, conversation_tokens) persist in the checkpoint.
Raw tool records never enter this state (ADR-0005)."""

from __future__ import annotations

from typing import Any, TypedDict


class TurnState(TypedDict, total=False):
    # per turn
    conversation_id: str
    turn_id: str
    correlation_id: str
    token: str
    question: str
    turn_type: str
    fault: str | None
    denied: dict[str, str] | None
    budget_limit: str | None
    plan_round: int
    tool_calls: list[list[Any]]
    pending_calls: list[list[Any]]
    reference_encounter_source_id: str | None
    window_since: str | None
    evidence: list[dict[str, Any]]
    raw_claims: list[dict[str, Any]] | None
    raw_summary: str
    raw_suggestions: list[str]
    summary: str
    summary_basis: str
    suggestions: list[str]
    narrate_error: str | None
    accepted: list[dict[str, Any]]
    rejected: list[dict[str, str]]
    rules: list[str]
    repair_attempted: bool
    limitations: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    usage: dict[str, int | float]
    timings_ms: dict[str, float]
    started_at: float
    status: str
    route: str
    # conversation (checkpointed)
    history: list[dict[str, Any]]
    conversation_tokens: int
    closed: bool


PER_TURN_DEFAULTS: dict[str, Any] = {
    "turn_type": "followup",
    "fault": None,
    "denied": None,
    "budget_limit": None,
    "plan_round": 0,
    "tool_calls": [],
    "pending_calls": [],
    "reference_encounter_source_id": None,
    "window_since": None,
    "evidence": [],
    "raw_claims": None,
    "raw_summary": "",
    "raw_suggestions": [],
    "summary": "",
    "summary_basis": "none",
    "suggestions": [],
    "narrate_error": None,
    "accepted": [],
    "rejected": [],
    "rules": [],
    "repair_attempted": False,
    "limitations": [],
    "sources": [],
    "usage": {},
    "timings_ms": {},
    "started_at": 0.0,
    "status": "complete",
    "route": "",
}
