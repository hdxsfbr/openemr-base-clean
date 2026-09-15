# Submission Checklist

This checklist supplements, rather than replaces, the official submission
portal. All deadlines are Central Time.

## Early Submission — Wednesday, September 16 at 11:59 PM

**Repository note (2026-09-14):** Per instructor direction, GitLab
(`labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean`, personal
namespace) is the actual working system of record — that's where `main`,
merges, and CI/history live going forward. The PRD's own submission table
names "GitHub Repository — Forked from OpenEMR" as the deliverable, and
`hdxsfbr/openemr-base-clean` on GitHub is kept as a genuine fork of
`Gauntlet-HQ/openemr-base-clean` to satisfy that literal requirement. GitHub
is not kept in sync with GitLab commit-for-commit — confirm with the
instructor/portal which URL is actually expected at submission time, and if
it's GitHub, push the final state there before submitting.

### Hard gates and repository

- [ ] Public repository is based on the required OpenEMR fork.
- [ ] `README.md` contains deployed URL, setup, architecture overview, demo
      credentials, test commands, and limitations.
- [x] `AUDIT.md` begins with an approximately 500-word key-findings summary and
      covers all five required audit areas. *(Complete and owner-reviewed
      2026-09-14; Stage 3 gate passed.)*
- [x] `USERS.md` defines the target user, workflow, and agent rationale for every
      use case; `USER.md` points to it. *(Revised and owner-approved
      2026-09-15; clinician-proxy validation checkboxes remain open.)*
- [x] `ARCHITECTURE.md` begins with an approximately 500-word summary and traces
      every capability to `USERS.md`. *(Revised against the audit and
      ADR-0002..0007; owner-approved 2026-09-15, Stage 5 gate passed.)*
- [x] `KEY_METRICS.md` defines and justifies product-success metrics.
      *(Definitions, targets, gaming defenses, and decision thresholds
      approved 2026-09-15; latency and cost thresholds provisional until the
      load baseline.)*
- [ ] `docs/REQUIREMENTS_TRACEABILITY.md` links requirements to current evidence.

### Product and engineering

- [x] Deployed OpenEMR is accessible and contains demo data only.
      *(2026-09-15: `v0.1.0-skeleton` on a disposable `sslip.io` hostname;
      synthetic cohort and demo users only. Owned hostname pending.)*
- [ ] Clinical Co-Pilot is embedded in the patient workflow.
- [ ] Multi-turn follow-up and tool chaining work in the live environment.
- [ ] Authorization is enforced for every retrieval.
- [ ] Every displayed factual claim passes verification and has a source.
- [ ] Correlation IDs connect UI, gateway, tools, LLM, verifier, and logs.
- [ ] Observability records order, latency, failures, tokens, and cost.
- [ ] Dashboard shows all PRD-required metrics.
- [ ] Eval suite includes boundary, invariant, and regression cases.
- [ ] `/health` and meaningful `/ready` endpoints pass expected tests.
- [ ] Runnable API collection covers core endpoints.
- [ ] No credentials, tokens, session IDs, PHI, or private trace URLs are
      committed.

### Submission package

- [ ] Live application URL tested from outside the development machine.
- [ ] Repository URL and exact commit recorded.
- [ ] Dashboard access or sanitized evidence prepared for evaluators.
- [ ] Eval dataset and results included.
- [ ] 3–5 minute demo recorded, reviewed, and uploaded.
- [ ] AI interview instructions confirmed.
- [ ] Technical interview scheduled within the required window.
- [ ] Submission completed with several hours of buffer.

## Final Submission — Sunday, September 20 at Noon

- [ ] Early checklist rerun against the final commit and deployment.
- [ ] Interview feedback addressed or documented as a tradeoff.
- [ ] Three required alert definitions and on-call responses are documented.
- [ ] CPU, memory, latency, and throughput baselines recorded.
- [ ] Load tests run at 10 and 50 concurrent users with p50/p95/p99 and errors.
- [ ] Actual development cost and 100/1K/10K/100K-user projections complete in
      `AI_COST_ANALYSIS.md`.
- [ ] Backup, restore, migration, rollback, and clean-deploy procedures tested.
- [ ] Residual risks and real-clinical-use limitations are explicit.
- [ ] Final 3–5 minute demo recorded and uploaded.
- [ ] Final live URL and repository commit tested.
- [ ] Social post published and linked.
- [ ] Final AI interview completed within its required window.
- [ ] Final submission completed before the portal deadline.

## Demo Proof Points

- [ ] Normal sourced pre-visit workflow.
- [ ] Multi-turn follow-up with more than one tool.
- [ ] Click-through to an original OpenEMR source.
- [ ] Honest missing-data response.
- [ ] Authorization denial before LLM invocation.
- [ ] Visible partial/fallback behavior during a tool failure.
- [ ] Correlation ID traced through the observability dashboard.
- [ ] Eval, load, latency, and cost results shown briefly.
