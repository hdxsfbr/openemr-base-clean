#!/usr/bin/env python3
"""Local review UI for error-analysis journals (evals/error_analysis.py).

A small, local-only tool for you (and an SME sitting with you) to read through a journal's
traces and fill in First issue / Notes without hand-editing markdown. It reads and writes the
exact same evals/error_analysis/*.md files the CLI does — this is a nicer way to edit that
format, not a second source of truth. It does not score or categorize anything: those stayed
out on purpose (see evals/README.md "Error Analysis" and error_analysis.py's docstring).

    agent/.venv/bin/python evals/review_ui.py
    agent/.venv/bin/python evals/review_ui.py --dir evals/error_analysis --port 8765

Then open http://127.0.0.1:8765/ in a browser. Bound to localhost only — this is meant to be
run on your machine with someone looking at your screen, not exposed to a network.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from error_analysis import JOURNAL_DIR, parse_journal, write_entry  # noqa: E402

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

app = FastAPI(title="Error Analysis Review")
JOURNALS_DIR = JOURNAL_DIR  # overridable via main() for --dir


def _safe_path(name: str) -> Path:
    """name must be a bare filename inside JOURNALS_DIR — no path traversal via '..' or '/'."""
    if name != Path(name).name or not name.endswith(".md"):
        raise HTTPException(400, "invalid journal name")
    path = JOURNALS_DIR / name
    if not path.is_file():
        raise HTTPException(404, "journal not found")
    return path


@app.get("/api/journals")
def list_journals() -> list[dict]:
    out = []
    for path in sorted(JOURNALS_DIR.glob("*.md"), reverse=True):
        entries = parse_journal(path)
        out.append({
            "name": path.name,
            "total": len(entries),
            "reviewed": sum(1 for e in entries if e.first_issue or e.notes or e.reviewed_by),
            "with_issue": sum(1 for e in entries if e.first_issue),
        })
    return out


@app.get("/api/journals/{name}")
def get_journal(name: str) -> list[dict]:
    path = _safe_path(name)
    return [
        {"index": e.index, "patient": e.patient, "question": e.question,
         "first_issue": e.first_issue, "notes": e.notes, "reviewed_by": e.reviewed_by,
         "raw": e.raw}
        for e in parse_journal(path)
    ]


@app.get("/api/journals/{name}/report")
def get_report(name: str) -> list[dict]:
    path = _safe_path(name)
    return [
        {"patient": e.patient, "question": e.question, "issue": e.first_issue}
        for e in parse_journal(path) if e.first_issue
    ]


class EntryUpdate(BaseModel):
    first_issue: str | None = None
    notes: str | None = None
    reviewer: str | None = None


@app.post("/api/journals/{name}/entries/{index}")
def update_entry(name: str, index: int, body: EntryUpdate) -> dict:
    path = _safe_path(name)
    try:
        e = write_entry(path, index, first_issue=body.first_issue, notes=body.notes, reviewer=body.reviewer)
    except KeyError:
        raise HTTPException(404, f"no entry {index} in {name}")
    return {"index": e.index, "patient": e.patient, "question": e.question,
            "first_issue": e.first_issue, "notes": e.notes, "reviewed_by": e.reviewed_by}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE


_PAGE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Error Analysis Review</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, system-ui, sans-serif; background: #f7f7f5; color: #1a1a1a; }
  #app { display: flex; height: 100vh; }
  #sidebar { width: 340px; border-right: 1px solid #ddd; display: flex; flex-direction: column; background: #fff; }
  #sidebar-header { padding: 12px; border-bottom: 1px solid #eee; }
  #sidebar-header select { width: 100%; padding: 6px; margin-bottom: 8px; }
  #progress { font-size: 12px; color: #555; }
  #filters { display: flex; gap: 6px; padding: 8px 12px; border-bottom: 1px solid #eee; flex-wrap: wrap; }
  #filters button { font-size: 11px; padding: 3px 8px; border: 1px solid #ccc; background: #f0f0f0; border-radius: 12px; cursor: pointer; }
  #filters button.active { background: #2563eb; color: #fff; border-color: #2563eb; }
  #list { flex: 1; overflow-y: auto; }
  .item { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; cursor: pointer; font-size: 13px; }
  .item:hover { background: #f5f7ff; }
  .item.selected { background: #e8edff; border-left: 3px solid #2563eb; }
  .item .q { color: #444; }
  .item .meta { display: flex; justify-content: space-between; margin-bottom: 2px; }
  .item .patient { font-weight: 600; color: #333; }
  .badge { font-size: 14px; }
  #main { flex: 1; overflow-y: auto; padding: 24px 32px; max-width: 780px; }
  #main h2 { margin-top: 0; }
  .section-label { font-weight: 600; font-size: 12px; text-transform: uppercase; color: #888; margin: 18px 0 6px; }
  .claim, .lim { padding: 4px 0; font-size: 14px; border-bottom: 1px dotted #eee; }
  .summary-box { background: #fafafa; border: 1px solid #eee; border-radius: 6px; padding: 10px 12px; font-size: 14px; }
  details summary { cursor: pointer; color: #666; font-size: 12px; margin-top: 8px; }
  .field-label { font-weight: 600; margin-top: 18px; display: block; }
  .hint { color: #888; font-size: 12px; font-weight: normal; }
  input[type=text], textarea { width: 100%; padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 4px; margin-top: 4px; font-family: inherit; }
  textarea { min-height: 60px; }
  .toolbar { display: flex; gap: 8px; margin-top: 16px; align-items: center; }
  button.primary { background: #2563eb; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-size: 14px; }
  button.secondary { background: #fff; border: 1px solid #ccc; padding: 8px 14px; border-radius: 4px; cursor: pointer; font-size: 14px; }
  button.secondary:disabled { opacity: 0.4; cursor: default; }
  #saved-flash { color: #0a7; font-size: 13px; margin-left: 8px; opacity: 0; transition: opacity 0.3s; }
  #reviewer-box { padding: 12px; border-top: 1px solid #eee; font-size: 12px; }
  #reviewer-box input { padding: 4px; font-size: 12px; }
  #export-pane { white-space: pre-wrap; background: #fff; border: 1px solid #ddd; padding: 12px; font-size: 13px; font-family: ui-monospace, monospace; max-height: 300px; overflow-y: auto; }
</style>
</head>
<body>
<div id="app">
  <div id="sidebar">
    <div id="sidebar-header">
      <select id="journal-select"></select>
      <div id="progress"></div>
    </div>
    <div id="filters">
      <button data-filter="all" class="active">All</button>
      <button data-filter="unreviewed">Unreviewed</button>
      <button data-filter="issue">Has issue</button>
      <button data-filter="noissue">Reviewed, no issue</button>
    </div>
    <div id="list"></div>
    <div id="reviewer-box">
      Reviewer name: <input id="reviewer-name" type="text" placeholder="e.g. Dr. Lee">
    </div>
  </div>
  <div id="main"><p style="color:#888">Pick a journal to begin.</p></div>
</div>
<script>
let journalName = null, entries = [], selectedIndex = null, filter = 'all';

const reviewerInput = document.getElementById('reviewer-name');
reviewerInput.value = localStorage.getItem('reviewerName') || '';
reviewerInput.addEventListener('input', () => localStorage.setItem('reviewerName', reviewerInput.value));

async function loadJournalList() {
  const journals = await (await fetch('/api/journals')).json();
  const sel = document.getElementById('journal-select');
  sel.innerHTML = journals.map(j =>
    `<option value="${j.name}">${j.name} (${j.reviewed}/${j.total} reviewed, ${j.with_issue} issues)</option>`
  ).join('');
  if (journals.length) {
    sel.value = journalName || journals[0].name;
    await loadJournal(sel.value);
  }
  sel.onchange = () => loadJournal(sel.value);
}

function status(e) {
  if (e.first_issue) return 'issue';
  if (e.reviewed_by || e.notes) return 'noissue';
  return 'unreviewed';
}
const badge = { issue: '⚠️', noissue: '✅', unreviewed: '⚪' };

async function loadJournal(name) {
  journalName = name;
  entries = await (await fetch(`/api/journals/${name}`)).json();
  selectedIndex = entries.length ? entries[0].index : null;
  renderList();
  renderMain();
  updateProgress();
}

function updateProgress() {
  const reviewed = entries.filter(e => e.first_issue || e.notes || e.reviewed_by).length;
  document.getElementById('progress').textContent = `${reviewed}/${entries.length} reviewed`;
}

function renderList() {
  const list = document.getElementById('list');
  const visible = entries.filter(e => filter === 'all' || status(e) === filter);
  list.innerHTML = visible.map(e => `
    <div class="item ${e.index === selectedIndex ? 'selected' : ''}" data-index="${e.index}">
      <div class="meta"><span class="patient">${e.patient}</span><span class="badge">${badge[status(e)]}</span></div>
      <div class="q">${e.question}</div>
    </div>
  `).join('') || '<p style="padding:12px;color:#888;font-size:13px">Nothing matches this filter.</p>';
  list.querySelectorAll('.item').forEach(el => el.onclick = () => {
    selectedIndex = parseInt(el.dataset.index, 10);
    renderList(); renderMain();
  });
}

document.querySelectorAll('#filters button').forEach(btn => btn.onclick = () => {
  document.querySelectorAll('#filters button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filter = btn.dataset.filter;
  renderList();
});

function renderMain() {
  const main = document.getElementById('main');
  const e = entries.find(x => x.index === selectedIndex);
  if (!e) { main.innerHTML = '<p style="color:#888">No trace selected.</p>'; return; }

  const claimLines = (e.raw.match(/\*\*Claims:\*\*\n([\s\S]*?)\n\n/) || ['', ''])[1];
  const limLines = (e.raw.match(/\*\*Limitations:\*\*\n([\s\S]*?)\n\n/) || ['', ''])[1];
  const summaryMatch = e.raw.match(/\*\*Summary:\*\* (.*)/);
  const evMatch = e.raw.match(/\*\*Evidence:\*\* (.*)/);
  const statusMatch = e.raw.match(/^Status: (.*)$/m);

  main.innerHTML = `
    <h2>${e.patient} — "${e.question}"</h2>
    <div style="color:#888;font-size:13px">${statusMatch ? statusMatch[1] : ''}</div>

    <div class="section-label">What the clinician would see</div>
    <div class="summary-box">${summaryMatch ? summaryMatch[1] : '(none shown)'}</div>

    <details open>
      <summary>Claims &amp; limitations (${claimLines.split('\n').filter(l => l.trim()).length} claims)</summary>
      ${claimLines.split('\n').filter(l => l.trim()).map(l => `<div class="claim">${l.replace(/^\s*-\s*/, '')}</div>`).join('')}
      ${limLines.split('\n').filter(l => l.trim() && l.trim() !== '- (none)').map(l => `<div class="lim">${l.replace(/^\s*-\s*/, '')}</div>`).join('')}
    </details>
    <details>
      <summary>Evidence (tool status)</summary>
      <div style="font-size:13px;color:#555">${evMatch ? evMatch[1] : ''}</div>
    </details>

    <label class="field-label">First issue <span class="hint">— stop at the first thing that looks wrong; leave blank if the turn looks right; do not list a second one</span></label>
    <input type="text" id="first-issue" value="${(e.first_issue || '').replace(/"/g, '&quot;')}">

    <label class="field-label">Notes <span class="hint">— anything else worth remembering, not a second issue</span></label>
    <textarea id="notes">${e.notes || ''}</textarea>

    <div class="toolbar">
      <button class="primary" id="save-btn">Save</button>
      <button class="secondary" id="save-noissue-btn">Mark reviewed, no issue</button>
      <button class="secondary" id="prev-btn" ${entries[0].index === e.index ? 'disabled' : ''}>&larr; Prev</button>
      <button class="secondary" id="next-btn" ${entries[entries.length - 1].index === e.index ? 'disabled' : ''}>Next &rarr;</button>
      <span id="saved-flash">Saved</span>
    </div>
  `;

  document.getElementById('save-btn').onclick = () => save(e.index);
  document.getElementById('save-noissue-btn').onclick = () => {
    document.getElementById('first-issue').value = '';
    save(e.index);
  };
  document.getElementById('prev-btn').onclick = () => step(-1);
  document.getElementById('next-btn').onclick = () => step(1);
}

function step(delta) {
  const idx = entries.findIndex(x => x.index === selectedIndex);
  const next = entries[idx + delta];
  if (next) { selectedIndex = next.index; renderList(); renderMain(); }
}

async function save(index) {
  const first_issue = document.getElementById('first-issue').value;
  const notes = document.getElementById('notes').value;
  const reviewer = reviewerInput.value || null;
  const resp = await fetch(`/api/journals/${journalName}/entries/${index}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ first_issue, notes, reviewer })
  });
  const updated = await resp.json();
  const i = entries.findIndex(x => x.index === index);
  entries[i] = { ...entries[i], ...updated };
  renderList();
  updateProgress();
  const flash = document.getElementById('saved-flash');
  flash.style.opacity = 1;
  setTimeout(() => flash.style.opacity = 0, 900);
}

document.addEventListener('keydown', (ev) => {
  if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'TEXTAREA') return;
  if (ev.key === 'ArrowRight' || ev.key === 'j') step(1);
  if (ev.key === 'ArrowLeft' || ev.key === 'k') step(-1);
});

loadJournalList();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(JOURNAL_DIR), help="directory of journal .md files")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="bind address; 0.0.0.0 exposes this to the network — there is no auth, so only do that on a network you trust")
    args = ap.parse_args()

    global JOURNALS_DIR
    JOURNALS_DIR = Path(args.dir)
    if not JOURNALS_DIR.is_dir():
        print(f"no such directory: {JOURNALS_DIR}", file=sys.stderr)
        return 2

    import uvicorn
    print(f"Serving journals from {JOURNALS_DIR} — open http://{args.host}:{args.port}/ (or http://127.0.0.1:{args.port}/ locally)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
