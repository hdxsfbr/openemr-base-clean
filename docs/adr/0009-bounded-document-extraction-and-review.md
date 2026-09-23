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

## Status notes (2026-09-22, GitLab #51: bounded OpenRouter PDF client)

`agent/app/openrouter_client.py` adds a small injectable client that sends
authorized PDF bytes to a pinned OpenRouter model (`google/gemini-2.5-flash`,
`openrouter_model_id`) with a requested JSON schema and returns a typed
result; a separate `CircuitBreaker` instance and one retry on 429/5xx (no
retry on timeout), matching decision 3's retry policy. It is not wired into
`intake_extractor` yet — #52-#54 do that. One live run confirms, rather than
changes, decision 3: with the `native` engine (page images passed directly to
the model), the pinned model correctly extracted every field of a synthetic
lab result and named the correct page for each, but returned an empty
bounding box for every field despite an explicit request and a schema
requiring one; the `pdf-text` engine (free, text-layer only) returned nothing
on a scanned-shaped page, confirming OCR (or this vision path) is needed for
non-text-layer documents, exactly as decision 3 assumes. Decision 6's
per-fact normalized bounding box will need to come from the deterministic
local OCR/render step's own page geometry, not from asking the OpenRouter
model to report one. Full detail, prompt, and both engine outputs:
`docs/audit/evidence/architecture/openrouter-pdf-client-smoke-2026-09-22.md`.
Engine selection per document shape (text-layer vs. scanned) is left to
#52-#54.

## Status notes (2026-09-22, GitLab #52: multi-result lab previews)

Decision 4's lab schema (`LabExtraction` in `agent/app/contracts/documents.py`)
changed from one flat six-field result to a report: one report-level
`collection_date` field plus a repeated `analytes` list, each with its own
`entry_id`, required `test_name`/`value`, and optional `unit`/
`reference_range`/`abnormal_flag` that are omitted, never defaulted or
invented, when not printed. `agent/app/intake_extractor.py`'s fixed-label
lab parser and citation resolver/verifier were extended to split a report
into per-analyte blocks and author a distinct citation per analyte field
(`analyte_<n>_<field>`); it is still the same deterministic, non-OCR parser
from decision 3's starting point, not the OpenRouter path — #53 replaces it.
The review-only chat preview (`copilot.js`) now renders the shared
collection date once and each analyte as its own labeled block, detected by
the presence of `analytes` rather than the old flat-field shape. This is a
contract/UI change only; no field-evidence, citation, or authorization
invariant from decisions 4-8 changed.

## Status notes (2026-09-23, GitLab #53: OpenRouter lab extraction and verification)

`agent/app/intake_extractor.py`'s lab branch replaced the fixed-label regex
parser from #52 with the pinned OpenRouter client from #51
(`resolve_lab_preview_via_model`). The model is asked, per the `LabExtraction`
schema from #52, for the report's `collection_date` and each analyte row; for
every field it must report whether it was printed and, when it was, an exact
verbatim quote -- and each row must additionally report its own verbatim
`row_text`. None of this is trusted on its own: the deterministic verifier
independently confirms every quote is real text in the locally-extracted PDF
text (the same non-OCR `_pdf_text` ground truth from #52) *and* is contained
within that row's own `row_text`, so a value copied from a different row of
the same document cannot pass verification just because it is real text
somewhere else in the document -- this is the "row pairing" check the task
asked for. A row whose own `row_text` is not found verbatim in the source is
dropped entirely rather than shown with invented structure. `verify_lab_preview`
(the final display-time authority from #52) is unchanged and still re-checks
every citation before render.

A scanned page with no local text layer (`_pdf_text` returns `""`) therefore
drops every row regardless of what the model claims to see in the page image,
and the whole extraction becomes `unavailable` -- an honest degraded state
rather than trusting vision-only output the deterministic side cannot confirm.
This is a conscious scope boundary, not a bug: decision 3's OCR-then-vision
pipeline and decision 6's renderer-derived normalized bounding boxes are not
implemented here (`normalized_box` stays unset, matching #52), consistent with
the #51 status note that per-fact geometry needs local render/OCR page
geometry, not a model's self-report. `openrouter_pdf_engine` stays at its
default (`pdf-text`); switching the default to `native` for image-only pages
is future engine/performance tuning, explicitly out of #53's scope.

The intake-form branch is untouched -- still the deterministic fixed-label
parser; #54 decides whether it also moves to the OpenRouter path.

## Status notes (2026-09-23, GitLab #54: OpenRouter intake extraction and verification)

The intake-form branch moved to the same architecture as #53's lab branch
(`resolve_intake_preview_via_model`), sharing its field-candidate schema and
per-row `row_text` pairing check. Two differences from the lab branch, both
driven by the intake contract's own optionality (`agent/app/contracts/documents.py`):
every demographics field and `chief_concern` are optional on `IntakeExtraction`
(`| None`), so they are omitted, not shown as missing, when the model itself
never claims that question is even printed on this form -- only a field the
model claims is printed but that fails independent verification is ever
surfaced as `unreadable`. The repeated entry types' own identifying field
(`medication.name`, `allergy.substance`, `family_history.relationship`/
`condition`) is contract-required and is always shown once its own row is
confirmed real, even when left blank -- a blank answer within a genuinely
printed row is the "uncertain, not a chart fact" case the task asked for,
distinct from a fully fabricated row (whose own `row_text` is never found in
the source, and which is dropped entirely, matching #53).

The synthetic forms' checkbox-style allergy answer is verified as two
separately quoted claims -- the substance text and the checkbox glyph/word --
so the printed check state is still classified deterministically from a
verified quote, never trusted from the model's own say-so; if only the
checkbox claim fails to verify, the substance still displays without a
resolved checked/unchecked state, rather than withholding it outright. The
same date-of-birth ambiguity and family-history conflicting-value
classifiers from the old regex parser are preserved, now running over the
model's verified quote instead of a regex capture. A scanned page with no
local text layer degrades to the same honest `unavailable` state as #53's
scanned lab case, for the same reason (nothing can be locally confirmed).

One known, accepted limitation: the field-candidate schema's `printed`
boolean cannot distinguish "this question's label is printed but left
blank" from "this form never asks the question at all" -- both collapse to
the same omitted-or-missing treatment described above. Giving the model a
three-way signal for that distinction is a reasonable follow-up, not done
here to keep this slice bounded.

## Status notes (2026-09-23, GitLab #55: verified integrated PDF previews)

The parent task's final child issue exercised the whole chain for real on
the local dev stack, for the first time end to end: browser upload through
the module UI, the module's own gateway, the agent service making real
OpenRouter calls with the pinned key, and the audit/compliance trail --
rather than the pytest doubles #51-#54 verified against. No local
integration environment for this existed yet (`docs/REQUIREMENTS_TRACEABILITY.md`
had flagged this as outstanding): a fresh `copilot-agent:local` image built
from `agent/`'s current source, and a minimal Caddy edge mirroring
`infra/digitalocean/runtime/Caddyfile`'s `/copilot-api/*` split, both
attached to the `development-easy` stack's Docker network. This surfaced
four real defects that no unit test could have caught, since none of them
depend on document content or extraction logic -- all four are fixed here:

1. **The pinned model can never actually respond, for either document
   type, regardless of content.** `LAB_EXTRACTION_SCHEMA` and
   `INTAKE_EXTRACTION_SCHEMA` (#52-#54) were shaped for a Gemini
   structured-output compiler limit neither schema respected: every real
   call to `google/gemini-2.5-flash` via OpenRouter failed `http_400`
   ("the specified schema produces a constraint that has too many states
   for serving"), independent of document content, so no extraction ever
   reached the model's own judgment about a page -- every previously green
   pytest run against `FakeOpenRouter` had validated the resolver/verifier
   boundary correctly but never touched this. Bisected directly against the
   live API: the lab schema's single `analytes` array serves up to 11 items
   (12 fails); the intake schema, asking for three repeated-entry arrays in
   one call, only serves 3 items each simultaneously (9 rows total; 4 each
   already fails). `agent/app/intake_extractor.py` now caps lab analytes at
   10 (one item of margin under the verified line), and splits intake into
   two schemas run concurrently via `asyncio.gather`: a primary call
   (demographics, chief_concern, medications; medications capped at 8, the
   verified figure) and a secondary call (allergies, family_history; capped
   at 6 each, verified). The secondary call failing on its own degrades to
   empty allergies/family_history rather than failing a preview whose
   primary section resolved fine -- new tests cover both the two-call split
   and this independent degradation. Verified end to end against the real
   API afterward: `synthetic-lab-varied-layout.pdf` resolves 2 analytes,
   `synthetic-intake-varied-layout.pdf` resolves 2 medications/2
   allergies/1 family-history entry, both fully verified; the scanned
   fixtures both correctly return `None` (honest unavailable) from a real,
   multi-second, `status: ok` OpenRouter call whose claims simply cannot be
   confirmed against a page with no local text layer, not a pre-call
   short-circuit -- the first time that specific scanned-page path was ever
   exercised against the real provider rather than a test double. Real
   observed latency for a two-analyte/two-medication document: 3.1-5.6 s
   per OpenRouter call (lab, one call; intake, two concurrent calls, total
   wall time close to the slower of the two) -- a fact recorded here per
   the task's own instruction, not yet tuned.
2. **The document-extraction path never wrote the compliance framework's
   own model-disclosure control.** `copilot-model-disclosure`
   (`docs/audit/compliance.md` section 5) is the audit row the module
   writes before patient-bound content leaves for a model provider; it
   existed for the chat path's `tools.php` since ADR-0003's amendment but
   was never extended to `gateway/source.php`, the one place the lab/intake
   extraction worker's source bytes exist before OpenRouter sees them --
   #53/#54 wired the model call itself but not this control. `source.php`
   now accepts the agent's `{provider, model}` declaration (query params,
   mirroring `tools.php`'s JSON body field) and writes the same
   `Audit::modelDisclosure` row before returning bytes, fail-closed the
   same way (`agent/app/gateway_client.py`'s `read_source`, `Gateway/Audit.php`).
   One row per document read regardless of how many OpenRouter calls follow
   from those bytes in-process (verified: the intake branch's two calls
   produce exactly one disclosure row, not two) -- consistent with the
   existing precedent that the row records a declared intent, not a
   per-model-call event.
3. **`Audit::modelDisclosure`'s own sanitizer silently discarded every real
   model id.** Its `$idShaped` regex (written for the chat path's
   Anthropic ids, which never contain a `/`) rejected OpenRouter's
   `vendor/model` convention, so `google/gemini-2.5-flash` always recorded
   as `"unspecified"` -- confirmed via the audit table, both before and
   after the fix. Widened to allow `/`.
4. **Two module bugs the local integration test surfaced, unrelated to any
   of the above:** `copilot.js`'s upload-rejection path read
   `data.code`, which `document_upload.php`'s 409 body never sets (the
   reason lives at `data.limitation.code`), so a real rejection (e.g. a
   fixture missing the intake format marker) always displayed the generic
   literal `"document_upload"` instead of the real reason; and
   `renderExtractionPreview`'s lab-vs-intake label inference defaulted to
   "Intake" for any `status: unavailable` result (no `extraction` object to
   infer the type from), so a failed *lab* upload displayed "Intake
   extraction preview only" -- worse, the render branch for that case had
   no null guard and threw a `TypeError` reading `extraction.collection_date`
   off a null `extraction`, which is what a clinician actually saw on
   screen before this fix. Both fixed; the label now falls back to the
   document type the clinician actually selected only when there is no
   extraction to structurally infer it from, and the lab render branch is
   now guarded the same way the intake branch already was.

Two smaller, non-blocking findings fixed in passing: the demo Droplet's
`infra/digitalocean/runtime/compose.yaml`/`start.sh`/`push-secrets.sh` never
declared or provisioned the `openrouter_api_key` secret at all, so a real
deployment today would have every extraction branch permanently
`not_configured` (`docs/deployment/digitalocean.md`, `agent/README.md`
updated); and `agent/app/logging_setup.py`'s structured-log field whitelist
had no `reason` key, so a real OpenRouter failure's own diagnostic field
(a bounded enum-like string, never content) was silently dropped from every
log line, which cost real time diagnosing defect 1 above before it was
found by calling the client directly and reading the raw provider error.

Two of the two intake evaluation fixtures needed a fix of their own, not
the application: `synthetic-intake-varied-layout.pdf` and
`synthetic-intake-scanned.pdf` (built for #54's pytest-level resolver
tests, which never go through the browser upload path) never carried
`IntakeFormPolicy::FORMAT_MARKER`, the literal byte string the module's own
upload boundary requires before it will store a file as an intake form
(`interface/modules/custom_modules/oe-module-copilot/src/Documents/IntakeFormPolicy.php`).
A real browser upload of either fixture was rejected at storage, before
ever reaching the extractor. Added as a PDF comment line (confirmed inert
to `_pdf_text()`'s `Tj`-scoped extraction and to every existing pytest
assertion) rather than regenerating either fixture's content.

**Confirmed working, not just re-asserted:** patient-bound authorization
(`UploadContext::fromSession` derives pid from the live OpenEMR session,
never a client-supplied value, and re-checks user-active/squad/document-ACL
on every upload and every later source read); review-only framing (present
on every rendered preview, in both the working and unavailable cases, now
correctly labeled per defect 4); no "accept into chart" affordance anywhere
in the UI (confirmed absent, matching the parent issue's explicit exclusion
of physician promotion); and no document content, prompt, or model
response in any log line or audit row across four full upload-to-preview
cycles -- only ids, byte counts, tool/event names, and bounded status
strings, in both the agent's structured logs and OpenEMR's own audit log.

**Still not implemented, unchanged from #51-#54 and explicitly out of this
task's scope:** OCR/vision retry for a scanned page (decision 3), renderer-
derived bounding boxes (decision 6), physician promotion into the chart
(ADR-0008), chat readback of an unreviewed document's extracted facts, and
any latency/cost tuning of the calls this note measured but did not tune.

## Revisit Triggers

- Measured extraction quality cannot meet the Week 2 boolean eval thresholds.
- Clinician review shows the field states or required schemas omit a repeated
  real workflow need.
- A renderer/OCR/model change alters coordinates, confidence behavior, or
  schema output.
