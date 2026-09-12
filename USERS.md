# Target Users and Use Cases

This document is the source of truth for product scope. Every implemented agent
capability must reference a use case here. The profiles below are initial
hypotheses and must be validated before the architecture is finalized.

## Primary User: High-Volume Primary-Care Physician

### Working profile

- Sees approximately 20 scheduled patients during a clinic day.
- Has about 90 seconds between visits to reorient to the next patient.
- Works inside the existing OpenEMR patient chart rather than a separate app.
- Needs changes, unresolved items, and supporting evidence—not a retelling of
  the entire chart.
- Will abandon the tool if it is slow, overconfident, hard to verify, or adds a
  separate login/workflow.

### Decisions this user makes

- What requires discussion during today's visit?
- What changed after the previous encounter?
- Which chart facts need reconciliation or clarification?
- Which original records should be opened before entering the room?

### Tolerance and constraints

- Unsupported clinical claims are unacceptable.
- A partial, explicit answer is preferable to a fabricated complete answer.
- The user must remain the decision-maker; the co-pilot does not diagnose,
  prescribe, or write to the chart.
- Evidence must be reachable without leaving the patient workflow.

## Workflow

1. **Before opening the chart:** The physician finishes documentation for the
   previous patient and sees the next appointment.
2. **At chart open:** OpenEMR establishes the physician's identity, role, and
   active patient.
3. **Within the first seconds:** The physician asks for changes since the last
   visit or opens a concise pre-visit brief.
4. **During review:** The physician asks one or two follow-ups and opens sources
   for facts that will affect the conversation.
5. **After review:** The physician enters the room with a short mental agenda.
   The co-pilot has not changed the record or made a clinical decision.

## Use Case UC-01: Changes Since the Last Visit

**User question:** "What changed since the last visit?"

**Need:** Build a time-bounded comparison across encounters, medications,
problems, allergies, labs, and relevant recent notes without manually opening
each section.

**Expected behavior:** Retrieve the last meaningful encounter, gather events
after that timestamp, group the changes, cite every statement, and call out
sources that are unavailable or ambiguous.

**Why an agent is appropriate:** The physician's follow-up depends on what the
first answer reveals. The system must dynamically select and combine several
data tools, then preserve the time window and patient context across questions.
A fixed dashboard can display feeds, but it cannot efficiently answer ad hoc
cross-record follow-ups.

**Boundaries:** No diagnosis, causal inference, treatment recommendation, or
claim that an undocumented issue is resolved.

**Success evidence:** Task-completion evals, citation correctness, latency, and
record click-through rate.

## Use Case UC-02: Unresolved Abnormal Laboratory Results

**User question:** "Which recent abnormal labs still appear unresolved?"

**Need:** Find recent observations explicitly marked abnormal or outside a
parseable source range, then look for later normalized results or documented
follow-up.

**Expected behavior:** Preserve the exact value, unit, date, and source range;
avoid comparing incompatible units; distinguish "no follow-up found" from
"clinically unresolved."

**Why an agent is appropriate:** The task requires conditional retrieval and a
conversational refinement of timeframe, lab type, or what counts as follow-up.
The agent can chain observations and encounter-note retrieval while a static
list cannot answer those refinements.

**Boundaries:** The co-pilot must not independently diagnose the meaning of a
result or recommend management. Domain checks are deterministic and based on
recorded flags/ranges.

**Success evidence:** Unit-mismatch, missing-range, later-result, missing-note,
and source-attribution evals.

## Use Case UC-03: Chart Evidence for a Medication

**User question:** "What does the chart say about why this medication is on the
list?"

**Need:** Retrieve the medication timeline and documented references from
problems or encounter notes.

**Expected behavior:** Report explicit documentation and clearly state when no
indication or relationship is documented. Never infer an indication from
general medical knowledge.

**Why an agent is appropriate:** The user may refer conversationally to "that
blood-pressure medication" or refine the date and prescriber after seeing the
first result. The agent resolves the reference and chains bounded searches
across medications and notes.

**Boundaries:** No assertion that a medication treats a condition unless the
patient record explicitly supports the link. No adherence, interaction, dosing,
or discontinuation advice.

**Success evidence:** Missing-indication and false-association evals, citation
precision, and successful follow-up reference resolution.

## Secondary Users

Nurses, residents, specialists, administrators, and compliance staff affect the
authorization and operational design, but they are not additional product
personas for the initial sprint. Their different permissions will be represented
in security tests rather than unsupported feature scope.

## Validation Work

- [ ] Interview or observe at least one plausible clinician/user proxy.
- [ ] Validate the 90-second workflow and the three proposed questions.
- [ ] Identify vocabulary the user naturally employs.
- [ ] Determine which source click-throughs are most useful.
- [ ] Confirm acceptable first-evidence and complete-response latency.
- [ ] Record rejected use cases and why they were deferred.
