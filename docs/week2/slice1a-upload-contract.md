# Slice 1A: lab source upload contract

This document describes the implemented boundary from GitLab #34. It is not
an extraction, preview, final-claim, or persistence workflow.

## Browser flow

1. The open-chart module calls `public/api/document_intent.php` with the
   existing `copilot` CSRF token and the closed `lab_pdf` document type. The
   server derives site, active user, current chart, squad and document ACL; it
   returns a 15-minute, server-bound intent. It accepts no patient identifier.
2. The browser submits the file and intent to `public/api/document_upload.php`.
   The endpoint repeats the session/CSRF/chart/ACL/break-glass checks and
   rejects a supplied `pid`, `patient_id`, or client-selected document type.
3. A valid upload is PDF-only, up to 20 MiB and 20 pages. OpenEMR's native
   `Document::createDocument()` stores the bytes in its configured protected
   document store. The module stores only an immutable source id, native UUID,
   SHA3-512 content hash, type, MIME, byte/page counts, and intent mapping.
   It never stores the original filename, bytes, OCR, or extracted values.
4. Repeating the same intent returns the same immutable source record. A
   mismatched user/site/open chart or expired/processing intent fails closed as
   `duplicate_or_replay`; it cannot attach a document to another patient.

The source category is module-owned (`AgentForge Lab Uploads`) and uses the
same `patients|docs` ACL as OpenEMR document operations. Upload audit events
contain bounded identifiers, type, size/page count, content hash, and
correlation id only; document content remains in OpenEMR's protected store.

## Internal source-read seam

`public/gateway/source.php?source_id=document:<id>` is deliberately an
internal gateway route, not a browser or public-file path. It requires a valid
per-turn delegation token, rebuilds the `AuthorizedPatientContext`, verifies
the source mapping's site/patient, document ACL, document owner, non-deleted
state, MIME, and SHA3-512 hash before returning PDF bytes to the later bounded
`intake_extractor` worker. The worker receives no database credential,
filesystem path, patient selector, or write route.

## Contract artifacts

`agent/app/contracts/documents.py` is the strict 2.0.0 document contract
source. Its exported schemas are `contracts/schema/lab_extraction.schema.json`,
`upload_intent.schema.json`, and `upload_result.schema.json`; each rejects
unknown fields. `LabExtraction` is explicitly a proposed fact payload. It
requires every lab field's visible extraction state/confidence and source
citation; it is not permitted to become a chart fact or final patient-record
claim in this slice.

Synthetic fixtures live under `evals/fixtures/documents/` and
`agent/tests/fixtures/week2/`. They contain no patient identifier or real
clinical content. Extraction, resolver/verifier display, preview UI, and a
source-page browser link are intentionally reserved for #35.
