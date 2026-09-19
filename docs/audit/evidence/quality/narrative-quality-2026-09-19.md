# Narrative quality: what was wrong and what changed (2026-09-19)

The owner's report after a debugging session on 2026-09-18: the lead paragraph
of many answers was terse, read oddly, and sometimes said nothing. This page
records what the traces showed, the four changes made, and what was measured.

## What the traces showed

Langfuse held no content at that point (digest mask), so the session was
reconstructed from trace metadata joined to the agent's PHI-free log lines by
correlation id: 10 manual sessions, 79 turns.

| Finding | Number |
|---|---|
| Turns whose model summary was discarded and replaced | 19 of 79 (24%) |
| Reasons: `ungrounded_number` / `claims_withheld` / `empty` / `no_verified_claims` / lexicon | 8 / 4 / 3 / 2 / 2 |
| Replaced summaries that were follow-up turns | 16 of 19 |
| First-turn narrate calls stopped by the 1,800-token output cap | 10% |
| First turn with a cut-off call (second call needed) vs without, p50 | 26.0 s vs 9.2 s |

What replaced a discarded summary was a count of claim types: "The chart shows
1 change, 1 documented reference and 1 reading across the chart." The same
sentence is 6 of the 20 entries in `evals/error_analysis/2026-09-16T190727Z-journal.md`.
Summaries that did survive used the prompt's own vocabulary: "the evidence
pack shows", "no records in the window".

## Changes

1. **Output cap 1,800 to 3,200 tokens** (`5d90982`). Thinking tokens count
   toward the cap; a cut-off JSON object paid for a second full call.
2. **Summary gate grounds dates as dates, numbers in canonical form; the
   fallback restates the first verified claims** (`e873a10`, ADR-0006
   decision 7 amended). "September 3, 2026" now matches a claim's `2026-09-03`
   and "October 3, 2026" does not. The digits of a claim's date or source id no
   longer ground a loose number.
3. **One malformed claim costs that claim, not the turn** (`f5fed01`). Found
   while testing change 4: an interpretation claim with `reading` beside
   `facts` and no `text` failed validation of the whole output.
4. **Prompt** (`prompt_version` `23000aa4a50a` to `2287bd6c24f4`). The
   summary is two to four sentences written for the physician ("the chart", never "the pack", "the window", a tool, or a status
   word), with dates as `YYYY-MM-DD` and no date or number a claim does not
   carry; claim `text` follows the same wording rule. The verifier's word
   filter is stated in plain words, generated from the same module
   (`FORBIDDEN_PLAIN`, `SUMMARY_FORBIDDEN_PLAIN`, held to the patterns by
   `tests/test_summary.py`), on top of the rules and not instead of them. The
   `documented_reference` line now says its `text` may not contain "for" or
   "indicat-" at all, which was the most frequent claim rejection in the runs
   below.

## Measured: old prompt vs new prompt

`evals/prompt_ab.py`: real model (`claude-sonnet-5`), real graph and verifier,
the recorded AF-DQ-A2 gateway fixtures, 8 questions (one UC-01 first turn,
seven follow-up shapes from the error-analysis bank), 2 runs each. Both arms
ran the new verifier and parser, so the difference is the prompt's.

| | Old prompt | New prompt |
|---|---|---|
| Turns | 16 | 16 |
| Model summary survived the gate | 11 | 13 |
| Replacement reasons | `empty` x2, `ungrounded_number`, `claims_withheld` x2 | `claims_withheld` x3 |
| Summaries with system wording | 2 | 0 |
| Claim texts with system wording | 1 of 73 | 0 of 73 |
| Rejected claims / repair rounds | 7 / 6 | 6 / 5 |
| Output tokens per turn | 1,766 | 2,015 |
| Seconds per turn (runs were sequential, so API load differs) | 17.4 | 21.4 |

After the `documented_reference` wording was added, the two questions that
produced those rejections ("Why are they on all these medications?", "Can you
catch me up on this patient?") were rerun 3 times each on the new prompt: 0
rejected claims, 0 repair rounds, 5 of 6 model summaries kept. The sixth was
`ungrounded_date`: the summary gave amlodipine's end date, which the conflict
claim's text did not carry. The prompt now says a date worth putting in the
summary goes in the claim's text first.

Same question, old and new:

> Old: "The pack contains only one LDL cholesterol result, dated 2026-08-31 at
> 162 mg/dL (abnormal), with no earlier LDL values available for comparison."
>
> New: "The chart contains a single LDL cholesterol result, 162 mg/dL, flagged
> abnormal, dated 2026-08-31. No earlier LDL cholesterol result is present in
> the chart for comparison."

And what a physician now sees when a summary is replaced:

> Before (journal of 2026-09-16, entry 10): "The chart shows 3 absences, 1
> conflict and 1 medication status across the chart. 1 statement(s) were
> withheld because they could not be verified."
>
> After (A/B run, "Can you catch me up on this patient?", one claim
> rejected): "Hemoglobin A1c 6.8%, flagged abnormal, dated 2026-08-31. LDL
> cholesterol 162 mg/dL, flagged abnormal, dated 2026-08-31. A1c down from
> 7.4% on 2026-06-16 to 6.8% on 2026-08-31. 6 more verified statements follow.
> 1 statement(s) were withheld because they could not be verified."

## What this does not show

- One chart, eight questions, 16 turns per arm. The direction is consistent;
  the sizes are not estimates. The live suite after deploy is the gate, and
  the `summary_model_kept` trace score is the number to watch by
  `prompt_version`.
- The new prompt writes more: about 14% more output tokens per turn in this
  sample, and a single-call first turn went from about 1,900 to about 2,250
  output tokens. That is latency and cost, and it is why the raised cap
  matters more under the new prompt than under the old one.
- Every remaining replacement in the new arm was `claims_withheld`: one
  rejected claim discards the whole summary, because prose cannot be attributed
  sentence by sentence. Sentence-level attribution (each summary sentence
  carries the ids of the claims it restates) is the next step if that share
  stays high.
- Numbers echoed from the physician's question are still not grounded, on
  purpose: "is the A1c above 9?" must not come back as a fact.
