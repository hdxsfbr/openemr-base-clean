# AgentForge Clinical Evidence Context

This context defines the terms used for document ingestion and clinical evidence
in the Week 2 Clinical Co-Pilot planning work.

## Clinical document terms

**Source document**:
The original file explicitly uploaded by a user and stored in OpenEMR as the
canonical clinical-document artifact.
_Avoid_: Input, attachment, upload blob.

**Proposed fact**:
A structured value extracted from a source document, with source and extraction
provenance, that has not yet been accepted into the patient's clinical record.
_Avoid_: Observation, verified fact, chart fact.

**Clinical record fact**:
A reviewed fact persisted as an immutable OpenEMR module record through the
authorized promotion boundary; it is distinct from OpenEMR's native medication,
allergy, problem, order, and procedure-result records.
_Avoid_: Proposed fact, model output, native chart fact.

**Proposed-facts ledger**:
The reviewable AgentForge persistence for proposed facts and their provenance;
it is not itself part of the patient's clinical record.
_Avoid_: Shadow chart, staging chart, source of truth.

**Promotion**:
The explicit, idempotent creation of a reviewed OpenEMR module record from a
human review, retaining the proposed value, reviewed value, source, and actor.
_Avoid_: Sync, publish, auto-write.

## Extraction terms

**Field evidence**:
The page, normalized bounding box, exact quote or value, and extraction metadata
that support one proposed fact.
_Avoid_: Citation, confidence score alone, source link.

**Review-required fact**:
A proposed fact shown to the physician because evidence exists but ambiguity,
low confidence, conflict, or incomplete validation prevents safe acceptance.
_Avoid_: Accepted fact, verified chart fact.

**Extraction version**:
An immutable attempt to extract proposed facts from one source-document version.
_Avoid_: Overwrite, latest truth, correction in place.

**Extraction state**:
The machine-processing result for one proposed fact: schema-valid,
review-required, rejected, or unavailable. It never records human approval.
_Avoid_: Accepted, approved, promoted.

**Review decision**:
The physician's append-only decision on a proposed fact: pending, approved,
corrected, rejected, or superseded.
_Avoid_: Extraction status, confidence, automatic acceptance.

## Guideline evidence terms

**Guideline corpus**:
A versioned, locally available collection of publisher-maintained recommendation
content that the co-pilot may retrieve as evidence. A corpus is not a license to
make a recommendation without matching patient evidence and physician judgment.
_Avoid_: The internet, medical knowledge, current guidelines.

**Evidence chunk**:
An addressable excerpt from a guideline corpus with publisher, source URL,
topic or section, corpus version, content hash, and exact text preserved for
inspection.
_Avoid_: Citation, passage, search result.

**Retrieval limitation**:
An explicit user-visible state when the corpus has no matching evidence or is
unavailable; it prevents the system from presenting an unsupported guideline
claim.
_Avoid_: Empty result, fallback answer, best effort.

## Final response terms

**Patient-record claim**:
A final clinical claim supported only by authorized patient records, including
a current promoted human-reviewed document record.
_Avoid_: Extracted claim, proposal, guideline claim.

**Guideline-evidence claim**:
A final evidence item that reproduces a bounded exact publisher excerpt from
the active approved corpus without deciding patient applicability.
_Avoid_: Recommendation, medical advice, guideline reference.

**Clinical citation**:
Resolver-produced metadata that connects one verified claim to its exact
record field, document region, or guideline chunk and integrity version.
_Avoid_: Model citation, source link alone, search result.

**Applicability conclusion**:
A judgment that guideline evidence applies to a particular patient. It is not
part of the Week 2 co-pilot; applicability remains physician judgment.
_Avoid_: Relevant evidence, retrieved excerpt.

## Orchestration terms

**Supervisor**:
The deterministic coordinator that selects an allowed route from a typed event
and trusted workflow state; it never makes a clinical judgment or writes an
answer.
_Avoid_: Router model, clinical agent, answer agent.

**Intake-extractor worker**:
The bounded document worker required by the Week 2 PRD; despite its name, it
extracts both lab reports and intake forms into reviewable proposed facts.
_Avoid_: Intake-only worker, chart writer, document-answer agent.

**Evidence-retriever worker**:
The read-only worker that executes a strict local evidence query against the
active guideline corpus and returns exact evidence chunks or a retrieval
limitation.
_Avoid_: Recommendation agent, applicability agent, medical search agent.

**Worker handoff**:
A typed, status-bearing request and result linking one supervisor route to one
worker run through identifiers, versions, reasons, timing, and limitations.
_Avoid_: Prompt, agent conversation, raw worker transcript.
