# Slice 1B: lab extraction preview

GitLab #35 implements the review-only continuation of the #34 upload seam.
It does not promote a value into the chart, feed it into a chat answer, add a
supervisor, or add release telemetry/gating.

## Implemented boundary

After the browser stores a `lab_pdf`, it obtains the existing fresh delegated
ticket and submits only the immutable `document:<id>` reference to
`POST /v1/conversations/{id}/lab-extractions`. The agent's PRD-named
`intake_extractor` reads that one source through `gateway/source.php`; the
gateway repeats delegation, user, site, patient, lab/document ACL, document
owner, MIME, deleted-state, and SHA3-512 checks before returning bytes.

The committed one-page synthetic fixture has a deliberately simple PDF text
layer. The worker parses only its fixed lab labels, so no VLM/model call or
untrusted document instruction can select a patient, route, tool, schema,
deadline, authority, or write action. It marks every required field as
`extracted`, `missing`, `ambiguous`, `unreadable`, or `malformed`; a valid
field remains visible if another is absent. The deterministic resolver—not
the parser—then authors the source id, page, field id, exact printed value,
and source hash citation. The final verifier rechecks every displayed value
against those bytes. Any bad source/hash/citation or worker outage returns an
explicit limitation without an extraction payload.

The panel labels the result **Extraction preview only** and renders it through
DOM text nodes. A citation opens `document_source.php`, which repeats live
session/open-chart/ACL/squad/break-glass and source-integrity checks before
serving the immutable PDF. The endpoint accepts no patient parameter. Preview
values are not persisted and the chat graph has no path to them.

## Evidence and remaining work

Focused evidence is `agent/tests/test_intake_extractor.py` (complete,
partial, prompt-like text, citation tamper, fault, and denial) and the
API-contract test in `agent/tests/test_api.py`. The module PHPUnit suite and
PHP lint exercise the existing upload boundary and changed endpoints. An
authenticated synthetic development-stack smoke passed stored source → fresh
ticket → reauthorized source read → complete six-field worker preview. The
development stack does not include the public agent edge route, so browser
request-through-edge and public-deployment smoke remain required before #35
can close; #36 owns release telemetry, the starter gate, and video.
