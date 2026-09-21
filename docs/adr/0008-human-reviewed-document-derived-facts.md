# ADR-0008: Human-reviewed promotion of document-derived facts

- **Status:** Accepted 2026-09-21; expanded after independent review the same day
- **Date:** 2026-09-21
- **Owners:** Andre Batista (OpenEMR module and clinical write boundary)
- **Related requirements:** Week 2 PRD “FHIR and OpenEMR integrity” and Core
  Agent Requirement 1; source documents and derived facts must round-trip
  without duplicate or untraceable records. `AGENTS.md`: agent operations
  remain read-only unless an explicit narrow write workflow is authorized.
- **Related use cases:** UC-01 and UC-02; Week 2 document-derived changes and
  unresolved abnormal laboratory results.
- **Related decisions:** ADR-0002 (patient-scope authorization), ADR-0003
  (module gateway), ADR-0005 (patient-bound state), ADR-0006 (verification),
  ADR-0009 (extraction states).

## Context

The Week 2 PRD requires the source document and reviewed derived facts to
round-trip through OpenEMR. Runtime testing found that OpenEMR document upload
is duplicate-prone, ordinary FHIR create routes for the needed resources are
absent, and one standard binary-download failure can place decrypted bytes in
logs. The Week 1 agent is intentionally read-only and must not acquire database
credentials or become a clinical-write authority.

The owner requires explicit human review and permits source upload only through
a deliberate UI action. A safe design therefore needs two distinct records:
model-proposed facts and human-reviewed OpenEMR records.

## Decision

1. **Module ownership.** The OpenEMR custom module—not the agent service—owns
   module tables for source-upload intents, extraction versions, proposed
   facts, reviews, and promotions. The agent accesses them only through the
   authorized module gateway. OpenEMR remains the canonical owner of the
   original document bytes.
2. **Explicit upload.** Only the patient-bound upload UI can create a source
   document. The boundary rechecks the live user, site, active patient,
   requested operation, `patients/docs` and category ACLs, squad policy, and
   break-glass denial. Chat and model output cannot invoke upload.
3. **Upload idempotency.** Each UI intent has a server-issued UUID. A unique
   key over `(site, patient, category, upload_intent_uuid)` maps retries to one
   OpenEMR document identity. The content hash is retained for integrity and
   duplicate warning, but identical bytes under a new intent are not silently
   deduplicated.
4. **Proposed facts.** Extraction creates immutable module-owned proposed-fact
   rows with patient, source-document UUID and content hash, extraction
   version, schema version, field evidence, value, and extraction state. These
   rows are OpenEMR module records but are not reviewed chart facts.
5. **Human review.** The physician may approve, correct, or reject each field.
   A correction creates an append-only review record containing the reviewed
   value, original proposed value, supporting page/region, reviewer, timestamp,
   and reason; it never overwrites extraction evidence. Low confidence does not
   prevent review, and high confidence does not bypass it.
6. **Promotion targets.** Promotion creates immutable, module-owned OpenEMR
   reviewed records through one narrow gateway action:
   - a lab promotion stores one reviewed lab report plus analyte children using
     an Observation-shaped schema (test/code when present, typed value, unit,
     reference range, collection date, abnormal flag, and source evidence);
   - an intake promotion stores one reviewed FHIR R4
     `QuestionnaireResponse`-shaped record containing the approved answers.
   These records round-trip through the module gateway and co-pilot UI. Week 2
   does not mutate native demographics, medication, allergy, problem, order,
   or procedure-result tables and does not expose unsupported FHIR create
   routes. Existing OpenEMR reconciliation workflows remain authoritative for
   those native lists.
7. **Promotion idempotency and transaction.** The deterministic key is
   `SHA-256(site | patient | source_document_uuid | source_hash |
   extraction_version | reviewed_fact_or_response_id | target_type)`. A unique
   constraint covers it. The action, reviewed target, provenance link, and
   audit outbox row commit in one database transaction. A completed retry
   returns the existing target; an interrupted `started` action is reconciled
   before retry and can never create a second target.
8. **Authorization and audit.** Every review and promotion rechecks live user,
   site, patient, operation scope, target-specific write ACL, squad, and
   break-glass state. Audit data includes correlation ID, bounded action type,
   target ID, source/extraction version, idempotency outcome, reviewer ID, and
   result—but no OCR, document bytes, raw values, or unrestricted prompts.
9. **Failure and compensation.** Missing authorization, source mismatch,
   conflict, stale extraction, unavailable target contract, or failed
   transaction leaves the fact unpromoted with an explicit limitation.
   Correction or withdrawal creates a compensating version and audit event;
   reviewed history is never deleted or silently changed.

## Alternatives Considered

### Automatic FHIR or native clinical writes

- Benefits: superficially direct interoperability.
- Costs and risks: required create routes are absent, core services do not
  supply this authorization/idempotency/provenance contract, and model output
  would become chart truth without review.
- Reason rejected: violates the owner’s review requirement and Week 1 safety
  boundary.

### Write native medication, allergy, demographics, and lab-order tables

- Benefits: values appear in existing chart widgets.
- Costs and risks: an intake answer is not a reconciled medication/allergy
  list, and an external lab document does not prove an OpenEMR order occurred.
- Reason rejected: it would manufacture clinical workflow state and broaden
  the write surface beyond the PRD.

### Keep the ledger in the agent service only

- Benefits: simpler Python persistence.
- Costs and risks: derived facts would not round-trip through OpenEMR and the
  agent would become the clinical-record owner.
- Reason rejected: conflicts with the PRD and existing trust boundary.

## Consequences

### Positive

- The core demonstrates a complete UI upload → extraction → review → OpenEMR
  module record → authorized read-back round trip.
- The model and agent remain unable to write clinical records.
- Idempotency and immutable provenance are testable at one narrow boundary.

### Negative and residual risk

- Reviewed records are module-owned and are not interchangeable with core
  OpenEMR medications, allergies, procedure results, or public FHIR creates.
- Other OpenEMR screens will not automatically consume the reviewed facts.
- The module schema, transaction/outbox behavior, and read-back projection must
  be implemented and migrated carefully.

## Verification

- Upload the same synthetic document twice with the same intent and assert one
  document mapping; use a new intent and assert an explicit duplicate warning.
- For both document types, approve synthetic facts and re-read the reviewed
  record, source identity, extraction version, review, and page/region through
  the authorized gateway.
- Retry promotion before response, after transaction commit, and after an
  injected partial failure; assert one target and one completed action.
- Negative tests cover patient switch, missing write ACL, squad restriction,
  break-glass, stale extraction, source-hash mismatch, and rejected fact.
- Inspect audit/log/trace output and assert no document text, OCR, raw value, or
  image bytes are present.

## Revisit Triggers

- OpenEMR exposes supported create APIs with equivalent authorization,
  provenance, idempotency, and audit semantics.
- Clinician validation requires reviewed facts to populate a native chart list.
- A module-owned reviewed record cannot satisfy grading after demonstrating the
  documented OpenEMR round trip.
