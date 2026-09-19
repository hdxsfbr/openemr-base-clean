# Skipping `plan` for the agent's own follow-ups (2026-09-19)

## The proposal and what the traces said

Proposed: route a clicked suggestion chip straight to `narrate`, on the
reasoning that `plan` costs 10 to 12 s of the follow-up path and that chips are
bounded by the evidence pack, so there is nothing to plan. Two measurements
changed the design.

1. **`plan` costs about 2 s, not 10.** Langfuse, 2026-09-18, 199 follow-up
   turns: `plan` generation p50 2.0 s, p95 2.9 s; `narrate` p50 6.2 s, p95
   15.1 s. `plan` was a median 34% of follow-up latency. The follow-up p95
   (29.6 s in that window, which included a load test) is `narrate` plus the
   repair round.
2. **A chip is not bounded by the pack.** The pack lives for one turn (an
   in-process cache with a 120 s TTL), so a follow-up has nothing to narrate
   from until it retrieves, and what it must retrieve is what `plan` decides.
   For the model-written chip "Are there earlier LDL results to compare?",
   `plan` called `lab_results` with `analyte: "LDL"` and no window; the first
   turn's pack was windowed to the last visit and could not have answered it.
   Skipping `plan` for model-written chips would answer from the wrong
   records.

## What was built

The five follow-ups the agent writes itself (two of the three starter chips
and the three deterministic suggestions) have fixed wording. `plan` was run 3
times on each with an empty pack:

| Question | Calls chosen (3 runs) |
|---|---|
| Which recent abnormal labs still have no later result or documented follow-up? | `lab_results`, `clinical_notes` (3 of 3) |
| What does the chart say about why each current medication is on the list? | `medications`, `clinical_notes` (3 of 3), plus `problems` (1 of 3) |
| Which of these lab results are flagged abnormal? | `lab_results` (3 of 3) |
| Was the conflicting medication change documented in a note? | `medications`, `clinical_notes` (3 of 3) |
| What does the chart say about the newest problem? | `problems` (3 of 3) |

No call carried a parameter. Those calls are now a table
(`KNOWN_PLANS`, `agent/app/graph/nodes.py`; the medication question takes the
union) and a question that matches one of the agent's own constants, after
case, spacing, and punctuation are normalized, skips the `plan` model call.
Retrieval, narrate, and the verifier are unchanged.

There is no client flag and so no forged-flag case: the match is on text the
agent compares to its own constants, and a physician who types the same words
gets the same retrieval the chip would. A test holds every follow-up the
agent can write itself to an entry in the table
(`test_the_agents_own_follow_ups_retrieve_without_a_plan_call`).

Expected effect: about 2 s and one model call (about USD 0.004) off each of
those turns. The second and third starter chips are the first click of any
conversation that does not open with UC-01, so this is the path a new user
is most likely to take. Not measured live yet.

## Not built

Skipping `plan` for model-written chips. It needs the tool call to come with
the chip: `narrate` would emit, for each suggestion, the call that answers it,
validated by the same parameter models `plan`'s output is, stored with the
turn, and executed when that chip's text comes back. That changes the model
output contract and the prompt and costs output tokens on every turn to save
2 s on some; it should follow a live measurement of how often chips are
clicked (the first-turn-type counter and the panel events added the same day
give the denominator).
