# ADR-0009: Bounded document extraction with visible review states

- **Status:** Accepted 2026-09-21; sections 1, 4, 5, and 6 superseded by
  ADR-0011 on 2026-09-21
- **Date:** 2026-09-21
- **Owners:** Andre Batista (document extraction and review workflow)
- **Related requirements:** Week 2 PRD Stages 1 and 5, Core Agent Requirements
  1, 2, 5, and 7; strict lab/intake schemas, source citations, visual bounding
  boxes, safe behavior on imperfect scans, PHI-free telemetry.
- **Related use cases:** UC-01 and UC-02; document-derived changes and abnormal
  laboratory review before a visit.
- **Related decisions:** ADR-0005 (patient-bound state), ADR-0006
  (deterministic verification), ADR-0007 (PHI-safe telemetry), ADR-0008
  (human-reviewed promotion), ADR-0011 (canonical document contracts;
  partially supersedes this decision).

## Context

Scanned laboratory reports and intake forms contain uncertain pixels,
untrusted free text, and patient data. A vision model can invent labels or
values, while numeric model confidence is not calibrated clinical evidence.
The physician needs partial useful results, exact click-to-source support, and
visible uncertainty without allowing extraction output to become chart truth.

## Decision

1. **Accepted files.** Lab reports accept PDF up to 20 MiB and 20 pages.
   Intake forms accept PDF, PNG, or JPEG up to 10 MiB and 10 pages. Encrypted,
   corrupt, unsupported, oversized, decompression-bomb, or non-renderable files
   are rejected before model invocation. MIME is content-sniffed, not trusted
   from the filename.
2. **Deterministic preprocessing.** Preserve the original OpenEMR document.
   Render PDF pages at 200 DPI RGB, normalize orientation, deskew, and apply
   non-generative contrast/noise cleanup. Record renderer and preprocessing
   versions plus each rendered-page hash. Preprocessing may not synthesize or
   erase clinical characters.
3. **OCR then bounded vision retry.** Local OCR runs first. Strict-schema
   extraction uses OCR text and page geometry. Only fields that remain
   ambiguous may be sent as bounded page/region crops to the already approved,
   version-pinned vision-capable provider from ADR-0004. The first extraction
   has a 60 s deadline; one retry waits 500 ms and has a 30 s deadline; the
   document pipeline has a 95 s wall-clock cap. There is no retry for file,
   schema, authorization, or safety rejection. Timeout produces
   `review_required` or `unavailable`, never an unbounded retry.
4. **Strict lab schema.** A report includes source identity and collection date;
   each analyte requires test name, typed value, unit when printed, reference
   range when printed, abnormal flag when printed, and field evidence. A code
   may be preserved only when explicitly printed or deterministically mapped
   by an approved table; the model may not invent one.
5. **Strict intake schema.** It supports the PRD fields: demographic answers,
   chief concern, current medication entries, allergy entries, family-history
   entries, and field evidence. Extracted medication/allergy/demographic
   answers are proposed intake responses, not reconciled native chart lists.
6. **Field evidence.** Every proposed fact carries patient and source-document
   binding, source hash, extraction/schema version, page number, normalized
   bounding box, stable field ID, exact field-level quote or printed value,
   OCR span, diagnostic confidence, and validation result. OCR text and page
   geometry are retained in the protected module ledger; raw content never
   enters ordinary logs, metrics, traces, or error responses.
7. **Separate state machines.** Extraction state is `schema_valid`,
   `review_required`, `rejected`, or `unavailable`. Review decision is
   `pending`, `approved`, `corrected`, `rejected`, or `superseded`. Promotion
   state is separate under ADR-0008. No state named `accepted` is used.
   Confidence is diagnostic only and cannot advance either review or
   promotion.
8. **Validation and partial results.** Deterministic checks enforce types,
   printed units/ranges, dates, required evidence, page bounds, and exact
   quote/OCR resolution. Conflicting duplicate fields remain review-required.
   Independently valid fields may be returned while failed fields carry a
   limitation. Missing content is never imputed.
9. **Untrusted document content.** Instructions, URLs, QR text, or prompt-like
   language in the document are data. They cannot change schemas, tools,
   routing, prompts, retry limits, or authorization.
10. **Immutable reprocessing.** Reprocessing creates a new extraction version
    linked to the same source version. It never overwrites OCR, evidence,
    reviews, or earlier proposed facts and cannot duplicate ledger entries for
    the same `(source, extraction version, field ID)`.

## Alternatives Considered

### Vision-model-only extraction

- Benefits: one model path and good tolerance of irregular layouts.
- Costs and risks: higher cost/latency, weak character-level provenance, and
  greater hallucination exposure.
- Reason rejected: OCR supplies deterministic text/geometry and bounds vision
  use to ambiguous regions.

### Confidence threshold automatically accepts fields

- Benefits: less physician review.
- Costs and risks: model scores are not calibrated safety probabilities and do
  not prove the displayed value exists on the page.
- Reason rejected: evidence and deterministic validation—not confidence—control
  state, and all promotion remains human-reviewed.

### Reject the entire document after one bad field

- Benefits: simple all-or-nothing semantics.
- Costs and risks: discards independently supported facts and hides where the
  scan failed.
- Reason rejected: explicit per-field states provide safer useful partials.

## Consequences

### Positive

- Every proposed value is inspectable at a precise source region.
- Failure, uncertainty, and conflict remain visible without becoming chart
  truth.
- Time, size, pages, model calls, and retries are concretely bounded.

### Negative and residual risk

- OCR text and page images are sensitive retained data requiring encryption,
  access control, retention, and deletion behavior in the operations contract.
- Bounding boxes can drift if a renderer changes; renderer versions and page
  hashes are therefore part of evidence.
- The selected vision provider still needs extraction-quality evaluation on
  degraded synthetic scans.

## Verification

- Contract tests cover every required lab/intake field and reject unknown or
  invented fields.
- Synthetic normal, rotated, noisy, multi-page, partial, conflicting,
  prompt-injected, encrypted, corrupt, oversized, and timeout documents cover
  positive and adversarial paths.
- Every returned fact resolves to the source hash, page, normalized box, and
  exact OCR/printed value; deliberately shifted boxes and quotes fail closed.
- Fault tests prove exactly one bounded retry and a 95 s maximum pipeline
  state transition.
- Telemetry tests assert that OCR, page crops, document bytes, and raw values
  do not appear in logs, metrics, traces, or errors.

## Revisit Triggers

- Measured extraction quality cannot meet the Week 2 boolean eval thresholds.
- Clinician review shows the field states or required schemas omit a repeated
  real workflow need.
- A renderer/OCR/model change alters coordinates, confidence behavior, or
  schema output.
