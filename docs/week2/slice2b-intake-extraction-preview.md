# Slice 2B: intake extraction and cited preview

GitLab #38 extends the existing review-only `intake_extractor` path to the
`intake_form` source type introduced in #37. It does not create a second
worker, add a clinical write route, or make a preview usable as chat evidence.

## Implemented boundary

The module still derives the open-chart patient and stores the source before
the agent sees an immutable `source_id`. The internal source reader now returns
the persisted closed document type in `X-Copilot-Document-Type`. The worker
requires that value: missing or unknown type is an unavailable result, rather
than silently defaulting to a lab parser.

For the supported synthetic PDF, the worker reads only fixed printed labels and
builds the strict `IntakeExtraction` proposal. It returns demographics (given
name and the ambiguous date of birth represented by the fixture), chief
concern, a medication, an allergy and reaction state, and family-history
relationship and condition. Each printed value or ambiguous/conflicting
selection carries the shared `SourceCitation` shape with source hash, page,
field ID, and exact printed quote. Missing and unreadable fields intentionally
have neither a value nor citation.

The resolver verifies every field that can render: source ID/hash, page,
field ID, printed quote, and that any displayed value is present in that quote.
A mismatch produces a typed no-content failure. Ambiguous, conflicting, and
missing fields make the job `partial`; independently verified values remain in
the preview. Confidence remains diagnostic only.

The existing chart UI selects `lab_pdf` or `intake_form` before it creates the
same server-bound upload intent. It renders an explicit intake-preview label,
field state, exact printed evidence where it differs from the proposed value,
and the existing reauthorized source-page link. DOM text nodes render all
document-provided text, so prompt-like text stays inert data. The preview says
it is not saved to the chart and cannot support later chart answers.

Telemetry keeps the existing bounded status, timing, confidence, record-count,
zero-token/cost, verifier, and eval-outcome metadata. It does not emit source
bytes, form fields, source IDs, patient identity, or document text.

## Evidence and remaining work

Focused deterministic tests cover successful fixture parsing, partial-field
survival, prompt-like chief concern text, type mismatch, missing document type,
fault outage, strict unknown-field rejection, and source-citation field-ID
tampering. The contract export check confirms 15 generated schemas are in sync,
and JavaScript syntax validation covers the changed preview UI.

This is code-level evidence only. Authenticated development-stack upload to
preview, browser interaction, deployment, complete two-document gate, and
privacy-channel evidence are not claimed here; #39 owns release/deployment
hardening. No extracted fact is persisted or used as a patient-record claim.
