# Slice 4B: bounded evidence-worker dispatch

GitLab #47 consumes the sealed Slice 4A supervisor contracts at the local
evidence-worker boundary. It does not add a chat route, source resolver,
claim verifier, UI lane, model call, persistence write, or deployment claim.

## Implemented boundary

`agent/app/supervisor_dispatch.py` accepts only a validated
`RouteDecision` that selects the `evidence_retriever`, opaque conversation and
turn identifiers, up to three closed `GuidelineTopic` selectors, an absolute
deadline, and two boolean-only callbacks:

- `reauthorize()` rechecks the current authorization just before dispatch and
  immediately after worker completion;
- `corpus_is_current()` rechecks that the approved corpus is still current at
  the same two points.

Neither callback receives or returns patient identity, clinical text, document
bytes, excerpts, prompts, or source content. A false or failing preflight
creates no worker handoff. Once a handoff exists, it receives one generated
opaque ID, one bounded `EvidenceQuery` (at most three topics, five results,
and the lesser of the remaining deadline and two seconds), and no retry.

The bridge validates the worker's `3.0.0` terminal envelope, correlation,
handoff ID, and active corpus version before recording a `4.0.0` terminal
handoff reference. It retains no excerpts. It maps no-result, cancellation,
timeout, malformed result, availability, authorization, and freshness failures
to bounded supervisor limitations. A timeout or a post-dispatch freshness or
authorization failure cooperatively calls the worker cancellation hook, so a
late worker result cannot become a successful handoff.

The small `chat_intent_projection` helper may inspect protected user text only
to emit finite signals, then discards it; it is not a routing authority. The
sealed Slice 4A route table remains the routing authority.

## Evidence

`agent/tests/test_supervisor_dispatch.py` proves successful bounded dispatch,
authorization and source-freshness rechecks, denied/invalid preflight,
correlation and envelope mismatch, no-result versus cancellation, stale
authorization after worker completion, timeout cancellation, and a privacy
canary. It is run alongside the Slice 4A contracts and the worker's own race
tests:

```bash
agent/.venv/bin/python -m pytest \
  agent/tests/test_supervisor_dispatch.py \
  agent/tests/test_supervisor_contracts.py \
  agent/tests/test_evidence_retriever_worker.py
```

This is a runtime bridge, not final integration evidence. The future chat
graph/source-registry/verifier/UI-lane slice still must invoke the bridge from
an authenticated chart boundary and re-resolve sources before rendering.
