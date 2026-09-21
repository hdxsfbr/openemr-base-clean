# Week 2 patient-record and guideline-evidence contracts

- **Status:** Normative design contract for Week 2 implementation
- **Date:** 2026-09-21
- **Applies to:** ADR-0012; extends ADR-0006 without changing Week 1 as-built
  behavior
- **Depends on:** the reviewed-document contracts in
  `week2-document-record-contracts.md` and the corpus contract in ADR-0010

This specification defines the final-response boundary between patient-record
facts and guideline evidence. Implementation must encode these types as strict
Pydantic discriminated unions, export JSON Schema, and consume those schemas at
the module/UI boundary. Unknown properties are rejected. Proposed extraction
facts never satisfy this contract.

## Common identifiers

The common `Uuid`, `Sha256`, `DateTime`, `CorrelationId`, `FieldId`, and
`NormalizedBox` types are exactly those in
`week2-document-record-contracts.md`.

`ClaimId` matches `^c[0-9]{1,3}$`. `CitationId` matches
`^ct[0-9]{1,3}$`. `RegistrySlug` matches
`^[a-z0-9][a-z0-9._-]{0,63}$`. Every UUID in a source ID is lowercase
canonical form and every integer is base-10 without leading zeroes.
`RelativeHref` is a string of `1..1000` characters beginning with `/` and
contains no scheme, control character, or fragment. `AbsoluteHttpsUrl` is a
validated absolute HTTPS URL of `1..1000` characters.

`SourceId` remains a string of at most 240 characters and is the union of:

| Source type | Canonical URI | Identity |
| --- | --- | --- |
| OpenEMR record | `openemr:{table}:{id}[:{uuid}]` | Existing Week 1 record identity; its current `SourceRef` constraints remain normative. |
| Reviewed document field | `document:{source_document_id}:record:{record_id}:v:{record_version}:field:{field_id}` | One field in one immutable version of a promoted reviewed record. `record_version` is `1..2147483647`. |
| Guideline chunk | `guideline:{corpus_version}:{document_id}:{chunk_id}` | One immutable chunk in one approved corpus version. Each variable is a `RegistrySlug`. |

Source IDs contain no user, patient, filename, publisher URL, quote, or raw
clinical value. They are opaque outside the source registry even though their
grammar is inspectable.

## Closed source registry

The registry has exactly three handlers: `openemr`, `document`, and
`guideline`. A handler receives a `SourceId` and the server-held `TurnBinding`;
it may resolve only a source already returned by an authorized tool in that
turn. It cannot fetch an arbitrary URL, query the OpenEMR database from the
agent, or reinterpret an unknown prefix.

`TurnBinding` is server-only and has exactly `site_id`, `user_id`, `patient_id`,
`conversation_id`, `turn_id`, `correlation_id`, and `authorized_at`. It is not
accepted from the model/browser, returned in `TurnResponse`, or written to
ordinary telemetry. Patient-source resolvers require an exact site, patient,
conversation, turn, and authorized-user match. The guideline resolver ignores
patient identity but requires the same turn and correlation ID.

`site_id`, `user_id`, `patient_id`, `conversation_id`, and `turn_id` are
non-empty server-issued strings of `1..128` characters; `correlation_id` and
`authorized_at` use the common types above. None may be supplied or overridden
inside a source-resolution request.

Resolution returns exactly one member of `ResolvedSource`:

### `OpenEmrRecordSource`

| Field | Type |
| --- | --- |
| `source_type` | literal `openemr_record` |
| `source_id` | matching `openemr:` `SourceId` |
| `source_ref` | existing strict `SourceRef` |
| `chart_section` | string `1..64` from a fixed module allowlist |
| `record_label` | UI-safe string `1..160`, derived by the gateway |
| `source_version` | tool implementation version string `1..64` |
| `retrieved_at` | `DateTime` |
| `fields` | strict source-type record projection used by ADR-0006 verification |
| `href` | `RelativeHref` produced by the module; never model supplied |

The authorized gateway projection, not a whole-row hash, is authoritative for
legacy OpenEMR records. It is re-fetched for each turn as required by ADR-0005.

### `ReviewedDocumentFieldSource`

| Field | Type |
| --- | --- |
| `source_type` | literal `reviewed_document` |
| `source_id` | matching `document:` `SourceId` |
| `source_document_id` | `Uuid` equal to the URI component |
| `source_content_sha256` | `Sha256` |
| `record_id` | `Uuid` equal to the URI component |
| `record_version` | integer equal to the URI component |
| `record_status` | `active` or `amended`; `withdrawn`/`stopped` cannot resolve |
| `record_type` | `lab_report` or `intake_response` |
| `field_id` | `FieldId` equal to the URI component |
| `review_id` | `Uuid` of the current approved/corrected review |
| `review_decision` | `approved` or `corrected` |
| `reviewed_value` | exact `DocumentFieldValue` from the promoted record |
| `evidence` | array of `1..3` immutable `FieldEvidence` objects |
| `schema_version` | strict record schema version |
| `retrieved_at` | `DateTime` |
| `href` | patient-bound `RelativeHref` generated by the module |

The resolver verifies that the record is the current usable version, that the
field points through its review to the same source/extraction, and that each
evidence item still matches the retained OCR/page hashes. Extraction proposals,
pending/rejected/superseded reviews, and inactive record versions do not
resolve.

### `GuidelineChunkSource`

| Field | Type |
| --- | --- |
| `source_type` | literal `guideline` |
| `source_id` | matching `guideline:` `SourceId` |
| `corpus_version` | `RegistrySlug` equal to the URI component |
| `document_id` | `RegistrySlug` equal to the URI component |
| `chunk_id` | `RegistrySlug` equal to the URI component |
| `publisher` | string `1..160` |
| `title` | string `1..300` |
| `jurisdiction` | string `1..80` |
| `canonical_url` | `AbsoluteHttpsUrl` from the manifest |
| `publication_date` | `YYYY-MM-DD` or absent when the publisher supplies none |
| `topic` | manifest topic string `1..160` |
| `section_path` | array of `1..8` strings, each `1..200` |
| `chunk_ordinal` | integer `>= 0` |
| `exact_text` | string `1..4000` |
| `source_sha256` | `Sha256` |
| `chunk_sha256` | `Sha256` of `exact_text` bytes in UTF-8 |
| `retrieved_at` | `DateTime` for the local retrieval operation |
| `corpus_retrieved_at` | `DateTime` for publisher snapshot acquisition |
| `approved_at` | `DateTime` for corpus activation/re-approval |
| `href` | `AbsoluteHttpsUrl`; `canonical_url` with a publisher section locator when available |

The resolver requires the source to be one of at most five final reranked
results from this turn, and checks the immutable manifest, active-version
pointer, hashes, and ADR-0010 freshness approval. Retrieval scores and ranks
may accompany internal evidence but are not citation support and are omitted
from the clinical claim.

## Final claim union

The model emits `ClaimCandidate`, discriminated by `claim_class`, with no
`citations` field. A patient candidate has the current Week 1 fields plus
`claim_class`; a guideline candidate has exactly `id`, `claim_class`, `type`,
`facts`, `source_ids`, and `section` and cannot supply `text` or any citation
metadata. `FinalClaim` is the verified response form and is exactly one of
`PatientRecordClaim` or `GuidelineEvidenceClaim`. Every final claim has
`id`, `claim_class`, `type`, `text`, `facts`, `source_ids`, `section`, and
`citations`. Patient `text` is `1..400` characters; guideline `text` is
`1..700` characters so a 500-character exact quote plus attribution fits.
`citations` is a non-empty array of `1..24` resolver-generated `Citation`
objects whose `claim_id` equals the claim `id`; absence claims alone may have
an empty array under the existing ADR-0006 retrieval-state rule. The model
cannot emit or modify `citations`.

### Patient-record claims

`PatientRecordClaim` has `claim_class: "patient_record"`. Its `type` may use
the existing ADR-0006 patient-record types `change_event`,
`medication_status`, `problem_status`, `lab_result`, `lab_comparison`,
`documented_reference`, `absence`, `conflict`, or `undated`, plus the new
`intake_answer`. The existing `interpretation` type is interaction text, not a
patient-record fact, and is not a member of this final clinical-claim union.
Its `text` remains model-authored but must pass the existing ADR-0006 typed-fact
and lexicon checks before it can become a `FinalClaim`.

Its `source_ids` contains `1..8` items for every type except `absence`, which
may contain `0..8` under ADR-0006. Every non-absence source must generate at
least one citation; one source may generate up to three document-region
citations, which is why a final patient claim permits at most 24 citations.

The existing strict fact shapes and verifier rules remain unchanged except:

- `lab_result` may cite either the exact required field projections from one
  `openemr:` lab record or the `document:` fields for test name, value,
  collection date, and every optional unit/range/flag asserted by the claim;
- `lab_comparison` may compare native and reviewed-document labs only when both
  resolve, analyte identity and dates match, values are numeric, units are
  present and equal, and neither value is a superseded same-day result;
- `intake_answer` facts have exactly `link_id`, optional `repeat_key`, and
  `answer: ReviewedAnswer`; they cite exactly one matching current
  `document:` field;
- an `absence` claim is permitted only from a successfully retrieved patient
  source/tool state. No-result guideline retrieval is a limitation, never a
  patient absence claim; and
- a `conflict` claim cites every deterministically identified conflicting
  patient source. No ordinary status/result claim may flatten that conflict.

Only current promoted reviewed records may support document-backed patient
claims. Confidence, extraction state, OCR alone, proposed facts, and review
decisions without promotion are insufficient.

### Guideline-evidence claims

`GuidelineEvidenceClaim` has exactly:

| Field | Type |
| --- | --- |
| `id` | `ClaimId` |
| `claim_class` | literal `guideline_evidence` |
| `type` | literal `guideline_excerpt` |
| `text` | deterministic publisher-attribution template containing the exact quote, maximum 700 characters |
| `facts` | `GuidelineExcerptFacts` |
| `source_ids` | array containing exactly one `guideline:` `SourceId` |
| `section` | literal `guideline_evidence` |
| `citations` | array containing exactly one `GuidelineCitation` |

`GuidelineExcerptFacts` has exactly `quote: string 1..500`, `publisher: string
1..160`, `title: string 1..300`, `topic: string 1..160`, and `section_path:
array 1..8`. `quote` must be a contiguous exact substring of the resolved
chunk's `exact_text`; line endings are canonicalized to `\n`, but whitespace,
punctuation, case, numbers, and units may not otherwise change. The other facts
must exactly equal the source metadata.

The displayed claim is rendered deterministically as publisher attribution plus
the exact quote. The model may select an eligible source and substring but may
not paraphrase, infer applicability, add an eligibility judgment, or convert
the excerpt into diagnosis, treatment, or dosing advice.

Two guideline excerpts may both render when a curated manifest explicitly
marks their source sections as differing or supersession is unresolved. The UI
does not synthesize which one wins. A model assertion that two excerpts
conflict is not deterministically supported and is withheld.

## Citation union

`Citation` is discriminated by `source_type`, carries `citation_id`,
`claim_id`, and `source_id`, and is emitted by the matching trusted resolver.
The model output contains no citation object.

### `OpenEmrRecordCitation`

| Field | Type |
| --- | --- |
| `citation_id`, `claim_id`, `source_id` | matching identifiers |
| `source_type` | literal `openemr_record` |
| `title` | resolver-derived label `1..160` |
| `page_or_section` | `{kind: "chart_section", section: string 1..64}` |
| `field_or_chunk_id` | fixed source-field name `1..64` |
| `quote_or_value` | `{kind: "record_value", value: string 1..500}` exactly matching the canonical projected value |
| `source_version` | tool source version `1..64` |
| `href` | same-chart `RelativeHref` |
| `retrieved_at` | `DateTime` |

One claim may receive several citations when several fields or records are
required. The resolver never places unrestricted note text into a citation;
only the bounded exact mention already authorized for the claim is used.

### `ReviewedDocumentCitation`

| Field | Type |
| --- | --- |
| `citation_id`, `claim_id`, `source_id` | matching identifiers |
| `source_type` | literal `reviewed_document` |
| `title` | fixed document-type label plus record version, `1..160` |
| `page_or_section` | `{kind: "document_region", page_number: integer >= 1, box: NormalizedBox}` |
| `field_or_chunk_id` | exact `FieldId` |
| `quote_or_value` | `{kind: "reviewed_document_value", reviewed_value: DocumentFieldValue, printed_quote: string 1..500, review_decision: "approved" | "corrected"}` |
| `source_content_sha256` | `Sha256` |
| `rendered_page_sha256` | `Sha256` |
| `ocr_text_sha256` | `Sha256` |
| `record_id`, `record_version`, `review_id`, `evidence_id` | exact source identities |
| `href` | patient-bound `RelativeHref` carrying no raw value |
| `retrieved_at` | `DateTime` |

Each evidence region produces one citation. The preview opens the immutable
source version at `page_number` and overlays the normalized box only after the
module repeats authorization and hash checks. For `review_decision=corrected`,
the UI labels `reviewed_value` as physician-corrected and `printed_quote` as
the source text; they are never collapsed into one value.

### `GuidelineCitation`

| Field | Type |
| --- | --- |
| `citation_id`, `claim_id`, `source_id` | matching identifiers |
| `source_type` | literal `guideline` |
| `title` | publisher plus source title, `1..470` |
| `page_or_section` | `{kind: "guideline_section", section_path: array 1..8, chunk_ordinal: integer >= 0}` |
| `field_or_chunk_id` | exact `chunk_id` |
| `quote_or_value` | `{kind: "exact_quote", quote: string 1..500}` equal to the verified claim quote |
| `publisher`, `jurisdiction`, `canonical_url`, `publication_date`, `topic` | exact manifest metadata |
| `corpus_version`, `source_sha256`, `chunk_sha256` | exact immutable corpus identities |
| `href` | `AbsoluteHttpsUrl` canonical publisher URL/section locator |
| `retrieved_at` | `DateTime` |

This union contains every field in the PRD minimum citation shape. Fields are
typed instead of represented by ambiguous free strings.

## Deterministic verification order

The verifier executes the following order and never calls a model:

1. Validate the strict claim schema and reject unknown fields.
2. Enforce the `claim_class`/`type` pair and source-scheme allowlist.
3. Resolve every `source_id` from this turn through the closed registry.
4. Recheck patient binding and current source/record version, or active corpus
   version, approval, freshness, and hashes, as applicable.
5. Apply the claim-type fact rules against the resolved typed sources.
6. Apply the existing forbidden diagnosis, treatment, dosing, causality, and
   advice lexicon to patient-claim text and to any model-authored framing.
   Exact publisher text may contain words such as “recommends”; it is rendered
   only inside the fixed attributed-quote template and is not treated as the
   co-pilot's advice. Guideline claims reject every model-authored addition,
   applicability statement, or eligibility judgment outside that template.
7. Generate strict citations from accepted sources and validate each citation
   against its JSON Schema.
8. Accept the claim only when every required source and citation succeeds.

Additional class rules are mandatory:

- Patient-record claims use only `openemr:` and/or `document:` sources. Every
  patient source must have the same `TurnBinding`; a different patient, site,
  user authorization, conversation, or turn rejects the claim.
- A document source must be current, promoted, and human reviewed. Field value,
  record version, review, source hash, OCR hash, page hash, page number, box,
  and printed quote must all resolve. A corrected field verifies the reviewed
  value and printed evidence separately.
- Guideline-evidence claims use exactly one `guideline:` source returned by the
  current turn's final reranked result. Corpus version, active pointer,
  freshness/re-approval, document/chunk identity, hashes, metadata, and exact
  quote must all match.
- Retrieval rank, reranker score, model confidence, and extraction confidence
  are diagnostic only and can never make a claim pass.
- A patient source cannot support a guideline claim, a guideline source cannot
  support a patient claim, and no final claim can cite both classes.

## Freshness and conflict states

The source registry returns one of `resolved`, `stale`, `withdrawn`,
`unauthorized`, `not_found`, `hash_mismatch`, `version_mismatch`, or
`unavailable`. Only `resolved` may support a claim.

- A legacy OpenEMR record is current only when it was authorized and retrieved
  in this turn and its typed fields still match at verification.
- A reviewed document field is current only when its record version is the
  current usable version. Superseded, withdrawn, or stopped versions are stale
  for new claims even though retained for audit.
- A guideline chunk is current only when its exact corpus is still active and
  is no older than ADR-0010's 14-day limit or carries explicit current demo
  re-approval. Candidate and failed-refresh corpora never resolve.
- Contradictory patient sources produce only an explicit patient `conflict`
  claim citing all sides; the verifier does not select a winner.
- Publisher excerpts remain separate evidence. Deterministic manifest metadata
  may flag disagreement, but the system does not infer it or choose a winner.
- A difference between the patient record and guideline text is not flattened
  into one conflict claim. The lanes remain separate and neither changes the
  authority of the other.

## Rendering and failure behavior

Week 2 uses contract version `2.0.0` because the claim union and citation
response are breaking changes to the Week 1 shape. `TurnResponse.claims` is an
array of `0..40` `FinalClaim` objects. `TurnResponse.sources` remains the
existing `0..100` `SourceSummary` array for backward-compatible OpenEMR record
navigation only; it is resolver-derived, contains no document or guideline
payload, and cannot satisfy the Week 2 citation contract. The UI partitions
`claims` by `claim_class` into `patient_record` and `guideline_evidence` lanes.
Patient claims render first.
The guideline lane carries a fixed label: “Guideline evidence for physician
review; patient applicability was not determined.”

There is no model-authored clinical summary that combines the lanes. Existing
patient-only summaries remain subject to ADR-0006. A mixed response may use
only deterministic lane headings/counts plus the individually verified claim
renderings.

Failure is atomic per claim:

- failure of any required source, fact check, citation field, preview locator,
  version, hash, or authorization withholds the entire claim;
- other independently verified claims may render, and the response becomes
  `partial` with `withheld_count` and a non-PHI typed limitation;
- an empty patient lane reports the applicable patient limitation without
  substituting guideline evidence;
- an empty guideline lane reports `guideline_no_evidence`,
  `guideline_stale`, or `guideline_retrieval_unavailable`, never “no guideline
  exists” and never an RRF-only or web-search fallback; and
- if neither lane has a verified claim, the response contains only authorized
  evidence summaries and explicit limitations, never unverified model prose.

Click-time source reopening repeats authorization. A later denial or source
integrity failure replaces the preview with a limitation and emits no document
bytes, OCR, raw value, or unrestricted text in its error.

Contract `2.0.0` adds `guideline_no_evidence`, `guideline_stale`, and
`guideline_retrieval_unavailable` to `LimitationKind`. Their `section` is
always `guideline_evidence`; `detail` is a fixed UI-safe string and carries no
query, patient concept, retrieved text, score, or source URL.

## Required verification fixtures

- Positive: native patient fact; approved and corrected document fields; mixed
  native/document lab comparison; intake answer; exact guideline excerpt;
  patient plus guideline lanes with no applicability statement.
- Source integrity: unknown scheme, malformed URI, missing source, source from
  another turn/patient, inactive document version, changed review, shifted box,
  quote/value/OCR/page/source hash mismatch, stale and inactive corpus, altered
  chunk metadata, and unavailable preview.
- Claim separation: proposed fact in a final response, patient claim citing a
  guideline, guideline claim citing a patient source, mixed-source claim,
  guideline paraphrase, applicability language, inferred guideline conflict,
  and a model-authored cross-lane summary.
- Degradation: one claim fails while another renders; patient lane only;
  guideline lane only; neither lane; no result; retrieval outage; corpus stale;
  patient source withdrawn between retrieval and verification.
- Contract: every discriminator, enum, bound, conditional requirement, and
  unknown-field denial in Python, exported JSON Schema, module fixtures, and UI
  fixtures.
