"""Turn-graph tests with the recorded gateway fixtures and a scripted model.
Each test guards a boundary, invariant, or regression risk (evals/README.md)."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app import budget
from app.graph.build import build_graph
from app.graph.nodes import Runtime
from app.graph.state import PER_TURN_DEFAULTS
from conftest import FakeGateway, FakeModel

TODAY = dt.date(2026, 9, 15)
CID = "57b815a321edb1bbab13699dec3adb20"


def turn_input(question: str, turn_id: str = "fb5c2fa60b22e600", fault: str | None = None) -> dict[str, Any]:
    state = dict(PER_TURN_DEFAULTS)
    state.update({"conversation_id": CID, "turn_id": turn_id, "correlation_id": "test-turn-0001", "token": "t.t", "question": question, "fault": fault})
    return state


def make_graph(model, gateway=None):
    return build_graph(Runtime(gateway=gateway or FakeGateway(), model=model, today=lambda: TODAY), checkpointer=InMemorySaver())


CFG = {"configurable": {"thread_id": CID}}

# Source ids from the recorded AF-DQ-A2 fixtures.
A1C_LATEST = "openemr:procedure_result:9000003:a2bfa267-ec71-4353-9c11-3657a2f525f8"
HYPERLIPIDEMIA = "openemr:lists:9000003:a2bfa267-d103-4be7-a4c2-a3699fdea462"
METFORMIN = "openemr:lists:9000006:a2bfa267-d463-4eb1-a9e8-74774bc1d5f7"


@pytest.mark.anyio
async def test_uc01_first_turn_without_model_renders_deterministic_brief() -> None:
    budget.daily.reset()
    g = make_graph(model=None)
    final = await g.ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["turn_type"] == "uc01_first"
    assert final["status"] == "fallback"
    assert final["window_since"] == "2026-06-16"  # last clinical visit
    assert final["reference_encounter_source_id"].startswith("openemr:form_encounter:9000003")
    kinds = {(c["facts"]["section"], c["facts"]["kind"]) for c in final["accepted"]}
    assert ("problems", "added") in kinds and ("medications", "started") in kinds and ("labs", "resulted") in kinds
    assert all(c["source_ids"] for c in final["accepted"])
    assert any(l["kind"] == "narrative_unavailable" for l in final["limitations"])
    tools = {e["tool"] for e in final["evidence"]}
    assert tools == {"encounters", "patient_context", "problems", "medications", "allergies", "lab_results", "clinical_notes"}


@pytest.mark.anyio
async def test_model_claims_are_verified_and_bad_ones_withheld() -> None:
    budget.daily.reset()
    good = {"id": "c1", "type": "lab_result", "text": "Hemoglobin A1c 6.8 % on 2026-08-31, flagged abnormal.", "facts": {"analyte": "Hemoglobin A1c", "value_text": "6.8", "unit": "%", "date": "2026-08-31", "flag": "abnormal"}, "source_ids": [A1C_LATEST]}
    altered = {"id": "c2", "type": "lab_result", "text": "Hemoglobin A1c 7.8 % on 2026-08-31.", "facts": {"analyte": "Hemoglobin A1c", "value_text": "7.8", "unit": "%", "date": "2026-08-31", "flag": "abnormal"}, "source_ids": [A1C_LATEST]}
    fabricated = {"id": "c3", "type": "change_event", "text": "Insulin started.", "facts": {"section": "medications", "kind": "started", "date": "2026-08-25"}, "source_ids": ["openemr:lists:1:nope"]}
    advice = {"id": "c4", "type": "change_event", "text": "Metformin started; you should increase the dose.", "facts": {"section": "medications", "kind": "started", "date": "2026-08-25"}, "source_ids": [METFORMIN]}
    model = FakeModel(claims=[good, altered, fabricated, advice], repair_claims=[good])
    g = make_graph(model)
    final = await g.ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["status"] == "partial"  # three statements withheld
    assert [c["id"] for c in final["accepted"]] == ["c1"]
    assert {r["claim_id"] for r in final["rejected"]} == {"c2", "c3", "c4"}
    assert {r["rule"] for r in final["rejected"]} == {"type_facts", "source_exists", "lexicon:advice"}
    assert final["repair_attempted"] is True and model.narrate_calls == 2
    assert final["sources"][0]["source_id"] == A1C_LATEST and final["sources"][0]["table"] == "procedure_result"
    # Statements were withheld, so the model's prose is not shown; the summary is built from verified claims only.
    assert final["summary_basis"] == "deterministic" and "1 lab result" in final["summary"] and "3 statement(s) were withheld" in final["summary"]
    assert final["history"][-1]["summary"] == final["summary"] and final["history"][-1]["sources"] == final["sources"]


@pytest.mark.anyio
async def test_paraphrased_advice_and_inference_are_rejected_like_the_direct_wording() -> None:
    """A model can satisfy a 'never say should/likely' instruction by rewording rather than by
    not giving advice or unsupported inference. The verifier's lexicon has to catch the meaning,
    not the literal keyword (2026-09-16 eval hardening, after a manual paraphrase sweep of the
    FORBIDDEN list found these gaps)."""
    budget.daily.reset()
    direct = {"id": "c1", "type": "change_event", "text": "Metformin started; the dose should be increased.", "facts": {"section": "medications", "kind": "started", "date": "2026-08-25"}, "source_ids": [METFORMIN]}
    paraphrase_advice = {"id": "c2", "type": "change_event", "text": "Metformin started; it would be wise to review the dose.", "facts": {"section": "medications", "kind": "started", "date": "2026-08-25"}, "source_ids": [METFORMIN]}
    paraphrase_inference = {"id": "c3", "type": "change_event", "text": "Metformin started, which points toward better glycemic control.", "facts": {"section": "medications", "kind": "started", "date": "2026-08-25"}, "source_ids": [METFORMIN]}
    model = FakeModel(claims=[direct, paraphrase_advice, paraphrase_inference], repair_claims=[])
    g = make_graph(model)
    final = await g.ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["accepted"] == []
    assert {r["claim_id"] for r in final["rejected"]} == {"c1", "c2", "c3"}
    assert all(r["rule"] in ("lexicon:advice", "lexicon:inference") for r in final["rejected"])


@pytest.mark.anyio
async def test_model_summary_shown_only_when_every_claim_verifies() -> None:
    budget.daily.reset()
    good = {"id": "c1", "type": "lab_result", "text": "Hemoglobin A1c 6.8 % on 2026-08-31, flagged abnormal.", "facts": {"analyte": "Hemoglobin A1c", "value_text": "6.8", "unit": "%", "date": "2026-08-31", "flag": "abnormal"}, "source_ids": [A1C_LATEST]}
    model = FakeModel(claims=[good], summary="One result is flagged abnormal: hemoglobin A1c at 6.8 % on 2026-08-31.")
    final = await make_graph(model).ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["status"] == "complete" and final["summary_basis"] == "model" and final["summary"].startswith("One result is flagged")

    # Counts up to the number of claims and the window date are agent-established facts, so they are grounded.
    model = FakeModel(claims=[good], summary="Since the visit on 2026-06-16 there is 1 flagged result: hemoglobin A1c 6.8 %.")
    final = await make_graph(model).ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["window_since"] == "2026-06-16" and final["summary_basis"] == "model"

    # A number the claims do not carry makes the summary ungrounded: replaced, claims untouched.
    model = FakeModel(claims=[good], summary="A1c rose from 6.1 to 6.8 %.")
    final = await make_graph(model).ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["status"] == "complete" and final["summary_basis"] == "deterministic" and len(final["accepted"]) == 1

    # Suggestions: the model's questions pass a shape and lexicon filter; bad ones are replaced by deterministic follow-ups.
    model = FakeModel(claims=[good], summary="One result is flagged abnormal: hemoglobin A1c at 6.8 % on 2026-08-31.",
                      suggestions=["Was the A1c result discussed in a note?", "Should the dose be increased?", "What changed since the last visit?"])
    final = await make_graph(model).ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["suggestions"][0] == "Was the A1c result discussed in a note?"
    assert all("dose" not in s and s != "What changed since the last visit?" for s in final["suggestions"]) and 2 <= len(final["suggestions"]) <= 3
    assert final["history"][-1]["suggestions"] == final["suggestions"]

    # Trajectory judgments in the summary are replaced too; claims stay.
    model = FakeModel(claims=[good], summary="A1c is improving at 6.8 %.")
    final = await make_graph(model).ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["summary_basis"] == "deterministic" and len(final["accepted"]) == 1

    # Management-shaped suggestions are dropped even when phrased as questions.
    model = FakeModel(claims=[good], summary="One result is flagged abnormal: hemoglobin A1c at 6.8 % on 2026-08-31.",
                      suggestions=["Does the A1c need addressing?", "What is the management plan for A1c?", "Are there earlier A1c results to compare?"])
    final = await make_graph(model).ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["suggestions"][0] == "Are there earlier A1c results to compare?" and not any("addressing" in s or "plan" in s for s in final["suggestions"])

    # Advice language in the summary is rejected by the same lexicon as claims.
    model = FakeModel(claims=[good], summary="A1c is abnormal; you should recheck it.")
    final = await make_graph(model).ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["summary_basis"] == "deterministic"


@pytest.mark.anyio
async def test_absence_claim_requires_successful_retrieval() -> None:
    budget.daily.reset()
    absence = {"id": "c1", "type": "absence", "text": "No lab results in the window.", "facts": {"section": "labs", "state": "no_records_in_window"}, "source_ids": []}
    model = FakeModel(claims=[absence], repair_claims=[])
    g = make_graph(model, gateway=FakeGateway(failing={"lab_results"}))
    final = await g.ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["accepted"] == []
    assert any(r["rule"] == "absence_requires_retrieval" for r in final["rejected"])
    assert any(l["kind"] == "unavailable" and l["section"] == "lab_results" for l in final["limitations"])
    assert final["status"] == "partial"


@pytest.mark.anyio
async def test_followup_plans_tools_and_keeps_window() -> None:
    budget.daily.reset()
    g = make_graph(FakeModel(claims=[]))
    await g.ainvoke(turn_input("What changed since the last visit?", turn_id="aaaaaaaaaaaaaaa1"), CFG)
    model = FakeModel(claims=[{"id": "c1", "type": "change_event", "text": "Hyperlipidemia added to the problem list on 2026-08-31.", "facts": {"section": "problems", "kind": "added", "date": "2026-08-31"}, "source_ids": [HYPERLIPIDEMIA]}], plan_calls=[("clinical_notes", {"term": "amlodipine"})])
    gw = FakeGateway()
    g2 = build_graph(Runtime(gateway=gw, model=model, today=lambda: TODAY), checkpointer=g.checkpointer)
    final = await g2.ainvoke(turn_input("Was the amlodipine stop documented in a note?", turn_id="aaaaaaaaaaaaaaa2"), CFG)
    assert final["turn_type"] == "followup"
    assert gw.calls[0][0] == "clinical_notes" and gw.calls[0][1].get("term") == "amlodipine"
    assert len(final["history"]) == 2 and final["conversation_tokens"] > 0
    assert model.plan_rounds >= 1


@pytest.mark.anyio
async def test_budget_exhaustion_routes_to_deterministic_fallback() -> None:
    budget.daily.reset()
    model = FakeModel(claims=[{"id": "c1", "type": "undated", "text": "x", "facts": {}, "source_ids": []}])
    g = make_graph(model)
    final = await g.ainvoke(turn_input("What changed since the last visit?", fault="budget"), CFG)
    assert final["status"] == "fallback"
    assert model.narrate_calls == 0
    assert any(l["kind"] == "model_budget_exhausted" for l in final["limitations"])
    assert final["accepted"], "deterministic brief still rendered"


@pytest.mark.anyio
async def test_closed_conversation_is_denied_before_any_tool_call() -> None:
    gw = FakeGateway()
    g = make_graph(FakeModel(), gateway=gw)
    await g.aupdate_state(CFG, {"closed": True})
    final = await g.ainvoke(turn_input("What changed since the last visit?"), CFG)
    assert final["status"] == "denied" and gw.calls == []


# ---------------------------------------------------------------- verifier details found by the 2026-09-16 cohort sweep

from app.contracts import Claim, ToolResponse  # noqa: E402
from app.evidence import EvidencePack, add_responses  # noqa: E402
from app.verifier import verify  # noqa: E402
from conftest import FIXTURE_DIR  # noqa: E402

HYPERTENSION = "openemr:lists:9000001:a2bfa267-cec6-4277-bd56-093500afd394"


def _pack(*tools: str) -> EvidencePack:
    pack = EvidencePack()
    add_responses(pack, [ToolResponse.model_validate(json.loads((FIXTURE_DIR / f"af-dq-a2.{t}.json").read_text())) for t in tools])
    return pack


def test_lab_result_with_missing_unit_verifies_and_mismatch_names_the_field() -> None:
    pack = _pack("lab_results")
    resp = pack.responses["lab_results"]
    rec = resp.records[0].model_copy(update={"unit": None, "comparable": False})
    pack.responses["lab_results"] = resp.model_copy(update={"records": [rec]})
    pack.records[rec.source.source_id] = rec
    base = {"id": "c1", "type": "lab_result", "text": f"{rec.analyte} {rec.value_text}, unit missing.", "source_ids": [rec.source.source_id]}
    facts = {"analyte": rec.analyte, "value_text": rec.value_text, "date": rec.date.value.date().isoformat(), "flag": rec.flag}
    ok = verify([Claim.model_validate({**base, "facts": {**facts, "unit": None}})], pack)
    assert [c.id for c in ok.accepted] == ["c1"]
    guessed = verify([Claim.model_validate({**base, "facts": {**facts, "unit": "mmol/L"}})], pack)
    assert guessed.rejected and guessed.rejected[0]["detail"].startswith("unit 'mmol/L'")


def test_absence_rejection_names_the_section_and_allowed_state() -> None:
    pack = _pack("problems", "allergies")
    populated = Claim.model_validate({"id": "c1", "type": "absence", "text": "No problems documented.", "facts": {"section": "problems", "state": "no_records_in_window"}})
    res = verify([populated], pack)
    assert res.rejected[0]["detail"].startswith("problems has 3 record(s)")


def test_problem_status_claim_verifies_against_title_or_code_only() -> None:
    pack = _pack("problems")
    good = {"id": "c1", "type": "problem_status", "text": "Essential hypertension is on the problem list, active.", "facts": {"name": "Essential hypertension", "status": "active"}, "source_ids": [HYPERTENSION]}
    translated = {"id": "c2", "type": "problem_status", "text": "Hypertension (ICD-9 401.9) is active.", "facts": {"name": "401.9", "status": "active"}, "source_ids": [HYPERTENSION]}
    wrong_status = {"id": "c3", "type": "problem_status", "text": "Essential hypertension inactive.", "facts": {"name": "Essential hypertension", "status": "inactive"}, "source_ids": [HYPERTENSION]}
    res = verify([Claim.model_validate(c) for c in (good, translated, wrong_status)], pack)
    assert [c.id for c in res.accepted] == ["c1"]
    assert {r["claim_id"] for r in res.rejected} == {"c2", "c3"}


@pytest.mark.anyio
async def test_model_is_not_called_when_every_clinical_section_is_unavailable() -> None:
    budget.daily.reset()
    model = FakeModel(claims=[])
    gateway = FakeGateway(failing={"encounters", "problems", "medications", "allergies", "lab_results", "clinical_notes"})
    g = make_graph(model, gateway)
    final = await g.ainvoke(turn_input("What changed since the last visit?", turn_id="fb5c2fa60b22e6ff"), CFG)  # own turn id: the pack store is keyed by it
    assert model.narrate_calls == 0
    assert final["status"] == "partial" and final["accepted"] == []
    assert {l["kind"] for l in final["limitations"]} == {"unavailable"}
    assert "retrievable" in final["summary"]


def test_field_level_absences_become_limitation_lines() -> None:
    from app.graph.nodes import pack_limitations
    pack = _pack("allergies", "lab_results")
    allergy = pack.responses["allergies"].records[0].model_copy(update={"reaction": None, "severity": None})
    lab = pack.responses["lab_results"].records[0].model_copy(update={"unit": None, "comparable": False})
    pack.records[allergy.source.source_id] = allergy
    pack.records[lab.source.source_id] = lab
    lims = pack_limitations(pack)
    assert any(l["kind"] == "not_documented" and l["section"] == "allergies" and "reaction and severity not documented" in l["detail"] and l["source_ids"] == [allergy.source.source_id] for l in lims)
    assert any(l["kind"] == "not_documented" and l["section"] == "labs" and "unit not recorded" in l["detail"] for l in lims)


def test_analyte_with_code_suffix_verifies_and_same_day_pairs_are_not_trends() -> None:
    pack = _pack("lab_results")
    recs = [r for r in pack.responses["lab_results"].records if r.analyte == "Hemoglobin A1c"]
    latest = recs[0]
    claim = {"id": "c1", "type": "lab_result", "text": "A1c 6.8 %.", "source_ids": [latest.source.source_id],
             "facts": {"analyte": f"{latest.analyte} ({latest.analyte_code})", "value_text": latest.value_text, "unit": latest.unit, "date": latest.date.value.date().isoformat(), "flag": latest.flag}}
    assert [c.id for c in verify([Claim.model_validate(claim)], pack).accepted] == ["c1"]
    twin = latest.model_copy(update={"value_text": "6.9", "numeric_value": 6.9, "corrected": True, "source": latest.source.model_copy(update={"source_id": latest.source.source_id + ":twin", "id": latest.source.id + 1})})
    pack.records[twin.source.source_id] = twin
    cmp = {"id": "c2", "type": "lab_comparison", "text": "A1c changed within the day.", "source_ids": [latest.source.source_id, twin.source.source_id],
           "facts": {"analyte": "Hemoglobin A1c", "earlier_source_id": latest.source.source_id, "later_source_id": twin.source.source_id, "direction": "up"}}
    res = verify([Claim.model_validate(cmp)], pack)
    assert res.rejected and "same-day" in res.rejected[0]["detail"]


def test_unknown_author_and_corrected_result_become_limitation_lines() -> None:
    from app.graph.nodes import pack_limitations
    pack = _pack("clinical_notes", "lab_results")
    note = pack.responses["clinical_notes"].records[0]
    note = note.model_copy(update={"author": note.author.model_copy(update={"username": None})})
    lab = pack.responses["lab_results"].records[0].model_copy(update={"corrected": True})
    pack.records[note.source.source_id] = note
    pack.records[lab.source.source_id] = lab
    lims = pack_limitations(pack)
    assert any(l["kind"] == "not_documented" and l["section"] == "notes" and "author not recorded" in l["detail"] for l in lims)
    assert any(l["kind"] == "conflict" and l["section"] == "labs" and "corrected result" in l["detail"] and l["source_ids"] == [lab.source.source_id] for l in lims)


def test_indication_text_value_and_cross_source_status_become_limitation_lines() -> None:
    from app.graph.nodes import pack_limitations
    pack = _pack("medications", "lab_results")
    meds = [r for r in pack.responses["medications"].records]
    med = meds[0].model_copy(update={"documented_indication": None})
    pack.records[med.source.source_id] = med
    twin = med.model_copy(update={"provenance": "prescriptions" if med.provenance != "prescriptions" else "lists", "status": "inactive" if med.status != "inactive" else "active",
                                  "source": med.source.model_copy(update={"source_id": med.source.source_id + ":twin", "id": med.source.id + 1})})
    pack.records[twin.source.source_id] = twin
    lab = pack.responses["lab_results"].records[0].model_copy(update={"value_text": ">200", "numeric_value": None, "comparable": False})
    pack.records[lab.source.source_id] = lab
    lims = pack_limitations(pack)
    assert any(l["kind"] == "not_documented" and l["section"] == "medications" and "no documented indication" in l["detail"] and l["source_ids"] == [med.source.source_id] for l in lims)
    assert any(l["kind"] == "not_documented" and l["section"] == "labs" and "recorded as text" in l["detail"] for l in lims)
    conflict = [l for l in lims if l["kind"] == "conflict" and "differs across sources" in l["detail"]]
    assert conflict and set(conflict[0]["source_ids"]) == {med.source.source_id, twin.source.source_id}
