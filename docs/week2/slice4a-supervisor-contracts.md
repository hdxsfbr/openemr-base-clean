# Slice 4A: deterministic supervisor contracts

GitLab #46 establishes the pure, inspectable contract boundary for the Week 2
supervisor. It adds no graph node, worker invocation, source retrieval, UI,
rendering, deployment assertion, or claim verification change.

## Boundary

`agent/app/contracts/supervisor.py` is the source of truth for the versioned
`4.0.0` contracts. A supervisor request contains an authorization attestation,
opaque event/source references, an absolute deadline, and finite trusted intent
signals. It cannot contain patient identity, chart text, document bytes, OCR,
extracted values, notes, questions, answers, prompts, or guideline excerpts.
The exported JSON Schema files are the only cross-runtime representation.

The routing input deliberately uses a finite `ChatIntentSignal`, not free text.
The future authenticated boundary may inspect protected content transiently to
derive a signal, but must discard that content before it creates request state,
a handoff, telemetry, a fixture, or an error. This keeps a user-controlled
instruction from changing worker identity, authorization, deadline, attempt,
or contract version.

## Deterministic decision table

| Trusted event / signal | Action | Worker | Reason | Patient-record path |
| --- | --- | --- | --- | --- |
| Authorized `document_uploaded` or `reprocess_requested` | dispatch | `intake_extractor` | `document_event` | no chat path |
| Chat with Include-guideline-evidence control | dispatch | `evidence_retriever` | `explicit_control` | preserved |
| Chat with explicit guideline/source/standard/publisher signal | dispatch | `evidence_retriever` | `explicit_guideline_terms` | preserved |
| Chat asking evidence for an approved supported finding/topic | dispatch | `evidence_retriever` | `evidence_for_supported_finding` | preserved |
| Ambiguous evidence signal | clarify | none | `ambiguous` | preserved |
| Diagnosis, treatment, dosing, or patient-applicability signal | refuse before retrieval | none | `disallowed_advice` | not retrieved |
| Any other authorized chat | chart only | none | `patient_record_only` | preserved |

The advice/applicability row has priority over every evidence route, including
the explicit control. Routing is a pure function and makes no model call.

## Handoff and transition policy

`DispatchRecord` has exactly one worker, an `attempt` fixed at `1`, a deadline,
and a versioned input reference. The intake worker can receive only an
authorized document-source reference on a document event. The evidence worker
can receive only an evidence-request reference on an allowed chat reason.
`HandoffCompletion` has one terminal status, either a versioned opaque output
reference or one bounded non-retryable limitation, never both. A worker output
reference must match the worker's Slice 2 or Slice 3 contract version.

`complete_handoff` and `apply_handoff_completion` reject version or correlation
mismatches, wrong workers, stale deadlines, malformed output references, and a
second terminal result. `answer_readiness` only observes branch completion and
the existing verifier's source-resolution/accept-or-withhold references; it
does not verify or approve claims itself.

## Evidence

`agent/tests/test_supervisor_contracts.py` covers every table row, all four
advice/applicability signals, malformed/unknown/protected fields, missing
version/correlation/deadline, wrong worker, invalid output contract, stale and
duplicate completion, and serialization/error privacy canaries. The valid
cross-runtime fixture is
`agent/tests/fixtures/week2/valid_supervisor_contracts.json` and contains only
opaque IDs, enums, timing, and version references.

The next subtask (#47) may consume these contracts at the authorized graph and
worker boundaries. It must recheck authorization and source freshness there;
this contract layer cannot supply that runtime proof.
