# Submission Checklist

This checklist supplements, rather than replaces, the official submission
portal. All deadlines are Central Time.

## Early Submission — Wednesday, September 16 at 11:59 PM

**Repository note (updated 2026-09-15):** GitLab
(`labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean`, branch
`main`) is the system of record and the URL to submit; owner decision,
pending instructor confirmation. `hdxsfbr/openemr-base-clean` on GitHub stays
a genuine fork of `Gauntlet-HQ/openemr-base-clean` for the PRD's literal
"forked from OpenEMR" requirement and is not kept in sync. The challenge
README is `README_AGENT_FORGE.md` at the repository root so it does not
conflict with OpenEMR's own `README.md`.

### Hard gates and repository

- [x] Public repository is based on the required OpenEMR fork. *(GitLab
      repository initialised from the `Gauntlet-HQ/openemr-base-clean` fork;
      OpenEMR history retained. 2026-09-16.)*
- [x] `README_AGENT_FORGE.md` contains deployed URL, setup, architecture
      overview, demo credentials, test commands, and limitations. *(2026-09-16.)*
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
- [x] `docs/REQUIREMENTS_TRACEABILITY.md` links requirements to current evidence.
      *(Refreshed 2026-09-16 against the eval run and the live deployment.)*

### Product and engineering

- [x] Deployed OpenEMR is accessible and contains demo data only.
      *(2026-09-15: `v0.1.0-skeleton` on a disposable `sslip.io` hostname;
      synthetic cohort and demo users only. Owned hostname pending.)*
- [x] Clinical Co-Pilot is embedded in the patient workflow. *(`v0.2.0-slice`:
      panel on the dashboard runs a full UC-01 turn on the deployment.)*
- [x] Multi-turn follow-up and tool chaining work in the live environment.
      *(2026-09-15: follow-up planned a note search and cited two notes.)*
- [x] Authorization is enforced for every retrieval. *(Parity gateway per
      tool call; per-role matrix evals still to record.)*
- [x] Every displayed factual claim passes verification and has a source.
      *(Verifier before render; `every_claim_cited` and `sources_resolve` on
      every live eval turn, 2026-09-16.)*
- [x] Correlation IDs connect UI, gateway, tools, LLM, verifier, and logs.
      *(`docs/operations/correlation-id-walkthrough.md` with a real turn.)*
- [x] Observability records order, latency, failures, tokens, and cost.
      *(Langfuse traces per turn, verified 2026-09-15.)*
- [x] Dashboard shows all PRD-required metrics. *(Langfuse dashboard
      "Clinical Co-Pilot": requests, p50/p95, errors, retries, tool calls,
      tool failures, tokens, cost; `docs/operations/langfuse-dashboard.md`,
      2026-09-16. Screenshot for evaluators still to attach.)*
- [x] Eval suite includes boundary, invariant, and regression cases. *(33
      cases, 33/33 after the DQ-HIGH-002 gateway fix, `evals/results/`.)*
- [x] `/health` and meaningful `/ready` endpoints pass expected tests.
- [x] Runnable API collection covers core endpoints. *(Bruno, 21/21 on the
      deployment 2026-09-16.)*
- [x] No credentials, tokens, session IDs, PHI, or private trace URLs are
      committed. *(Secret scan 2026-09-16: only OpenEMR's own bundled test
      key matched; secrets live in `~/.config/agentforge` and Docker
      secrets on the Droplet.)*

### Submission package

- [x] Live application URL tested from outside the development machine.
      *(Owner opened `https://openemr-137-184-4-22.sslip.io` from a phone on
      mobile data, 2026-09-16.)*
- [ ] Repository URL and exact commit recorded.
- [ ] Dashboard access or sanitized evidence prepared for evaluators.
- [x] Eval dataset and results included. *(`evals/cases/`, `evals/results/`.)*
- [ ] 3–5 minute demo recorded, reviewed, and uploaded.
- [ ] AI interview instructions confirmed.
- [ ] Technical interview scheduled within the required window.
- [ ] Submission completed with several hours of buffer.

## Final Submission — Sunday, September 20 at Noon

- [ ] Early checklist rerun against the final commit and deployment.
- [ ] Interview feedback addressed or documented as a tradeoff.
- [x] Three required alert definitions and on-call responses are documented.
      *(`docs/operations/alerts.md`, `agent/app/alerts.py`, 2026-09-16.)*
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
