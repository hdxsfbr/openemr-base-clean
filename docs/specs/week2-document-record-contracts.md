# Week 2 document extraction, review, and record contracts

- **Status:** Normative design contract for Week 2 implementation
- **Date:** 2026-09-21
- **Applies to:** ADR-0011, which partially supersedes ADR-0008 and ADR-0009
- **Out of scope:** Claim/citation URI shapes, which are owned by the next
  patient-record-versus-guideline claim contract decision

This document fixes the types, cardinalities, states, and gateway shapes for
the two approved document workflows. Implementation must encode these models
as strict Pydantic models, export JSON Schema, and use the same generated
schemas at the module gateway. Unknown properties are rejected. All examples,
fixtures, and verification data must be synthetic.

## Common types and invariants

| Type | Contract |
| --- | --- |
| `Uuid` | Lowercase canonical UUID string. |
| `Sha256` | Exactly 64 lowercase hexadecimal characters. |
| `Date` | ISO 8601 full date, `YYYY-MM-DD`. |
| `DateTime` | ISO 8601 UTC timestamp ending in `Z`. |
| `OpenEmrUserId` | Non-empty server-side user identifier, `1..128` characters. |
| `CorrelationId` | String matching `^[A-Za-z0-9\-._]{8,64}$`; the existing `{conversation}.{turn}` identifier from ADR-0007. |
| `FieldId` | String matching `^[a-z][a-z0-9_.-]{0,127}$`. |
| `NormalizedBox` | Object with decimal `x`, `y`, `width`, and `height`; each is in `[0,1]`, and `x + width <= 1`, `y + height <= 1`. |
| `ExtractionState` | `schema_valid`, `review_required`, `rejected`, or `unavailable`. |
| `ReviewDecision` | `pending`, `approved`, `corrected`, `rejected`, or `superseded`. |
| `ValidationCode` | `valid`, `low_confidence`, `missing`, `ambiguous`, `conflicting`, `invalid_type`, `invalid_format`, `quote_mismatch`, or `out_of_bounds`. |

The gateway derives `site_id`, `patient_id`, and requesting user from its
authorized server-side context. No command below accepts any of them from the
browser or agent. A patient-context change invalidates the command.

`SourceDocumentRef` has exactly these required fields:

| Field | Type |
| --- | --- |
| `source_document_id` | `Uuid` |
| `openemr_document_id` | non-empty string, maximum 128 characters |
| `upload_intent_id` | `Uuid` |
| `document_type` | `lab_report` or `intake_form` |
| `content_sha256` | `Sha256` |
| `byte_count` | positive integer, conditionally bounded below |
| `mime_type` | conditionally bounded below |
| `page_count` | positive integer, conditionally bounded below |

The source discriminator is normative: `lab_report` requires
`mime_type=application/pdf`, `byte_count <= 20,971,520`, and `page_count <= 20`.
`intake_form` requires `byte_count <= 10,485,760` and `page_count <= 10`; PDF
permits 1–10 pages, while PNG and JPEG require exactly one page. A mismatched
combination is rejected before permanent storage or extraction. The values in
this reference are the module's measured values, not browser declarations.

`FieldEvidence` has exactly these required fields:

| Field | Type |
| --- | --- |
| `evidence_id` | `Uuid` |
| `page_number` | integer `1..source.page_count` |
| `box` | `NormalizedBox` |
| `printed_quote` | string `1..500` characters; exact text or printed value displayed to the reviewer |
| `ocr_span_start` | integer `>= 0` |
| `ocr_span_end` | integer `> ocr_span_start` and within the retained page OCR text |
| `ocr_text_sha256` | `Sha256` of the retained page OCR text |
| `rendered_page_sha256` | `Sha256` |
| `confidence` | decimal in `[0,1]`; diagnostic only |
| `validation` | non-empty array of `1..10` distinct `ValidationCode` values |

Every proposed field uses the following generic shape. `value` is nullable so
the UI can show a missing or unavailable field, but it may be null only when
`state` is `review_required` or `unavailable`; a `schema_valid` field always has
a non-null value.

| `ProposedField<T>` field | Type |
| --- | --- |
| `field_id` | required stable `FieldId` |
| `value` | required `T` or null |
| `state` | required `ExtractionState`; never represents human approval |
| `evidence` | required array of `1..3` `FieldEvidence` items for non-null values; empty only for a missing/unavailable null |

`OcrToken` has exactly `token_index: integer >= 0`, `text: string 1..500`,
`span_start: integer >= 0`, `span_end: integer > span_start`, `box:
NormalizedBox`, and `confidence: decimal in [0,1]`. Tokens are ordered by
`token_index`, indexes are contiguous from zero, spans are non-overlapping and
within the page text, and token text must equal its page-text span.

`OcrPage` has exactly `page_number: integer >= 1`, `text: string 0..100000`,
`text_sha256: Sha256`, `rendered_page_sha256: Sha256`, `renderer_version:
string 1..64`, `preprocessing_version: string 1..64`, and `tokens: array of
0..50000 OcrToken` objects. An empty OCR result has empty text and tokens but
still carries page/render/version hashes.

`ExtractionEnvelope<T>` has required `extraction_id: Uuid`,
`extraction_version: integer >= 1`, `schema_name`, `schema_version` fixed by the
payload type, `source: SourceDocumentRef`, `state: ExtractionState`,
`created_at: DateTime`, `ocr_pages`, and `payload: T`. `ocr_pages` contains
exactly `source.page_count` `OcrPage` items numbered contiguously from one. OCR
text is protected ledger data and is never emitted in ordinary logs, traces,
metrics, or errors.

## Laboratory extraction and reviewed record

The extraction envelope fixes `schema_name` to `lab-report` and
`schema_version` to `1.0.0`. Its payload is:

| Field | Type and cardinality |
| --- | --- |
| `collection_date` | exactly one `ProposedField<Date>` |
| `analytes` | array of `1..200` `ProposedAnalyte` items |

Each `ProposedAnalyte` has a required `analyte_id: Uuid` and these fields:

| Field | Type |
| --- | --- |
| `test_name` | exactly one `ProposedField<string 1..200>` |
| `code` | zero or one `ProposedField<CodedValue>` |
| `value` | exactly one `ProposedField<QuantityValue | TextValue>` discriminated by `kind` |
| `unit` | zero or one `ProposedField<string 1..80>`; omitted when not printed |
| `reference_range` | zero or one `ProposedField<ReferenceRange>`; omitted when not printed |
| `abnormal_flag` | zero or one `ProposedField<AbnormalFlag>`; omitted when not printed |

`CodedValue` contains `system` (URI, maximum 500), `code` (string `1..100`),
and optional `display` (string `1..200`). It is allowed only when printed or
produced by an approved deterministic mapping table whose version is recorded
with the extraction. `QuantityValue` is `{kind: "quantity", value: decimal}`;
`TextValue` is `{kind: "text", value: string 1..500}`. `ReferenceRange` is an
object containing at least one of `low: decimal`, `high: decimal`, or
`text: string 1..200`, plus optional printed `unit: string 1..80`.
`AbnormalFlag` is `low`, `high`, `abnormal`, `normal`, or `unknown`.

Every promoted value uses `ReviewedField<T>` with exactly `value: T`,
`source_field_id: FieldId`, `review_id: Uuid`, and `evidence_ids` (unique array of
`1..3` UUIDs). It has no extraction state or confidence. `ReviewedAnalyte` has
exactly `analyte_id: Uuid`, required `test_name:
ReviewedField<string 1..200>` and `value: ReviewedField<QuantityValue |
TextValue>`, plus optional `code: ReviewedField<CodedValue>`, `unit:
ReviewedField<string 1..80>`, `reference_range:
ReviewedField<ReferenceRange>`, and `abnormal_flag:
ReviewedField<AbnormalFlag>`. Optional fields are absent rather than null or
invented.

`ReviewedLabReport` has exactly:

| Field | Type and cardinality |
| --- | --- |
| `record_id` | `Uuid` |
| `record_version` | integer `>= 1` |
| `status` | `active`, `amended`, or `withdrawn` |
| `supersedes_record_id` | absent at version 1; otherwise required `Uuid` |
| `source` | `SourceDocumentRef` with `document_type=lab_report` |
| `extraction_id` | `Uuid` |
| `extraction_version` | integer `>= 1` |
| `schema_version` | literal `1.0.0` |
| `collection_date` | `ReviewedField<Date>` |
| `analytes` | array of `1..200` `ReviewedAnalyte` objects |
| `review_ids` | unique array of `1..1201` UUIDs; exactly the union of nested `review_id` values |
| `reviewed_by` | `OpenEmrUserId` |
| `reviewed_at` | `DateTime` |
| `lifecycle_reason` | absent for version 1; required string `1..500` for amended/withdrawn versions |
| `provenance` | `RecordProvenance` defined below |

Amendment or withdrawal creates a new record version and does not overwrite
the prior one. A withdrawn version retains the prior values and provenance for
audit/read-back; it is not usable as a current clinical record.

## Intake extraction and reviewed record

The extraction envelope fixes `schema_name` to `intake-form` and
`schema_version` to `1.0.0`. Its payload contains exactly these collections:

| Field | Type and cardinality |
| --- | --- |
| `demographics` | exactly one `ProposedDemographics` object |
| `chief_concern` | zero or one `ProposedField<string 1..2000>` |
| `medications` | array of `0..50` `ProposedMedication` entries |
| `allergies` | array of `0..50` `ProposedAllergy` entries |
| `family_history` | array of `0..50` `ProposedFamilyHistory` entries |

`ProposedDemographics` has zero or one `ProposedField` for each of:
`given_name` and `family_name` (string `1..100`), `date_of_birth` (`Date`),
`administrative_sex` (`female`, `male`, `other`, or `unknown`),
`gender_identity` and `pronouns` (string `1..100`), `address` (string
`1..500`), and `phone` (string `1..50`). These answers help detect a mismatch;
they never select or change the active patient.

Every collection entry has a required `entry_id: Uuid`. A medication requires
`name: ProposedField<string 1..200>` and permits zero or one proposed field for
`strength`, `dose`, `route`, `frequency` (each string `1..100`), and `status`
(`active`, `inactive`, `stopped`, or `unknown`). An allergy requires
`substance: ProposedField<string 1..200>` and permits `reaction` (string
`1..500`), `severity` (`mild`, `moderate`, `severe`, or `unknown`), and `status`
(`active`, `inactive`, `resolved`, or `unknown`). Family history requires
`relationship` and `condition` (each `ProposedField<string 1..200>`) and
permits `onset_age_years: ProposedField<integer 0..130>`.

The stable `link_id` mapping is exact:

| Source field | `link_id` | Answer kind |
| --- | --- | --- |
| `demographics.given_name`, `.family_name`, `.gender_identity`, `.pronouns`, `.address`, `.phone` | same path with dots changed to hyphens | `string` |
| `demographics.date_of_birth` | `demographics-date-of-birth` | `date` |
| `demographics.administrative_sex` | `demographics-administrative-sex` | `choice` |
| `chief_concern` | `chief-concern` | `string` |
| medication `name`, `strength`, `dose`, `route`, `frequency` | `medication-<field>` | `string` |
| medication `status` | `medication-status` | `choice` |
| allergy `substance`, `reaction` | `allergy-<field>` | `string` |
| allergy `severity`, `status` | `allergy-<field>` | `choice` |
| family-history `relationship`, `condition` | `family-history-<field>` | `string` |
| family-history `onset_age_years` | `family-history-onset-age-years` | `integer` |

`ReviewedAnswer` is a discriminated union of `{kind: "string", value: string
1..2000}`, `{kind: "date", value: Date}`, `{kind: "integer", value: integer
0..130}`, or `{kind: "choice", value: one of the field's declared enum}`.
`ReviewedQuestionnaireItem` has exactly `item_id: Uuid`, `link_id` from the
table, `repeat_key` (required entry `Uuid` for medication, allergy, or family
history; otherwise absent), `source_field_id`, `review_id: Uuid`,
`evidence_ids` (unique array of `1..3` UUIDs), and `answer: ReviewedAnswer`.

`ReviewedIntakeResponse` has exactly:

| Field | Type and cardinality |
| --- | --- |
| `record_id` | `Uuid` |
| `record_version` | integer `>= 1` |
| `resource_type` | literal `QuestionnaireResponse` |
| `questionnaire` | literal `urn:agentforge:questionnaire:intake:v1` |
| `status` | `completed`, `amended`, or `stopped` |
| `supersedes_record_id` | absent at version 1; otherwise required `Uuid` |
| `source` | `SourceDocumentRef` with `document_type=intake_form` |
| `extraction_id` | `Uuid` |
| `extraction_version` | integer `>= 1` |
| `schema_version` | literal `1.0.0` |
| `subject` | server-derived string matching `^Patient/[A-Za-z0-9.-]{1,64}$` |
| `authored` | `DateTime` |
| `reviewed_by` | `OpenEmrUserId` |
| `review_ids` | unique array of `1..659` UUIDs; exactly the union of item `review_id` values |
| `items` | array of `1..659` `ReviewedQuestionnaireItem` objects |
| `lifecycle_reason` | absent for version 1; required string `1..500` for amended/stopped versions |
| `provenance` | `RecordProvenance` defined below |

This is a module-owned FHIR R4 QuestionnaireResponse-shaped record, not a
public FHIR create and not a mutation of native patient lists. A new version
links the prior one with `supersedes_record_id`.

## Review and promotion commands

`CorrectedValue` is a union discriminated by `kind`:

| `kind` | `value` |
| --- | --- |
| `string` | string `1..2000` |
| `date` | `Date` |
| `integer` | integer `0..130` |
| `choice` | one of `female`, `male`, `other`, `unknown`, `active`, `inactive`, `stopped`, `resolved`, `mild`, `moderate`, `severe`, `low`, `high`, `abnormal`, or `normal`; the target field narrows this set |
| `coded` | `CodedValue` |
| `measurement` | `QuantityValue` or `TextValue`, using its nested `kind` discriminator |
| `reference_range` | `ReferenceRange` |

The `field_id` selects exactly one permitted branch and its narrower field
bounds; a different branch or an out-of-range value is `invalid_contract`.
`DocumentFieldValue` in stored reviews is the explicit union of string
`1..2000`, `Date`, integer `0..130`, the listed choice enum, `CodedValue`,
`QuantityValue`, `TextValue`, or `ReferenceRange`. The target `field_id`
deterministically narrows that union and its bounds.

`ReviewFactCommand` contains exactly:

| Field | Type |
| --- | --- |
| `idempotency_key` | `Uuid` |
| `extraction_id` | `Uuid` |
| `expected_extraction_version` | integer `>= 1` |
| `field_id` | `FieldId` from the extraction |
| `action` | `approve`, `correct`, or `reject` |
| `corrected_value` | absent unless `action=correct`; then required `CorrectedValue` |
| `reason` | absent for approval; required string `1..500` for correction or rejection |

One command produces one append-only `FactReview` with exactly:

| Field | Type and cardinality |
| --- | --- |
| `review_id` | server-issued `Uuid` |
| `idempotency_key` | command `Uuid` |
| `extraction_id` | command `Uuid` |
| `extraction_version` | command integer `>= 1` |
| `field_id` | command `FieldId` |
| `proposed_value` | required `DocumentFieldValue` or null, copied from the immutable proposal |
| `final_value` | `DocumentFieldValue` for approval/correction; absent for rejection |
| `evidence_ids` | copied unique array of `0..3` UUIDs; zero only for a rejected missing field |
| `decision` | `approved`, `corrected`, or `rejected` |
| `reason` | absent for approval; required string `1..500` otherwise |
| `reviewed_by` | `OpenEmrUserId` |
| `reviewed_at` | `DateTime` |
| `supersedes_review_id` | absent or one prior `Uuid` for the same proposed field |
| `idempotency_outcome` | `created` or `replayed` |

Approval is rejected for a null proposed value. A stale extraction, source
mismatch, or changed patient context cannot create a review. The read model
derives `current_status=superseded` for a review referenced by a later review;
the immutable recorded `decision` is never rewritten.

`PromoteReviewedDocumentCommand` contains exactly `idempotency_key: Uuid`,
`extraction_id: Uuid`, `expected_extraction_version: integer >= 1`,
`source_content_sha256: Sha256`, `target_type` (`lab_report` or
`intake_response`), and `review_ids` (unique array of `1..1201` UUIDs). The
server computes `review_set_sha256` from the lexically sorted,
newline-delimited UUIDs and uses the ADR-0011 deterministic key. Every
promotable non-null field must have one current approved or corrected review;
no rejected, pending, superseded, missing, or unavailable field is promoted.

`RecordProvenance` has exactly `action_id: Uuid`, `action` (`promote`, `amend`,
or `withdraw`), `action_idempotency_key: Uuid`, `review_set_sha256: Sha256`,
`source_content_sha256: Sha256`, `extraction_id: Uuid`,
`extraction_version: integer >= 1`, `acted_by: OpenEmrUserId`, `acted_at:
DateTime`, and `correlation_id: CorrelationId`.
`PromoteReviewedDocumentResponse` has exactly `promotion_id: Uuid`,
`target_type` (`lab_report` or `intake_response`), `target_record_id: Uuid`,
`record_version: integer >= 1`, `review_set_sha256: Sha256`, and `outcome`
(`created` or `replayed`). Validation failures use the errors below and create
no target.

`ReviseReviewedRecordCommand` has exactly `idempotency_key: Uuid`,
`record_id: Uuid`, `expected_record_version: integer >= 1`, `action` (`amend`
or `withdraw`), `review_ids`, and `reason: string 1..500`. For amendment,
`review_ids` is a unique complete current set of `1..1201` UUIDs; for
withdrawal it must be absent, and the prior version's review set is retained.
The server derives source, extraction, target type, and patient from the
current record and rejects cross-source reviews. It creates exactly the next
record version. An amendment status is `amended`; a withdrawal status is
`withdrawn` for a lab or `stopped` for an intake response.
`ReviseReviewedRecordResponse` has exactly `action_id: Uuid`, `record_id:
Uuid`, `record_version: integer >= 2`, `status` (`amended`, `withdrawn`, or
`stopped`), `review_set_sha256: Sha256`, and `outcome` (`created` or
`replayed`).

## Gateway routes and read-back

Only the patient-bound co-pilot UI may call the upload routes. The agent may
read authorized extraction/review/record projections but cannot call review,
promotion, amendment, or withdrawal routes.

| Method and route | Request / response |
| --- | --- |
| `POST /documents/upload-intents` | `CreateUploadIntentCommand` to `UploadIntentResponse`, both defined below. |
| `POST /documents/upload-intents/{intent_id}/content` | Multipart bytes plus upload token to `UploadContentResponse`. The body cannot select a patient. |
| `GET /documents/{source_document_id}/extractions/{version}` | Authorized `ExtractionEnvelope`; OCR text is included only in the explicit reviewer projection. |
| `POST /document-reviews` | `ReviewFactCommand` to `FactReview`. |
| `POST /document-promotions` | `PromoteReviewedDocumentCommand` to promotion response. |
| `POST /reviewed-records/{record_id}/revisions` | `ReviseReviewedRecordCommand` to `ReviseReviewedRecordResponse`; only the UI may call it. |
| `GET /reviewed-records/{record_id}` | Exact `ReviewedLabReport` or `ReviewedIntakeResponse`, source reference, extraction version, reviews, provenance, and current/superseded status. |

`CreateUploadIntentCommand` has exactly `idempotency_key: Uuid`, `category`
(`lab_report` or `intake_form`), `original_filename` (basename only, `1..255`
characters), `mime_type`, `byte_count`, and `page_count`, with the conditional
limits from `SourceDocumentRef`; `category` must equal the eventual source
`document_type`. `UploadIntentResponse` has exactly
`upload_intent_id: Uuid`, `upload_token` (opaque string `32..512` characters),
`expires_at: DateTime`, and `outcome` (`created` or `replayed`). The unique key
is the server-derived site/patient/category plus command idempotency key; a
retry after a lost response returns the same intent and token lifetime.
MIME, bytes, and pages in the command are declarations used for early denial;
the content endpoint independently content-sniffs MIME and measures actual
bytes/pages before permanent storage. A mismatch returns `invalid_contract`
and creates no OpenEMR document.

`UploadContentResponse` has exactly `source: SourceDocumentRef`, `outcome`
(`created` or `replayed`), and `warnings` (array of `0..1` `UploadWarning`).
`UploadWarning` has exactly `code: "duplicate_content"`,
`matching_source_document_ids` (unique array of `1..10` UUIDs for the same
authorized patient), and `message` (fixed UI-safe string `1..200`). A new UI
action with identical bytes succeeds with `outcome=created` and this warning;
a retry of the same intent returns `outcome=replayed`. A duplicate warning is
never an error or an idempotency outcome.

All routes recheck user, site, active patient, operation scope, target ACL,
squad policy, and break-glass denial. `ErrorEnvelope` has exactly `code`,
`correlation_id: CorrelationId`, `retryable: boolean`, and `limitation: string
1..500`. `code` is `forbidden`, `patient_context_changed`, `not_found`,
`invalid_contract`, `source_mismatch`, `stale_extraction`, `review_required`,
`conflict`, or `unavailable`. Error bodies contain no document text, OCR,
field values, page images, or prompts.

## Module persistence and transaction constraints

The implementation owns these logical tables; physical OpenEMR prefixes may
be added but their responsibilities may not be merged with native clinical
tables:

- `copilot_document_upload`: unique `(site, patient, category,
  upload_request_idempotency_key)` for intent creation and unique `(site,
  patient, category, upload_intent_id)` for immutable source hash/OpenEMR
  document mapping.
- `copilot_document_extraction`: unique `(source_document_id,
  extraction_version)` and canonical schema-valid extraction JSON.
- `copilot_proposed_fact`: unique `(extraction_id, field_id)` with canonical
  typed value JSON and evidence references.
- `copilot_fact_review`: append-only, unique review-command idempotency key;
  only one current non-superseded review per proposed fact.
- `copilot_promoted_record`: immutable versioned canonical record JSON, unique
  deterministic promotion key and stored `review_set_sha256` from ADR-0011.
- `copilot_action_outbox`: audit/provenance event committed in the same
  transaction as review, promotion, amendment, or withdrawal.

Promotion and revision validate canonical JSON against the exported schema,
insert the new record version and provenance, and append the outbox event in
one transaction. Read-back validates stored JSON before returning it. A
validation or commit failure returns `unavailable` or `conflict` and exposes
no partial target.

## Required contract verification

- JSON Schema snapshot tests and Python/module cross-runtime fixtures cover
  every union, enum, cardinality, nullability rule, and unknown-field denial.
- Positive round trips cover one multi-analyte lab and one intake containing
  every collection; the read-back value, source, evidence, reviewer, and
  version must exactly match the reviewed input.
- Negative tests cover patient switch, stale version, source/hash mismatch,
  missing evidence, shifted boxes, quote mismatch, null approval, wrong typed
  correction, duplicate review, partial transaction failure, and agent/model
  attempts to invoke write routes.
- Idempotency tests replay upload, review, and promotion before response and
  after commit and assert one source mapping, one review, and one target.
