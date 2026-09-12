# Architecture Decision Records

Use a decision record for choices that affect trust boundaries, security,
clinical behavior, operability, cost, or the ability to change the system later.

Create records by copying `0000-template.md` and assigning the next number. Keep
accepted records immutable except for status and links to superseding decisions.

Expected early decisions include:

- OpenEMR module integration point.
- Clinical-data access boundary.
- Agent framework and model selection.
- Canonical schema technology.
- Conversation-state storage and patient isolation.
- Verification and domain-constraint strategy.
- Observability and PHI-redaction strategy.
- Public deployment topology.
