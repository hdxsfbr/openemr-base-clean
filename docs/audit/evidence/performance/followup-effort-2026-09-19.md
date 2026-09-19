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
