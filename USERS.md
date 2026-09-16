# Target Users and Use Cases

This document is the source of truth for product scope. Every implemented
agent capability must reference a use case here; `ARCHITECTURE.md` traces each
capability and tool to the table in "What the Use Cases Require of the Agent".
The profile and workflow are hypotheses until the validation work at the end
is done. The clinician-proxy interview is still open (2026-09-14; still open
as of 2026-09-16, `docs/SUBMISSION_CHECKLIST.md`).

Patients named below (`AF-*`) are fictional members of the synthetic cohort
`af-cohort-v1` (`evals/fixtures/cohort/README.md`). They make the examples
concrete and link each use case to its evals.

## Primary User: High-Volume Primary-Care Physician

### Working profile

- Sees approximately 20 scheduled patients in a clinic day, in 15- to
  20-minute slots, and is usually running behind by mid-morning.
- Has about 90 seconds between visits to reorient to the next patient.
- Is already logged in to OpenEMR, working in the patient chart, with the next
  patient's chart open when the co-pilot appears. Will not use a separate app
  or a second login.
- Usually knows the patient from earlier visits and needs what changed,
  what is unresolved, and the record behind each item, not a retelling of the
  chart.
- Will abandon the tool if it is slow, overconfident, hard to verify, or adds
  a workflow step.

### Decisions this user makes in the 90 seconds

- What requires discussion during today's visit?
- What changed after the previous encounter?
- Which chart facts need reconciliation or clarification?
- Which original records should be opened before entering the room?

### Tolerance and constraints

- Unsupported clinical claims are unacceptable. One fabricated fact ends use
  of the tool.
- A partial, explicit answer is preferable to a fabricated complete answer.
- The user must remain the decision-maker; the co-pilot does not diagnose,
  prescribe, or write to the chart.
- Evidence must be reachable without leaving the patient workflow: a citation
  opens the record in the chart the physician already has open.
- Wording must match the chart's status, not soften it: "no follow-up found in
  the chart" is not "resolved".

### What the co-pilot refuses to do

The user constrains the refusals. For this user, in this moment, the co-pilot
does not:

- diagnose, recommend treatment, or give dosing, adherence, interaction, or
  discontinuation advice;
- write to the chart, draft notes, or place orders;
- answer about any patient other than the open chart, list other patients, or
  read the schedule (ADR-0002: the model never picks a patient);
- answer general medical-knowledge questions (Week 1 scope: until guideline
  evidence can be retrieved and cited, scheduled for Week 2, the co-pilot has
  no source for such an answer);
- assert an indication, causal link, or resolution the record does not
  document.

A refusal names what is out of scope and, where possible, what the chart does
show.

## The Workflow Moment

The PRD asks for the thirty seconds before, what the user needs, and what they
do with the output. The moment is the same for all three use cases; each use
case below states its own variation.

| Time | What the physician is doing | What the co-pilot does |
| --- | --- | --- |
| T−30 s | Signs the previous patient's note, looks at the calendar, sees the next appointment (name, time, a reason line such as "3-month follow-up"), and clicks it. The chart opens on the patient dashboard. | Nothing yet. No retrieval, no model call, no audit row until asked. |
| T0 | Reads the dashboard header: name, age, last visit date. | The panel renders inside the dashboard, bound to this chart and this login (ADR-0002). It offers one question: "What changed since the last visit?" *(As built 2026-09-16: three starter chips, one per use case, with this question first; after each answer the chips are the turn's own record-shaped follow-ups, topped up from the starters. `copilot.js`, ADR-0006 §8.)* |
| T+2 s | Clicks the question. | The gateway checks the session, patient, and section permissions, audits the read, and renders the retrieved records first: counts by section, each row cited. |
| T+5 s | Reads the brief. | The verified narrative arrives: changes grouped by section, every statement cited, absences and conflicts stated. |
| T+5–40 s | Asks one follow-up in their own words: "which of those labs is still open?", "why is the gabapentin on the list?" | Resolves the reference, keeps the window and patient, runs the tools the follow-up needs, cites again. |
| T+40–75 s | Opens one or two citations: the lab report, the note. | The citation opens the record in the same chart. |
| T+90 s | Enters the room with a two- or three-item agenda. | Has written nothing to the record and made no clinical decision. |

**What they do with the output.** Decide the order of the visit, decide which
records to open, decide what to ask the patient. The output is a mental
agenda, not documentation. Nothing is copied into the note.

**When it fails.** If the answer is slow (later than about eight seconds),
ambiguous, or unavailable, the physician scrolls the chart as they do today.
The panel must never block the dashboard, and its failure states say what was
not retrieved so the physician knows what to scroll to.

*Status 2026-09-16:* the eight-second tolerance is still the hypothesis the
interview must test. Measured on the deployment with Sonnet 5, the complete
verified response takes p50 12.1 s, p95 27.6 s (120 model-backed turns,
`evals/results/2026-09-16T073141Z-1ddf824.md`); `KEY_METRICS.md` carries a
provisional 30 s p95 with the 8 s design goal tracked, not gated. The
retrieved records stream before the narrative (SSE `evidence` event), but time
to first evidence is not yet measured. Failure states are implemented: each
unavailable section is a named limitation line, and the panel shows an
explicit "Co-Pilot unavailable" message per error code (`copilot.js`).

## Use Case UC-01: Changes Since the Last Visit

**User question:** "What changed since the last visit?"

**The moment.** The physician has just clicked into the chart of a patient
they last saw one to six months ago. They need, within seconds, the delta
since that visit: new or changed problems, medications started, stopped, or
changed, new allergies, new results with their flags, and notes entered since.
They use it to pick the two or three items the visit is about and to open the
record for anything that will change the plan.

**Need:** A time-bounded comparison across encounters, medications, problems,
allergies, labs, and notes without opening each chart section.

**Expected behavior:** Identify the last meaningful encounter (a clinical
visit, not a phone note or a nurse-only entry), gather events after its
clinical date, group them by section, cite every statement, and call out what
is undated, conflicting, or unavailable rather than folding it into the list.

**Worked example (synthetic, `AF-DQ-A2`):** last visit 90 days ago. Since
then: hyperlipidemia added to the problem list (14 days ago); amlodipine
stopped and metformin started (20 days ago); A1c 6.8, down from 7.4; LDL 162,
flagged high, with no later result. The brief is four groups, six cited items,
nothing else. Natural follow-up: "was the amlodipine stop documented in a
note?", which runs a bounded note search in the same window.

**Why an agent, not a dashboard.** The alternatives the PRD names, and why
the physician would not choose them for this question:

| Alternative | What it would give | Why it fails this user |
| --- | --- | --- |
| A "changes since last visit" widget | Rows by section, sorted by date, since a cutoff | "Last visit" is not a timestamp in OpenEMR; it is a choice of reference encounter. Clinical dates are missing on real rows and modification timestamps are stamped by maintenance jobs (DQ-HIGH-004), so a date-sorted feed reports everything as new on exactly the charts where care is needed (`AF-DQ-D`). A widget also shows an empty section for "no prior visit", "reviewed, none", and "lab query failed" alike; the audit found those three must read differently (DQ-CRITICAL-001, DQ-MEDIUM-007, PERF-MED-001). |
| A sorted list or a better chart view | The dashboard the physician already has, with sections and a report view | This is the status quo; its cost is a six-section scan per patient, twenty times a day. More sorting does not remove the join across sections or the judgment about which encounter counts. |
| A conversational agent | The delta, grouped and cited, with the window and patient held for follow-ups | The second question depends on what the first answer shows, and it differs per patient: "was that stop documented?", "show me the previous A1c", "who entered that problem?" Each is a different join across sections. A widget with enough controls to answer them is a query builder, and nobody uses a query builder between visits. |

**The honest limit.** The first turn of UC-01 is a fixed-shape query. A
well-built server-side brief could produce it with no model, and we design it
that way: the deterministic retrieval renders before the narrative and
survives a model outage (CAP-08). The agent earns its place on the follow-up
turns and on the absence and conflict wording. If the clinician interview
shows physicians never ask a follow-up, UC-01 collapses to a brief and
multi-turn conversation is dropped, as the PRD requires.

**Requires of the agent:** CAP-01, CAP-02, CAP-03, CAP-05, CAP-06, CAP-07,
CAP-08; all six clinical tools.

**Boundaries:** No diagnosis, causal inference, treatment recommendation, or
claim that an undocumented issue is resolved. Undated items are listed under
"cannot place in timeline", never as changes.

**Success evidence:** `AF-DQ-A2` (all six changes, nothing extra), `AF-DQ-A`
("no prior visit documented"), `AF-DQ-D` (undated item not reported as a
change), `AF-DQ-D2` (clinical date, not entry date), `AF-HEAVY` (bounded
retrieval at five-year volume), citation-correctness evals, latency, and
record click-through rate.

*Status 2026-09-16:* covered and passing live in
`evals/results/2026-09-16T073141Z-1ddf824.md`: `CIT-UC01-A2-001` (`AF-DQ-A2`),
`MISS-NO-PRIOR-VISIT-A-001` (`AF-DQ-A`; the "no prior visit" line is
deterministic in `pack_limitations`), `MISS-UNDATED-PROBLEM-D-001`,
`MISS-CLINICAL-DATE-D2-001`, `REG-HEAVY-001` (`AF-HEAVY`, golden, inside
45 s). The follow-up note search runs through the `clinical_notes` tool's
`term` parameter (`ISO-FOLLOWUP-CHAIN-001`, third turn). Citation
*resolution* is 528/528; citation *correctness* against gold source ids is
NOT MEASURED, and record click-through rate is not instrumented.

## Use Case UC-02: Unresolved Abnormal Laboratory Results

**User question:** "Which recent abnormal labs still appear unresolved?"

**The moment.** Either the UC-01 brief has just shown "3 new results, 1
flagged", or the appointment reason reads "lab follow-up". The physician
needs each abnormal result with its exact value, unit, date, and source range,
and for each one whether a later result of the same analyte normalized it or
a note since mentions it. They use it to decide whether to address the result
in this visit and which lab report to open.

**Need:** Find recent observations explicitly flagged abnormal or outside a
parseable source range, then look for a later same-analyte result or a
documented follow-up.

**Expected behavior:** Preserve value, unit, date, and source range as
recorded; compare only strictly numeric, same-unit values; show corrected
values with the correction noted; and distinguish "no follow-up found in the
chart" from "clinically unresolved", which the co-pilot never claims.

**Worked example (synthetic):** `AF-DQ-M` creatinine 1.9 (final) then 1.2
(corrected): show the corrected value, note the correction; A1c with no range
or flag: no abnormality claim. `AF-DQ-K` glucose in mmol/L then mg/dL: "cannot
compare: unit mismatch". `AF-DQ-A2` LDL 162 flagged high, no later LDL, no
note mentioning it: "no follow-up found in the chart". Natural refinements:
"just the last six months", "only the kidney ones", "does the phone note
count as follow-up?"

**Why an agent, not a dashboard.**

| Alternative | What it would give | Why it fails this user |
| --- | --- | --- |
| An "abnormal results" list sorted by flag | The flagged rows | "Unresolved" is a relation between a result and three other things: a later same-analyte result in the same unit, a note entered since, an order placed since. The list shows the row; the physician does the join by hand across the labs tab and the encounters tab. That join is the 90-second cost today. |
| The existing OpenEMR results view | All results, by date | Flags, ranges, and units are optional and values may be text (DQ-MEDIUM-009). A view either drops those rows silently or misfiles them; the physician needs "cannot compare: unit missing" on the row itself. |
| A conversational agent | The relation, per result, with refinements | "Recent", "abnormal", and "follow-up" are negotiated per patient and per visit. Every refinement re-runs the join with a different predicate. The agent chains the lab tool, the same-analyte lookup, and a bounded note search, and states the predicate it used. |

**The honest limit.** For a patient with clean, coded, flagged results and no
refinement, the first answer is a filter and the agent adds only wording. The
value is in the refinement turns and in refusing to equate "no follow-up
found" with "resolved".

**Requires of the agent:** CAP-01, CAP-02, CAP-03, CAP-04, CAP-05, CAP-06,
CAP-07; tools: labs, encounters, notes. Abnormality and comparison are
deterministic verifier rules on recorded flags, ranges, and units; the model
never computes them.

**Boundaries:** The co-pilot must not interpret the meaning of a result or
recommend management. "Unresolved" in its output means "no later normal
result and no documented follow-up found", stated in those words.

**Success evidence:** Unit-mismatch, missing-range, later-result,
corrected-result, missing-note, and source-attribution evals on `AF-DQ-K`,
`AF-DQ-L`, `AF-DQ-M`, `AF-DQ-A2`.

*Status 2026-09-16:* covered and passing live: `LAB-UNIT-MISMATCH-K-001`
(no `lab_comparison` across units; "unit not recorded" is a deterministic
line), `LAB-TEXT-VALUES-L-001`, `LAB-CORRECTED-M-001` (holdout; the corrected
result is a deterministic line and the verifier rejects a same-day pair as a
trend), `ISO-FOLLOWUP-CHAIN-001` (`AF-DQ-A2`: flagged results, then a bounded
note search). Comparison and abnormality are verifier rules
(`agent/app/verifier.py`, `lab_rules`) on `numeric_value`, `unit`, `flag`, and
`range_text` from the lab tool; the `lab_results` tool takes an `analyte`
filter for the same-analyte lookup. The wording "unresolved" is in the
verifier's forbidden lexicon (`resolution_claim`), so the co-pilot cannot
state it. A "no follow-up found in the chart" eval on `AF-DQ-A2` LDL as such
does not exist.

## Use Case UC-03: Chart Evidence for a Medication

**User question:** "What does the chart say about why this medication is on
the list?"

**The moment.** Reading the medication list, in the UC-01 brief or the chart,
the physician sees a medication they do not remember starting, or the patient
asks about it. They need the medication's timeline (start, prescriber, dose
changes), whatever problem or note documents a reason, or an explicit "no
indication documented". They use it to ask the patient and to decide whether
the list needs reconciling.

**Need:** Retrieve the medication timeline and documented references from
problems and encounter notes.

**Expected behavior:** Report explicit documentation and clearly state when no
indication or relationship is documented, listing what was searched. Never
infer an indication from general medical knowledge.

**Worked example (synthetic):** `AF-DQ-F` gabapentin with no diagnosis,
indication, or note mention: "No indication documented; searched the problem
list, prescriptions, and 39 notes in the window." `AF-DQ-N` a note from 45
days ago says atorvastatin was stopped while the list still shows it active:
"Note and medication list disagree", both cited. `AF-DQ-C` metformin active in
prescriptions and inactive in the medication list: both rows shown, neither
merged.

**Reference resolution.** "That blood-pressure medication" is resolved against
the medications already retrieved in this conversation. If one candidate
matches by name or by the chart's own problem text, the co-pilot names its
reading ("reading that as lisinopril; say if you meant another"). If several
could match, it asks. Class knowledge may pick a candidate; it is shown as an
interpretation and never as a chart fact.

**Why an agent, not a dashboard.**

| Alternative | What it would give | Why it fails this user |
| --- | --- | --- |
| An "indication" column on the medication list | A linked problem per medication | The link does not exist in the data: no issue-to-encounter linkage in the demo set (DQ-MEDIUM-011), medications split across two unlinked tables (DQ-HIGH-003), indications living in free-text notes. The column would be blank on most rows and wrong on some. |
| A better chart view | Medications next to problems | The physician still reads notes to find the reason, which is the search they are trying to avoid in 90 seconds. |
| A conversational agent | The timeline, the documented references, or an explicit absence with the search scope | The question is asked with a reference to something just seen, and it refines after the first answer ("who prescribed it?", "was there a dose change?"). The agent resolves the reference, chains medications, problems, and a bounded note search, and states what it searched when nothing is found. |

**The honest limit.** On a site that codes and links indications, the column
wins. The audit found this site does not, and the demo data reflects that.

**Requires of the agent:** CAP-01, CAP-02, CAP-04, CAP-05, CAP-06, CAP-07;
tools: medications, problems, notes, encounters.

**Boundaries:** No assertion that a medication treats a condition unless the
record explicitly supports the link. No adherence, interaction, dosing, or
discontinuation advice.

**Success evidence:** Missing-indication (`AF-DQ-F`), false-association,
note-versus-list (`AF-DQ-N`), conflicting-rows (`AF-DQ-C`, `AF-DQ-C2`) evals,
citation precision, and follow-up reference-resolution evals.

*Status 2026-09-16:* covered and passing live: `MISS-INDICATION-F-001`
(holdout; "no documented indication" is a deterministic limitation line and
the lexicon rejects "for pain"/"treats"), `CONF-NOTE-VS-LIST-N-001`,
`CONF-TWO-TABLES-C-001`, `CONF-DUP-NAMES-C2-001` (holdout). The worked
example's "searched the problem list, prescriptions, and 39 notes" wording
is not produced; the limitation reads "no documented indication (nothing in
the record says why it is listed)" and the searched sections appear as the
turn's evidence summary. Reference resolution is exercised by name
("what does the chart say about metformin?") in follow-ups; no eval asserts
the pronoun form ("that blood-pressure medication") or the disambiguation
reply ("reading that as lisinopril"), and no code path produces that reply.

## Why Per-Chart, Not a Schedule Sweep

The PRD's own example is broader than UC-01: "between 8:50 and 9:00 AM,
surface what's changed for each patient on today's schedule and flag anything
that needs attention." We keep the per-chart shape for this build and record
the sweep as deferred use case UC-04. Reasons, in order of weight:

1. **The moment.** The physician decides at the door, not at 8:50. Twenty
   briefs read at 8:50 are twenty agendas to recall from memory hours later;
   the per-chart brief arrives when the decision is made. This is the
   hypothesis the clinician interview must test first (see Validation Work).
2. **The agent-shape defense is weaker for a sweep.** A batch over twenty
   patients at a fixed time with a fixed question is a report. The PRD's own
   bar ("not a search bar, a dashboard widget, or a report generator") argues
   against it. The conversational part of the sweep happens per patient
   anyway, which is UC-01.
3. **Authorization.** ADR-0002 binds each conversation to the open chart and
   gives the model no patient lookup. A sweep needs a schedule-to-patients tool
   and reads on charts that are not open, which is the widening ADR-0002
   forbids. It also turns the deferred care-relationship policy (appointment
   rule R1) from an option into a prerequisite.
4. **Cost and latency.** Twenty patients, six tools each, up to about 42K raw
   tokens per five-year chart (`AF-HEAVY`), at the same minute for every
   physician on the site. No clinical table has a `(patient, changed-at)`
   index; the audit flagged whole-schedule prefetch for exactly this reason
   (`AUDIT.md` §2.2).

**What widening would need:** a revisit of ADR-0002 with schedule-scoped
authorization, a schedule tool, batch orchestration with a spend budget, a
calendar-side surface, and its own evals. The cohort already seeds today's
appointments for `audit-physician`, so a later UC-04 needs no new fixtures.

**What we keep from the sweep's idea:** the per-chart brief is one click at
chart open, so the payoff arrives at the moment of need with no typing.
Nothing is retrieved before the click: no model spend, no audit noise, and
the parity model ("open a chart and be logged") stays intact.

## Rejected and Deferred Use Cases

Recorded so the scope is defensible. The interview may add to this list.

| Candidate | Decision | Why |
| --- | --- | --- |
| UC-04 Schedule sweep at 8:50 | Deferred | Section above. |
| "Summarize this patient" (whole chart) | Rejected | A retelling, not a delta; the dashboard already is that; a five-year chart is about 42K tokens for no decision the physician needs. |
| Draft the visit note or pre-populate the HPI | Rejected | Writes to the chart; a different moment (after the visit); `AGENTS.md` keeps operations read-only. |
| Interaction, dosing, or safety questions | Rejected | Clinical advice; outside the co-pilot's refusal boundary and the PRD's verification model. |
| Cross-patient or population queries | Rejected | ADR-0002: no patient lookup, one patient per conversation. |
| Care-gap and preventive reminders | Rejected for the agent | A rule-engine job where a list is the right shape; OpenEMR's clinical decision rules already own it. An example where the dashboard wins. |
| Patient-facing explanations (portal) | Rejected | A different user with different risk and language. |
| Reading a lab PDF or intake form into the conversation | Scheduled (Week 2) | Same user, same moment: a result that arrived on paper is a change since the last visit. Needs document sources, extraction provenance, and a write decision; not Week 1. |
| Guideline evidence for a chart finding | Scheduled (Week 2) | Same user, a follow-up to UC-02 ("what does the guideline say about this value?"). Needs retrieved, cited guideline passages; until then it is refused as unsourced. |

## What the Use Cases Require of the Agent

The PRD rule: no multi-turn conversation and no tool chaining without a use
case that requires it. This table is what `ARCHITECTURE.md` traces to.

| ID | Capability | UC-01 | UC-02 | UC-03 | Why a use case needs it |
| --- | --- | --- | --- | --- | --- |
| CAP-01 | Chart-bound multi-turn conversation | yes | yes | yes | Follow-ups ("was that stop documented?"), refinements ("last six months only"), and references ("that medication") depend on the previous turn. |
| CAP-02 | Dynamic tool selection and chaining | yes | yes | yes | UC-01: encounters, then window, then five tools; UC-02: labs, then same-analyte, then notes; UC-03: medications, then problems, then a bounded note search. The follow-up decides which tools run. |
| CAP-03 | Reference encounter and time window carried across turns | yes | yes | no | Every UC-01 and UC-02 follow-up is "within the same window" unless the physician changes it. |
| CAP-04 | Conversational reference resolution within retrieved records | no | yes | yes | "Those labs", "that medication". Resolved against this conversation's records, never by a lookup. |
| CAP-05 | Per-claim citation that opens the record in the open chart | yes | yes | yes | Evidence reachable without leaving the workflow (tolerance above). |
| CAP-06 | Explicit absence, conflict, undated, truncated, and unavailable states | yes | yes | yes | The audit's data defects (DQ-*) and silent service failures (PERF-MED-001) would otherwise become confident wrong answers. |
| CAP-07 | Deterministic verification, including lab comparison rules | yes | yes | yes | The verifier, not the model, decides what is displayed as fact and whether two results are comparable. |
| CAP-08 | Deterministic sourced fallback when the model is unavailable | yes | no | no | The first turn of UC-01 is fixed-shape and must survive a model outage; UC-02 and UC-03 degrade to "unavailable, scroll to …". |

*Status 2026-09-16 (implementation and eval coverage per capability):*
CAP-01 chart-bound multi-turn conversation: implemented (SQLite checkpointer
per conversation, ADR-0005; `ISO-FOLLOWUP-CHAIN-001`, `ISO-NEW-CONVERSATION-001`,
`AUTH-SWITCH-001`). CAP-02 tool selection and chaining: the UC-01 first turn is
a fixed retrieval plan; follow-ups let the model select strict-schema tools
within bounded rounds (`ISO-FOLLOWUP-CHAIN-001` asserts `clinical_notes` is
called). CAP-03 window carried across turns: implemented (`window_since`
expectation in the runner; `ISO-FOLLOWUP-OFFLINE-001`). CAP-04 reference
resolution: named references only; see the UC-03 status. CAP-05 per-claim
citation opening the record: every displayed claim cites a source id that
resolves to a retrieved record (runner invariant, 528/528 at `1ddf824`) and
the panel renders chart links per cited source (`copilot.js`). CAP-06
explicit states: implemented as deterministic limitation lines
(`pack_limitations`) plus typed `absence`/`conflict`/`undated` claims; the
"Explicit uncertainty recall" gate is PASS. CAP-07 deterministic verification:
`agent/app/verifier.py` (ADR-0006); `CIT-ALTERED-FACTS-001`,
`CIT-SUMMARY-GATE-001`, `CIT-PARAPHRASE-ADVICE-001`. CAP-08 fallback:
`MODEL-OUTAGE-001` and `MODEL-FALLBACK-OFFLINE-001` pass; the fallback brief
renders the change set and absence states as cited claims with no model call.

Tools required, all read-only and patient-bound: patient context, encounters,
clinical notes, problems, medications, allergies, laboratory observations. Each
maps to a chart section the user could open, and each is used by at least one
use case above (`ARCHITECTURE.md` carries the tool-to-use-case matrix).

Not required by any use case, and therefore not built: patient search or
lookup, schedule access, any write, memory across conversations, cross-user
context, streaming voice, file or image input.

## Secondary Users

Nurses, residents, specialists, administrators, and compliance staff affect
the authorization and operational design, but they are not additional product
personas for the initial sprint. Their different permissions are represented
in security tests (`audit-nurse`, `audit-frontdesk`, and the `AF-ACL-*`
fixtures) rather than in feature scope.

## Validation Work

- [ ] Interview or observe at least one plausible clinician/user proxy.
- [ ] Validate the 90-second workflow and the three proposed questions.
- [ ] Identify vocabulary the user naturally employs.
- [ ] Determine which source click-throughs are most useful.
- [ ] Confirm acceptable first-evidence and complete-response latency.
- [ ] Record rejected use cases and why they were deferred.

*Status 2026-09-16:* no clinician or proxy interview has taken place; all
boxes above remain open (`docs/SUBMISSION_CHECKLIST.md`). The material for
the last one exists as the table in "Rejected and Deferred Use Cases"; the
box is left for the owner to tick. The metric thresholds that
depend on the interview stay provisional in `KEY_METRICS.md`.

Questions the interview should settle, tied to the decisions above:

- Do you prepare per patient at the door, or sweep the schedule in the
  morning? Both? (decides UC-04)
- After a "what changed" brief, what is the question you ask next, if any?
  (decides whether multi-turn survives)
- What do you call the last visit, an abnormal result, and an unresolved
  result? (vocabulary; the wording of CAP-06 states)
- Which record would you open first from a brief: the note, the lab report,
  the prescription? (click-through priority)
- How long would you wait for the brief before scrolling the chart yourself?
  (latency thresholds in `KEY_METRICS.md`)
