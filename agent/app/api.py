"""Co-pilot HTTP API v1 (ARCHITECTURE.md, "Agent HTTP API"). Authenticated by
the per-turn delegation token; the conversation id in the path must match the
token. Bodies are generic on error; specifics go to logs and the audit trail."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from . import __version__
from .contracts import CONTRACT_VERSION, ErrorEnvelope, TurnRequest, TurnResponse, Verification
from .delegation import Delegation, DelegationError, verify
from .graph.state import PER_TURN_DEFAULTS
from .metrics import metrics
from .settings import settings
from .state_store import drop_token, mark_conversation_closed, put_token
from .telemetry import finish_turn_trace, trace_config, turn_trace
from .turn_outcome import verification_outcome

router = APIRouter(prefix="/v1")

_turn_times: dict[str, deque[float]] = defaultdict(deque)


def _error(status: int, code: str, message: str, correlation_id: str) -> JSONResponse:
    body = ErrorEnvelope(code=code, message=message, correlation_id=correlation_id).model_dump(mode="json")
    return JSONResponse(status_code=status, content=body, headers={"X-Correlation-Id": correlation_id})


def _token_from(request: Request, authorization: str | None, x_copilot_token: str | None) -> str | None:
    if x_copilot_token:
        return x_copilot_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _authenticate(request: Request, conversation_id: str, authorization: str | None, x_copilot_token: str | None) -> Delegation | JSONResponse:
    correlation_id = request.state.correlation_id
    token = _token_from(request, authorization, x_copilot_token)
    if not token:
        metrics.denial("missing_token")
        return _error(401, "unauthorized", "A delegation token is required.", correlation_id)
    try:
        delegation = verify(token)
    except DelegationError as exc:
        metrics.denial(exc.reason)
        return _error(403, "unauthorized", "Request denied.", correlation_id)
    if delegation.conversation_id != conversation_id:
        metrics.denial("conversation_mismatch")
        return _error(403, "unauthorized", "Request denied.", correlation_id)
    return delegation


def _rate_limited(conversation_id: str) -> bool:
    now = time.time()
    q = _turn_times[conversation_id]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= settings.turns_per_minute:
        return True
    q.append(now)
    return False


def _fault(request: Request) -> str | None:
    if not settings.fault_injection:
        return None
    value = request.headers.get("X-Copilot-Fault", "").strip().lower()
    return value or None


def _turn_input(delegation: Delegation, req: TurnRequest, correlation_id: str, fault: str | None) -> dict[str, Any]:
    state = dict(PER_TURN_DEFAULTS)
    # The delegation token is deliberately absent: graph state is checkpointed after every
    # step (ADR-0005), so the token goes into the per-turn cache (`put_token`) instead.
    state.update({
        "conversation_id": delegation.conversation_id,
        "turn_id": delegation.turn_id,
        "correlation_id": correlation_id,
        "question": req.message,
        "fault": fault,
    })
    return state


def _count_first_turn(state: dict[str, Any]) -> None:
    """The funnel's last stage: what kind of question opened this conversation.
    Render appends one history entry per answered turn, so one entry means first."""
    if len(state.get("history") or []) == 1:
        metrics.conversation_first_turn(state.get("turn_type"))


def _response_from_state(state: dict[str, Any], correlation_id: str) -> TurnResponse:
    return TurnResponse.model_validate({
        "turn_id": state["turn_id"],
        "conversation_id": state["conversation_id"],
        "turn_type": state.get("turn_type") or "followup",
        "status": state.get("status") or "failed",
        "reference_encounter_source_id": state.get("reference_encounter_source_id"),
        "window_since": state.get("window_since"),
        "evidence": state.get("evidence") or [],
        "claims": state.get("accepted") or [],
        "sources": state.get("sources") or [],
        "limitations": state.get("limitations") or [],
        "withheld_count": len(state.get("rejected") or []) if not state.get("narrate_error") else 0,
        "summary": state.get("summary") or "",
        "summary_basis": state.get("summary_basis") or "none",
        "suggestions": state.get("suggestions") or [],
        "answered_at": state.get("answered_at"),
        "verification": Verification(
            outcome=verification_outcome(state),
            rules_applied=state.get("rules") or [],
            rejected=state.get("rejected") or [],
            repair_attempted=bool(state.get("repair_attempted")),
        ).model_dump(mode="json"),
        "usage": {**(state.get("usage") or {}), **{f"{k}_ms": v for k, v in (state.get("timings_ms") or {}).items()}},
        "correlation_id": correlation_id,
        "contract_version": CONTRACT_VERSION,
    })


@router.post("/conversations/{conversation_id}/turns")
async def post_turn(
    conversation_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_copilot_token: str | None = Header(default=None),
    accept: str | None = Header(default=None),
):
    correlation_id = request.state.correlation_id
    auth = _authenticate(request, conversation_id, authorization, x_copilot_token)
    if isinstance(auth, JSONResponse):
        return auth
    try:
        req = TurnRequest.model_validate(await request.json())
    except (ValueError, ValidationError):
        return _error(400, "invalid_request", "Invalid turn request.", correlation_id)
    if req.correlation_id:
        correlation_id = req.correlation_id
        request.state.correlation_id = correlation_id
    if _rate_limited(conversation_id):
        metrics.denial("rate_limited")
        return _error(429, "rate_limited", "Too many turns; wait a moment.", correlation_id)

    graph = request.app.state.graph
    config: dict[str, Any] = {"configurable": {"thread_id": conversation_id}}
    config.update(trace_config(correlation_id, conversation_id, "turn"))
    turn_input = _turn_input(auth, req, correlation_id, _fault(request))
    started = time.perf_counter()
    stream = req.stream or (accept or "").startswith("text/event-stream")

    if not stream:
        put_token(auth.turn_id, auth.raw)
        metrics.turn_started()
        try:
            with turn_trace(correlation_id, conversation_id) as span:
                try:
                    final = await asyncio.wait_for(graph.ainvoke(turn_input, config), timeout=settings.turn_wall_clock_seconds)
                except asyncio.TimeoutError:
                    metrics.turn("failed", (time.perf_counter() - started) * 1000, {})
                    finish_turn_trace(span, {"status": "timeout"})
                    return _error(504, "dependency_unavailable", "The turn exceeded its time budget.", correlation_id)
                except Exception:
                    # The middleware answers 500 `internal_error`; the trace still records the error.
                    metrics.turn("failed", (time.perf_counter() - started) * 1000, {})
                    finish_turn_trace(span, {"status": "failed"})
                    raise
                finish_turn_trace(span, final)
        finally:
            metrics.turn_finished()
            drop_token(auth.turn_id)
        response = _response_from_state(final, correlation_id)
        metrics.turn(response.status, (time.perf_counter() - started) * 1000, dict(final.get("usage") or {}), final.get("rejected") or [], verification=response.verification.outcome)
        _count_first_turn(final)
        status_code = 403 if response.status == "denied" else 200
        return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"), headers={"X-Correlation-Id": correlation_id})

    async def events():
        final_state: dict[str, Any] = dict(turn_input)
        put_token(auth.turn_id, auth.raw)
        metrics.turn_started()
        try:
            with turn_trace(correlation_id, conversation_id) as span:
                try:
                    async for update in graph.astream(turn_input, config, stream_mode="updates"):
                        for node, delta in update.items():
                            final_state.update(delta or {})
                            if node == "retrieve":
                                yield f"event: evidence\ndata: {json.dumps({'evidence': delta.get('evidence', []), 'window_since': delta.get('window_since'), 'correlation_id': correlation_id})}\n\n"
                            # Node completions drive the panel's progress line; no claim text leaves before the verifier.
                            yield f"event: progress\ndata: {json.dumps({'node': node, 'next': (delta or {}).get('route', '')})}\n\n"
                except Exception:
                    finish_turn_trace(span, {"status": "failed"})
                    raise
                finish_turn_trace(span, final_state)
            response = _response_from_state(final_state, correlation_id)
            metrics.turn(response.status, (time.perf_counter() - started) * 1000, dict(final_state.get("usage") or {}), final_state.get("rejected") or [], verification=response.verification.outcome)
            _count_first_turn(final_state)
            yield f"event: claims\ndata: {json.dumps(response.model_dump(mode='json'))}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': response.status})}\n\n"
        except Exception as exc:  # noqa: BLE001
            metrics.turn("failed", (time.perf_counter() - started) * 1000, {})
            yield f"event: error\ndata: {json.dumps({'code': 'internal_error', 'message': 'Turn failed.', 'error_class': exc.__class__.__name__, 'correlation_id': correlation_id})}\n\n"
        finally:
            metrics.turn_finished()
            drop_token(auth.turn_id)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Correlation-Id": correlation_id, "Cache-Control": "no-store"})


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request, authorization: str | None = Header(default=None), x_copilot_token: str | None = Header(default=None)):
    correlation_id = request.state.correlation_id
    auth = _authenticate(request, conversation_id, authorization, x_copilot_token)
    if isinstance(auth, JSONResponse):
        return auth
    snapshot = await request.app.state.graph.aget_state({"configurable": {"thread_id": conversation_id}})
    values = snapshot.values if snapshot else {}
    body = {
        "conversation_id": conversation_id,
        "closed": bool(values.get("closed")),
        "turns": values.get("history") or [],
        "conversation_tokens": values.get("conversation_tokens") or 0,
        "correlation_id": correlation_id,
        "agent_version": __version__,
    }
    return JSONResponse(content=body, headers={"X-Correlation-Id": correlation_id})


@router.delete("/conversations/{conversation_id}")
async def end_conversation(conversation_id: str, request: Request, authorization: str | None = Header(default=None), x_copilot_token: str | None = Header(default=None)):
    correlation_id = request.state.correlation_id
    auth = _authenticate(request, conversation_id, authorization, x_copilot_token)
    if isinstance(auth, JSONResponse):
        return auth
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": conversation_id}}
    await graph.aupdate_state(config, {"closed": True})
    retention_path = getattr(request.app.state, "checkpoint_path", None)
    if retention_path is not None:
        mark_conversation_closed(retention_path, conversation_id, closed_at=datetime.now(timezone.utc))
    return JSONResponse(content={"conversation_id": conversation_id, "closed": True, "correlation_id": correlation_id}, headers={"X-Correlation-Id": correlation_id})
