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
      approved 2026-09-15; latency thresholds provisional until the load
      baseline; the cost gate was configured 2026-09-17 at the $0.0223
      projection, warn to $0.0446, block above.)*
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
      trace with its correlation id. Verification pass/fail rate and error
      rate are not on those nine panels; since 2026-09-17 every trace carries
      the `verification_passed` and `turn_error` scores and `/metrics` has
      `copilot_verification_total{outcome}`, and the two panels over the
      scores are an owner action in the Langfuse UI before the final
      capture.)*
- [x] Eval suite includes boundary, invariant, and regression cases.
      *(Release gate: `evals/results/2026-09-20T051146Z-0f11642.md`, the
      week1-final release run at `0f11642`, whose runtime tree is
      byte-identical to the deployed `c37b9e6`. 48 cases x 3 attempts, 123
      passed, every blocking gate PASS, golden set 29/29, citations 615/615
      resolved, model-backed p95 15.8 s, $0.0104 per model-backed turn, no
      5xx. The one miss, `CONF-DUP-NAMES-C2-001`, is a holdout-tier hedging
      flip that passed the other two attempts. Against the early-submission
      baseline (`…-0f11642-vs-a4a5856.md`): p95 24.1 s to 15.8 s, task success
      95% to 100%, cost $0.0127 to $0.0104, and `CONF-NOTE-VS-LIST-N-001`
      FAIL to pass.
      Suite shape: 48 cases on disk, one per cohort defect, in three tiers —
      a 29-case golden set with a blocking "Golden set integrity" gate, a
      12-case holdout tier, and behavioural coverage by category
      (`evals/README.md`). A full run's exit code follows the release gates;
      gates the runner cannot measure read NOT MEASURED, never PASS. Every
      results file opens with the KEY_METRICS gate table and a scorecard.
      Flakiness is confined to model wording: `MISS-AUTHOR-J-001`,
      `CONF-NOTE-VS-LIST-N-001` and `CONF-DUP-NAMES-C2-001` have each flipped
      run to run, while every deterministic assertion has passed every time.
      History kept in `evals/results/`: 44/45 at `a4a5856` (the early
      submission), 44/44 at `a7641e9`, 114/116 over a same-commit `--repeat 3`
      at `1ddf824`, and `2026-09-20T041411Z-6c787bd.md`, the run that failed
      `ISO-RECENT-PATIENT-RESUME-001` three times of three and exposed the
      split-clock regression.)*
- [x] `/health` and meaningful `/ready` endpoints pass expected tests.
      *(`agent/tests/test_health.py`: liveness echoes or mints the correlation
      id, `/ready` is 503 when a dependency fails and 200 when all pass; runs
      in CI `test:agent`; Bruno `4 Health` requests against the deployment.
      OpenEMR's own `readyz` stays unrouted by design. `/ready` probes the
      tracer since 2026-09-17 (`GET /api/public/projects` on the Langfuse host
      with basic auth, 5 s timeout; `test_ready_is_503_when_tracer_unreachable`),
      and the three network checks run concurrently. The traceability row
      stays "In progress" until the M3 deploy shows `tracer: reachable` on the
      Droplet. The panel probes `/health`, not `/ready`
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
- [x] Three required alert definitions, on-call responses, and working delivery.
      *(`docs/operations/alerts.md`, `agent/app/alerts.py`, 2026-09-16.
      Scheduled on the host by the `alerts` service in
      `infra/digitalocean/runtime/compose.yaml` every 300 s. Delivery to Slack
      proven end to end 2026-09-20: five faulted turns produced two `page`
      alerts with exact denominators (5 of 5 medications calls, 5 of 35 tool
      calls) and both landed in the channel. Proving it found two defects —
      the tool-failure numerator was structurally zero after the
      batched-gateway change, and the first delivery failed on Slack's payload
      shape — both fixed and regression-tested
      (`docs/audit/evidence/observability/alerts-slack-2026-09-20.log`). The
      webhook URL is a Docker secret, never argv, never in the repository.)*
- [x] CPU, memory, latency, and throughput baselines recorded.
      *(`docs/audit/evidence/performance/baseline-2026-09-18.md`, sampled every 5 s by
      `docs/audit/scripts/droplet-stats.sh` during each load level; CSVs in
      `evals/load/results/`. Idle: `openemr` 0.6%/6.3% CPU, 11 httpd procs, 1,195 MiB
      host memory. At 50 users `openemr` peaks 103.2% and `database` 111.0% — each
      alone past a full vCPU — while `agent` never exceeds 43.7%; 58 httpd procs,
      150 MariaDB connections, `load1` 24.47. Throughput 13.5 turns/min at 10 users,
      32.2 at 50. Memory was never the constraint, so ADR-0001's 8 GiB fallback
      trigger did not fire. Measured before the batched-gateway, low-effort-follow-up
      and brief-on-open changes; the bottleneck they identify is structural and
      unchanged, the absolute numbers are not re-measured.)*
- [x] Load tests run at 10 and 50 concurrent users with p50/p95/p99 and errors.
      *(Run 2026-09-18 against the live Droplet; `docs/audit/evidence/performance/load-test-2026-09-18.md`,
      raw JSON in `evals/load/results/`. Real model, 10 users: turn p50 18.8 s, p95 45.0 s,
      p99 45.1 s, 10.0% errors (both 504 on AF-HEAVY), 90% of turns complete. 50 users:
      p50 8.3 s, p95 43.8 s, p99 45.0 s, 5.6% errors, and the share that matters —
      18.3% complete, 76.1% partial — because latency alone is gamed by degrading early.
      A `--fault model` control run making zero model calls reproduced the same shape
      (chart-open p95 46.15 s, 97.7% tool-gateway unavailability), which puts the ceiling
      in OpenEMR's Apache/PHP and MariaDB rather than in the agent or the provider.
      Both levels contradict the provisional 30 s p95 threshold in `KEY_METRICS.md`
      under concurrency; the single-user figure still meets it.)*
- [x] Actual development cost and 100/1K/10K/100K-user projections complete in
      `AI_COST_ANALYSIS.md`. *(Part A recounted at the final commit 2026-09-20:
      151 commits over 10 days, ~$5 of infrastructure, $23-$32 of model calls of
      which the largest single line is the droplet-tier capacity test, not the
      product. Part B has the measured per-turn cost and the per-tier
      "what breaks first" table grounded in the load data.)*
- [x] Backup, restore, migration, rollback, and clean-deploy procedures tested.
      *(Rehearsed end to end 2026-09-18 on a throwaway `s-2vcpu-4gb` at `146.190.154.222`
      in its own Terraform workspace, never against the live host; timings table in
      `docs/deployment/digitalocean.md` "Rehearsal Runbook". Clean deploy 2m36s, demo-seed
      plus a 14/14 golden run 3m10s, `backup.sh` 15s, rollback to tag `week1` 2m36s
      (14/14 golden there too), roll forward 1m13s, `restore.sh` 3m19s, destroy 25s.
      The restore was proven to actually restore rather than no-op: a conversation created
      after the backup came back `Unknown conversation.` afterwards. Two real bugs were
      found and fixed in the process — `deploy.sh`'s bootstrap wait was too short, and
      `push-secrets.sh` failing silently inside `deploy.sh` had deployed once with both
      `llm_provider` and `tracer` unconfigured. Destroy left the account at its
      pre-rehearsal resource count. Migration is not applicable: the co-pilot is read-only
      and owns no schema beyond the module's registration.)*
- [x] Residual risks and real-clinical-use limitations are explicit.
      *(`AUDIT.md` §9 Residual Risk, the Known Limitations section of `ARCHITECTURE.md`,
      the limitations block in `README_AGENT_FORGE.md`, and — new for the final —
      "Known gaps at submission" in `docs/INTERVIEW_NOTES.md`, which states the gaps an
      evaluator could find before they find them: load and baseline numbers measured
      before three later performance changes, two dashboard panels still to build, the
      two gates that read NOT MEASURED by design, tickets not single-use, the 24-hour
      purge unimplemented, unrestricted egress accepted for Week 1, and the disposable
      hostname. Every document repeats the same sentence: demo system, synthetic data
      only, not for real PHI, not HIPAA-certified.)*
- [ ] Final 3–5 minute demo recorded and uploaded. *(Script `docs/DEMO_SCRIPT.md`
      is ready to record from as of 2026-09-20: no placeholders remain, every
      number in it is measured, the three beats that pointed at evidence files
      which were never written now point at the real ones, and the release-run
      figures are in. Owner action.)*
- [x] Final live URL and repository commit tested. *(2026-09-20:
      `/copilot-api/health` reports 0.3.0 and `/copilot-api/ready` returns all
      five dependencies ok including the tracer; `session.php` serves
      `module_version` 0.5.0 and `brief_on_open` true for the walkthrough
      patients; the release run executed 48 cases x 3 against this host. Both
      remotes are at `90b7e4b` with tag `week1-final`. Owner still to repeat
      the from-a-phone check.)*
- [ ] Social post published and linked. *(Draft `docs/SOCIAL_POST.md`, LinkedIn
      and X versions, numbers refreshed to the release run 2026-09-20; the X
      version is 252 characters with the video URL counted. Links the public
      GitHub fork, never the GitLab. Only `<final video URL>` is left to fill,
      once the video exists. Owner action.)*
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
