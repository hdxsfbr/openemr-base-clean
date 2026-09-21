# ADR-0013: Deterministic supervisor and bounded worker handoffs

- **Status:** Accepted 2026-09-21 (owner approval)
- **Date:** 2026-09-21
- **Owners:** Andre Batista (agent orchestration and worker boundaries)
- **Related requirements:** Week 2 PRD Stage 3 and Core Agent Requirement 4;
  one inspectable supervisor, one intake-extractor worker, one
  evidence-retriever worker, and logged explicit handoffs.
- **Related use cases:** UC-01 and UC-02; document-derived changes, abnormal
  laboratory review, and bounded guideline evidence in the pre-visit workflow.
- **Related decisions:** ADR-0004 (LangGraph and the existing turn graph),
  ADR-0005 (patient-bound state), ADR-0006 (deterministic verification),
  ADR-0007 (PHI-safe telemetry), ADR-0009 (bounded extraction), ADR-0010
  (bounded retrieval), ADR-0011 (document lifecycle), and ADR-0012 (separate
  evidence lanes).

## Context

The Week 1 graph already authorizes, retrieves patient records, narrates,
verifies, repairs once, and renders a response. Week 2 must add two named
workers without replacing that tested safety boundary or turning routing into
an opaque model decision. Document extraction can take up to 95 seconds and
ends in human review, while guideline retrieval is a two-second read-only
operation that can contribute evidence to a chat turn. Treating those as one
unbounded agent loop would mix incompatible lifecycles and let unreviewed
proposals approach the final-answer path.

## Decision

1. **Graph shape.** A small parent supervisor coordinates the existing Week 1
   turn graph and exactly two worker subgraphs: `intake_extractor` and
   `evidence_retriever`. The Week 1 graph remains the only path that composes,
   verifies, repairs, and renders a chat answer. A separate model critic is not
   part of the core graph.
2. **Deterministic routing authority.** The supervisor is a plain LangGraph
   state-machine node over a typed event and trusted workflow state; it makes
   no model call. Fixed policy, contract validation, authorization outcome,
   source/review state, allowed intent, dependency readiness, and remaining
   budget determine the route. A model or document instruction may propose
   bounded content inside a worker but cannot select a broader route. Ambiguous
   requests do not escalate authority: they stay on the chart-only path or ask
   the physician to request guideline evidence explicitly.
3. **Routes.** `document_uploaded` and `reprocess_requested` may dispatch only
   the intake-extractor after the module has created and authorized the source
   intent. A `chat_turn` always uses the existing patient turn graph and may
   additionally dispatch the evidence-retriever only for explicit, permitted
   guideline-evidence intent whose `EvidenceQuery` passes ADR-0010. Review,
   correction, promotion, amendment, and withdrawal remain UI-only module
   commands under ADR-0011; the supervisor and workers cannot invoke them.
   Diagnosis, treatment, dosing, or applicability intent refuses before the
   evidence worker runs.
4. **Worker boundaries.** The intake-extractor may read one authorized source
   version and create one immutable extraction version containing proposed
   facts and field evidence. It cannot promote facts, call guideline retrieval,
   answer a chat question, or decide confidence-based acceptance. The
   evidence-retriever may execute one strict local query and return exact
   version-bound chunks or a retrieval limitation. It cannot access raw
   documents or unrestricted chart text, infer patient applicability, author
   a recommendation, or write any record.
5. **No extraction-to-answer shortcut.** Extraction terminates at a reviewable
   extraction version. It never joins the chat-answer path in the same run.
   Only current promoted, human-reviewed document records may later be read by
   the patient turn graph. This makes extraction, physician review, and a later
   grounded answer deliberately sequential.
6. **Parallel work.** On a permitted mixed chat turn, authorized patient-record
   retrieval and guideline retrieval may run concurrently because both are
   read-only and independently bounded. Their results join before ADR-0012
   source resolution and deterministic verification. Failure or absence in one
   lane produces that lane's typed limitation and does not erase independently
   verified claims from the other lane.
7. **Typed handoffs.** A worker request contains only `handoff_id`,
   `correlation_id`, optional `conversation_id` and `turn_id`, event kind,
   worker, bounded reason code, attempt, deadline, versioned input references,
   and contract versions. A worker result contains the same identity plus
   `status` (`completed`, `partial`, `unavailable`, `failed`, or `canceled`),
   versioned output references, bounded limitation codes, retryability, and
   stage timings. Raw document bytes, page images, OCR, field values, note
   text, prompts, and evidence excerpts never enter the handoff envelope or
   checkpoint; protected stores and per-turn evidence caches retain them.
8. **Completion conditions.** Intake extraction completes when one immutable
   extraction result or terminal typed limitation is persisted and referenced
   for the review UI. Evidence retrieval completes with at most five exact
   active-corpus chunks or a terminal typed limitation. A chat answer is ready
   only after every participating branch has joined and the existing verifier
   has accepted or withheld each claim. Neither supervisor nor worker may mark
   a clinical claim verified.
9. **Budgets, retries, and cancellation.** Extraction is a separate job with
   ADR-0009's 60-second first attempt, one 500 ms backoff and 30-second bounded
   region retry, and 95-second document cap. Guideline retrieval has ADR-0010's
   two-second total deadline and no supervisor retry. The chat graph retains
   its 45-second wall clock and existing provider retry/circuit-breaker rules.
   Cancellation prevents undispatched work and cooperatively stops active
   work; already committed immutable extraction versions and audit events are
   retained rather than rolled back or deleted.
10. **Follow-ups and freshness.** Every follow-up re-enters the supervisor and
    re-evaluates the current typed event, authorization, record versions, and
    corpus version. Prior route summaries and source identities may remain in
    conversation state, but the current turn re-resolves the evidence it cites;
    a prior worker result cannot silently authorize a current claim.
11. **Inspectability and audit.** Every supervisor decision emits a PHI-free
    `supervisor.route` event and every dispatch/completion emits a
    `worker.handoff` event containing correlation and handoff IDs, worker,
    reason, status, attempt, timing, limitation code, and contract/model/index
    revisions. These appear as explicit parent/child spans and bounded local
    JSON logs. Patient-document access and extraction start/result also create
    bounded OpenEMR audit rows through the module; existing gateway reads,
    model disclosure, review, and promotion retain their own audit events.
    Raw queries, OCR, values, excerpts, prompts, and images are excluded from
    ordinary telemetry and audit comments.

## Alternatives Considered

### Model-driven supervisor

- Benefits: can classify vague natural-language requests without an explicit
  intent rule.
- Costs and risks: adds latency, cost, nondeterministic routes, duplicated
  planning, and a routing-level prompt-injection surface; it would also require
  a separate proof that its worker choices cannot widen authority.
- Reason rejected: only three meaningful routes exist and their prerequisites
  are already explicit. Models remain useful inside bounded extraction and
  narration, but not as routing authority.

### Merge the workers into the Week 1 turn graph

- Benefits: one graph and one request lifecycle.
- Costs and risks: a 95-second review-producing document job would exceed the
  chat budget, and unreviewed proposals could become adjacent to final claims.
- Reason rejected: extraction and answer generation have different authority,
  persistence, timeout, and human-review boundaries.

### Let workers compose their own final responses

- Benefits: less parent-graph plumbing.
- Costs and risks: duplicates citation and safety behavior and permits a worker
  to bypass the accepted deterministic verifier.
- Reason rejected: ADR-0006 and ADR-0012 establish one final verification and
  rendering boundary.

## Consequences

### Positive

- Every route and handoff is enumerable, traceable, and testable without asking
  a model why it chose a worker.
- The Week 1 graph, authorization boundary, verifier, and failure behavior stay
  intact.
- Long-running extraction cannot consume the chat deadline or expose proposed
  facts as patient-record claims.

### Negative and residual risk

- Ambiguous guideline requests may require explicit physician wording instead
  of being inferred by a routing model.
- A separate extraction job needs durable job status and cancellation handling;
  the current per-turn delegation ticket is not itself a 95-second job lease.
- Parallel patient and guideline reads must preserve independent deadlines and
  deterministic join behavior under cancellation.

## Verification

- Route-table tests cover every typed event, unsupported transition, ambiguous
  request, forbidden intent, stale state, and unavailable dependency.
- Adversarial documents and user text cannot alter worker, route, deadline,
  retry, contract version, or authorization state.
- Handoff contract fixtures reject unknown fields, raw-content fields, invalid
  transitions, mismatched correlations, stale versions, and duplicate terminal
  results.
- Extraction tests prove no same-run path reaches narration, verification, or
  promotion; only a later authorized read of a promoted record can support a
  patient claim.
- Mixed-turn tests prove parallel branches join before verification, one-lane
  failure yields a partial response, and cancellation/deadline races emit one
  terminal status per handoff.
- Trace and audit tests reconstruct route order from correlation and handoff IDs
  while finding no synthetic patient text, OCR, field values, document bytes,
  images, prompts, or evidence excerpts.

## Revisit Triggers

- Supported worker types or route combinations grow beyond a small enumerable
  policy.
- Clinician testing shows explicit guideline intent causes material task
  failure that a bounded classifier can solve without widening authority.
- Extraction moves into a synchronous budget shorter than the chat turn, or a
  future approved workflow allows reviewed data to become available during the
  same interaction.
