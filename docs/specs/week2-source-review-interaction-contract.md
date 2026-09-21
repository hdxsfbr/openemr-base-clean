# Week 2 source-review interaction contract

- **Status:** Owner-approved interaction decision for Week 2 implementation
- **Date:** 2026-09-21
- **Applies to:** click-to-source review of patient records, reviewed-document
  fields, extraction proposals, and guideline evidence in the existing
  OpenEMR Clinical Co-Pilot panel
- **Prototype:**
  [week2-click-to-source-review.html](../prototypes/week2-click-to-source-review.html)
- **Related decisions:** ADR-0006, ADR-0009, ADR-0010, ADR-0011, ADR-0012,
  and ADR-0013

This specification records the interaction contract approved from the rough
prototype. It constrains the production UI; it does not claim that the
prototype itself is production code or that the behavior is implemented.
All examples and fixtures use synthetic data.

## Interaction outcome

A physician can activate any displayed citation without leaving the current
chart, inspect the exact source authority behind it, and return to the answer
without losing context. The interface keeps three concepts visibly distinct:

1. current patient-record claims that passed deterministic verification;
2. exact guideline excerpts supplied for physician review; and
3. unreviewed extraction proposals awaiting a human decision.

The UI never visually promotes an extraction proposal into a patient-record
claim and never combines patient and guideline evidence into an applicability
or treatment conclusion.

## Panel and source-view behavior

- The existing non-modal right-side Co-Pilot drawer remains the entry point.
- Activating a citation opens an in-place source view. At desktop widths the
  panel uses a split layout: the answer or review queue remains on the left and
  the activated source appears on the right.
- Citation activation does not navigate the whole chart, replace the current
  conversation, or open a second login surface.
- The active citation receives a visible selected state. Its source title,
  source class, immutable version, and location are announced in an
  `aria-live="polite"` region.
- Selecting another citation updates the existing source view rather than
  stacking previews.
- Source selection, the current page, unresolved review edits, and the active
  Answer/Source view survive presentation-only resizing. They are not stored
  as clinical state in browser storage.
- Native OpenEMR record citations may use the existing same-chart record link.
  Reviewed-document and guideline citations use the source behavior below.

## Evidence lanes

### Patient record

The patient-record lane renders first. It contains only claims accepted by the
deterministic verifier and supported by current authorized `openemr:` or
promoted, human-reviewed `document:` sources. Proposed extraction fields,
pending reviews, rejected reviews, superseded records, and withdrawn records
cannot appear in this lane.

Each claim exposes one or more resolver-authored citation controls. The model
does not author their labels, destinations, source metadata, or source values.

### Guideline evidence

The guideline lane is visually distinct from the patient-record lane and
appears only for an explicit, permitted guideline-evidence request. It renders
the verified exact excerpt and publisher attribution, followed by the fixed
boundary:

> Guideline evidence for physician review; patient applicability was not
> determined.

Guideline evidence never amends, overrides, or visually merges with a patient
claim. A mixed response has no model-authored cross-lane clinical summary.

### Extraction proposals

The document-review area is separate from both final-answer lanes. It is
labeled as a review queue and shows the source document and extraction version.
Its fields are proposals, even when schema-valid or high-confidence. No
confidence value, badge color, or default selection constitutes approval.

## Citation activation by source class

| Source class | Activation behavior | Required visible context |
| --- | --- | --- |
| Native OpenEMR record | Open the resolver-generated same-chart destination using the existing chart navigation behavior. | Chart section, record label, canonical displayed value, and retrieval time where useful. |
| Reviewed document | Reauthorize at click time, verify the immutable source/record version and hashes, open the matching page, and focus the normalized bounding box. | Document type, record version, page number, field ID, printed source text, reviewed value, and review decision. |
| Guideline chunk | Show the verified exact excerpt and immutable corpus metadata in the source view. A canonical publisher link may be offered separately. | Publisher, title, section path, corpus version, publication metadata when present, and the no-applicability boundary. |

The source view has no generic URL fallback. A citation whose source cannot be
reauthorized, resolved, hash-checked, or reopened becomes an explicit
limitation and emits no document bytes, OCR, raw value, or unrestricted text
in its error response.

## PDF page and bounding-box focus

- A reviewed-document citation opens the immutable source version named by the
  citation, not the latest file with a similar name.
- The viewer selects `page_number` and overlays the normalized `box` from the
  resolver-authored citation only after authorization and source, page, OCR,
  and rendered-page hash checks succeed.
- The focused region is indicated by more than color: it has a visible outline
  and a concise text label.
- Page controls remain available. Moving away from the cited page hides the
  focus box rather than relocating it to unrelated content.
- Returning to the citation restores its exact page and region.
- If rendering or integrity verification fails, the viewer shows a limitation
  in place of the page and disables approval or correction actions that depend
  on inspecting that evidence.

## Reviewed values and printed evidence

A corrected value is never presented as if it were printed in the document.
For `review_decision=corrected`, the source detail shows both:

- **Reviewed:** the physician-corrected value used by the promoted record; and
- **Printed:** the immutable original `printed_quote` from the evidence region.

The labels remain visible without hover. The printed text may be visually
secondary or struck through, but it remains readable and inspectable. The
correction marker, review identity, reason, and source region remain linked in
the durable record even when the compact answer shows only a short correction
note.

## Field review contract

Every unresolved proposed field offers only actions valid for its evidence
state:

| Field state | Visible behavior | Allowed physician actions |
| --- | --- | --- |
| Schema-valid with exact evidence | Show proposed value and region. No automatic acceptance. | Approve, correct with reason, or reject with reason. |
| Low confidence | Show the proposed value, low-confidence label, diagnostic confidence when enabled, and exact region. | Approve as printed, correct with reason, or reject with reason. |
| Unreadable or missing | Show that no supported value was extracted and focus the attempted region when one exists. | Enter a correction only when the source supports it, with a required reason, or reject the field. No approval of a null value. |
| Ambiguous or conflicting | Show every relevant evidence region without selecting a winner. | Correct with reason or reject; approval is available only if the proposal itself is an exact supported reading. |
| Source unavailable or integrity failure | Show a typed limitation and no raw fallback content. | Retry through the authorized workflow when retryable; review actions remain disabled. |

Review actions create append-only review decisions. Editing never overwrites
the immutable proposal or its evidence. Reopening a completed field shows its
current review decision and allows a new authorized review command that
supersedes the prior review rather than mutating it.

## Partial extraction and promotion

- Independently valid fields remain reviewable when other fields are missing,
  unreadable, ambiguous, conflicting, or unavailable.
- A compact document-level summary reports reviewed and unresolved counts. It
  does not convert those counts into a quality score.
- Each affected field carries its own state and source access; the document is
  not represented as wholly successful or wholly failed.
- Missing content is never imputed. Rejection is an explicit physician
  decision, not a hidden omission.
- Promotion remains disabled until every non-null promotable field has one
  current approved or corrected review and every omitted field has an explicit
  rejection or applicable terminal limitation.
- The promotion control states why it is disabled and updates as decisions are
  completed.
- Promotion is an explicit UI-only command. Chat, the supervisor, and both
  workers cannot trigger it.

## Loading and cancellation

Document extraction is displayed as a separate job, not as a chat turn. The
loading state shows bounded stages such as upload stored, pages rendered/OCR,
field and evidence validation, and physician review waiting.

- The physician may close the panel while extraction continues.
- The UI states the 95-second document cap without implying that completion is
  guaranteed.
- Cancellation prevents undispatched work and requests cooperative
  cancellation of active work. It does not delete immutable extraction
  versions or audit events already committed.
- Extraction completion enters the review queue. It never joins the same-run
  answer path; only a later authorized read of a promoted reviewed record may
  support a patient claim.

## Errors and lane-local degradation

- A failure in one evidence lane does not erase independently verified content
  from the other lane.
- Patient-source failure yields a patient limitation; guideline retrieval
  failure yields `guideline_no_evidence`, `guideline_stale`, or
  `guideline_retrieval_unavailable` as applicable.
- Guideline failure never falls back to RRF-only output, web search, model
  knowledge, or the wording “no guideline exists.”
- A document preview hash, version, authorization, or rendering failure shows
  no page image and disables evidence-dependent review actions.
- If a whole claim loses any required source or citation field, the entire
  claim is withheld. Other verified claims may render and the answer becomes
  partial.
- Error copy names what is unavailable and what remains usable without
  exposing identifiers, raw clinical values, document text, queries, prompts,
  or internal exception details.

## Small-screen behavior

At narrow widths the panel becomes a single-column drawer with two explicit
views: **Answer & review** and **Source**.

- Activating a citation switches to Source and focuses the exact source.
- Returning to Answer & review preserves the active citation, page, pending
  correction inputs, field decisions, and scroll context where practical.
- Essential source metadata and all review actions remain available without
  hover.
- The interface never shrinks a desktop split view until labels, values, or
  controls overlap; it reflows into the two-view interaction.
- Touch targets are approximately 44 by 44 CSS pixels where space permits,
  and no horizontal page scrolling is required at 320 CSS pixels.

## Accessibility and safety requirements

- Use semantic buttons and form controls with visible labels and native focus
  behavior.
- Announce citation changes, page/region focus, field decisions, validation
  errors, and promotion readiness through polite live regions. Validation
  errors use `role="alert"`.
- Pair every status color with text and, where helpful, an icon or border
  treatment.
- Keep source content text-only unless rendering the authorized immutable page;
  never execute document links, QR content, instructions, or embedded scripts.
- Recheck live user, site, patient, operation, ACL, squad, break-glass state,
  source version, and integrity at click and write boundaries.
- Do not place filenames containing patient information, raw values, OCR,
  page images, excerpts, or prompts in ordinary telemetry or URLs.

## Required implementation verification

1. Citation fixtures activate native records, approved and corrected document
   fields, and exact guideline excerpts with the expected source metadata.
2. A corrected document fixture displays reviewed and printed values
   distinctly and focuses the exact page/box.
3. Shifted boxes, changed hashes, stale versions, withdrawn records, another
   patient, and click-time authorization loss fail closed without source
   content.
4. Low-confidence, unreadable, missing, ambiguous, and conflicting fields
   expose only valid actions; null approval and correction without a reason
   are rejected.
5. Partial extraction preserves independently reviewable fields and blocks
   promotion until every included or omitted field has an explicit current
   decision.
6. Patient and guideline lanes render separately; lane-local outages preserve
   other verified claims and produce typed limitations.
7. Loading, cancellation, 95-second timeout, no same-run extraction-to-answer
   path, and retry behavior match the supervisor and worker contracts.
8. Desktop and 320-pixel layouts support keyboard and touch operation without
   clipped controls or horizontal page scrolling.
9. UI, gateway, audit, log, metric, and trace fixtures contain no real PHI and
   assert that protected source content is absent from ordinary telemetry.

## Out of scope

- Production styling, final copy polish, or a general document-management UI.
- Automatic acceptance from confidence, extraction directly supporting chat,
  model-authored citation metadata, or model-selected promotion.
- Patient applicability, diagnosis, treatment, dosing, or a synthesized
  patient-versus-guideline recommendation.
- Additional document types, a lab-trend widget, or modification of native
  OpenEMR medication, allergy, demographics, problem, order, or procedure
  result tables.
