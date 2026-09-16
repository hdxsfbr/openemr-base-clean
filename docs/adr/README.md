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
| [0003](0003-integration-point-module-gateway.md) | Integration point: in-process module gateway, SMART on FHIR deferred | Accepted 2026-09-14 |
| [0004](0004-agent-runtime-contracts-and-model.md) | Agent runtime (LangGraph), canonical contracts, and model | Accepted 2026-09-15; model amended to Sonnet 5 the same day |
| [0005](0005-conversation-state-and-delegation.md) | Conversation state, isolation, and per-turn delegation | Accepted 2026-09-15 |
| [0006](0006-verification-strategy.md) | Deterministic claim verification | Accepted 2026-09-15 |
| [0007](0007-observability-and-telemetry.md) | Observability and PHI-free telemetry | Accepted 2026-09-15 |

The early decisions this index was expected to cover, and where each landed:

- OpenEMR module integration point: ADR-0003.
- Clinical-data access boundary: ADR-0002 (authorization), ADR-0003 (gateway).
- Agent framework and model selection: ADR-0004.
- Canonical schema technology: ADR-0004 (Pydantic contracts, exported JSON Schema).
- Conversation-state storage and patient isolation: ADR-0005.
- Verification and domain-constraint strategy: ADR-0006.
- Observability and PHI-redaction strategy: ADR-0007.
- Public deployment topology: ADR-0001.

No decision has been superseded. Dated status notes inside an accepted record
mark follow-ups as done or still open without rewriting the decision.
