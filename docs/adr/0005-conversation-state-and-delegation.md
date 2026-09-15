# ADR-0005: Conversation State, Isolation, and Per-Turn Delegation

- **Status:** Accepted 2026-09-15 (owner approval)
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
   patient identifier. The agent forwards it on every gateway call; the
   gateway validates signature, expiry, single use of `jti` within its
   window, and conversation state, then re-runs section ACL and squad for the
   bound username. A mismatch closes the conversation with
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
   state, no model-side memory, nothing in browser storage; a new
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
- PHI at rest in the agent is limited to claim text with a 24 h TTL.

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
- TTL sweeper test: checkpoints older than 24 h are gone; binding rows are
  closed and later deleted.
- Checkpoint content test: no tool record fields (values, note text) appear
  in any stored checkpoint after a full turn on `AF-HEAVY`.

## Revisit Triggers

- A second agent instance or a multi-node deployment.
- A requirement to retain conversations beyond a day (would need retention
  policy, encryption at rest, and deletion procedures per compliance §2).
- Upstream adds a per-tab patient context, removing ARCH-HIGH-001.
