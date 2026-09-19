"""A/B a prompt change before deploying it: the real model, the real graph and
verifier, and the recorded AF-DQ-A2 gateway fixtures, so no stack is needed.
OLD is the prompt at a git ref, NEW is the working tree; both run against the
working tree's verifier and parser, so a difference is the prompt's. Prints the
share of model summaries that survive the summary gate, the replacement
reasons, rejected claims and repair rounds, system wording ("the pack", "window",
status words) in summaries and claim texts, output tokens and seconds per turn,
then the raw summaries side by side for reading.

    agent/.venv/bin/python evals/prompt_ab.py [<old-git-ref>=HEAD] [<reps>=1]

Costs about USD 0.03 per turn on the configured model (8 questions x reps x 2
prompts). The key is read from COPILOT_ANTHROPIC_API_KEY_FILE, default
~/.config/agentforge/anthropic_api_key. Env: AB_QUESTIONS="q1|q2" to narrow the
questions, AB_ONLY=NEW to skip the old prompt, AB_OUT=<file> to keep the rows.

The same harness compares two values of one agent setting under the working
tree's prompt, which is how a latency lever is measured before it ships:

    AB_SETTING=effort_followup:medium,low agent/.venv/bin/python evals/prompt_ab.py HEAD 2

One chart and a handful of questions: read it as a smoke test and a wording
check, not as a release gate; the live suite (evals/run.py) stays the gate."""

from __future__ import annotations

import ast
import asyncio
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CFG_DIR = Path.home() / ".config" / "agentforge"
os.environ.setdefault("COPILOT_ANTHROPIC_API_KEY_FILE", str(CFG_DIR / "anthropic_api_key"))
os.environ.setdefault("COPILOT_ANTHROPIC_WORKSPACE_ID_FILE", str(CFG_DIR / "anthropic_workspace_id"))
sys.path[:0] = [str(REPO / "agent"), str(REPO / "agent" / "tests")]

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app import budget, model as model_module  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.graph.nodes import Runtime  # noqa: E402
from app.graph.state import PER_TURN_DEFAULTS  # noqa: E402
from conftest import FakeGateway  # noqa: E402

QUESTIONS = [
    "What changed since the last visit?",
    "Can you catch me up on this patient?",
    "Are there earlier LDL results to compare?",
    "Why are they on all these medications?",
    "Any red flags in the labs?",
    "Do they have any allergies I should worry about?",
    "What does the most recent note say?",
    "Is there anything undocumented or unclear in this chart?",
]
if os.environ.get("AB_QUESTIONS"):
    QUESTIONS = os.environ["AB_QUESTIONS"].split("|")
SYSTEM_SPEAK = re.compile(r"\b(evidence pack|the pack|pack\b|window|not_documented|no_records_in_window|reviewed_none|tool)\b", re.IGNORECASE)


def prompts_at(ref: str) -> dict[str, str]:
    source = subprocess.run(["git", "-C", str(REPO), "show", f"{ref}:agent/app/model.py"], capture_output=True, text=True, check=True).stdout
    out: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("SYSTEM_PROMPT", "OUTPUT_INSTRUCTIONS") and node.targets[0].id not in out:
            out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


def coerce(current: object, text: str) -> object:
    """A setting value from the command line, as the type the setting already has."""
    if isinstance(current, bool):
        return text.lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(text)
    if isinstance(current, float):
        return float(text)
    return text


async def run_variant(name: str, prompts: dict[str, str], reps: int, setting: tuple[str, str] | None = None) -> list[dict]:
    model_module.SYSTEM_PROMPT = prompts["SYSTEM_PROMPT"]
    model_module.OUTPUT_INSTRUCTIONS = prompts["OUTPUT_INSTRUCTIONS"]
    if setting:
        attr, value = setting
        setattr(model_module.settings, attr, coerce(getattr(model_module.settings, attr), value))
    live = model_module.live_model()
    assert live is not None, "no API key file"
    rows: list[dict] = []
    sem = asyncio.Semaphore(4)

    async def one(i: int, question: str, rep: int) -> None:
        async with sem:
            thread = f"{abs(hash((name, i, rep))):032x}"[:32]
            graph = build_graph(Runtime(gateway=FakeGateway(), model=live, today=lambda: dt.date(2026, 9, 15)), checkpointer=InMemorySaver())
            state = dict(PER_TURN_DEFAULTS)
            state.update({"conversation_id": thread, "turn_id": f"{i:04x}{rep:04x}{abs(hash(name)) % 0xFFFFFFFF:08x}", "correlation_id": re.sub(r"[^A-Za-z0-9._-]", "-", f"ab-{name}-{i}-{rep}")[:64], "token": "t.t", "question": question, "fault": None})
            t0 = time.perf_counter()
            try:
                final = await graph.ainvoke(state, {"configurable": {"thread_id": thread}})
            except Exception as exc:  # noqa: BLE001
                rows.append({"variant": name, "question": question, "error": repr(exc)[:200]})
                return
            rows.append({
                "variant": name, "question": question, "rep": rep, "seconds": round(time.perf_counter() - t0, 1),
                "status": final.get("status"), "turn_type": final.get("turn_type"),
                "summary_basis": final.get("summary_basis"), "summary_reason": final.get("summary_reason"),
                "summary": final.get("summary"), "raw_summary": final.get("raw_summary"),
                "claims": [c["text"] for c in final.get("accepted") or []],
                "rejected": [(r["rule"], r.get("detail", "")[:60]) for r in final.get("rejected") or []],
                "repair": bool(final.get("repair_attempted")), "narrate_error": final.get("narrate_error"),
                "usage": final.get("usage") or {},
            })

    await asyncio.gather(*(one(i, q, rep) for i, q in enumerate(QUESTIONS) for rep in range(reps)))
    return rows


def report(rows: list[dict]) -> None:
    variants = list(dict.fromkeys(r["variant"] for r in rows))
    for variant in variants:
        rs = [r for r in rows if r["variant"] == variant and "error" not in r]
        kept = [r for r in rs if r["summary_basis"] == "model"]
        words = [len((r["raw_summary"] or "").split()) for r in rs if r["raw_summary"]]
        speak_summary = sum(1 for r in rs if SYSTEM_SPEAK.search(r["raw_summary"] or ""))
        speak_claims = sum(1 for r in rs for c in r["claims"] if SYSTEM_SPEAK.search(c))
        n_claims = sum(len(r["claims"]) for r in rs)
        rejected = [rule for r in rs for rule, _ in r["rejected"]]
        print(f"\n##### {variant}: turns={len(rs)} errors={sum(1 for r in rows if r['variant'] == variant and 'error' in r)}")
        print(f"  model summary kept: {len(kept)}/{len(rs)}   replaced reasons: {[r['summary_reason'] for r in rs if r['summary_basis'] != 'model']}")
        print(f"  raw summary words: mean {sum(words) / max(1, len(words)):.0f}  min {min(words or [0])}  max {max(words or [0])}")
        print(f"  system-speak: {speak_summary}/{len(rs)} summaries, {speak_claims}/{n_claims} claim texts")
        print(f"  rejected claims: {len(rejected)} {sorted(set(rejected))}   repairs: {sum(r['repair'] for r in rs)}")
        print(f"  output tokens/turn: {sum(r['usage'].get('output_tokens', 0) for r in rs) / max(1, len(rs)):.0f}   seconds/turn: {sum(r['seconds'] for r in rs) / max(1, len(rs)):.1f}")
    print("\n================ side by side (raw model summary; [basis/reason])")
    for q in QUESTIONS:
        print(f"\nQ: {q}")
        for variant in variants:
            for r in [r for r in rows if r["variant"] == variant and r["question"] == q]:
                if "error" in r:
                    print(f"  {variant}: ERROR {r['error']}")
                else:
                    print(f"  {variant} [{r['summary_basis']}/{r['summary_reason']}] {r['raw_summary']}")


async def main() -> None:
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    new = {"SYSTEM_PROMPT": model_module.SYSTEM_PROMPT, "OUTPUT_INSTRUCTIONS": model_module.OUTPUT_INSTRUCTIONS}
    old = prompts_at(ref)
    assert os.environ.get("AB_SETTING") or os.environ.get("AB_ONLY") == "NEW" or old["SYSTEM_PROMPT"] != new["SYSTEM_PROMPT"], "prompts are identical"
    budget.daily.reset()
    if os.environ.get("AB_SETTING"):
        attr, _, values = os.environ["AB_SETTING"].partition(":")
        assert hasattr(model_module.settings, attr), f"no such setting: {attr}"
        rows = []
        for value in values.split(","):
            rows += await run_variant(f"{attr}={value}", new, reps, (attr, value))
    else:
        rows = [] if os.environ.get("AB_ONLY") == "NEW" else await run_variant("OLD", old, reps)
        rows += await run_variant("NEW", new, reps)
    if os.environ.get("AB_OUT"):
        Path(os.environ["AB_OUT"]).write_text(json.dumps(rows, indent=1))
    report(rows)


asyncio.run(main())
