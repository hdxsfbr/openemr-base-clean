#!/usr/bin/env python3
"""Error-analysis journal (Evals Lecture 1, Stage 3): a human — ideally an engineer plus a
domain-adjacent reviewer — reads real traces and writes down the *first* issue in each one,
nothing more. This script is deliberately not an LLM: Aaron's lecture and Byron's deck both
say finding the issue is a manual step, because an LLM does not reliably know what to look for
in a system nobody has scripted yet.

This is not a replacement for the curated cases in evals/cases/ — those probe known, named
boundaries. This is for the opposite blind spot: questions nobody scripted, asked the way a
clinician might actually phrase them, so gaps in the fixed case matrix surface before a user
finds them.

Workflow
--------

1. `sample` drives the deployed co-pilot with unscripted questions across a spread of cohort
   patients and writes a journal file with blank annotation fields:

       python evals/error_analysis.py sample --base-url https://host -n 20

   Each entry gets exactly two blank fields to fill by hand: **First issue** (stop at the
   first thing that looks wrong — do not keep reading and do not list more than one) and
   **Notes** (anything else worth remembering, not a second issue).

2. Open the journal, read each trace, fill in the two fields. Leave "First issue" blank when
   the turn looks right. Do not score, do not categorize yet — that is the next step, and
   doing it now anchors you on the first pattern you notice instead of the real distribution.

3. Once you have a batch (Byron's lecture: aim for around 100 filled issues before trying to
   see the shape of it, fewer is fine to start):

       python evals/error_analysis.py report --journal evals/error_analysis/<file>.md

   This prints every filled-in issue as a flat, numbered list — nothing clustered. Paste that
   list into a chat and ask for categories, the same way the lecture demoed it: categorizing
   after the fact is fine to delegate, finding the issue in the first place is not. Recurring
   categories become new cases in evals/cases/ (evals/README.md "Required Case Metadata").

Traces and journals hold synthetic af-cohort-v1 content only; never point --base-url at a
deployment with real patient data.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import Session  # noqa: E402  (reuse the same login/open_chart/turn plumbing as run.py)

ROOT = Path(__file__).resolve().parents[1]
JOURNAL_DIR = ROOT / "evals" / "error_analysis"
COHORT_PATH = ROOT / "evals" / "cases" / "cohort.json"

# Deliberately not the wording already scripted in evals/cases/*.yaml (see that grep before
# adding to this list) — the point is to probe phrasing nobody wrote a case for yet.
QUESTION_BANK = [
    "Can you catch me up on this patient?",
    "Anything new I should know about before I go in?",
    "What's changed with their meds recently?",
    "Any red flags in the labs?",
    "Why are they on all these medications?",
    "Has anything been flagged as abnormal?",
    "What's the story with their kidney function?",
    "Do they have any allergies I should worry about?",
    "When did we last see them?",
    "Is there anything undocumented or unclear in this chart?",
    "What does the most recent note say?",
    "Summarize their active problems.",
    "Are there any conflicting entries in this chart?",
    "What should I bring up at this visit?",
    "Has their blood pressure been an issue?",
]


def sample(base_url: str, password: str, n: int, seed: int | None) -> Path:
    cohort = json.loads(COHORT_PATH.read_text())
    patients = [p for p in cohort if not p.startswith("AF-ACL")]  # ACL fixtures are authorization-only, not chart content
    rng = random.Random(seed)
    picks = [(rng.choice(QUESTION_BANK), rng.choice(patients)) for _ in range(n)]

    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    path = JOURNAL_DIR / f"{stamp}-journal.md"
    lines = [
        f"# Error-analysis journal {stamp}",
        "",
        f"{n} unscripted turns across {len(set(p for _, p in picks))} patients, dataset `af-cohort-v1`.",
        "",
        "For each trace: read it, then fill in **First issue** (stop at the first thing that "
        "looks wrong; leave blank if the turn looks right) and **Notes**. One issue per trace, "
        "no scoring, no categorizing yet — see the docstring in evals/error_analysis.py.",
        "",
    ]
    for i, (question, patient) in enumerate(picks, start=1):
        session = Session(base_url, "audit-physician", password, cohort)
        try:
            session.open_chart(patient)
            session.start()
            resp, latency_ms = session.turn(question)
            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                body = {"_raw_status": resp.status_code}
        except Exception as exc:  # noqa: BLE001 - one bad trace must not stop the sample
            body = {"_error": f"{exc.__class__.__name__}: {str(exc)[:200]}"}
            latency_ms = 0.0
        finally:
            session.close()
        lines += _entry(i, patient, question, body, latency_ms)
        print(f"[{i}/{n}] {patient}: {question}")
    path.write_text("\n".join(lines) + "\n")
    print(f"\nJournal written: {path.relative_to(ROOT)}")
    print("Open it, read each trace, and fill in First issue / Notes by hand before running `report`.")
    return path


def _entry(i: int, patient: str, question: str, body: dict[str, Any], latency_ms: float) -> list[str]:
    claims = body.get("claims") or []
    claim_lines = [f"  - `{c.get('type')}` {c.get('text', '')}" for c in claims] or ["  - (none)"]
    limitations = body.get("limitations") or []
    lim_lines = [f"  - {l.get('kind')}: {l.get('detail', '')}" for l in limitations] or ["  - (none)"]
    evidence = body.get("evidence") or []
    ev_line = ", ".join(f"{e.get('tool')}={e.get('status')}" for e in evidence) or "(none)"
    return [
        f"## {i}. {patient} — {question}",
        "",
        f"Status: `{body.get('status', body.get('_error', '?'))}` · latency {latency_ms:.0f} ms · "
        f"model calls {(body.get('usage') or {}).get('model_calls', '?')}",
        "",
        "**Claims:**",
        *claim_lines,
        "",
        "**Summary:** " + (body.get("summary") or "(none shown)"),
        "",
        "**Limitations:**",
        *lim_lines,
        "",
        f"**Evidence:** {ev_line}",
        "",
        "**First issue (one only, blank if none):** ",
        "",
        "**Notes:** ",
        "",
        "---",
        "",
    ]


HEADER_RE = re.compile(r"^##\s*(\d+)\.\s*(\S+)\s*—\s*(.+)$")
FIRST_ISSUE_LABEL = "First issue (one only, blank if none)"
NOTES_LABEL = "Notes"
REVIEWED_BY_LABEL = "Reviewed by"


@dataclass
class JournalEntry:
    """One trace in a journal, as the review UI and `report` both need it. `raw` is the exact
    on-disk block text (header line through, but not including, the next entry's header) —
    write_entry patches specific lines inside it rather than reconstructing the block, so a
    save never touches formatting it didn't ask to change."""

    index: int
    patient: str
    question: str
    first_issue: str
    notes: str
    reviewed_by: str
    raw: str


def _field(block: str, label: str) -> str:
    # [ \t]* only (not \s*): \s* would cross the following blank line into the next field when
    # this one is empty, since . does not match \n but \s does.
    m = re.search(r"\*\*" + re.escape(label) + r":\*\*[ \t]*(.*)", block)
    return m.group(1).strip() if m else ""


def _entry_spans(text: str) -> list[tuple[int, int]]:
    """Byte ranges of every '## N. patient — question' block, from its header to the next
    header (or EOF). Skips the file's own header/instructions preamble."""
    starts = [m.start() for m in re.finditer(r"^## \d+\.", text, re.MULTILINE)]
    return [(s, starts[i + 1] if i + 1 < len(starts) else len(text)) for i, s in enumerate(starts)]


def parse_journal(path: Path) -> list[JournalEntry]:
    text = path.read_text()
    entries = []
    for s, e in _entry_spans(text):
        block = text[s:e]
        header = HEADER_RE.match(block.splitlines()[0])
        if not header:
            continue
        idx, patient, question = header.groups()
        entries.append(JournalEntry(
            index=int(idx), patient=patient, question=question,
            first_issue=_field(block, FIRST_ISSUE_LABEL),
            notes=_field(block, NOTES_LABEL),
            reviewed_by=_field(block, REVIEWED_BY_LABEL),
            raw=block,
        ))
    return entries


def write_entry(path: Path, index: int, *, first_issue: str | None = None, notes: str | None = None, reviewer: str | None = None) -> JournalEntry:
    """Update one entry's fields in place. Re-reads the file fresh (not a cached copy) and
    writes back atomically, so a concurrent hand-edit or a second browser tab can't be silently
    lost — the read-modify-write window is as short as one function call. Fields left as None
    (vs. an explicit empty string) are left untouched."""
    text = path.read_text()
    spans = _entry_spans(text)
    for s, e in spans:
        block = text[s:e]
        header = HEADER_RE.match(block.splitlines()[0])
        if not header or int(header.group(1)) != index:
            continue
        lines = block.split("\n")

        def _set(label: str, value: str, insert_after_label: str | None = None) -> None:
            prefix = f"**{label}:** "
            for i, line in enumerate(lines):
                if line.startswith(f"**{label}:**"):
                    lines[i] = prefix + value
                    return
            # Label not present yet (an older journal without a Reviewed-by line): insert a new
            # line right after the anchor label's line.
            for i, line in enumerate(lines):
                if insert_after_label and line.startswith(f"**{insert_after_label}:**"):
                    lines.insert(i + 1, prefix + value)
                    return

        if first_issue is not None:
            _set(FIRST_ISSUE_LABEL, first_issue)
        if notes is not None:
            _set(NOTES_LABEL, notes)
        if reviewer is not None:
            _set(REVIEWED_BY_LABEL, reviewer, insert_after_label=NOTES_LABEL)
        new_block = "\n".join(lines)
        new_text = text[:s] + new_block + text[e:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(new_text)
        tmp.replace(path)  # atomic on POSIX
        updated = parse_journal(path)
        return next(en for en in updated if en.index == index)
    raise KeyError(f"no entry {index} in {path}")


def report(journal_paths: list[Path]) -> None:
    issues: list[tuple[str, str, str]] = []  # (patient, question, issue text)
    for path in journal_paths:
        for entry in parse_journal(path):
            if entry.first_issue:
                issues.append((entry.patient, entry.question, entry.first_issue))
    if not issues:
        print("No filled-in 'First issue' entries found. Fill in the journal(s) before running report.")
        return
    print(f"{len(issues)} issue(s) found across {len(journal_paths)} journal(s).\n")
    print("Paste the numbered list below into a chat and ask for categories — that step is fine "
          "to delegate; finding each issue by hand is the part that isn't.\n")
    for i, (patient, question, issue) in enumerate(issues, start=1):
        print(f"{i}. [{patient}: {question!r}] {issue}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample", help="drive unscripted questions and write a blank journal")
    s.add_argument("--base-url", default="https://openemr-137-184-4-22.sslip.io")
    s.add_argument("--password-file", default="-", help="file with the demo password, or '-' for DEMO_PASSWORD env var")
    s.add_argument("-n", type=int, default=20, help="number of traces to sample")
    s.add_argument("--seed", type=int, default=None, help="for a reproducible sample; omit for a fresh random draw")

    r = sub.add_parser("report", help="print filled-in issues from one or more journals, ready to paste for categorization")
    r.add_argument("--journal", nargs="+", required=True, help="journal markdown file(s)")

    args = ap.parse_args()
    if args.cmd == "sample":
        import os
        password = os.environ.get("DEMO_PASSWORD", "") if args.password_file == "-" else Path(args.password_file).read_text().strip()
        if not password:
            print("a demo password is required (DEMO_PASSWORD or --password-file)", file=sys.stderr)
            return 2
        sample(args.base_url, password, args.n, args.seed)
    elif args.cmd == "report":
        report([Path(p) for p in args.journal])
    return 0


if __name__ == "__main__":
    sys.exit(main())
