"""Graph nodes: plain functions over TurnState. Every routing decision is
returned in state (`route`) so it appears in the trace."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from pydantic import ValidationError

from .. import budget
from ..contracts import Claim, ClaimType, LabsParams, NotesParams, ToolResponse, WindowParams
from ..evidence import EvidencePack, _day, add_responses, build_uc01_window, derive_changes, render
from ..gateway_client import GatewayPort, unavailable
from ..model import ModelError, ModelPort, NarrateResult, PlanResult, Usage
from ..settings import settings
from ..state_store import get_pack, put_pack
from ..verifier import verify
from .state import TurnState

UC01_PATTERNS = [r"what (has )?changed", r"changes? since", r"since (the |my )?last visit", r"pre-?visit brief", r"^brief$"]
PARAM_MODELS = {"clinical_notes": NotesParams, "lab_results": LabsParams}
UC01_TOOLS = ("patient_context", "problems", "medications", "allergies", "lab_results", "clinical_notes")


@dataclass
class Runtime:
    gateway: GatewayPort
    model: ModelPort | None
    today: Callable[[], date] = date.today


def _usage_dict(u: Usage) -> dict[str, int | float]:
    return {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens, "cache_read_tokens": u.cache_read_tokens, "model_calls": u.model_calls}


def _add_usage(state: TurnState, u: Usage) -> dict[str, int | float]:
    cur = dict(state.get("usage") or {})
    for k, v in _usage_dict(u).items():
        cur[k] = cur.get(k, 0) + v
    return cur


def _turn_tokens(state: TurnState) -> int:
    u = state.get("usage") or {}
    return int(u.get("input_tokens", 0) + u.get("output_tokens", 0))


# ---------------------------------------------------------------- nodes


def make_nodes(rt: Runtime) -> dict[str, Callable]:
    async def authorize(state: TurnState) -> dict[str, Any]:
        if state.get("closed"):
            return {"denied": {"code": "conversation_closed", "message": "This conversation is closed."}, "status": "denied", "route": "render"}
        limit = budget.check(0, int(state.get("conversation_tokens") or 0))
        if state.get("fault") == "budget":
            limit = "model_budget_exhausted"
        return {"budget_limit": limit, "route": "classify"}

    async def classify(state: TurnState) -> dict[str, Any]:
        q = state["question"].strip().lower()
        first = not (state.get("history") or [])
        canonical = any(re.search(p, q) for p in UC01_PATTERNS)
        turn_type = "uc01_first" if (first or canonical) and (canonical or len(q) < 80) else "followup"
        if first and not canonical:
            turn_type = "followup"
        return {"turn_type": turn_type, "route": "retrieve" if turn_type == "uc01_first" else "plan"}

    async def _call(tool: str, params: dict[str, Any], state: TurnState) -> ToolResponse:
        if state.get("fault") == f"tool:{tool}":
            return unavailable(tool, "fault_injected", state["correlation_id"])
        model = PARAM_MODELS.get(tool, WindowParams)
        try:
            clean = model.model_validate(params).model_dump(mode="json", exclude_none=True)
        except ValidationError:
            return unavailable(tool, "invalid_params", state["correlation_id"])
        return await rt.gateway.call(tool, clean, state["token"], state["correlation_id"])

    async def retrieve(state: TurnState) -> dict[str, Any]:
        pack = get_pack(state["turn_id"]) or EvidencePack()
        calls: list[list[Any]] = list(state.get("tool_calls") or [])
        if state["turn_type"] == "uc01_first" and not calls:
            encounters = await _call("encounters", {}, state)
            calls.append(["encounters", {}])
            ref, since = build_uc01_window(encounters, rt.today())
            pack.reference_encounter = ref
            pack.window_since = since
            add_responses(pack, [encounters])
            params = {"since": since.isoformat()} if since else {}
            sem = asyncio.Semaphore(settings.tool_concurrency)

            async def one(tool: str) -> ToolResponse:
                async with sem:
                    return await _call(tool, {} if tool == "patient_context" else params, state)

            responses = await asyncio.gather(*(one(t) for t in UC01_TOOLS))
            calls.extend([t, {} if t == "patient_context" else params] for t in UC01_TOOLS)
            add_responses(pack, list(responses))
        else:
            pending = list(state.get("pending_calls") or [])
            room = settings.max_tool_calls_per_turn - len(calls)
            pending = pending[: max(0, room)]
            if pack.window_since is None and (state.get("window_since")):
                pack.window_since = date.fromisoformat(state["window_since"])
            responses = await asyncio.gather(*(_call(t, p, state) for t, p in pending))
            calls.extend([t, p] for t, p in pending)
            add_responses(pack, list(responses))
        derive_changes(pack)
        render(pack, settings.evidence_pack_max_chars)
        put_pack(state["turn_id"], pack)
        more_plans = state["turn_type"] == "followup" and (state.get("plan_round") or 0) < settings.max_plan_rounds and len(calls) < settings.max_tool_calls_per_turn and bool(state.get("pending_calls"))
        return {
            "tool_calls": calls,
            "pending_calls": [],
            "evidence": pack.evidence_summary(),
            "reference_encounter_source_id": pack.reference_encounter.source.source_id if pack.reference_encounter else None,
            "window_since": pack.window_since.isoformat() if pack.window_since else None,
            "route": "plan" if more_plans else "narrate",
        }

    async def plan(state: TurnState) -> dict[str, Any]:
        pack = get_pack(state["turn_id"]) or EvidencePack()
        if pack.window_since is None and state.get("window_since"):
            pack.window_since = date.fromisoformat(state["window_since"])
        round_no = (state.get("plan_round") or 0) + 1
        limit = state.get("budget_limit") or budget.check(_turn_tokens(state), int(state.get("conversation_tokens") or 0))
        if rt.model is None or limit or state.get("fault") == "model":
            return {"plan_round": round_no, "pending_calls": [], "narrate_error": "model_unavailable" if not limit else limit, "route": "narrate"}
        prior = [(c[0], c[1]) for c in (state.get("tool_calls") or [])]
        try:
            result: PlanResult = await rt.model.plan(state["question"], pack.text, prior)
        except ModelError as exc:
            return {"plan_round": round_no, "pending_calls": [], "narrate_error": exc.kind, "usage": state.get("usage") or {}, "route": "narrate"}
        allowed = {t for t in UC01_TOOLS} | {"encounters"}
        pending = [[t, p] for t, p in result.tool_calls if t in allowed][: settings.max_tool_calls_per_turn]
        return {"plan_round": round_no, "pending_calls": pending, "usage": _add_usage(state, result.usage), "route": "retrieve" if pending else "narrate"}

    async def narrate(state: TurnState) -> dict[str, Any]:
        if state.get("narrate_error"):
            return {"raw_claims": None, "route": "render"}
        limit = state.get("budget_limit") or budget.check(_turn_tokens(state), int(state.get("conversation_tokens") or 0))
        if limit:
            return {"raw_claims": None, "narrate_error": limit, "route": "render"}
        if state.get("fault") == "model" or rt.model is None:
            return {"raw_claims": None, "narrate_error": "fault_injected" if state.get("fault") == "model" else "model_unavailable", "route": "render"}
        pack = get_pack(state["turn_id"])
        effort = settings.effort_first_turn if state["turn_type"] == "uc01_first" else settings.effort_followup
        try:
            result: NarrateResult = await rt.model.narrate(state["question"], pack.text if pack else "", effort)
        except ModelError as exc:
            return {"raw_claims": None, "narrate_error": exc.kind, "route": "render"}
        budget.daily.add(result.usage.total)
        if result.claims is None:
            return {"raw_claims": None, "narrate_error": result.error, "usage": _add_usage(state, result.usage), "route": "render"}
        return {"raw_claims": [c.model_dump(mode="json") for c in result.claims.claims], "usage": _add_usage(state, result.usage), "route": "verify"}

    async def verify_node(state: TurnState) -> dict[str, Any]:
        pack = get_pack(state["turn_id"]) or EvidencePack()
        claims = [Claim.model_validate(c) for c in (state.get("raw_claims") or [])]
        result = verify(claims, pack)
        # After a repair, a first-round rejection that the repair did not resurrect stays withheld.
        rejected = list(result.rejected)
        if state.get("repair_attempted"):
            accepted_ids = {c.id for c in result.accepted}
            seen = {(r["claim_id"], r["rule"]) for r in rejected}
            for prior in state.get("rejected") or []:
                if prior["claim_id"] not in accepted_ids and (prior["claim_id"], prior["rule"]) not in seen:
                    rejected.append(prior)
        route = "repair" if result.rejected and not state.get("repair_attempted") and rt.model is not None else "render"
        return {"accepted": [c.model_dump(mode="json") for c in result.accepted], "rejected": rejected, "rules": result.rules_applied, "route": route}

    async def repair(state: TurnState) -> dict[str, Any]:
        pack = get_pack(state["turn_id"])
        effort = settings.effort_first_turn if state["turn_type"] == "uc01_first" else settings.effort_followup
        try:
            result = await rt.model.narrate(state["question"], pack.text if pack else "", effort, rejections=state.get("rejected") or [])  # type: ignore[union-attr]
        except ModelError:
            return {"repair_attempted": True, "route": "render"}
        budget.daily.add(result.usage.total)
        if result.claims is None:
            return {"repair_attempted": True, "usage": _add_usage(state, result.usage), "route": "render"}
        return {"repair_attempted": True, "raw_claims": [c.model_dump(mode="json") for c in result.claims.claims], "usage": _add_usage(state, result.usage), "route": "verify"}

    async def render_node(state: TurnState) -> dict[str, Any]:
        started = time.perf_counter()
        if state.get("denied"):
            return {"status": "denied", "limitations": [], "route": "end"}
        pack = get_pack(state["turn_id"]) or EvidencePack()
        limitations = pack_limitations(pack)
        accepted = [Claim.model_validate(c) for c in (state.get("accepted") or [])]
        status = "complete"
        if state.get("narrate_error"):
            kind = "model_budget_exhausted" if state["narrate_error"] == "model_budget_exhausted" else "narrative_unavailable"
            limitations.append({"kind": kind, "section": None, "detail": f"Narrative not available ({state['narrate_error']}); showing verified records only.", "source_ids": []})
            if state["turn_type"] == "uc01_first":
                accepted = verify(fallback_claims(pack), pack).accepted
                status = "fallback"
            else:
                status = "fallback"
        elif state.get("rejected"):
            status = "partial"
        if any(e["status"] == "unavailable" for e in state.get("evidence") or []):
            status = "partial" if status == "complete" else status
        withheld = len(state.get("rejected") or []) if not state.get("narrate_error") else 0
        if withheld:
            limitations.append({"kind": "withheld", "section": None, "detail": f"{withheld} statement(s) withheld: could not be verified against the chart.", "source_ids": []})
        cited = {sid for c in accepted for sid in c.source_ids}
        sources = [source_summary(pack.records[sid]) for sid in sorted(cited) if sid in pack.records]
        history = list(state.get("history") or [])
        history.append({
            "turn_id": state["turn_id"],
            "question": state["question"][:200],
            "turn_type": state["turn_type"],
            "claims": [c.model_dump(mode="json") for c in accepted],
            "limitations": limitations,
            "window_since": state.get("window_since"),
            "reference_encounter_source_id": state.get("reference_encounter_source_id"),
            "status": status,
        })
        usage = dict(state.get("usage") or {})
        usage["render_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return {
            "accepted": [c.model_dump(mode="json") for c in accepted],
            "limitations": limitations,
            "sources": sources,
            "status": status,
            "history": history,
            "conversation_tokens": int(state.get("conversation_tokens") or 0) + int(usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
            "usage": usage,
            "route": "end",
        }

    return {"authorize": authorize, "classify": classify, "plan": plan, "retrieve": retrieve, "narrate": narrate, "verify": verify_node, "repair": repair, "render": render_node}


# ---------------------------------------------------------------- helpers


def pack_limitations(pack: EvidencePack) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if "encounters" in pack.responses and pack.reference_encounter is None and pack.responses["encounters"].status.value in ("ok", "empty"):
        out.append({"kind": "not_documented", "section": "encounters", "detail": "No prior clinical visit documented; showing the whole chart without a change window.", "source_ids": []})
    for tool, r in pack.responses.items():
        if r.status.value == "unavailable":
            out.append({"kind": "unavailable", "section": tool, "detail": f"{tool} could not be retrieved ({r.reason}); nothing is claimed about this section.", "source_ids": []})
        elif r.status.value == "partial":
            out.append({"kind": "unavailable", "section": tool, "detail": f"{tool} returned partial data ({r.reason}).", "source_ids": []})
        if r.truncated:
            out.append({"kind": "truncated", "section": tool, "detail": f"{tool}: {r.omitted_count} older record(s) not shown; narrow the window to see them.", "source_ids": []})
        if r.absence_state is not None and r.absence_state.value != "documented":
            detail = "Allergy list reviewed; none recorded." if r.absence_state.value == "reviewed_none" else "Allergies not documented (never reviewed)."
            out.append({"kind": r.absence_state.value, "section": tool, "detail": detail, "source_ids": []})
    for rec in pack.records.values():
        if getattr(rec, "undated", False):
            out.append({"kind": "undated", "section": rec.source.table, "detail": f"{getattr(rec, 'title', None) or getattr(rec, 'name', None) or getattr(rec, 'substance', 'record')}: no clinical date; cannot be placed in the timeline.", "source_ids": [rec.source.source_id]})
        if getattr(rec, "status_conflict", False):
            out.append({"kind": "conflict", "section": "medications", "detail": f"{rec.name}: end date and activity flag disagree (status shown by activity).", "source_ids": [rec.source.source_id]})
    if pack.truncated:
        out.append({"kind": "truncated", "section": None, "detail": "Evidence pack truncated at its size cap.", "source_ids": []})
    return out


def fallback_claims(pack: EvidencePack) -> list[Claim]:
    """Deterministic, source-cited claims from the change set (CAP-08)."""
    claims: list[Claim] = []
    n = 0
    for ev in pack.changes[:40]:
        n += 1
        claims.append(Claim(id=f"c{n}", type=ClaimType.change_event, text=f"{ev.summary} ({ev.date.isoformat() if ev.date else 'undated'})", facts={"section": ev.section, "kind": ev.kind, "date": ev.date.isoformat() if ev.date else None}, source_ids=[ev.source_id], section=ev.section))
    for tool, r in pack.responses.items():
        if r.absence_state is not None and r.absence_state.value != "documented" and n < 40:
            n += 1
            claims.append(Claim(id=f"c{n}", type=ClaimType.absence, text="Allergies: " + ("list reviewed, none recorded" if r.absence_state.value == "reviewed_none" else "not documented"), facts={"section": "allergies", "state": r.absence_state.value}, source_ids=[], section="allergies"))
    return claims


def source_summary(rec: Any) -> dict[str, Any]:
    label = rec.source.table
    day = _day(getattr(rec, "date", None))
    when = day.isoformat() if day else "undated"
    if hasattr(rec, "analyte"):
        label = f"Lab result {when}: {rec.analyte}"
    elif hasattr(rec, "title"):
        label = f"Problem: {rec.title}"
    elif hasattr(rec, "name"):
        label = f"Medication ({rec.provenance}): {rec.name}"
    elif hasattr(rec, "substance"):
        label = f"Allergy: {rec.substance}"
    elif hasattr(rec, "text"):
        label = f"Note {when}"
    elif hasattr(rec, "encounter_id") and hasattr(rec, "category"):
        label = f"Encounter {when}: {rec.category or ''}"
    elif hasattr(rec, "age_band"):
        label = "Patient"
    return {
        "source_id": rec.source.source_id,
        "table": rec.source.table,
        "id": rec.source.id,
        "label": label[:160],
        "encounter_id": getattr(rec, "encounter_id", None),
        "order_id": getattr(rec, "order_id", None),
    }
