# Follow-up effort: medium vs low (2026-09-19)

`output_config.effort` sets how much the model thinks before it answers, and
thinking tokens are output tokens: they are paid for in seconds. First turns
run at `low` (`settings.effort_first_turn`), follow-ups at `medium`
(`effort_followup`, which also sets the effort of the `plan` call and of a
follow-up's repair round).

## Why look

The first live follow-up after the 2026-09-19 deploy took about 24 s, nearly
all of it in `narrate`: 2,220 output tokens for about 640 tokens of visible
JSON, so roughly 70% of the call was thinking (estimated from the length of
the visible text; the API does not report the split). The first turn beside it,
at `low`: 1,976 output tokens for about 850 visible.

## Measured

`AB_SETTING=effort_followup:medium,low evals/prompt_ab.py HEAD 2`: the real
model, graph, verifier and parser on the AF-DQ-A2 fixtures, the working tree's
prompt (`2287bd6c24f4`), seven follow-up questions, two runs each.

| | medium | low |
|---|---|---|
| Turns | 14 | 14 |
| Seconds per turn | 18.1 | 11.9 (-34%) |
| Output tokens per turn | 1,788 | 1,231 (-31%) |
| Model summaries kept | 10 | 11 |
| Claims rejected after repair / repair rounds | 2 / 3 | 1 / 4 |
| Claims per turn | 4.9 | 3.9 |
| System wording in summaries | 0 | 0 |

Per question (claims, seconds; medium / low): catch me up 10 / 10, 26.2 /
20.6; why on these medications 7 / 3, 18.4 / 8.3; red flags in the labs 6 / 4,
13.3 / 9.2; most recent note 3.5 / 3.5, 20.6 / 7.3; undocumented or unclear
8 / 6, 38.2 / 27.2; allergies 0 / 0.5, 7.5 / 7.8. The LDL question returned
nothing in 4 of 4 runs in both arms, which was not effort: the planner's
garbled optional parameters cancelled the retrieval (fixed the same day,
`bea1c00`).

## Reading it

- The time and token savings are large and consistent across questions.
- Verification did not get worse: rejections and kept summaries are level.
- `low` writes fewer claims. On "undocumented or unclear" that was an
  improvement (medium listed labs and a medication start that were neither).
  On "why are they on these medications" one `low` run left out the claims that
  the notes mention lisinopril and amlodipine without a reason, which is the
  substance of UC-03. One run of one question is not a rate, but it is the
  risk to watch.

## Decision

`effort_followup` is set to `low`. The check is the live suite: its task
success gate (model recall on the planted findings, UC-02 and UC-03 included)
and `claims_per_turn` against the 2026-09-19 run at `medium`
(`evals/results/2026-09-19T223524Z-12cd849a.json`: 100% recall, 4.21 claims per
turn, follow-up p50 8.1 s and p95 12.3 s). If recall drops, the setting goes
back: `COPILOT_EFFORT_FOLLOWUP=medium` needs no code change.

## The live suite at low (same day)

Commit `f4f69ab`, GitLab job 77550, the full run with the holdout set
(`evals/results/2026-09-19T230512Z-f4f69ab4.json`) against the run at
`medium` two hours earlier (`12cd849a`), by `evals/compare.py`:

| | medium (`12cd849a`) | low (`f4f69ab4`) |
|---|---|---|
| Cases passed | 47 of 48 | 48 of 48 |
| Blocking gates | all PASS | all PASS |
| Task success (model recall) | 100% | 100% |
| Claims per turn | 4.21 | 4.10 |
| Model summary share | 81.0% | 88.1% |
| Repair rate / withheld rate | 14.3% / 1.1% | 19.0% / 1.7% |
| Follow-up p50 / p95 | 8.1 s / 12.3 s | 7.2 s / 11.9 s |
| Cost per model-backed turn | $0.0116 | $0.0111 |
| First-turn p50 / p95 | 9.5 s / 18.0 s | 9.2 s / 24.8 s |

- Recall held at 100% and claims per turn barely moved, so the concern from
  the fixture run (fewer claims on the medication question) did not show up
  as a lost finding. The setting stays at `low`.
- The follow-up gain is about 11% at the median here, not the 34% of the
  fixture run: the suite's follow-ups are lighter questions than the fixture
  bank's, with less thinking to save.
- Repairs went from 6 to 8 of 42 turns. Small numbers, but it is the direction
  less thinking would push, and it is the number to watch.
- First turns do not use this setting (`effort_first_turn` was already
  `low`), so the first-turn p95 moving from 18.0 s to 24.8 s is not this
  change: with 24 first turns the p95 is one slow turn, and the median fell.
- `CONF-DUP-NAMES-C2-001` passed this time with no prompt change, so its
  failure in the earlier run was wording that varies run to run, not a fixed
  defect and not now a fixed one. It stays a holdout case nobody tunes on.
