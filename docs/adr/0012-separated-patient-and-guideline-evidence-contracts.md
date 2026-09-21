# ADR-0012: Separate patient-record claims from guideline evidence

- **Status:** Accepted 2026-09-21 (owner approval)
- **Date:** 2026-09-21
- **Owners:** Andre Batista (claim, citation, and verification boundary)
- **Related requirements:** Week 2 PRD evidence grounding and citation
  contract; every clinical claim must carry machine-readable source metadata,
  document citations must focus the supporting page region, and patient facts
  must remain distinct from guideline evidence.
- **Related use cases:** UC-01 and UC-02; document-derived changes and bounded
  guideline evidence for physician review.
- **Related decisions:** ADR-0002 (patient authorization), ADR-0005
  (patient-bound state), ADR-0006 (deterministic verification), ADR-0009
  (field evidence), ADR-0010 (guideline corpus), and ADR-0011 (reviewed record
  contracts).

## Context

The Week 1 claim contract cites authorized OpenEMR rows, while Week 2 adds two
materially different evidence classes: human-reviewed facts derived from
patient documents and public guideline excerpts. Treating both as generic
model-authored claims would allow a guideline to masquerade as a chart fact,
an unreviewed extraction to reach the final response, or a fluent paraphrase to
outrun deterministic verification. The physician must be able to tell what the
patient record says, what a publisher says, and what the system did not decide.

## Decision

1. **Two clinical claim classes.** Final clinical claims are discriminated as
   `patient_record` or `guideline_evidence` and render in separate lanes. A
   claim cannot mix source classes. Proposed extraction facts are review-UI
   data and never final patient-record claims; only current, promoted,
   human-reviewed document records may support one.
2. **No applicability conclusion.** Guideline retrieval may provide relevant
   publisher evidence, but the co-pilot does not assert that a recommendation
   applies to the patient, combine the two lanes into advice, or let guideline
   evidence amend or override the record. The UI states that applicability was
   not determined and remains physician judgment.
3. **Closed source registry.** The accepted URI families are the existing
   `openemr:` record identity, an immutable reviewed-document field identity
   `document:{source}:record:{record}:v:{version}:field:{field}`, and an
   immutable guideline chunk identity
   `guideline:{corpus_version}:{document}:{chunk}`. Resolution is allowed only
   through registered typed resolvers and the current turn's evidence set;
   there is no generic URI or network fallback.
4. **Resolver-authored citations.** The model may select source IDs but cannot
   author citation metadata. After a claim verifies, the source resolver emits
   the strict citation union required by the
   [Week 2 claim contract](../specs/week2-claim-citation-verification-contracts.md).
   It includes the PRD minimum—source type and ID, page or section, field or
   chunk ID, and quote or value—plus the immutable versions and hashes needed
   to verify and reopen the source.
5. **Exact guideline excerpts.** A guideline-evidence claim contains a bounded
   exact excerpt from one active, approved corpus chunk, not a model paraphrase.
   The verifier checks the quote against the immutable chunk text and hashes.
   Scores and rank never authorize a claim.
6. **Reviewed value and printed evidence stay distinct.** A document citation
   carries the reviewed value and the original printed quote, page, normalized
   box, evidence ID, and page/source hashes. If the physician corrected the
   value, both are rendered with an explicit correction marker; the system
   never implies that the corrected value was printed on the page.
7. **Binding, freshness, and conflicts.** Patient sources must match the live
   authorized site, patient, conversation, turn, and current source/record
   version. Guideline sources must match the active approved corpus version,
   freshness policy, and source/chunk hashes. Patient conflicts cite every
   conflicting record; deterministically declared guideline disagreement
   renders as separate exact excerpts. Neither evidence class wins over the
   other.
8. **Atomic fail-closed rendering.** An unresolved, stale, unauthorized,
   wrong-class, altered, or incompletely cited source withholds the whole claim.
   Independently verified claims may still render with a typed limitation. If
   a lane has no verified claim, it renders only its limitation. A mixed answer
   has no model-authored cross-lane clinical summary.

The reserved names `document_extract` and `guideline_reference` are not final
claim types. The former confuses an unreviewed proposal with a clinical record
fact; the latter does not guarantee exact publisher evidence. Implementations
use the discriminated contracts in the normative specification instead.

## Alternatives Considered

### One generic claim and citation type

- Benefits: fewer schemas and minimal change to the Week 1 response.
- Costs and risks: source-class confusion, optional provenance, and no
  type-level prevention of a guideline supporting a patient fact.
- Reason rejected: separation is an explicit PRD safety requirement.

### Deterministically verify model paraphrases of guidelines

- Benefits: smoother prose.
- Costs and risks: exact string and metadata checks cannot establish semantic
  entailment; a second model judge would violate the existing verification
  boundary and is outside mandatory core.
- Reason rejected: exact excerpts are inspectable and mechanically verifiable.

### Let schema-valid extraction proposals support the chat

- Benefits: facts could appear before physician review.
- Costs and risks: machine confidence would become clinical authority and the
  final response could disagree with the reviewed OpenEMR module record.
- Reason rejected: owner approval requires human review before promotion.

### Infer patient applicability from record facts and retrieved guidance

- Benefits: more directive answers.
- Costs and risks: creates a clinical recommendation/eligibility engine,
  exceeds the bounded pre-visit workflow, and cannot be validated by source
  identity and exact-value rules alone.
- Reason rejected: evidence is provided for physician judgment, not advice.

## Consequences

### Positive

- The final response makes source authority visually and structurally clear.
- Every displayed Week 2 claim can be checked without asking a model to grade
  another model.
- A corrected value remains traceable to both the review decision and the
  original document region.
- Failure in one evidence lane does not force fabrication or erase verified
  evidence from the other.

### Negative and residual risk

- Exact guideline excerpts are less conversational than paraphrases.
- Relevance does not prove clinical applicability; clinician-reviewed retrieval
  evals remain a release gate under ADR-0010.
- Native OpenEMR rows without immutable content hashes retain the Week 1
  limitation: exact typed fields and same-turn resolution, rather than a whole-
  row hash, establish support.
- Source preview availability and cross-runtime citation rendering require
  integration tests during implementation.

## Verification

- Contract fixtures reject mixed source classes, proposal-backed patient
  claims, unknown schemes, unknown fields, altered values/quotes, shifted
  boxes, wrong hashes, stale record/corpus versions, and missing citation
  fields.
- Authorization cases cover a patient switch, another patient's source ID,
  inactive/withdrawn document records, and agent attempts to resolve review-UI
  proposals.
- Guideline cases cover exact quote resolution, corpus-pointer mismatch,
  snapshot staleness, chunk/source hash mismatch, disallowed applicability or
  advice wording, no result, and retrieval outage.
- Rendering cases prove separate patient/guideline lanes, dual display of a
  corrected reviewed value and printed quote, atomic per-claim withholding,
  partial-lane degradation, and zero unverified cross-lane summary text.

## Revisit Triggers

- A deterministic, non-model semantic entailment mechanism is adopted and
  shown to preserve exact source meaning.
- Clinician validation requires an explicitly scoped applicability workflow;
  that requires a new use case, safety contract, and decision rather than an
  implicit extension of this one.
- A new evidence authority or document type cannot fit one of the three typed
  source families without weakening provenance.
