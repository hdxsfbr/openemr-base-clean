"""Graph nodes: plain functions over TurnState. Every routing decision is
returned in state (`route`) so it appears in the trace."""

from __future__ import annotations

import contextlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from pydantic import ValidationError

from .. import budget
from ..contracts import Claim, ClaimType, LabsParams, NotesParams, ToolResponse, WindowParams
from ..evidence import EvidencePack, _day, add_responses, build_uc01_window, derive_changes, render
from ..gateway_client import GatewayPort, unavailable
from ..metrics import metrics
from ..model import ModelError, ModelPort, NarrateResult, PlanResult, Usage
from ..settings import settings
from ..state_store import get_pack, get_token, put_pack
from ..telemetry import record_tool_result, tool_observation
from ..verifier import default_suggestions, deterministic_summary, filter_suggestions, verify, verify_summary
from .state import TurnState

log = logging.getLogger("copilot.graph")

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


def _timed(name: str, fn: Callable) -> Callable:
    """Record each node's wall time in state so the trace and the response show where a turn's time went."""

    async def wrapped(state: TurnState) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            out = await fn(state)
        finally:
            duration = round((time.perf_counter() - t0) * 1000, 1)
            log.info("node", extra={"component": name, "duration_ms": duration, "correlation_id": state.get("correlation_id")})
        timings = dict(state.get("timings_ms") or {})
        timings[name] = round(timings.get(name, 0.0) + duration, 1)
        out["timings_ms"] = timings
        out.setdefault("route", state.get("route", ""))
        return out

    return wrapped


def _elapsed(state: TurnState) -> float:
    started = float(state.get("started_at") or 0.0)
    return time.time() - started if started else 0.0


def _narratable(pack: EvidencePack) -> bool:
    """True when at least one clinical section (anything but patient_context) came back ok or empty."""
    return any(tool != "patient_context" and r.status.value in ("ok", "empty") for tool, r in pack.responses.items())


def make_nodes(rt: Runtime) -> dict[str, Callable]:
    async def authorize(state: TurnState) -> dict[str, Any]:
        if state.get("closed"):
            return {"denied": {"code": "conversation_closed", "message": "This conversation is closed."}, "status": "denied", "route": "render"}
        limit = budget.check(0, int(state.get("conversation_tokens") or 0))
        if state.get("fault") == "budget":
            limit = "model_budget_exhausted"
        return {"budget_limit": limit, "started_at": state.get("started_at") or time.time(), "route": "classify"}

    async def classify(state: TurnState) -> dict[str, Any]:
        q = state["question"].strip().lower()
        first = not (state.get("history") or [])
        canonical = any(re.search(p, q) for p in UC01_PATTERNS)
        turn_type = "uc01_first" if (first or canonical) and (canonical or len(q) < 80) else "followup"
        if first and not canonical:
            turn_type = "followup"
        return {"turn_type": turn_type, "route": "retrieve" if turn_type == "uc01_first" else "plan"}

    def _clean_params(tool: str, params: dict[str, Any]) -> dict[str, Any] | None:
        model = PARAM_MODELS.get(tool, WindowParams)
        try:
            return model.model_validate(params).model_dump(mode="json", exclude_none=True)
        except ValidationError:
            return None

    async def _call_batch(calls: list[tuple[str, dict[str, Any]]], state: TurnState) -> list[ToolResponse]:
        """One gateway request serving every call in `calls`: one OpenEMR
        bootstrap (translation/ACL/layout lookups, PERF-MED-002) instead of
        one per tool. Fault-injected and invalid-params tools are resolved
        locally without ever reaching the gateway, exactly as before; each
        live tool still gets its own tracing observation and metric even
        though the network call is shared."""
        results: list[ToolResponse | None] = [None] * len(calls)
        live: list[tuple[int, str, dict[str, Any]]] = []
        for i, (tool, params) in enumerate(calls):
            if state.get("fault") == f"tool:{tool}":
                results[i] = unavailable(tool, "fault_injected", state["correlation_id"])
                continue
            clean = _clean_params(tool, params)
            if clean is None:
                results[i] = unavailable(tool, "invalid_params", state["correlation_id"])
                continue
            live.append((i, tool, clean))

        if live:
            # The token lives in the per-turn cache, never in graph state (ADR-0005); a turn
            # the API did not register sends an empty token and the gateway denies and audits it.
            token = get_token(state["turn_id"]) or ""
            with contextlib.ExitStack() as stack:
                observations = [stack.enter_context(tool_observation(tool, state["correlation_id"])) for _, tool, _ in live]
                responses = await rt.gateway.call_batch([(tool, clean) for _, tool, clean in live], token, state["correlation_id"])
                for (i, tool, _), obs, response in zip(live, observations, responses):
                    record_tool_result(obs, response)
                    metrics.tool_call(tool, response.status.value, response.reason)
                    results[i] = response

        return [r for r in results if r is not None]

    async def retrieve(state: TurnState) -> dict[str, Any]:
        pack = get_pack(state["turn_id"]) or EvidencePack()
        calls: list[list[Any]] = list(state.get("tool_calls") or [])
        if state["turn_type"] == "uc01_first" and not calls:
            # encounters and patient_context need no window; the rest of UC01_TOOLS need
            # encounters' own result to derive `since`, so they can't share one batch with it.
            encounters, patient_context = await _call_batch([("encounters", {}), ("patient_context", {})], state)
            calls.extend([["encounters", {}], ["patient_context", {}]])
            ref, since = build_uc01_window(encounters, rt.today())
            pack.reference_encounter = ref
            pack.window_since = since
            add_responses(pack, [encounters, patient_context])
            params = {"since": since.isoformat()} if since else {}
            remaining = [t for t in UC01_TOOLS if t != "patient_context"]
            responses = await _call_batch([(t, params) for t in remaining], state)
            calls.extend([t, params] for t in remaining)
            add_responses(pack, responses)
        else:
            pending = list(state.get("pending_calls") or [])
            room = settings.max_tool_calls_per_turn - len(calls)
            pending = pending[: max(0, room)]
            if pack.window_since is None and (state.get("window_since")):
                pack.window_since = date.fromisoformat(state["window_since"])
            responses = await _call_batch(pending, state)
            calls.extend([t, p] for t, p in pending)
            add_responses(pack, responses)
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
            result: PlanResult = await rt.model.plan(state["question"], pack.text, prior, correlation_id=state.get("correlation_id"))
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
        if pack is not None and not _narratable(pack):
            # Every clinical section was denied or failed: there is nothing a claim could cite,
            # so the model is not invoked (authorization denial stays ahead of any LLM call).
            log.info("narrate skipped: no clinical section retrievable", extra={"component": "narrate", "correlation_id": state.get("correlation_id")})
            return {"raw_claims": [], "raw_summary": "", "raw_suggestions": [], "route": "verify"}
        effort = settings.effort_first_turn if state["turn_type"] == "uc01_first" else settings.effort_followup
        try:
            result: NarrateResult = await rt.model.narrate(state["question"], pack.text if pack else "", effort, correlation_id=state.get("correlation_id"))
        except ModelError as exc:
            return {"raw_claims": None, "narrate_error": exc.kind, "route": "render"}
        budget.daily.add(result.usage.total)
        if result.claims is None:
            return {"raw_claims": None, "narrate_error": result.error, "usage": _add_usage(state, result.usage), "route": "render"}
        return {"raw_claims": [c.model_dump(mode="json") for c in result.claims.claims], "raw_summary": result.claims.summary, "raw_suggestions": list(result.claims.suggestions), "usage": _add_usage(state, result.usage), "route": "verify"}

    async def verify_node(state: TurnState) -> dict[str, Any]:
        pack = get_pack(state["turn_id"]) or EvidencePack()
        claims = [Claim.model_validate(c) for c in (state.get("raw_claims") or [])]
        result = verify(claims, pack)
        # Repair only when it can still finish inside the turn's wall clock; otherwise withhold and render.
        time_left = settings.turn_wall_clock_seconds - _elapsed(state)
        can_repair = rt.model is not None and time_left > settings.model_timeout_seconds * 0.6
        # After a repair, a first-round rejection that the repair did not resurrect stays withheld.
        rejected = list(result.rejected)
        if state.get("repair_attempted"):
            accepted_ids = {c.id for c in result.accepted}
            seen = {(r["claim_id"], r["rule"]) for r in rejected}
            for prior in state.get("rejected") or []:
                if prior["claim_id"] not in accepted_ids and (prior["claim_id"], prior["rule"]) not in seen:
                    rejected.append(prior)
        route = "repair" if result.rejected and not state.get("repair_attempted") and can_repair else "render"
        return {"accepted": [c.model_dump(mode="json") for c in result.accepted], "rejected": rejected, "rules": result.rules_applied, "route": route}

    async def repair(state: TurnState) -> dict[str, Any]:
        pack = get_pack(state["turn_id"])
        effort = settings.effort_first_turn if state["turn_type"] == "uc01_first" else settings.effort_followup
        try:
            result = await rt.model.narrate(state["question"], pack.text if pack else "", effort, rejections=state.get("rejected") or [], correlation_id=state.get("correlation_id"))  # type: ignore[union-attr]
        except ModelError:
            return {"repair_attempted": True, "route": "render"}
        budget.daily.add(result.usage.total)
        if result.claims is None:
            return {"repair_attempted": True, "usage": _add_usage(state, result.usage), "route": "render"}
        return {"repair_attempted": True, "raw_claims": [c.model_dump(mode="json") for c in result.claims.claims], "raw_summary": result.claims.summary, "usage": _add_usage(state, result.usage), "route": "verify"}

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
        # The summary is prose: the model's is shown only when every claim verified (ADR-0006 §7);
        # otherwise the first verified claims are restated word for word.
        summary_ok, summary_reason = verify_summary(state.get("raw_summary") or "", accepted, state.get("rejected") or [], known_values=[state.get("window_since") or ""]) if not state.get("narrate_error") else (False, "narrative_unavailable")
        if summary_ok:
            summary, summary_basis = " ".join((state.get("raw_summary") or "").split()), "model"
        else:
            summary, summary_basis = deterministic_summary(accepted, withheld, state.get("window_since"), state.get("narrate_error")), "deterministic"
            # Rule name only: the ungrounded token itself is chart content and stays out of the log.
            log.info("summary replaced: %s", summary_reason.split(":")[0] if summary_reason.startswith("ungrounded") else summary_reason, extra={"component": "render", "correlation_id": state.get("correlation_id")})
        asked = [h.get("question", "") for h in (state.get("history") or [])] + [state["question"]]
        suggestions = filter_suggestions(state.get("raw_suggestions") or [], asked) if not state.get("narrate_error") else []
        if len(suggestions) < 2:
            suggestions = filter_suggestions(suggestions + default_suggestions(accepted, asked), asked)
        answered_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        history = list(state.get("history") or [])
        history.append({
            "turn_id": state["turn_id"],
            "answered_at": answered_at,
            "question": state["question"][:200],
            "turn_type": state["turn_type"],
            "summary": summary,
            "summary_basis": summary_basis,
            "suggestions": suggestions,
            "claims": [c.model_dump(mode="json") for c in accepted],
            "sources": sources,
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
            "summary": summary,
            "summary_basis": summary_basis,
            "summary_reason": summary_reason,
            "suggestions": suggestions,
            "answered_at": answered_at,
            "status": status,
            "history": history,
            "conversation_tokens": int(state.get("conversation_tokens") or 0) + int(usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
            "usage": usage,
            "route": "end",
        }

    nodes = {"authorize": authorize, "classify": classify, "plan": plan, "retrieve": retrieve, "narrate": narrate, "verify": verify_node, "repair": repair, "render": render_node}
    return {name: _timed(name, fn) for name, fn in nodes.items()}


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
        # Field-level absences are stated deterministically (DQ-MEDIUM-007, DQ-MEDIUM-009): the
        # claim types carry no "reaction not documented", so the record's gaps are limitation lines.
        if hasattr(rec, "substance") and (rec.reaction is None or rec.severity is None):
            missing = " and ".join(f for f, v in (("reaction", rec.reaction), ("severity", rec.severity)) if v is None)
            out.append({"kind": "not_documented", "section": "allergies", "detail": f"{rec.substance}: {missing} not documented.", "source_ids": [rec.source.source_id]})
        if hasattr(rec, "note_type") and not rec.author.username:
            out.append({"kind": "not_documented", "section": "notes", "detail": f"Note {_day(rec.date) or 'undated'}: author not recorded.", "source_ids": [rec.source.source_id]})
        if hasattr(rec, "analyte") and rec.corrected:
            out.append({"kind": "conflict", "section": "labs", "detail": f"{rec.analyte} ({_day(rec.date) or 'undated'}): corrected result {rec.value_text} {rec.unit or ''}; it supersedes any earlier value for that date and is not a trend.".replace("  ", " "), "source_ids": [rec.source.source_id]})
        if hasattr(rec, "provenance") and not rec.documented_indication:
            out.append({"kind": "not_documented", "section": "medications", "detail": f"{rec.name}: no documented indication (nothing in the record says why it is listed).", "source_ids": [rec.source.source_id]})
        if hasattr(rec, "analyte") and rec.unit is not None and rec.numeric_value is None and rec.value_text:
            out.append({"kind": "not_documented", "section": "labs", "detail": f"{rec.analyte} ({_day(rec.date) or 'undated'}): value recorded as text {rec.value_text!r}; quoted, never compared.", "source_ids": [rec.source.source_id]})
        if hasattr(rec, "analyte") and rec.unit is None:
            out.append({"kind": "not_documented", "section": "labs", "detail": f"{rec.analyte} ({_day(rec.date) or 'undated'}): unit not recorded; value {rec.value_text} is not comparable.", "source_ids": [rec.source.source_id]})
    # The same medication in the list and in prescriptions with different statuses (DQ-HIGH-003):
    # a deterministic conflict line citing both, so the state never depends on the model saying it.
    by_name: dict[str, list[Any]] = {}
    for rec in pack.records.values():
        if hasattr(rec, "provenance"):
            by_name.setdefault(_med_key(rec.name), []).append(rec)
    for key, recs in by_name.items():
        provenances = {r.provenance for r in recs}
        statuses = {r.status for r in recs}
        if len(provenances) > 1 and len(statuses) > 1:
            listing = ", ".join(f"{r.status} in {r.provenance}" for r in sorted(recs, key=lambda r: r.provenance))
            out.append({"kind": "conflict", "section": "medications", "detail": f"{recs[0].name}: status differs across sources ({listing}); both records shown, neither preferred.", "source_ids": [r.source.source_id for r in recs]})
    if pack.truncated:
        out.append({"kind": "truncated", "section": None, "detail": "Evidence pack truncated at its size cap.", "source_ids": []})
    return out


def _med_key(name: str) -> str:
    """First word of the medication name, lower-cased: 'Metformin 500 mg' and 'METFORMIN' group together; brand names do not."""
    return (name.split() or [""])[0].lower()


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
