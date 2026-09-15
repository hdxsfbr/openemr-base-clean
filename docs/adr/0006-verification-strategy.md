# ADR-0006: Deterministic Claim Verification

- **Status:** Accepted 2026-09-15 (owner approval)
- **Date:** 2026-09-14
- **Owners:** Andre Batista (agent service, verifier)
- **Related requirements:** PRD "Verification System": source attribution
  and domain constraint enforcement before any response reaches the user;
  "the model must not approve, grade, or bypass its own verification result"
  (`AGENTS.md`); `KEY_METRICS.md` unsupported-claim rate 0%, citation
  correctness, uncertainty recall. `AUDIT.md` §4.2 defects as failure modes.
- **Related use cases:** CAP-05, CAP-06, CAP-07; all of UC-01..03.
- **Related decisions:** ADR-0004 (structured output), ADR-0005 (records
  re-fetched per turn).

## Context

The central clinical safety failure is a fluent unsupported claim. The
model can be asked to cite, but citation presence is not correctness: a
source can be the wrong record, the wrong patient, or a record whose value
the model altered. The data itself contradicts and omits (status conflicts,
missing dates and units, text lab values, corrected results, duplicate
rows), so a verifier must also decide what the record supports. The PRD
leaves the method open; `AGENTS.md` fixes the property: the model never
approves its own output.

## Decision

A deterministic verifier in the agent service runs after generation and
before rendering, over the model's structured claims and the records
retrieved in that turn. It makes no model call.

1. **Claim schema.** Each claim has a `type`, display `text`, typed
   `facts`, and `source_ids[]`. Types: `change_event`, `medication_status`,
   `lab_result`, `lab_comparison`, `documented_reference`, `absence`,
   `conflict`, `undated`, `interpretation`.
2. **Source resolution.** Every `source_id` must exist among this turn's
   retrieved records for this conversation. Otherwise the claim is rejected.
3. **Fact matching.** Typed facts must equal the cited record's normalized
   fields (value text, unit, date, flag, range, status, provenance). The
   verifier computes comparisons (direction, delta) itself; it never takes a
   computed value from the model.
4. **Domain rules.** Abnormality only from a recorded flag or a parseable
   numeric range in the same unit. Comparison only between same-analyte,
   strictly numeric, same-unit values. Absence only when the section's tool
   returned `ok` or `empty` this turn, with the absence state matching the
   record flags. Indication or relationship only as `documented_reference`
   to a record containing the medication name or code, worded "mentions".
   No resolution claims; the permitted wording is "no later result and no
   documented follow-up found". A lexicon check rejects diagnostic,
   causal, dosing, interaction, and recommendation language.
5. **Outcome.** Passing claims render with citations. Rejected claims are
   withheld and counted; rejection reasons go to the trace and the audit
   event `copilot-verification-result`. One repair call with the rejection
   list; the result is verified again; no third attempt. Zero verified
   claims renders the evidence list plus a limitation.
6. **Fail closed.** Any exception in the verifier, or a response missing a
   verifier outcome, renders nothing from the model. The renderer refuses
   claims without a `verification` block.
7. **Summary paragraph (added 2026-09-15).** The model also writes a one-
   to three-sentence `summary` that answers the question by restating its
   claims. Prose cannot be checked fact by fact, so it is admitted under a
   stricter gate than claims: it is shown only when no claim was withheld
   in the turn (so nothing withheld can leak through the prose), it passes
   the same lexicon, and every number in it appears in a verified claim's
   text or facts. Otherwise the response carries a deterministic,
   count-only summary built from the verified claims and is labeled
   `summary_basis=deterministic`. Owner request: a list of rows without a
   direct answer was not readable.

## Alternatives Considered

### Model-graded verification (a second model call judges the first)

- Benefits: catches semantic drift a rule engine misses.
- Costs and risks: the model approves model output; non-deterministic;
  doubles cost and latency; violates the `AGENTS.md` invariant.
- Reason rejected as the gate; allowed only as a separately reported
  diagnostic in evals.

### Citation presence only

- Reason rejected: citation theater; the audit's defects would pass.

### Retrieval-constrained generation (model can only quote records)

- Benefits: strong grounding.
- Costs and risks: cannot express grouping, absence, or conflict wording,
  which are the product; still needs a check that quotes are faithful.
- Reason rejected as sufficient; the evidence-pack design keeps most of the
  benefit.

## Consequences

### Positive

- The displayed-unsupported-claim rate is a verifier property, testable with
  altered-fact evals, independent of model behavior.
- Absence and conflict states are enforced, not hoped for.
- The property is explainable in one sentence: nothing is shown as fact
  unless a record retrieved this turn says it.

### Negative and residual risk

- Facts are checked, sentences are not: two verified claims can be
  juxtaposed misleadingly; paraphrase in note matching is missed both ways.
- Rules are only as good as the normalization; a normalization bug passes
  through. Mitigated by one eval per `AF-DQ-*` patient.
- Withholding can make answers terse; the withheld count and the evidence
  list keep the physician informed of what was not said.

## Verification

- Altered-fact evals per claim type (value, unit, date, status, source
  swapped to another patient's record): all rejected.
- Absence evals: "no labs" with the lab tool `unavailable` is rejected;
  with `empty` it passes with the correct state.
- Lab rule evals on `AF-DQ-K`, `AF-DQ-L`, `AF-DQ-M`.
- Lexicon evals: recommendation and dosing phrasings rejected.
- Fail-closed eval: verifier exception renders no model text.
- Summary evals (`agent/tests/test_graph.py`): the model's summary is shown
  when every claim verifies; replaced when any claim is withheld, when it
  carries a number absent from the claims, or when it uses advice language.

## Revisit Triggers

- Evidence that juxtaposition or paraphrase errors reach users in the demo
  or interview.
- A use case that needs free-text summarization beyond typed claims.
- Terminology services become available, enabling code-based matching.
