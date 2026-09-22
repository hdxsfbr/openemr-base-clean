# Slice 2A: intake contracts and authorized source storage

GitLab #37 extends the existing Slice 1 source-upload seam to the closed
`lab_pdf | intake_form` discriminator. It does not invoke extraction, render a
preview, or create a clinical record.

## Supported intake upload format

Slice 2A deliberately supports one synthetic PDF intake format only: one to
ten pages, at most 10 MiB, `application/pdf`, and containing the stable visible
marker `AgentForge Synthetic Intake Form`. The marker is a file-format guard,
not a proposed clinical value. It makes a known lab PDF declared as
`intake_form` fail before native OpenEMR storage. Image/OCR intake support is
not claimed by this subtask.

The one-page synthetic fixture is
`evals/fixtures/documents/synthetic-intake-form.pdf`; its sidecar records the
happy, ambiguous, conflicting, prompt-like-text, and type-mismatch scenarios.
All fixture text is synthetic. Prompt-like text remains document data and no
upload code reads it to select a patient, route, schema, authority, or policy.

## Boundary and contracts

The browser names a document type only when it creates an intent. The module
derives site, user, and patient from the live OpenEMR session, applies the
existing CSRF, ACL, squad, break-glass, and audit path, and persists that
document type with the intent. The upload request cannot name a patient or a
document type. The stored intent selects the only validator that may run.

`agent/app/contracts/documents.py` exports the closed document union, the
conditional intake size/page limits, and strict review-only intake proposals:
demographics, chief concern, medications, allergies, family history,
per-field state/confidence, and resolver-addressable citations. Unknown
properties are rejected. `checked`, `unchecked`, `missing`, `ambiguous`,
`conflicting`, and `unreadable` remain separate states; confidence cannot
approve a value. The source mapping stores metadata only; OpenEMR retains the
bytes and the agent retains no direct database or filesystem access.

The existing same-intent transaction and immutable source mapping are shared
unchanged. A retry returns the original source only after the full trusted
context check; a patient, user, site, expired-intent, or document-type mismatch
cannot attach or disclose another source.

## Evidence scope

The committed unit and contract checks prove pure file-policy discrimination,
closed request shape, strict-schema rejection, and generated-schema drift.
Development-stack upload/source-read and deployed extraction-preview evidence
remain work for #37's authenticated integration verification and #38/#39,
respectively; they must not be inferred from these fixtures.
