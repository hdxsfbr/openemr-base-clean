# ADR-0011: Canonical reviewed-document record contracts and lifecycle

- **Status:** Accepted 2026-09-21; partially supersedes ADR-0008 sections 3,
  6, 7, and 9 and ADR-0009 sections 1, 4, 5, and 6
- **Date:** 2026-09-21
- **Owners:** Andre Batista (document review and module record boundary)
- **Related requirements:** Week 2 PRD FHIR/OpenEMR integrity, strict lab and
  intake schemas, source-grounded review, idempotent round trip, and explicit
  human approval.
- **Related use cases:** UC-01 and UC-02; document-derived changes and abnormal
  laboratory review before a visit.
- **Related decisions:** ADR-0002 (authorization), ADR-0003 (module gateway),
  ADR-0005 (patient-bound state), ADR-0006 (verification), ADR-0008 (human
  review), and ADR-0009 (bounded extraction).

## Context

ADR-0008 and ADR-0009 established the safe ownership and extraction model, but
their accepted text left the aggregate promotion identity, exact module record
shape, file-type discriminator, and post-promotion lifecycle open. Independent
review showed those omissions would force implementation-time clinical-data
decisions and make a retry-safe round trip impossible to test precisely.

## Decision

1. **Canonical contract.** The normative
   [Week 2 document contract](../specs/week2-document-record-contracts.md)
   fixes every extraction, evidence, review, promoted-record, lifecycle,
   gateway, error, and read-back field, including types, unions, enums,
   cardinalities, nullability, and conditional constraints. Implementation
   uses strict Pydantic models, exported JSON Schema, and cross-runtime module
   fixtures; unknown fields are rejected.
2. **Discriminated source limits.** A lab source is PDF-only, no more than 20
   MiB or 20 pages. An intake source is PDF, PNG, or JPEG, no more than 10 MiB
   or 10 pages; an image is exactly one page. Request metadata is only a
   declaration. The module content-sniffs MIME and measures bytes/pages before
   permanent storage or extraction, rejecting any mismatch.
3. **Retry-safe upload intent.** The deliberate UI action creates a UUID
   idempotency key. The server-derived `(site, patient, category,
   idempotency_key)` maps request retries to one server-issued intent; content
   retries on that intent map to one OpenEMR document. A different UI action
   may upload identical bytes but receives a visible duplicate warning.
4. **Aggregate promotion identity.** Sort the complete current review UUID set
   lexically and hash its newline-delimited canonical representation as
   `review_set_sha256`. The deterministic key is `SHA-256(site | patient |
   source_document_uuid | source_hash | extraction_version | target_type |
   review_set_sha256)`. Record, provenance, idempotency action, and outbox
   event commit in one transaction.
5. **Explicit lifecycle.** Initial promotion creates version 1. Amendment and
   withdrawal are explicit physician-only gateway commands with an expected
   record version, idempotency key, and reason. Amendment supplies a complete
   current review set and creates the next immutable version. Withdrawal
   creates a terminal next version retaining prior values for audit but making
   them unusable as the current record. Neither operation overwrites history or
   mutates native OpenEMR clinical lists.
6. **Authority and visibility.** Upload, review, promotion, amendment, and
   withdrawal recheck live user, site, active patient, operation, target ACL,
   squad policy, and break-glass denial. Only the UI can upload or write. The
   agent can receive authorized read projections but cannot invoke these write
   routes. OCR and raw values remain protected record data, not telemetry.

## Alternatives Considered

### Leave schemas and lifecycle to implementation

- Benefits: less planning text.
- Costs and risks: incompatible module/Python models, ambiguous retry identity,
  and unreviewed clinical semantics chosen inside code.
- Reason rejected: strict cross-boundary contracts are a safety invariant.

### Edit ADR-0008 and ADR-0009 in place

- Benefits: fewer files.
- Costs and risks: accepted decisions would lose stable history and review
  provenance.
- Reason rejected: the ADR index requires accepted records to remain immutable
  except for status and supersession links.

### Delete or overwrite a reviewed record

- Benefits: simpler current-state storage.
- Costs and risks: destroys provenance and makes prior physician decisions
  unauditable.
- Reason rejected: amendment and withdrawal must be append-only.

## Consequences

### Positive

- Module and agent implementations have one testable source of schema truth.
- Lost responses cannot create extra upload intents or reviewed records.
- Every promoted, amended, or withdrawn value resolves to a review and source
  region without granting the model write authority.

### Negative and residual risk

- The schema is intentionally narrow and requires a versioned ADR/contract
  change when a new clinical field or workflow is introduced.
- Module-owned reviewed records do not automatically populate native chart
  lists or public FHIR create routes.
- Storage migrations and retention controls still require implementation and
  operational verification.

## Verification

- Generate JSON Schema and run cross-runtime fixtures for every field, union,
  enum, bound, conditional file rule, and unknown-field denial.
- Retry intent creation, content upload, review, promotion, amendment, and
  withdrawal before and after commit; assert one immutable version per action.
- Round-trip complete synthetic lab and intake records and resolve each value
  to source hash, page, region, OCR span, review, actor, and provenance.
- Negative tests cover content/request mismatch, patient switch, ACL denial,
  stale extraction/record version, incomplete review set, wrong typed
  correction, shifted evidence, source mismatch, and agent/model writes.

## Revisit Triggers

- OpenEMR exposes supported native/FHIR write APIs with equivalent review,
  provenance, authorization, idempotency, and append-only lifecycle semantics.
- Clinician validation requires another field or native chart reconciliation.
- Cross-runtime schema generation cannot preserve the exact contract.
