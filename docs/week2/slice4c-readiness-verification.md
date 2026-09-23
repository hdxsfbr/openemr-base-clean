# Slice 4C: final answer readiness and lane-local verification

GitLab #48 extends the existing verifier/display seam. It does not add a
worker, source type, persistence path, corpus change, deployment proof, or a
new UI workflow.

## Implemented final-display boundary

The Week 1 patient-record graph now has a `revalidate` node between the
deterministic verifier and renderer. It replays only the bounded tool calls
already authorized for the turn, using the per-turn delegation token that is
intentionally held outside checkpoint state. Each replay enters the module
gateway again, which rechecks the live user, site, active patient, scope, and
ticket. The old evidence pack, model claims, and handoff output are context
only. A fresh pack is rebuilt and the existing deterministic verifier checks
each candidate claim against it before rendering.

Consequently, a record removed or changed while narration or repair is running
does not render. A failed final projection is an unavailable source; a missing
or altered cited record is withheld under the existing verifier rules. The
final state exposes only bounded readiness fields (`ready`, terminal/verified
booleans, state, correlation, and a limitation code) in the response and
history. It contains no record, source, question, or claim content.

The existing separate guideline lane now performs the equivalent final check:

1. after local retrieval returns, the agent makes a discarded `patient_context`
   gateway read using the current delegation to reauthorize the live chart;
2. only after that succeeds does `GuidelineReleaseService.reverify` reload the
   active corpus pointer and immutable chunk rows and recheck the exact quote,
   section, hashes, corpus version, and deterministic template; and
3. a failed authorization, changed correlation, stale pointer, missing chunk,
   or hash mismatch returns one typed guideline limitation and no excerpt.

The guideline renderer remains a separate publisher-evidence lane with its
existing no-applicability notice. It does not become a chart claim and this
slice adds no mixed model summary or advice path. The chat renderer preserves
its existing click-to-source links and adds an accessible bounded final-source
check label; it does not expose an internal handoff or protected source data.

Before either path begins, advice, diagnosis, dosing, and applicability
requests pass through the existing sealed deterministic route table. A refused
request retrieves no chart or guideline data and renders only a bounded
out-of-scope limitation.

`answer_readiness` now rejects a nonterminal, duplicate-worker, mismatched
correlation/handoff, or malformed in-memory branch even if a caller bypasses
schema parsing. It observes verifier references only; it never certifies a
claim itself.

## Focused evidence

`agent/tests/test_supervisor_readiness.py` uses a synthetic fixture whose lab
is available to narration and then removed for final resolution. The replayed
authorized calls occur before render, and the formerly accepted claim is
withheld. It also covers pending, duplicate, and correlation-corrupted branch
states. `agent/tests/test_guideline_release.py` covers active-corpus mutation
and correlation mismatch after the worker has returned. Existing supervisor
contract and dispatch tests continue to cover deterministic refusal, injection
signals, stale/duplicate/cancelled handoffs, and privacy canaries.

This is local focused evidence, not the Slice 4 release proof. The final task
(#49) must exercise the integrated route/fault matrix, deployed UI, PHI-free
trace reconstruction, and final parent recheck from `main`.
