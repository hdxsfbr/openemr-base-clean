# ADR-0005: Conversation State, Isolation, and Per-Turn Delegation

- **Status:** Accepted 2026-09-15 (owner approval)
- **Status note (2026-09-16):** implemented in commits 83f33a6, 948620f, and
  29b5c7b: `copilot_conversation` binding, per-turn HMAC ticket with a 90 s
  TTL (`Gateway/DelegationToken.php`, checked in `agent/app/delegation.py`),
  SQLite checkpointer as the only transcript store, per-turn record cache
  (its TTL is 120 s in `agent/app/state_store.py`, not the 60 s written in
  §3). Added beyond this record: a conversation whose last turn is older
  than 30 minutes is closed as idle (`ConversationRepository::IDLE_MINUTES`,
  commit 983657c). Verification status: done — new conversation empty
  (`ISO-NEW-CONVERSATION-001`), patient switch closes (`AUTH-SWITCH-001`),
  expired and tampered tickets (`AUTH-STALE-TICKET-001`, `AUTH-TAMPER-001`),
  ticket after `end` (Bruno `3 Failure Examples/07 Ticket after end`), token
  for another conversation refused
  (`test_turn_requires_token_and_matching_conversation`), closed conversation
  denied before any tool call (`AUTH-CLOSED-CONVERSATION-001`). Still open:
  same question across fresh conversations, two users on one patient, reused
  `jti`, ticket after logout, the 24 h TTL sweeper (no sweeper found in
  `agent/app/` as of this note). The checkpoint-content test
  (`ARCHITECTURE.md` open item 6) was added 2026-09-17 (see Verification).
- **Date:** 2026-09-14
- **Owners:** Andre Batista (module and agent service)
- **Related requirements:** PRD "multi-turn AI agent that can maintain
  context across a conversation"; authorization on every retrieval;
  conversation isolation (prior cohort context bleed,
  `docs/PRIOR_COHORT_LESSONS.md`); compliance rows 5, 10, 11 in
  `docs/audit/compliance.md` §4. `AUDIT.md` ARCH-HIGH-001, SEC-HIGH-002.
- **Related use cases:** CAP-01, CAP-03, CAP-04.
- **Related decisions:** ADR-0002 (checks per tool call), ADR-0003
  (delegation token).

## Context

Multi-turn conversation is required by all three use cases. The session
`pid` is a single mutable value per login shared by every tab
(ARCH-HIGH-001), the PHP session store is local to the container, and the
agent must hold no session cookie and see no `pid`. ADR-0002 requires the
live session and the open patient to be re-checked every turn; ADR-0003
issues one delegation token at panel render, which cannot express a later
patient switch. Conversation state with PHI must be bound to user, site,
patient, and conversation, short-lived, and never in browser or process
memory.

## Decision

1. **Binding lives in OpenEMR.** `conversation.start`, under the session and
   CSRF, records `(site_id, user_id, username, pid, correlation_id)` in the
   module table `copilot_conversation`. The client never sends a `pid`.
2. **Delegation is per turn.** `turn.ticket`, under the session and CSRF,
   re-checks session validity, `users.active`, session `pid` equals the bound
   `pid`, and break-glass membership, then mints an HMAC-signed token
   `{cid, jti, iat, exp = iat + 90 s, v}`. The token carries no user or
   patient identifier. The agent forwards it on every gateway call of that
   turn (one ticket, several tool calls); the gateway validates signature,
   expiry, and conversation state, then re-runs section ACL and squad for
   the bound username. A mismatch closes the conversation with
   `patient_context_changed`.
3. **Transcript is the LangGraph checkpoint.** `langgraph-checkpoint-sqlite`
   on a named volume, `thread_id` = conversation id (ADR-0004). The graph
   state schema holds, per conversation: user messages, verified claims and
   limitations, the tool log (tool, parameter hash, record source ids,
   status), the reference encounter and window, usage and budget counters.
   Tool records live in a per-turn in-memory cache keyed by turn id and are
   **not** part of graph state, so they are never checkpointed; each turn
   re-fetches (cache at most 60 s). Checkpoints expire after 24 h and are
   deleted when the binding closes.
4. **Isolation by construction.** State is keyed by conversation id only
   reachable with a valid token for that conversation; no process-global
   state, no model-side memory, no conversation content in browser storage
   (the panel keeps only the opaque conversation id in `sessionStorage` so
   a page reload can re-fetch the transcript behind a fresh ticket); a new
   conversation starts empty.

## Alternatives Considered

### One long-lived delegation token per panel render (ADR-0003 as written)

- Benefits: fewer module calls.
- Costs and risks: cannot see a patient switch or session end until the
  token expires; the gateway would need the session cookie to re-check,
  which hands the agent a session-hijack credential.
- Reason refined: the per-turn ticket keeps the session-dependent checks in
  the session and keeps the agent cookie-free.

### Transcript in the OpenEMR database via module tables

- Benefits: one store, OpenEMR backups cover it.
- Costs and risks: the agent has no database credentials by rule; writes
  would go through gateway endpoints, adding a hop per turn; PHI claim text
  in the EHR database outside the chart.
- Reason rejected: violates the no-credentials boundary for marginal gain.

### A separate transcript store beside the checkpointer

- Benefits: full control of the schema.
- Costs and risks: two stores for one conversation; drift between them.
- Reason rejected: the checkpointer already persists the state we need; the
  state schema is the contract.

### Postgres checkpointer (`langgraph-checkpoint-postgres`)

- Benefits: multi-instance ready.
- Costs and risks: another container on a 4 GiB Droplet before any need.
- Reason deferred: SQLite until the load test shows a second agent instance
  is needed; swapping the checkpointer is a one-line change.

### In-memory state

- Reason rejected: the prior cohort's context bleed; lost on restart;
  process-global by nature.

## Consequences

### Positive

- Every turn is re-authorized in the session; the agent holds no cookie.
- Isolation is testable with the fixtures and cheap to reason about.
- PHI at rest in the agent is limited to claim text. The 24 h TTL is a
  design target, not an implemented control: no sweeper runs and
  `ConversationRepository::sweep()` has no caller (see "Verification").

### Negative and residual risk

- A patient switch within a ticket's 90 s completes the in-flight turn for
  the bound patient (which the user could open anyway) and denies the next.
- Two module calls per turn (ticket, then agent) add about 50 ms.
- SQLite is single-instance; scaling the agent horizontally needs the
  Postgres checkpointer.
- The checkpointer stores whatever is in graph state; adding raw records to
  state by mistake would persist PHI. Guarded by the state schema and a test
  that inspects a checkpoint for record fields.
- The shared HMAC secret is a new credential in two containers; rotation is
  a redeploy.

## Verification

- Isolation evals: new conversation carries nothing; patient switch closes;
  same question across fresh conversations yields the same facts; two users
  on one patient never see each other's history; token for A cannot read B.
- Ticket evals: expired, reused `jti`, tampered signature, ticket after
  `end`, ticket after logout: all 403 with a denial event and no tool call.
- TTL sweeper test: **not written, and there is nothing to test yet.**
  `ConversationRepository::sweep()`
  (`src/Conversation/ConversationRepository.php:83`) implements the binding
  delete but has no caller and no schedule, and no checkpoint sweeper exists.
  Retention is a design target until one lands.
- Checkpoint content test: added 2026-09-17,
  `agent/tests/test_controls.py::test_checkpoint_holds_no_note_body_record_shape_or_token`.
  After a UC-01 turn and a notes follow-up on the af-dq-a2 fixtures through
  `AsyncSqliteSaver`, every table and column of the checkpoint is scanned: no
  raw record key (derived from the record contracts minus the keys graph
  state carries by design), no verbatim note body, and no delegation token.
  Lab values and doses are not asserted absent because verified claims carry
  them. The test found the token in graph state (`TurnState.token` at
  `66a6711`); it now lives in the per-turn cache (`state_store.put_token`).
  `AF-HEAVY` has no offline fixture, so the offline check runs on af-dq-a2.
  Checkpoints written before 2026-09-17 (the deployed tag `week1`, commit
  `e1dd331`, whose `TurnState` declared `token: str`) carry the delegation
  token in the `token` channel of every checkpoint on the Droplet's
  `agent_state` volume. The channel is no longer declared in `TurnState`, so
  those checkpoints hold a channel the current schema does not know. The M3
  deploy must either open a conversation checkpointed before the deploy and
  confirm it still loads, or confirm that the `agent_state` volume is
  recreated (which also removes the token bytes at rest). Each such token
  expired 90 s after minting and carries no user or patient identifier
  (Decision 2), so the residual is stale credential material, not PHI.

## Revisit Triggers

- A second agent instance or a multi-node deployment.
- A requirement to retain conversations beyond a day (would need retention
  policy, encryption at rest, and deletion procedures per compliance §2).
- Upstream adds a per-tab patient context, removing ARCH-HIGH-001.
