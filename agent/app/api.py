"""Co-pilot HTTP API v1 (ARCHITECTURE.md, "Agent HTTP API"). Authenticated by
the per-turn delegation token; the conversation id in the path must match the
token. Bodies are generic on error; specifics go to logs and the audit trail."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from . import __version__
from .contracts import (CONTRACT_VERSION, ErrorEnvelope, GuidelineEvidenceRequest, GuidelineSourceRequest,
    GuidelineEvidenceResponse, GuidelineRetrievalLimitation, GuidelineRetrievalLimitationCode,
    IntakeExtractionResult, LabExtractionRequest, TurnRequest, TurnResponse, Verification)
from .delegation import Delegation, DelegationError, verify
from .graph.state import PER_TURN_DEFAULTS
from .metrics import metrics
from .settings import settings
from .state_store import drop_token, put_token
from .telemetry import finish_turn_trace, tool_observation, trace_config, turn_trace
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


async def _reauthorize_chart_for_display(request: Request, token: str, correlation_id: str) -> bool:
    """Ask the module to recheck the live chart without retaining its record.

    The initial ticket proves only that the turn could start.  This last
    gateway read happens after worker/model work and before a guideline lane is
    displayed, so a user/site/patient/scope change turns into a typed lane
    limitation.  The response is intentionally discarded and never enters a
    model prompt, checkpoint, trace, or response body.
    """
    runtime = getattr(request.app.state, "runtime", None)
    gateway = getattr(runtime, "gateway", None)
    if gateway is None:
        return False
    try:
        result = await gateway.call("patient_context", {}, token, correlation_id)
    except Exception:
        return False
    return result.status.value == "ok"


def _guideline_authorization_limited(turn_id: str, correlation_id: str, worker) -> GuidelineEvidenceResponse:
    return GuidelineEvidenceResponse(
        turn_id=turn_id,
        correlation_id=correlation_id,
        status="limited",
        claims=[],
        limitations=[GuidelineRetrievalLimitation(
            code=GuidelineRetrievalLimitationCode.authorization_changed,
            detail="Guideline evidence is unavailable for this chart.",
        )],
        worker=worker,
    )


def _preview_confidence(result: Any) -> str:
    """Return a bounded summary, never an extracted value or source id."""
    extraction = getattr(result, "extraction", None)
    if extraction is None:
        return "unknown"
    analytes = getattr(extraction, "analytes", None)
    fields = []
    if analytes is not None:
        fields.append(getattr(extraction, "collection_date", None))
        for analyte in analytes:
            fields.extend(value for key, value in vars(analyte).items() if key != "entry_id" and value is not None)
    else:
        demographics = getattr(extraction, "demographics", None)
        if demographics is not None:
            fields.extend(value for value in vars(demographics).values() if value is not None)
        fields.extend([getattr(extraction, "chief_concern", None)])
        for group in (getattr(extraction, "medications", []), getattr(extraction, "allergies", []), getattr(extraction, "family_history", [])):
            for item in group:
                fields.extend(value for key, value in vars(item).items() if key != "entry_id" and value is not None)
    buckets = {field.evidence.confidence.value for field in fields if field is not None}
    for candidate in ("unknown", "low", "medium", "high"):
        if candidate in buckets:
            return candidate
    return "unknown"


def _preview_record_count(result: Any) -> int:
    extraction = getattr(result, "extraction", None)
    if extraction is None:
        return 0
    analytes = getattr(extraction, "analytes", None)
    if analytes is not None:
        return len(analytes)
    return len(getattr(extraction, "medications", [])) + len(getattr(extraction, "allergies", [])) + len(getattr(extraction, "family_history", []))


def _preview_document_type(result: Any) -> str:
    """Return the closed, worker-selected type without inspecting document text.

    The gateway's persisted discriminator selects the worker branch.  Result
    shape is only used here to emit its bounded operational label; it never
    accepts a client-supplied document type.
    """
    return "intake_form" if isinstance(result, IntakeExtractionResult) else "lab_pdf"


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
        "readiness": state.get("readiness") or {},
        "usage": {**(state.get("usage") or {}), **{f"{k}_ms": v for k, v in (state.get("timings_ms") or {}).items()}},
        "correlation_id": correlation_id,
        "contract_version": CONTRACT_VERSION,
    })


@router.post("/conversations/{conversation_id}/guideline-evidence")
async def post_guideline_evidence(conversation_id: str, request: Request, authorization: str | None = Header(default=None), x_copilot_token: str | None = Header(default=None)):
    """Run the explicit finite retrieval seam after a chart-bound ticket."""
    correlation_id = request.state.correlation_id
    auth = _authenticate(request, conversation_id, authorization, x_copilot_token)
    if isinstance(auth, JSONResponse):
        return auth
    try:
        body = GuidelineEvidenceRequest.model_validate(await request.json())
    except (ValueError, ValidationError):
        return _error(400, "invalid_request", "Invalid guideline evidence request.", correlation_id)
    service = getattr(request.app.state, "guideline_release", None)
    if service is None:
        return _error(503, "dependency_unavailable", "Guideline evidence is unavailable.", correlation_id)
    result = await asyncio.to_thread(service.invoke, conversation_id, auth.turn_id, correlation_id, body)
    if not await _reauthorize_chart_for_display(request, auth.raw, correlation_id):
        result = _guideline_authorization_limited(auth.turn_id, correlation_id, result.worker)
    else:
        result = await asyncio.to_thread(service.reverify, result, correlation_id)
    return JSONResponse(status_code=200, content=result.model_dump(mode="json"), headers={"X-Correlation-Id": correlation_id, "Cache-Control": "no-store"})


@router.post("/conversations/{conversation_id}/guideline-source")
async def post_guideline_source(conversation_id: str, request: Request, authorization: str | None = Header(default=None), x_copilot_token: str | None = Header(default=None)):
    """A source click must use a fresh module ticket and exact saved evidence."""
    correlation_id = request.state.correlation_id
    auth = _authenticate(request, conversation_id, authorization, x_copilot_token)
    if isinstance(auth, JSONResponse):
        return auth
    try:
        body = GuidelineSourceRequest.model_validate(await request.json())
    except (ValueError, ValidationError):
        return _error(400, "invalid_request", "Invalid guideline source request.", correlation_id)
    service = getattr(request.app.state, "guideline_release", None)
    source = None if service is None else await asyncio.to_thread(service.resolve, conversation_id, body.evidence_turn_id, body.source_id)
    if source is None:
        return _error(403, "unauthorized", "Source is unavailable.", correlation_id)
    return JSONResponse(status_code=200, content=source.model_dump(mode="json"), headers={"X-Correlation-Id": correlation_id, "Cache-Control": "no-store"})


@router.post("/conversations/{conversation_id}/lab-extractions")
async def post_lab_extraction(
    conversation_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_copilot_token: str | None = Header(default=None),
):
    """Run the bounded intake-extractor, not the conversation graph.

    The delegation token is verified before the worker can call the source
    gateway. The worker can read one source and return a verified preview only;
    it has no model, chat, or persistence capability.
    """
    correlation_id = request.state.correlation_id
    auth = _authenticate(request, conversation_id, authorization, x_copilot_token)
    if isinstance(auth, JSONResponse):
        return auth
    try:
        body = LabExtractionRequest.model_validate(await request.json())
    except (ValueError, ValidationError):
        return _error(400, "invalid_request", "Invalid document extraction request.", correlation_id)
    started = time.perf_counter()
    try:
        # A document preview has its own trace root because it is deliberately
        # outside the chat graph.  The only exported attributes are bounded
        # status/count/version metadata; source bytes and extraction values
        # never enter ordinary telemetry.
        # The conversation is an authorization/session identifier, not an
        # operational trace attribute for a document job. Correlation and the
        # worker's opaque handoff ID are sufficient to reconstruct this path.
        with turn_trace(correlation_id, "document_preview") as span:
            with tool_observation("intake_extractor", correlation_id) as observation:
                result = await asyncio.wait_for(
                    request.app.state.intake_extractor.extract(body.source_id, auth.raw, correlation_id, _fault(request)),
                    timeout=settings.model_timeout_seconds,
                )
                confidence = _preview_confidence(result)
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                observation.update(
                    level="ERROR" if result.status.value in {"unavailable", "failed"} else "DEFAULT",
                    status_message=result.status.value if result.status.value in {"unavailable", "failed"} else None,
                    metadata={
                        "status": result.status.value,
                        "handoff_id": result.handoff_id,
                        "contract_version": result.contract_version,
                        "model_version": "deterministic_parser_v1",
                        "document_type": _preview_document_type(result),
                        "timings_ms": {"extract": elapsed},
                        "usage": {"input_tokens": 0, "output_tokens": 0, "model_calls": 0, "cost_microusd": 0},
                        "record_count": _preview_record_count(result),
                        "extraction_confidence": confidence,
                        "retrieval_hit_count": 0,
                        "verification": "passed" if result.extraction else "not_run",
                        "eval_outcome": "not_run",
                    },
                )
    except PermissionError:
        metrics.denial("source_document")
        return _error(403, "unauthorized", "Request denied.", correlation_id)
    except asyncio.TimeoutError:
        # Keep the same typed no-content behavior as worker transport failure.
        from .intake_extractor import IntakeExtractor

        result = IntakeExtractor._unavailable(body.source_id, secrets.token_hex(16))
    metrics.extraction(_preview_document_type(result), result.status.value, (time.perf_counter() - started) * 1000, _preview_confidence(result))
    return JSONResponse(status_code=200, content=result.model_dump(mode="json"), headers={"X-Correlation-Id": correlation_id})


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
    return JSONResponse(content={"conversation_id": conversation_id, "closed": True, "correlation_id": correlation_id}, headers={"X-Correlation-Id": correlation_id})
