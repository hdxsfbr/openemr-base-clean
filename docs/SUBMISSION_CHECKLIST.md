# Submission Checklist

This checklist supplements, rather than replaces, the official submission
portal. All deadlines are Central Time.

## Early Submission — Wednesday, September 16 at 11:59 PM

**Repository note (updated 2026-09-17):** GitLab
(`labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean`, branch
`main`) is the system of record and the URL to submit; owner decision,
pending instructor confirmation. `hdxsfbr/openemr-base-clean` on GitHub stays
a genuine fork of `Gauntlet-HQ/openemr-base-clean` for the PRD's literal
"forked from OpenEMR" requirement. Both remotes are in sync: `gitlab/main`
and `origin/main` are both at `e1dd331`, and the `week1` tag (tag object
`c7253ed`) points at that commit. The challenge README is
`README_AGENT_FORGE.md` at the repository root; `README.md` itself now opens
with a 49-line challenge header above OpenEMR's own README (upstream content
resumes at line 51).

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
      tool call; per-role evidence recorded 2026-09-16: `AUTH-FRONTDESK-001`
      asserts every clinical section `unavailable` for Front Office, the nine
      authorization cases pass in every recorded run in `evals/results/`, and
      `bin/acl_matrix.php` prints the effective per-user matrix.)*
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
      2026-09-16. Evaluator screenshots are attached:
      `docs/audit/evidence/observability/` holds the nine panel renders, two
      full-page dashboard captures, a trace-view capture, and one exported
      trace with its correlation id.)*
- [x] Eval suite includes boundary, invariant, and regression cases. *(Release
      gate: latest full run `evals/results/2026-09-17T024919Z-a4a5856.md` at
      a4a5856, all 45 cases, 44 passed, every blocking gate PASS, Golden set
      integrity 14/14 for the first time, citations 177/177 resolved,
      model-backed p95 24.1 s, $0.0127 per model-backed turn; the one miss,
      CONF-NOTE-VS-LIST-N-001, is a model-recall check under the non-blocking
      task-success gate, which still reported PASS at 95%. Two recall checks
      flip run to run: MISS-AUTHOR-J-001 (missed at 1ddf824 attempts 1 and 3,
      and at 69560f05) and CONF-NOTE-VS-LIST-N-001 (missed at a4a5856); the
      deterministic lines passed every time. Kept as stability history: the
      same-commit `--repeat 3` report
      `evals/results/2026-09-16T073141Z-1ddf824` at 1ddf824, 44 cases x 3
      attempts, 114/116, every blocking gate PASS on all attempts, citations
      528/528 resolved, model-backed p95 27.6 s. Gates the runner cannot
      measure read NOT MEASURED, not PASS. 45
      cases on disk since 2026-09-16 (`CIT-PARAPHRASE-ADVICE-001` added with
      the widened advice lexicon),
      one per cohort defect; a 14-case golden tier with a blocking "Golden
      set integrity" gate and a 4-case holdout tier (`evals/README.md`); a
      full run's exit code follows the release gates. Every results file
      opens with the KEY_METRICS release-gate table and a quality scorecard.
      Seven full single runs on 2026-09-16 after the sweep fixes (41, 43, 43, 43, 43, 41, then 44 of 44); every earlier failure was either an assertion stricter than the required behavior, corrected, or a real gap fixed the same day (lab result with no unit, vague rejection details, model called on a denied turn, analyte-with-code match, same-day comparison as a trend, field-level absences); final single run `evals/results/2026-09-16T054701Z-a7641e9` at commit a7641e9: 44/44, every release gate PASS, citations 169/169, model-backed p95 23.3 s, $0.012 per turn. `evals/results/`.)*
- [x] `/health` and meaningful `/ready` endpoints pass expected tests.
      *(`agent/tests/test_health.py`: liveness echoes or mints the correlation
      id, `/ready` is 503 when a dependency fails and 200 when all pass; runs
      in CI `test:agent`; Bruno `4 Health` requests against the deployment.
      OpenEMR's own `readyz` stays unrouted by design. The traceability row is
      still "In progress" for a second reason: `/ready`'s tracer entry is
      presence-only — `check_tracer` (`agent/app/readiness.py`) reads the two
      Langfuse key files and sends no request, so an unreachable tracer still
      reports ready. The panel probes `/health`, not `/ready`
      (`public/assets/js/copilot.js:485`).)*
- [x] GitLab pipeline green on the submitted commit. *(Pipeline 23777 on
      3415bac, 2026-09-16: four lints, agent tests, offline evals green on the
      dedicated runner Droplet; the manual `test:evals-live` job (job 76210)
      ran all 44 cases against the deployment, 44/44, no blocking gate failed,
      results attached as an artifact. Root cause of "no pipelines" was the
      lab account's unconfirmed email; `docs/deployment/digitalocean.md`
      "CI Runner".)*
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
- [x] Repository URL and exact commit recorded. *(Early submission: commit
      `e1dd331`, tag `week1` — the tag object is `c7253ed`, which is not a
      commit sha. The commit is dated 2026-09-16 19:52 PT and the tag was
      written 2026-09-16 21:52 CT (`git cat-file -p week1`); `gitlab/main`
      and `origin/main` are both at `e1dd331`.)*
- [x] Dashboard access or sanitized evidence prepared for evaluators.
      *(`docs/audit/evidence/observability/`: the nine Clinical Co-Pilot
      dashboard panels rendered from the live page and one full trace export
      with its correlation id, PHI-checked, 2026-09-16. The Langfuse project
      itself stays private.)*
- [x] Eval dataset and results included. *(`evals/cases/`, `evals/results/`.)*
- [x] 3–5 minute demo recorded, reviewed, and uploaded. *(Early demo,
      2026-09-16: <https://youtu.be/oxm9xqJpiY8>; script `docs/DEMO_SCRIPT.md`.)*
- [x] AI interview instructions confirmed. *(Prep: `docs/INTERVIEW_NOTES.md`
      answers every question in the PRD's pre-search checklist with evidence
      pointers, 2026-09-16.)*
- [x] Technical interview scheduled within the required window. *(2026-09-17,
      12:00 PT, with Byron.)*
- [x] Submission completed with buffer. *(The submitted tag `week1` was
      written 2026-09-16 21:52 CT, about two hours before the 11:59 PM CT
      deadline — buffer, though not "several hours". The owner's portal
      confirmation time is not recorded in this repository.)*

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
