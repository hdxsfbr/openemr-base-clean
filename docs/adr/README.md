# Architecture Decision Records

Use a decision record for choices that affect trust boundaries, security,
clinical behavior, operability, cost, or the ability to change the system later.

Create records by copying `0000-template.md` and assigning the next number. Keep
accepted records immutable except for status and links to superseding decisions.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-ephemeral-single-droplet-baseline.md) | Ephemeral single-Droplet baseline on DigitalOcean | Accepted 2026-09-13; verified live 2026-09-14; follow-ups recorded in the status note |
| [0002](0002-patient-scope-authorization.md) | Patient-scope authorization for co-pilot tool calls (parity with the chart) | Accepted 2026-09-14 |
| [0003](0003-integration-point-module-gateway.md) | Integration point: in-process module gateway, SMART on FHIR deferred | Accepted 2026-09-14; status notes 2026-09-19 (batched gateway); amended 2026-09-19 (brief on chart open, module 0.5.0); status note 2026-09-20 (clock reverted to UTC) |
| [0004](0004-agent-runtime-contracts-and-model.md) | Agent runtime (LangGraph), canonical contracts, and model | Accepted 2026-09-15; model amended to Sonnet 5 the same day; plan rounds amended 3 -> 1 on 2026-09-18; status notes 2026-09-20 (follow-up effort `low`, output cap, known plans) |
| [0005](0005-conversation-state-and-delegation.md) | Conversation state, isolation, and per-turn delegation | Accepted 2026-09-15; status notes 2026-09-18 (recent conversation resumed per open chart) and 2026-09-19 (drawer session pinning, module 0.4.4) |
| [0006](0006-verification-strategy.md) | Deterministic claim verification | Accepted 2026-09-15; decision 7 amended 2026-09-19 (summary grounding and fallback) |
| [0007](0007-observability-and-telemetry.md) | Observability and PHI-free telemetry | Accepted 2026-09-15; amended 2026-09-19 (content capture mode); status note 2026-09-20 (Slack alert delivery) |
| [0008](0008-human-reviewed-document-derived-facts.md) | Human-reviewed promotion of document-derived facts | Accepted 2026-09-21; sections 3, 6, 7, and 9 superseded by ADR-0011 |
| [0009](0009-bounded-document-extraction-and-review.md) | Bounded document extraction with visible review states | Accepted 2026-09-21; sections 1, 4, 5, and 6 superseded by ADR-0011 |
| [0010](0010-bounded-local-guideline-retrieval.md) | Bounded local retrieval for guideline evidence | Accepted 2026-09-21 |
| [0011](0011-canonical-reviewed-document-record-contracts.md) | Canonical reviewed-document record contracts and lifecycle | Accepted 2026-09-21 |

The early decisions this index was expected to cover, and where each landed:

- OpenEMR module integration point: ADR-0003.
- Clinical-data access boundary: ADR-0002 (authorization), ADR-0003 (gateway).
- Agent framework and model selection: ADR-0004.
- Canonical schema technology: ADR-0004 (Pydantic contracts, exported JSON Schema).
- Conversation-state storage and patient isolation: ADR-0005.
- Verification and domain-constraint strategy: ADR-0006.
- Observability and PHI-redaction strategy: ADR-0007.
- Public deployment topology: ADR-0001.

ADR-0011 partially supersedes the listed sections of ADR-0008 and ADR-0009.
Dated status notes inside an accepted record mark follow-ups as done or still
open without rewriting the decision, and a
dated amendment records a shipped change to one. ADR-0001 through ADR-0007
carry as-built notes from 2026-09-16; the Status column above lists their later
amendments and notes. Week 2 ADRs remain design decisions until their separate
verification sections are satisfied during implementation.
