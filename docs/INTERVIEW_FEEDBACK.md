# Interview Feedback

Record of the technical interview (2026-09-17, 12:00 to 12:15 PT). One row per
question actually asked. The owner fills this in within an hour of the
interview; it is empty until then, and empty is the correct state before the
interview.

## Disposition rule

Every row gets exactly one disposition, chosen by what the answer revealed —
not by how the answer felt:

- **`fix-now`** — the gap is real, it is documentation or a bounded change
  inside `agent/`, `evals/`, `infra/`, `contracts/` or `docs/`, and it can land
  before the Sunday freeze. Add it to `docs/FINAL_SUBMISSION_TODOS.md` with a
  priority.
- **`week2`** — the gap is real but needs a design decision, a new dependency,
  a schema change, or a run that spends model budget. Add it to
  `docs/WEEK2_HANDOFF.md`. Do not start it this week.
- **`doc-only`** — the control or behaviour already exists and the interviewer
  was reacting to a document that describes it wrongly. Fix the document, not
  the code, and name the file and line in the evidence column.
- **`wont-do`** — settled by an accepted ADR (ADR-0002 parity authorization,
  ADR-0003 in-process module gateway, ADR-0004 LangGraph and Sonnet 5) or
  explicitly out of scope in `USERS.md`. Record the ADR and the revisit
  trigger; do not re-litigate it.
- **`answered`** — no gap. The answer was complete and evidence-backed, and
  nothing follows from it.

Two standing constraints on every `fix-now`: no change to the prompt, model id,
effort setting, planning rounds or verifier lexicon without a baseline run, the
change, a second run and an `evals/compare.py` diff; and nothing is written
down as implemented unless it is implemented.

## Rows

| Question | Answer given | Gap admitted | Disposition | Evidence |
| --- | --- | --- | --- | --- |
