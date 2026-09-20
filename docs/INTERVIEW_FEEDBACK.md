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

## Outcome

The early submission was graded 100%, an A+, and the interviewer's overall
verdict was positive. Whether the interviewer and the grader were the same
person is not known, so the grade is recorded as the portal reported it and
not attributed to the interview.

Three substantive questions were asked. All three are closed below, and all
three turned out to name something real: one was a live bug in the cost
arithmetic, one was a threshold that needed the work behind it, and one was a
capacity question that was still a guess at the time.

## Rows

| Question | Answer given | Gap admitted | Disposition | Evidence |
| --- | --- | --- | --- | --- |
| Why did the latency target move from 8 s to 30 s? | The 8 s figure was a design goal; 30 s was set as the release gate so every early-submission requirement could be met first, with latency taken on deliberately afterwards rather than traded against correctness under deadline. | Yes — the number had moved and the work behind it had not been done yet. | `fix-now`, done | Latency work landed 2026-09-18/19: `max_plan_rounds` 3 → 1, follow-ups at low effort, the batched gateway. Model-backed p95 went 24.1 s at `a4a5856` to **15.8 s** in the release run (`evals/results/2026-09-20T051146Z-0f11642.md`) and 20.0 s in the parity run at the deployed tree; the baseline comparison is `…-0f11642-vs-a4a5856.md`. Separately, the brief is now prepared as the chart opens (ADR-0003 amendment, module 0.5.0), so the first answer is waiting rather than typed for — `KEY_METRICS.md` measures that as physician wait against reading lag, not as turn latency, because precomputing moves who waits rather than making the turn faster. Scoped to patients with a visit today by `BriefPolicy`; follow-ups are already much faster than a first turn. |
| In the dollar-cost helper, is there a problem with `tokens = input_tokens - cache_read_tokens`? | Yes: it can go negative with no validation, and dollars held as a float invites rounding error. | Yes, on the spot. | `fix-now`, done | Real bug, and the sign was not the worst of it: the subtraction was clamped at zero, so the uncached-input line priced at **$0 on every turn whose cache reads exceeded uncached input — which was every recorded eval turn**, under-counting cost by about 10%. Fixed in `fbea630` (2026-09-17 22:30 PT, ten hours after the interview): each usage class is now priced at its own rate with nothing subtracted from anything, and `evals/run.py:552` carries the old behaviour and its blast radius so the pre-`a4a5856` reports stay readable. The float point is acknowledged and not acted on: at four-decimal precision on sub-cent amounts the representation error is ~1e-16 relative, immaterial for a release gate, though it would matter if these numbers ever billed anyone. |
| What would fail first at 50 users? At 300? | Load testing had not been run yet. The stated guess was the database, on the reasoning that everything runs in Docker on one Droplet. Explicitly flagged as unverified. | Yes — the answer was a hypothesis, and was labelled as one. | `fix-now`, done | Run 2026-09-18 at 10 and 50 concurrent users (`docs/audit/evidence/performance/load-test-2026-09-18.md`, baselines in `baseline-2026-09-18.md`). The guess was half right: at 50 users `database` peaks at **111% of a vCPU** — so it is a bottleneck — but `openemr`'s own Apache/PHP peaks at **103%** alongside it, while the `agent` never exceeds 44%. A `--fault model` control run making zero model calls reproduced the same collapse, which places the ceiling in OpenEMR rather than in the agent or the provider. At 50 users 76% of turns degrade to `partial` rather than failing outright. 300 users was not tested; the droplet-tier comparison (`droplet-tier-comparison-2026-09-18.md`) measures what vertical scaling buys and the per-tier table in `AI_COST_ANALYSIS.md` says what breaks first at each level. Horizontal scale-out is designed and diagrammed (`docs/INTERVIEW_NOTES.md`, `8a97dfd`) and deliberately not implemented this week. |
