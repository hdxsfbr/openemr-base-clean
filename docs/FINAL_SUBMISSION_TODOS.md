# Final Submission TODOs (Sunday 2026-09-20, 12:00 CT)

Written 2026-09-17 against HEAD `e1dd331` (tag `week1`). Every item was
checked against the files at that commit, not against what the docs say;
several docs are stale and the refresh table at the end lists them.

**What the early submission delivered.** A deployed read-only co-pilot inside
OpenEMR at `https://openemr-137-184-4-22.sslip.io`, a 45-case eval suite with
a committed full run (`evals/results/2026-09-17T024919Z-a4a5856.md`: 44/45,
every blocking gate PASS, model-backed p95 24.1 s, $0.0127 per turn), Langfuse
tracing, `/metrics`, three alert rules, a 21-request Bruno collection, and the
five hard-gate documents.

**What the final adds (PRD p.4, p.9).** A production-ready agent, a final
3 to 5 minute demo video, a social post tagging @GauntletAI, and an AI
interview within 24 hours of submission. Four graded engineering
requirements are open at HEAD: load tests at 10 and 50 concurrent users;
CPU, memory, latency and throughput baselines under those scenarios;
completion of `AI_COST_ANALYSIS.md` (Part A stops at 2026-09-15, the cost
gate reads NOT CONFIGURED, no per-tier architecture section); and the
backup, restore and rollback rehearsal (`docs/SUBMISSION_CHECKLIST.md:131`).

**Rules this list respects.** No OpenEMR fixes. ADR-0002, 0003 and 0004
stay settled. Evals before tuning: no model, prompt, effort or planning
change without a baseline and `evals/compare.py`, and none during the final
sprint. The early-submission deployment is not touched on Thursday.

**Priority key.** P0: the submission is incomplete or a graded requirement
is unmet without it. P1: graded quality, an explicit checklist item, or
interview defensibility. P2: only with slack; otherwise write the
limitation. Effort: S under 2 h, M 2 to 5 h, L over 5 h.

**Schedule reality.** The full P0 plus P1 set is about 100 hours of listed
work against roughly 35 to 45 hours of owner time. The P0 set fits. Use the
cut order at the end of this file; do not stretch the Saturday freeze.

---

## Thursday 2026-09-17 (interview day: docs, tests and local work only; no deploy)

The technical interview with Byron is 12:00 to 12:15 PT. Only two things
land before it. Everything else is after 12:30 PT.

### Before 12:00 PT

- [ ] **Write the twelve-question answer sheet in `docs/INTERVIEW_NOTES.md`** (P0, M)
  Why: PRD p.10 "Interview Preparation" (audit, architecture, evaluation,
  production thinking). State: `docs/INTERVIEW_NOTES.md` answers the
  Appendix checklist only; none of the twelve questions has a written
  answer, and the three Production Thinking questions have none anywhere.
  Do: a top section with a 3 to 5 sentence answer and an `Evidence:`
  pointer per question; the 300-user derivation (about 60 concurrent turns
  and about 140 gateway calls against a 6-wide semaphore in one uvicorn
  process with a SQLite checkpointer in a local state dir, so scale is a
  second agent container with a shared checkpointer, never `--workers N`);
  one committed worst failure mode (ADR-0006 §114-117); a dated
  "deployed today versus planned" table (edge allowlist, file secrets,
  `/ready` with presence-only tracer check, alerts run on demand, no
  rollback rehearsal, no backups, no egress restriction, no load test, no
  verification pass/fail panel, cost gate NOT CONFIGURED, agent-level
  denials without an OpenEMR audit row, `CONF-NOTE-VS-LIST-N-001` miss,
  journal unreviewed). Fix the four overclaims in the notes (:41-42 "streams
  in about 1 s" while TTFE is NOT MEASURED; :143-145 and :275-276 alerts job
  in present tense; :277-280 rollback stated as established; :113-114 cost
  "acceptable against the projection" with no threshold).

- [ ] **Fix the three one-line checklist errors** (P1, S)
  `docs/SUBMISSION_CHECKLIST.md:119` reads `- [HAHAHA] Submission completed
  with several hours of buffer.` (commit d6606ac); write "- [x] Submission
  completed (portal confirmation 2026-09-16 21:59 CT, commit e1dd331, tag
  `week1`)". Add the commit at :105. Delete "Screenshot for evaluators still
  to attach" at :64 (screenshots are committed under
  `docs/audit/evidence/observability/`).

Keep the live panel logged in as `audit-physician` on AF-DQ-A2 and the
Langfuse trace list open during the interview. Ask Byron which repository
URL is graded (GitLab or the GitHub fork) and record the answer at
checklist :8-15.

### After the interview (12:30 PT onward)

- [ ] **Record the early-submission AI video interview, hard stop Thu 19:59 PT** (P0, S)
  Why: PRD p.4 "AI Interview required 24 hours after submission" and the
  GATE note that interviews are required for admission. State: the email
  "Video Interview Ready: Week 1: Early Submission" from
  support@rs.gauntletai.com arrived 2026-09-17 02:59 UTC (Wed 19:59 PT) and
  is still unread; the portal confirmed the submission at 21:59 CT, so the
  24-hour window closes Thursday about 19:59 PT. Do: about 16:00 to 17:00
  PT after the doc fixes below, in Chrome, camera and mic tested, roughly
  75 s per question (four questions, 5 to 6 minutes total), with the answer
  sheet, `README_AGENT_FORGE.md` and the a4a5856 report on a second screen.
  Then tick a new line under checklist :116 with the time.

- [ ] **Create `docs/INTERVIEW_FEEDBACK.md` and fill it within an hour of the interview** (P1, S)
  Why: checklist :124 "Interview feedback addressed or documented as a
  tradeoff". Do: decision rule at the top (docs-only dispositions land by
  Friday; any code change goes through baseline run, change, full run,
  `evals/compare.py`, deployed only after the golden set passes; nothing
  touching gateway, verifier, prompt or model merges after Saturday's
  release run) and one row per question (question, answer given, gap
  admitted, disposition, evidence). Tick :124; set
  `docs/REQUIREMENTS_TRACEABILITY.md:40` to "held 2026-09-17".

- [ ] **Tell evaluators where the demo password comes from; stop pointing them at SSH** (P0, S)
  Why: PRD p.9 "the agent must work in the live environment" and p.8
  "Graders must be able to run any workflow from this collection without
  reading source code"; Byron said in #help (2026-09-16) that the
  submission form has username and password fields. State:
  `README_AGENT_FORGE.md:38-46` and :166-172, `docs/api-collection/README.md:7-13`
  and `collection.bru:14-18` give only the `ssh deployer@... cat` path;
  checklist :22-23 ticks "demo credentials" although only usernames are in
  the README. Do (docs only): "Evaluators: the `audit-physician` password
  is in the submission form (`audit-frontdesk` shares it); operators read it
  over SSH as below"; add the Bruno app and CLI paths
  (`bru run --env deployed --env-var DEMO_PASSWORD=<value>`, expected 21
  requests, 14 tests, 41 assertions); reword checklist :22-23. Never commit
  the value; rotate only after grading (re-seeding does not rotate it:
  `seed_users.php:6` skips existing users).

- [ ] **Doc refresh rows 1 to 6: latest run, both flaky cases, deployed tag** (P1, S)
  Why: PRD p.9 "Eval Dataset: your test suite with results"; AGENTS.md
  evidence gate; interview question "What did you find when you ran it?".
  State: the a4a5856 run exists at HEAD, but `KEY_METRICS.md`,
  `README_AGENT_FORGE.md`, the traceability matrix, `PROJECT_PLAN.md`,
  `INTERVIEW_NOTES.md`, `AUDIT.md` and `ARCHITECTURE.md` still say no
  45-case run exists, cite 1ddf824 or a7641e9, say "nine reports", or name
  `MISS-AUTHOR-J-001` as the only flaky case (`CONF-NOTE-VS-LIST-N-001`
  flipped in a4a5856). Several docs also say tag `v0.2.0-slice` is live;
  the host runs the tree of commit e1dd331 (tag `week1`; agent, module and
  infra unchanged since 831e1d8). Do: one docs commit from rows 1 to 6 of
  the refresh table. Add a risk-acceptance note to `KEY_METRICS.md`
  "Current status" (task success 95%; the two cases; causes: a follow-up
  conflict claim may omit the entity named in the question; no authorship
  claim type; fix in Week 2 with contract 1.3.0). Change
  `README_AGENT_FORGE.md:54` so AF-DQ-N no longer promises "the answer
  cites both" and name AF-DQ-A2's amlodipine conflict as the deterministic
  example. Do not tune the prompt for this case.

- [ ] **Doc refresh rows 7 to 18: claims the code contradicts** (P1, S)
  Why: AGENTS.md "Never describe a planned safeguard as implemented";
  interview question on trust boundaries. Verified at HEAD: no CSP exists
  (`INTERVIEW_NOTES.md:218`); ViewEvent dispatch is not implemented
  (ADR-0002:74-76, `AUDIT.md:741`); no "parity limitation" LimitationKind
  exists (ADR-0002:108, cohort README:92, `ARCHITECTURE.md:225-232`);
  `ConversationRepository::purge()` is `sweep()` with no caller and the
  24 h retention is a design target (`ARCHITECTURE.md:469`, :741-742);
  no code emits denial reason `unsupported_principal` (`KEY_METRICS.md:41`,
  :81, ADR-0002:88); the gateway validates params with a hand-written
  allowlist, not the JSON Schema files (ADR-0004:159-161,
  `ToolRegistry.php:37`); traceability row 25 says HIPAA handling
  "implementation not started"; row 34 blames "readyz unrouted" instead of
  the presence-only tracer check (`readiness.py:73-76`); two isolation
  invariants are called "tested" with no case (`ARCHITECTURE.md:482-487`);
  no source registry exists (:438-439); no PSR-3 per-call gateway log line
  exists (:588-590); "Open Items Before the Vertical Slice (2026-09-15)"
  (:840) is stale; fault injection is on by default on the demo host
  (`compose.yaml:143`, contradicting :838-839); notes cover Clinical Notes
  only, not SOAP (`README_AGENT_FORGE.md:246-247`); `/metrics` is public
  by choice, not "internal only" (`ARCHITECTURE.md:624`, ADR-0007 decision 6).
  Do: one docs pass; move Open Item 9 (agent-level denials) and the
  retention bullet into Known Limitations; comment-only edit to the
  `ToolRegistry.php` docblock, no rebuild.

- [ ] **Review the 20-trace error-analysis journal and record the issue list** (P1, M)
  Why: PRD p.10 "What did you find? What would you add next?";
  `evals/README.md` says finding the issue is not delegable. State: all 20
  "First issue" and "Notes" fields in
  `evals/error_analysis/2026-09-16T190727Z-journal.md` are blank. Visible
  clusters: traces 5 and 9 ("When did we last see them?") ended partial with
  a withheld statement because no encounter-date claim type exists; trace 18
  (blood pressure, no vitals tool) emitted no out-of-scope limitation;
  traces 8, 10, 15 and 20 ran 30 to 39 s with 4 to 5 model calls. Do:
  `agent/.venv/bin/python evals/review_ui.py` (offline), fill all 20, run
  `evals/error_analysis.py report`, commit the journal with a footer of
  issues and categories, and change the three "unreviewed" sentences
  (`evals/README.md:197-199`, `PROJECT_PLAN.md:208-211`,
  `INTERVIEW_NOTES.md:292-294`). Do not change the agent or prompt.

- [x] **Set the cost-per-turn release threshold and wire the eval gate** (P1, S) — done 2026-09-17 (M2 WS-EVAL E1: `evals/run.py` `COST_PER_TURN_PROJECTION_USD`, `cost_gate()`; AI_COST_ANALYSIS.md basis and daily-budget paragraphs via the doc-apply pass)
  Why: `KEY_METRICS.md:27` and :91 promise a threshold "with the first
  measured token mix"; every report up to `a4a5856` prints NOT CONFIGURED (the hard-coded row, `evals/run.py:647` at that commit); since 2026-09-17 the row is judged by `cost_gate()` and a full run prints a real state.
  Do: `COST_PER_TURN_PROJECTION_USD = 0.0223` beside `PRICE_PER_MTOK`
  (run.py:141); gate PASS at or under $0.0223, warn between 1x and 2x with
  risk acceptance, block above $0.0446; keep NOT CONFIGURED only when there
  are no model-backed turns. Explain in `AI_COST_ANALYSIS.md` (after line
  84) why the basis is $0.0223 and the eval mix measures $0.0127 (four
  post-deploy turns at about 1,950 output tokens versus about 1,170 in the
  eval mix; no setting changed). Define the daily budget from the
  2,000,000-token halt (about 1,100 turns, about $14 per day warn, $42 page)
  at `KEY_METRICS.md:91`. Update `KEY_METRICS.md:27`, :74,
  `README_AGENT_FORGE.md:122`, :266, `evals/README.md:52`,
  `INTERVIEW_NOTES.md:113-114`, `DEMO_SCRIPT.md:26` ("between one and two
  cents a turn"). Verify with `--offline-only` and `--golden-only`. Must
  land before the final full run.

- [ ] **Decide the `CONF-NOTE-VS-LIST-N-001` matcher and record it as a scope decision** (P1, S)
  State: in a4a5856 the conflict claim was verified and cited both tables
  but its text lacked "atorvastatin", so only the claim-text regex
  (run.py:185) failed; 11 of 12 recorded runs pass the strict matcher. Do:
  either keep the assertion and record the miss as a wording miss in the
  risk-acceptance note, or replace `text: atorvastatin` with
  `kind: note_vs_list` in `claims_include` (keep `type: conflict`,
  `tables_all` and the turn-level drug-name check) and record that in the
  case `risk:` line and `evals/README.md`. Never a silent loosening. Verify
  with `evals/run.py --case CONF-NOTE-VS-LIST-N-001 --repeat 3` (about $0.10).

- [ ] **Renew the api-scope GitLab PAT and take the write token out of the remote URL** (P1, S)
  State: the PAT file at `~/.config/agentforge/gitlab_pat` is expired
  (`personal_access_tokens/self` returns "Token is expired"); the `gitlab`
  remote URL embeds a `write_repository` token (valid to 2026-10-14) that
  every `git remote -v` prints. Pushes still work, so Sunday is not at risk.
  Do: create a PAT with `api` and `write_repository` (expiry 2026-10-10 or
  later) into the same file (mode 600); `git remote set-url gitlab
  https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean.git`;
  `git config credential.helper 'store --file ~/.config/agentforge/git-credentials'`,
  enter the token once, `chmod 600` that file, `git push --dry-run gitlab
  main`; revoke the old token; name the PAT file (never its value) in
  `docs/deployment/digitalocean.md` "CI Runner". Then confirm the pipeline
  for e1dd331 is green and replace pipeline 23777 / 3415bac at checklist
  :86-92 (the pipeline shows "blocked" until the manual `test:evals-live`
  job is played; play it Thursday or Friday if a CI artifact is wanted,
  about $0.55 and 12 minutes, never during Saturday's load tests).

- [ ] **Record the scope decision that closes `PROJECT_PLAN.md:221-227`** (P2, S)
  Replace the Thursday-Friday "deepen UC-02, note-level citations,
  injection hardening" lines with a dated decision: UC-02 runs (Bruno
  `2 Use Cases/03`, `ISO-FOLLOWUP-CHAIN-001`); no further deepening in
  Week 1; the two isolation cases land Friday or are listed under
  `evals/README.md` "Not automated in Week 1". Otherwise Sunday's ticking
  is silent scope narrowing (`KEY_METRICS.md:55-56` forbids it).

- [ ] **Close the owned-hostname item as an accepted limitation** (P2, S)
  The sslip.io name with valid TLS meets PRD Stage 2; the hostname is
  hard-coded in 14 files and every eval report stores it, so a change
  breaks comparability with a4a5856. Write the sentence under "Document as
  limitation" and do not attempt DNS this week.

---

## Friday 2026-09-18 (build day: one agent deploy batch, harness, rehearsal prep)

Order: (1) tests and harness work that never touches the deployment; (2)
one agent code batch, deployed once with `infra/digitalocean/deploy.sh`
and followed by `evals/run.py --golden-only`; (3) load driver and infra
scripts; (4) doc drafts with placeholders. Keep the Caddy-stuck-in-Created
recovery command (`docs/deployment/digitalocean.md:349-357`) at hand.

### Must land Friday (PRD-graded or prerequisites of Saturday)

- [ ] **Confirm model-provider credit and Langfuse unit headroom** (P1, S; first thing)
  Why: `readiness.py:57-70` probes the provider with `models.retrieve`,
  which succeeds with zero credit, so `/ready` stays green while every
  graded turn falls back to "Records only". Saturday spends about $5 of
  model budget plus grading traffic. Do: confirm remaining credit or the
  monthly cap covers about $10 with margin; confirm Langfuse units used
  plus about 300 turns x 12 units stay under the 50K Hobby limit; write
  both numbers (never keys) with the date into `digitalocean.md` "Current
  Deployment"; recheck Sunday 06:30 PT. Top up Friday, not Saturday.

- [ ] **Make `/ready` probe Langfuse reachability with the configured keys** (P0, S)
  Why: PRD p.8 "/ready must actually check that OpenEMR, the LLM provider,
  and the observability backend are reachable". State:
  `agent/app/readiness.py:73-76` returns "configured" when the two key files
  are non-empty and sends no request; gateway and LLM checks are real
  probes; no test covers a tracer-unreachable state. Do: make
  `check_tracer` async; keep `not_configured` when a key is absent;
  otherwise `GET {langfuse_host}/api/public/projects` with basic auth,
  5 s timeout, 200 means reachable, other status `http_<code>`, `HTTPError`
  its class name; gather the three checks; add
  `test_ready_is_503_when_tracer_unreachable`; update `ARCHITECTURE.md:555`,
  :558 (the panel probes `/health`, `copilot.js:485`, not `/ready`), :629,
  ADR-0007:119-122, traceability row 34, checklist :80-85, `alerts.md:99-102`.

- [ ] **Ship the Friday agent batch (cut line applied)** (P1, M)
  Why: PRD p.8 dashboard minimum names "verification pass/fail rate",
  "queue depth" and "error rate"; correlation ID in every log entry; alert
  correctness. State: `main.py:62-69` increments `copilot_in_flight` for
  every request including the 30 s healthcheck; `api.py:110-115` computes
  `Verification.outcome` but never exports it and the nine Langfuse panels
  have no verification or error-rate panel (`langfuse-dashboard.md:20-30`);
  `telemetry.py:146`, :165 and `model.py:265` log without the correlation
  id; `alerts.py:20-23` counts `forbidden` denials as tool failures (in
  a4a5856, 6 of the 7 `unavailable` results were `forbidden` from
  `AUTH-FRONTDESK-001`, a burst above the page threshold). Do, in one
  branch with tests (`cd agent && pytest -q && python -m app.contracts.export --check`),
  then `evals/run.py --offline-only`, deploy, `--golden-only`:
  (a) `agent/Dockerfile` pins `--workers 1` with a comment naming the
  process-local structures (metrics, limiter, breaker, daily halt,
  SQLite checkpointer);
  (b) `copilot_turns_in_flight` incremented around `graph.ainvoke` and the
  SSE generator, decremented in `finally`, test that `/health` leaves it 0;
  (c) `score_trace("verification_passed")` and `score_trace("turn_error")`
  in `finish_turn_trace`, `copilot_verification_total{outcome}` in
  `/metrics`, two Langfuse widgets (verification pass rate, turn error
  rate), panels re-rendered into `docs/audit/evidence/observability/`;
  (d) pass `correlation_id` explicitly into the two telemetry warnings and
  the `model.py:265` info line (no ContextVar, no PHP change);
  (e) `copilot_tool_calls_total{tool,status,reason}` with a bounded reason
  set; `forbidden` excluded in `evaluate_tool_failure_rate`; test with six
  forbidden among 40 not warning; remove the known-gap paragraphs at
  `alerts.py:20-23`, `alerts.md:141-145`, `README_AGENT_FORGE.md:206-212`.
  Deferred to Week 2 with one sentence each: single-use tickets
  (ADR-0005:139-140 reworded "not enforced; a ticket is valid for 90 s"),
  the correlation ContextVar, the module `error_log` calls. Update
  `ARCHITECTURE.md:574-579` (scale-out is a second container with a shared
  checkpointer, never uvicorn workers), :599-602, `KEY_METRICS.md:32-39`,
  traceability row 30, checklist :61-64, `INTERVIEW_NOTES.md:43-45`.

- [ ] **Schedule the alert evaluator as a compose service in the same deploy** (P1, S)
  State: `alerts.py`, `alerts_cli.py` and 26 tests exist; nothing in
  `compose.yaml`, cloud-init, `start.sh` or `deploy.sh` runs it. Do: an
  `alerts` service (`image: agentforge/copilot-agent:local`,
  `python -m app.alerts --url http://agent:8080/metrics --ready-url
  http://agent:8080/ready --state /var/lib/copilot/alerts-state.json
  --interval 300`, `agent_state` volume, `frontend` network,
  `restart: unless-stopped`, `healthcheck: {disable: true}` because the
  inherited Dockerfile HEALTHCHECK would stall `docker compose up --wait`
  in `start.sh:63`); `docker compose config --quiet`; confirm heartbeat
  lines in `docker compose logs alerts`. Update `ARCHITECTURE.md:606-612`,
  :78-80, ADR-0007:116-118, `alerts.md` "Running the job", traceability row 31.

- [ ] **Pin the agent's Python dependencies from the running container** (P1, S; before the batch deploy)
  State: `agent/pyproject.toml:8-20` has lower bounds only; no lock file;
  `start.sh:62` runs `docker compose build --pull` on every deploy; CI
  installs unpinned; ADR-0004:145 says "pinned". Do:
  `ssh deployer@137.184.4.22 'cd /opt/agentforge && docker compose exec -T agent pip freeze' | grep -v '^agentforge-copilot-agent' > agent/requirements.lock`;
  Dockerfile installs `-r requirements.lock` then `pip install --no-deps .`;
  CI the same with `'.[dev]'`; fresh venv from the lock passes the tests and
  `export --check`; ADR-0004 status line; refresh procedure in `agent/README.md`.

- [ ] **Make `start.sh` recover a Caddy left in Created state and fail loudly** (P1, S; log rotation P2)
  State: `start.sh:61-63` is one `docker compose up --detach --wait
  --wait-timeout 600` with no post-check; `caddy` depends on `openemr`
  healthy with a 180 s start period; no `logging:` block on any service.
  Do: after :63 add `docker compose up --detach --wait --wait-timeout 120 caddy`,
  then `docker compose ps` and exit non-zero if database, openemr, agent,
  caddy or alerts is not running, then a `curl --fail
  https://${public_hostname}/meta/health/livez` retry loop (6 x 10 s); add
  an `x-logging` anchor (`json-file`, `max-size: 10m`, `max-file: 3`) on
  every service; validated by the rehearsal deploy; `digitalocean.md:358`
  says automated.

- [ ] **Build the load driver and the Droplet sampler; smoke at 2 users** (P0, L; the build half)
  Why: PRD p.9 load tests at 10 and 50 concurrent users with p50/p95/p99 and
  error rate, and baselines under those scenarios. State: nothing exists;
  only serial latencies (a4a5856 scorecard, n=40). Do:
  `evals/load/run_load.py` (asyncio plus `httpx.AsyncClient`, no new
  dependency) porting the six-step handshake from `evals/run.py:63-119`
  `Session`; each virtual user logs in as `audit-physician` or `physician`,
  opens AF-DQ-A2 900001 / AF-DQ-N 900018 / AF-HEAVY 900023, times chart
  open, `session.php`, start, mint, UC-01 turn, mint, one follow-up;
  `--users`, ramp about 30 s, `--label`, `--fault model` (capacity without
  provider limits); at 1 and 10 users also send the first turn with
  `Accept: text/event-stream` and record time to `event: evidence`; write
  `evals/load/results/<UTC>-<sha>.json` with a fixed schema (per level and
  scenario p50/p95/p99 for chart open, ticket and turn; error rate split by
  5xx, 504, 429, transport, denials; status share complete/partial/fallback/
  failed; tool `unavailable` count by reason from `copilot_tool_calls_total`
  deltas). `docs/audit/scripts/droplet-stats.sh` (read-only over SSH, 5 s
  samples to CSV): `docker stats --no-stream` for openemr, database, agent,
  caddy; `docker top <openemr> | grep -c httpd` against the 250 prefork cap;
  `SHOW GLOBAL STATUS LIKE 'Threads_connected'`; host `free -m` (no swap);
  `/metrics` at the start and end of each level. Expect and record, never
  fix on the spot: 50 users x tool_concurrency 6 is up to 300 gateway
  requests against 250 prefork workers with a 2.0 s timeout
  (`settings.py:18-19`), so the likely 50-user failure is `partial` turns,
  not 5xx; provider 429s open the breaker for 60 s and convert turns to
  fallback.

- [ ] **Rehearse clean deploy, rollback, roll-forward and restore on a throwaway Droplet** (P1, M; Friday evening if the pin and `start.sh` fix land, else Saturday morning)
  Why: checklist :131; `PROJECT_PLAN.md:237`; PRD Appendix 15;
  `INTERVIEW_NOTES.md:277-280` asserts rollback with no evidence. State:
  never rehearsed; `main.tf:11-14` registers the SSH key as a resource
  (one registration per key on DigitalOcean); `deploy.sh:60` pushes the
  real model key to any host it deploys to. Do: a separate SSH key
  (`~/.ssh/agentforge_rehearsal`); in `infra/digitalocean`, `set -a; .
  ~/.config/agentforge/do.env; set +a; ./tf.sh workspace new rehearsal &&
  ./tf.sh apply -var project_name=agentforge-rehearsal -var
  ssh_public_key_path=~/.ssh/agentforge_rehearsal.pub`; `deploy.sh`,
  demo-seed, `evals/run.py --golden-only --base-url https://<rehearsal>`
  (ACME on a second sslip name may lag a minute); rollback: `git worktree
  add /tmp/rb week1` and deploy from it, confirm `/copilot-api/health` and
  the golden subset; roll forward to HEAD; run `restore.sh` here; time each
  step; destroy the same day (`./tf.sh destroy` in the rehearsal workspace,
  `./tf.sh workspace select default`, delete the throwaway key). Never
  touch the default workspace or 137.184.4.22; never run
  `smoke-cycle.sh` or `tf.sh apply` against the default state. Write
  commands and timings into `digitalocean.md` "Failure and Recovery"
  (replace :309-316), fix `INTERVIEW_NOTES.md:277-280`, tick checklist :131
  and `SETUP.md:239`. About $0.04 per hour.

- [ ] **Add `backup.sh` and `restore.sh`; back up Terraform state; delete stale plans** (P1, M)
  State: `main.tf:22` `backups = false`; no scripts; `start.sh:32-37`
  generates the MySQL, admin, delegation and demo passwords on the host
  only, so losing `/opt/agentforge/secrets` orphans the database volume and
  changes the demo password; `terraform.tfstate`, `runner/terraform.tfstate`
  and `terraform.tfvars` exist only on this workstation (gitignored);
  `deploy.tfplan` and `runner/runner.tfplan` are stale. Do: `backup.sh <ip>`
  (over SSH: `mariadb-dump --single-transaction` of openemr, `tar` of the
  `openemr_sites` and `agent_state` volumes, `tar` of
  `/opt/agentforge/secrets` and `.env`, one timestamped archive encrypted
  with `age` or `gpg --symmetric` under `~/.config/agentforge/backups/`,
  never the repo); `restore.sh <ip> <archive>` (stop openemr and agent,
  untar secrets and `.env`, load the dump, untar the volumes, `up -d
  --wait`); run backup against 137.184.4.22 (read-only) and restore on the
  rehearsal Droplet, then `--golden-only` there; copy both tfstate files and
  `terraform.tfvars` to `~/.config/agentforge/tfstate/<date>/` (mode 600)
  now and after every apply; delete the two `.tfplan` files; document
  backup, restore, snapshot restore (a restored Droplet gets a new IP and
  sslip hostname and needs the CI variable updated), retention, and the
  "demo password depends on this host" fact in `digitalocean.md`; ADR-0001
  status note; `README_AGENT_FORGE.md:244`, :267, `README.md:16-19`,
  `SETUP.md:239`.

### Friday drafts (placeholders now, numbers Saturday)

- [ ] **Draft the per-tier architectural-changes table for `AI_COST_ANALYSIS.md`** (P1, S now, fill Saturday)
  Why: PRD p.9 "consider architectural changes needed at each level. This
  is not simply cost-per-token * n users". State: :102-109 is node
  arithmetic on unmeasured assumptions; :124-126 says "scales linearly".
  Do: a four-row table (tier | what breaks first | change | cost effect)
  grounded in code: 100 users on one Droplet with the daily halt and
  per-conversation cap (halt is per process, `budget.py:38`); 1K splits
  agent and OpenEMR, managed MariaDB, higher provider rate tier,
  backpressure from `copilot_turns_in_flight`, cache-hit monitoring
  (4,759 of 6,559 tokens per turn are cache reads); 10K horizontal agent
  nodes needing the checkpointer off local SQLite (`state_store.py:38-40`)
  and the halt in a shared store, self-hosted Langfuse with 10% sampling,
  cheaper planning model and claim caps as levers to test with baseline
  plus compare.py; 100K multi-site OpenEMR (out of estimate), committed-use
  model capacity, regional deployment, per-tenant budgets. Rewrite :124-126
  as "linear until the tier levers apply".

- [ ] **Revise `docs/DEMO_SCRIPT.md` for the final video with placeholders** (P1, S)
  State: :13-29 is the early script (ends at 4:25; no load, baseline, alert
  or rollback beat); all eight proof points at checklist :139-148 unticked.
  Do: a one-line "since the early submission" opener; replace rows 3:50 to
  4:25 with the eval report at the final commit (10 s, name the non-blocking
  miss if it persists), load results at 10 and 50 users with p50/p95/p99,
  error rate and the CPU/memory baseline (15 s), one alert rule and the
  alerts service output (10 s), the rollback rehearsal in one sentence
  (5 s), the cost line "$0.013 measured over the eval run, $0.022
  conservative basis" with the cost gate's real state (10 s); cut the dosing
  refusal at 1:45; keep the commit and tag on screen. If load results slip,
  the script must not claim them.

- [ ] **Draft `docs/SOCIAL_POST.md` (LinkedIn and X) and plan the 20 to 30 s clip** (P1 draft, S; posting is Sunday P0)
  Why: PRD p.9 "Share on X or LinkedIn: describe the project, show the
  agent, tag @GauntletAI". State: no draft or media anywhere; the lab
  GitLab is login-only, so only the public GitHub fork and the unlisted
  video are shareable. Do: hook ("90 seconds between patient rooms"), what
  it is (read-only co-pilot inside OpenEMR; every statement cites a chart
  record; a deterministic verifier checks each claim), three or four numbers
  (45 cases, p95, cost per turn, the 50-user result if it exists), one audit
  lesson (the fail-open ACL helper the gateway bypasses), links to the
  GitHub fork and the final video, tag @GauntletAI; X version under 280
  characters.

- [ ] **Pre-write the egress risk-acceptance text and the post-grading rotation checklist** (P1, S)
  State: `main.tf:54-69` allows all outbound; the agent is on `frontend`;
  no host firewall; the DigitalOcean cloud firewall cannot express
  hostnames and both endpoints are anycast CDNs, so host-level DOCKER-USER
  rules are the only vehicle. Do: the risk-acceptance paragraph (what code
  execution in the agent gains: model and tracer keys, the evidence pack;
  compensating controls: file secrets only in that container, no database
  route, deny-by-default edge, PHI-free telemetry, 2M-token daily halt,
  disposable Droplet) for `AUDIT.md` §7.2, `ARCHITECTURE.md` Known
  Limitations, README limitations and `digitalocean.md`, so Saturday's
  decision flips one sentence. Add the dated "After grading" rotation list
  to `digitalocean.md` (new Anthropic key with a spend cap and Langfuse keys
  via `push-secrets.sh`, new DigitalOcean token, runner token reset, new
  delegation secret with `--force-recreate openemr agent`, GitLab PAT;
  MariaDB and demo passwords stay). Execute only after the final AI
  interview window.

- [ ] **Add the tests that prove controls the docs already cite** (P1, S; lint and tracer-down P2)
  State: 60 tests; nothing covers checkpoint content (ADR-0005:128-130
  claims it; `ARCHITECTURE.md:851` says still to add), the 429 rate limit,
  the circuit breaker, or the LangSmith guard. Do (tests only, excluded
  from the deploy tar): `test_checkpoint_content.py` with `AsyncSqliteSaver`
  on `tmp_path` after a UC-01 turn and a follow-up on the af-dq-a2 fixtures,
  asserting no verbatim note body, no raw-record key shapes, and the
  delegation token absent (do not assert lab values or doses are absent;
  verified claims carry them by design); register it as offline golden case
  `ISO-CHECKPOINT-OFFLINE-001`; `turns_per_minute = 2` and a third turn 429
  in `test_api.py`; breaker opens after three failures and closes after the
  cooldown; `guard_environment()` raises on `LANGSMITH_TRACING=1`. If the
  checkpoint test finds a raw record shape, that is an ADR-0005 breach to
  fix before the freeze.

- [ ] **Write `docs/WEEK2_HANDOFF.md`** (P1, M; keep to one page if time is short)
  Why: PRD p.2 "good architecture will compound"; Week 2 adds ingestion,
  hybrid RAG, a supervisor with two workers, a 50-case golden set and a
  PR-blocking eval gate. Do: read-first order; a seams table honest about
  code versus prose (`SourceRef.id` is an int, reserved claim types are a
  comment, no source registry, no `actions/` directory); the compare.py
  baseline (`a4a5856.json`); residuals (fault injection on by default on the
  demo host, no checkpoint sweeper, daily halt counts input plus output
  only, langchain present only for the Langfuse callback, Langfuse public
  API v2 migration due 2026-11-16); the two deferred experiments
  (deterministic note-versus-list conflict line in `pack_limitations`; one
  planning round for follow-ups) each with the protocol "baseline
  `--repeat 2`, change, `--repeat 2`, `evals/compare.py`"; operational state
  by file name only. Link from `README_AGENT_FORGE.md:114` and
  `PROJECT_PLAN.md:247`; fix `ARCHITECTURE.md:438-439` in the same commit.

### Friday, only if under two hours each (otherwise list under `evals/README.md` "Not automated in Week 1")

- [ ] **`ISO-FRESH-REPEAT-001` and `ISO-TWO-USERS-001`** (P1, M)
  Both invariants are called "tested" at `ARCHITECTURE.md:482-487` with no
  case (prior-cohort context-bleed lesson). Harness and YAML only:
  fresh-conversation repeat on AF-DQ-C with `history turns_max 0` and
  `text_must_not_match` for "as I mentioned earlier" phrasings; an
  `as_user:` step opening a second session as `physician` plus a ticket
  step carrying the first user's conversation id expecting 403/404.

- [ ] **Journal-derived cases that pass against the frozen agent** (P1, M)
  Only cases that pass now; cases needing a new claim type or an
  out-of-scope emission go to a holding directory `manifest()` does not
  glob, marked "Week 2: contract 1.3.0". Must land before Saturday's
  release run or not at all.

Deferred to Week 2 with one sentence each (do not start): single-use
tickets; `AUTH-NURSE-001`, no-session and bad-CSRF negatives (record the
manual break-glass run date at traceability row 24 if it happens); TTFE
through `--stream`; the near-miss canary false positives (the 15% at
a4a5856 is mostly the deterministic "could not be verified" sentence and
CONF-DUP-NAMES' required "may be duplicate" wording); `evals/cases/INDEX.md`;
the Week 2 gate recipe; both optional experiments.

---

## Saturday 2026-09-19 (evidence day; freeze 18:00 PT; final deploy and release run; demo)

Order: rehearsal and backup first if they did not land Friday, then the
snapshot, then the load runs, the egress decision by noon, code freeze at
18:00 PT, deploy of the frozen tree, the `--repeat 3` release run started
no later than 19:00 PT, the demo dry run and recording. Nothing that
changes gateway, verifier, prompt or model merges after the release run.

- [ ] **Snapshot the Droplet and copy the Terraform state first** (P0, S)
  `doctl compute droplet-action snapshot $(./tf.sh output -raw droplet_id)
  --snapshot-name week1-final-2026-09-19` (about $0.06 per GB-month). A
  restored Droplet gets a new IP and hostname, so this is the rollback of
  last resort, not the first.

- [ ] **Run the load tests at 10 and 50 concurrent users** (P0, L; the run half)
  Only after the rehearsal, restore test and snapshot; never during an
  eval run or the demo. Five-minute idle baseline with the sampler, then
  `--users 10` and `--users 50` with the real model (about 20 and 100
  model-backed turns, about $0.25 and $1.30; read `copilot_tokens_total`
  first because the daily halt is process-local) and again with
  `--fault model`; check `/ready` and `docker compose ps` after each level;
  record status share (latency is gamed by falling back early,
  `KEY_METRICS.md:26`) and tool-unavailable reasons. Write
  `docs/audit/evidence/performance/load-test-2026-09-19.md` in the
  `page-timing-local.md` style with the serial release-run numbers as the
  concurrency-1 row; commit the JSON. Never resize the Droplet or change
  `tool_concurrency` inside the window.

- [ ] **Capture CPU, memory, throughput, Apache-worker and DB-connection baselines** (P0, M)
  Why: PRD p.9 baselines under the load scenarios; checklist :127;
  traceability row 35; `KEY_METRICS.md:43`. Do: `droplet-stats.sh` for the
  idle window and each level and scenario; turns per minute and requests
  per minute; commit `docs/audit/evidence/performance/baseline-2026-09-19.md`
  (per level and scenario: mean and peak CPU per container, peak memory,
  host free-memory low-water mark, peak httpd count, peak
  `Threads_connected`, turns/min, p50/p95/p99, error rate, status share)
  plus the CSVs; replace `docs/audit/performance.md:237`, :259-267; update
  `KEY_METRICS.md:43`, :110-112 (confirm or revise the 30 s p95 beside the
  baseline), `AI_COST_ANALYSIS.md:102-109`, `ARCHITECTURE.md:79`, :574-579,
  :835, `AUDIT.md:342-345`, :746, traceability rows 35-36, checklist
  :127-128, `README_AGENT_FORGE.md:265`, `INTERVIEW_NOTES.md:43-45`, and an
  ADR-0001 status line on whether the 4 GiB size held against its :123
  trigger.

- [ ] **Interpret the 50-user result: worker count and Droplet size** (P1, S)
  Write the decision into `ARCHITECTURE.md` "Latency and Scale" (expected:
  one asyncio process per node because limiter, metrics, breaker, daily
  halt and the SQLite checkpointer are process-local; scale by nodes) and
  the measured headroom into ADR-0001's status note. Only if the host swaps
  or saturates: snapshot first, `droplet_size = "s-4vcpu-8gb"` in
  `terraform.tfvars`, `./tf.sh apply` (the plan must show a resize only,
  about 2 minutes of power-off), before the release run so the final
  baseline matches the final host. No global turn semaphore this week.

- [ ] **Egress decision by noon: paste the risk acceptance** (P1, S)
  Default: paste Friday's text into `AUDIT.md` §7.2, `ARCHITECTURE.md:694-697`,
  `README_AGENT_FORGE.md:244-245`, :267, `digitalocean.md:381` and tick
  checklist :132. Build the DOCKER-USER rules only if they were tried and
  passed the blocked-egress test on the rehearsal Droplet on Friday; never
  build them first on 137.184.4.22; never on Sunday.

- [ ] **Rehearse the alerts service and commit the log** (P1, S)
  Five `X-Copilot-Fault: tool:medications` turns and one `model` turn;
  commit the PHI-free lines as
  `docs/audit/evidence/observability/alerts-rehearsal-2026-09-19.log`; a
  real page line from the 50-user run is better evidence if one fires.

- [ ] **Fill the per-tier cost table and fold the load baseline into `AI_COST_ANALYSIS.md`** (P1, S)
  Measured concurrent-turn capacity, the load-test token mix and its model
  spend; any threshold revision per `KEY_METRICS.md:110-112`; traceability
  row 37; `README_AGENT_FORGE.md:122`.

- [ ] **Code freeze 18:00 PT; deploy the frozen tree from a clean worktree; run the `--repeat 3` release run** (P0, M)
  Why: PRD p.9 deployed application and eval results; checklist :123,
  :134; `KEY_METRICS.md:113` (a release run executes the whole suite);
  `evals/README.md:81-82`. State: the only `--repeat 3` report is 1ddf824
  (44 cases); every Friday item changes the manifest, harness or agent;
  `deploy.sh:48-66` tars the working tree, so the deployed tree is whatever
  checkout it runs from; no deployed commit or image digest is recorded.
  Do: (1) `curl -s https://api.ipify.org` against the SSH allowlist in
  `terraform.tfvars`; if different, edit and `./tf.sh apply` (plan shows
  only the firewall), and the runner root. (2) Optional: bump
  `agent/app/__init__.py:3` and `pyproject.toml:3` to 0.3.0 so `/health`
  names the release. (3) `git status --porcelain` empty; `git worktree add
  /tmp/final <frozen-sha>` and run `infra/digitalocean/deploy.sh
  137.184.4.22 openemr-137-184-4-22.sslip.io <tls-email>` from it (do not
  rerun demo-seed). (4) `smoke.sh`, `/copilot-api/ready` 200, `bru run
  --env deployed` 21/21, `evals/run.py --golden-only`, then
  `DEMO_PASSWORD=... agent/.venv/bin/python evals/run.py --repeat 3 --label
  "week1-final release run"` (about 36 min, about $1.65); commit JSON and
  MD; `evals/compare.py evals/results/2026-09-17T024919Z-a4a5856.json
  evals/results/<final>.json > evals/results/<final>-vs-a4a5856.md`. If a
  blocking gate fails: roll back by deploying tag `week1` from a worktree
  and submit the early agent with the new evidence; never edit an assertion
  to pass; a new recall miss gets a risk-acceptance note. (5) Record the
  commit, results file and `docker compose images` digests in
  `digitalocean.md` "Current Deployment", `README.md:8-9`,
  `SETUP.md:249-250`, `ARCHITECTURE.md:72`; state that the final tag differs
  from the deployed tree only in docs and results. (6) From a phone on
  mobile data: log in as `audit-physician`, run a starter question, click
  one citation; tick checklist :123 and :134. Play `test:evals-live` on the
  frozen commit from the GitLab UI and keep the job URL.

- [ ] **Re-run the deny-by-default edge probe after the final deploy** (P2, S)
  `deploy.sh:49` re-copies the whole runtime directory including the
  Caddyfile, so the final deploy can regress the allowlist. Run
  `docs/audit/scripts/cloud-probe.sh openemr-137-184-4-22.sslip.io
  137.184.4.22 5 > docs/audit/evidence/security/cloud-probe-2026-09-19-final.txt`,
  confirm the sensitive, gateway, `/apis` and `/oauth2` paths still 404,
  commit, and cite it from `digitalocean.md:367-372` and
  `ARCHITECTURE.md:698-703`.

- [ ] **Record, verify, upload and link the final demo video** (P0, M; after the release run)
  Why: PRD p.9 demo video 3 to 5 minutes; checklist :133 and the eight
  proof points :139-148; synthetic data only. Do: dry-run every beat once;
  use AF-DQ-N only if the dry run cites both the note and the list,
  otherwise the AF-DQ-A2 amlodipine row; `audit-physician` on pid 900001,
  Langfuse filtered to the last hour with the sidebar collapsed, the Bruno
  tool-outage request ready; never run `git remote -v` on camera (token in
  the URL) and never `cat` a secrets file; play back with sound on; confirm
  3:00 to 5:00 and no password, token or session id beyond the `ref` the
  script shows; upload unlisted; write the URL into `README_AGENT_FORGE.md`
  "Demo video" (keep the early link labelled), `DEMO_SCRIPT.md:6`,
  checklist :133, traceability row 39; tick each proof point with its
  timestamp. Budget a second take.

- [ ] **Trim the `AUDIT.md` Executive Summary toward the 500-word gate** (P2, S)
  Measured 635 words (`ARCHITECTURE.md` summary is 594). Move the
  2026-09-15/16 status and remediation sentences into §7 and cut to about
  550; remove no finding; set traceability row 13 to the real count.

- [ ] **Add "Known gaps at submission" to `docs/INTERVIEW_NOTES.md` and the two evals notes** (P1, S)
  Load and baseline status, the recall-miss state after the release run,
  cost gate state, hostname, backup and egress outcomes (for both AI
  interviews). Add to `evals/README.md:66-76` and `KEY_METRICS.md:82`, :93
  that `repair_rate` is the fraction of turns where the verifier rejected on
  the first pass and that the rejection-rule table lists only rejections
  that survived repair (`nodes.py:213-220`); keep citation correctness NOT
  MEASURED at `KEY_METRICS.md:85` with the Week 2 gold-source-id plan.

- [ ] **Final documentation pass, part 1** (P1, L; Friday evening for the placeholders, Saturday evening for the numbers)
  Replace each "target 2026-09-19 / pending / planned" passage (13 lines
  across 7 docs: `KEY_METRICS.md:8`, :110; `README_AGENT_FORGE.md:265-267`;
  `ARCHITECTURE.md:576-578`; `AUDIT.md:335`, :344;
  `docs/audit/performance.md:107`, :135, :265-267;
  `docs/audit/architecture.md:357`; traceability :17) with the report path
  and headline numbers; for anything not done write the same sentence
  everywhere ("not done for Week 1; residual risk, see AUDIT.md §9") with no
  future date and move it from `ARCHITECTURE.md:70-80` into Known
  Limitations; rewrite `digitalocean.md` "Failure and Recovery" for the
  long-lived host (reboot, secrets loss, expired model key, Caddy stuck in
  Created); repeat the eval refresh with the final results file using
  `grep -rn '1ddf824\|a7641e9\|69560f0\|a4a5856\|44 cases\|MISS-AUTHOR-J-001\|nine \(eval\|result\)' --include='*.md' . | grep -v evals/results`;
  walk the 202 "2026-09-16" status lines outside `evals/results` and update
  each or append "unchanged as of 2026-09-20".

Fallback: if the video is uploaded Saturday night, publish the social post
then instead of Sunday morning.

---

## Sunday 2026-09-20 (docs only; docs freeze 07:00 PT; submit 08:00 PT = 10:00 CT; hard deadline 10:00 PT = 12:00 CT)

- [ ] **06:00 to 07:00 PT: publish the social post and record the clip** (P0, S)
  A 20 to 30 s screen recording of a starter question on AF-DQ-A2 with the
  claims table and a citation click-through (`ref` and session values
  blurred, no credentials); LinkedIn and X from `docs/SOCIAL_POST.md`, tag
  @GauntletAI; paste the URL into checklist :135 and traceability row 41.
  If the video or load numbers slipped, post with the eval numbers and the
  clip rather than miss the deadline.

- [ ] **06:30 PT: rerun the early checklist against the final commit and deployment; no deploys** (P0, S)
  `evals/run.py --golden-only` and the phone check again; `git ls-remote
  origin` and `git ls-remote gitlab` show the same `main` and tag; provider
  credit and Langfuse units rechecked; `README.md:8-9` and
  `README_AGENT_FORGE.md` name the final tag. If anything under `agent/`,
  the module, the prompt or `evals/cases` changed after Saturday's release
  run, repeat the `--repeat 3` run now and finish by 08:00 PT; otherwise do
  not. Anything not green is written up as a limitation, never hot-fixed.

- [ ] **Refresh `AI_COST_ANALYSIS.md` Part A to the final commit** (P1, S; last edit to the cost doc)
  State: Part A says "through 2026-09-15", 36 commits, about 13 h, Droplet
  "$0.20 measured", model dev spend "$1 to $15"; HEAD has 66 project commits
  (27 `Assisted-by`, 56 `Co-Authored-By`); the CI runner Droplet
  (s-1vcpu-1gb, $0.00893 per hour since 2026-09-16 05:04 UTC) is absent; the
  ten scorecards sum about $6.20 of eval model spend. Do: recompute commits,
  trailers and spans from `git log --format='%ci'`; Droplet hours since
  2026-09-15 19:12 UTC at $0.03571 per hour plus the runner, the rehearsal
  Droplet and snapshot storage; a planned teardown date after grading and
  the AI interview; "Eval and load-test model spend" from every results
  file plus the load runs; keep Claude Code as a labelled estimate; tick
  checklist :129-130; traceability row 37 Verified. Never run `destroy.sh`
  or `smoke-cycle.sh` on either Terraform root before grading is confirmed.

- [ ] **Final documentation pass, part 2: tag `week1-final`, links, ticks, pipeline id, push both remotes** (P1, M)
  Replace checklist :86-92 with the final green pipeline (or record that
  it shows "blocked" because the manual job was not played); add the final
  demo and social post URLs everywhere listed on Saturday; reword the three
  "for the early submission" latency sentences (`KEY_METRICS.md:26`,
  `ARCHITECTURE.md:565-567`, `alerts.md:32-33`); convert
  `PROJECT_PLAN.md:218-245` into ticked items with evidence links or an
  explicit "not done"; `git tag -a week1-final -m "Week 1 final submission;
  deployed tree = <frozen-sha>, differs only in docs and results"`; run the
  secret scan from checklist :95-98; `git push gitlab main --tags && git
  push origin main --tags`; record the tag beside the deployed commit and
  digests in `digitalocean.md`, `README.md:8-9`, `README_AGENT_FORGE.md:31-36`,
  `SETUP.md:250`, `ARCHITECTURE.md:72`.

- [ ] **08:00 PT: submit the final form** (P0, S)
  Live URL `https://openemr-137-184-4-22.sslip.io`; repository URL per
  Byron's answer (GitLab
  `labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean`, with
  "public mirror, identical commits and tags:
  https://github.com/hdxsfbr/openemr-base-clean" in the notes) plus the
  final commit hash and tag; video URL; social post URL; username
  `audit-physician` and the password from `ssh deployer@137.184.4.22 cat
  /opt/agentforge/secrets/demo_user_password`; note "audit-frontdesk uses
  the same password; Bruno: `cd docs/api-collection && bru run --env
  deployed --env-var DEMO_PASSWORD=<same>`"; tick checklist :137 with the
  timestamp. The final commit must be on GitLab `main` before the form is
  submitted.

- [ ] **Record the final AI video interview within 24 hours (block Sunday afternoon)** (P0, S)
  The early-submission email arrived about 7 minutes after the tag push.
  Watch the challenger inbox and the portal badge after submitting; record
  in Chrome with the answer sheet, the final eval report and the load-test
  table on a second screen; confirm the upload; tick checklist :136.

After grading and the interview window: run the rotation checklist from
`digitalocean.md`; only then consider tearing down the Droplets.

---

## Cut order when time runs short

Cut in this order, and write one sentence per cut item under
`evals/README.md` "Not automated in Week 1" or the Known Limitations:

1. Every P2 item and both deferred experiments.
2. Harness items that need new cases: the two ISO cases, journal-derived
   cases, `AUTH-NURSE` and the anonymous and CSRF negatives, TTFE `--stream`.
3. Egress restriction (paste the risk acceptance).
4. Agent-batch tails (single-use tickets, the correlation ContextVar) as
   Known Limitations sentences.
5. `WEEK2_HANDOFF.md` shrinks to a one-page stub.

Never cut: the Thursday docs corrections (they protect both interviews and
cost under six hours together); the early AI interview by 19:59 PT
Thursday; the dependency pin and the `start.sh` fix (they guard the one
deploy that must not fail); the rehearsal in its minimum form (rollback to
tag `week1` on a throwaway Droplet); the cost gate before the final run;
the load tests and baselines; the Saturday 18:00 PT freeze; the release
run; the demo; the social post; the submission by 08:00 PT.

If the release run fails a blocking gate on Saturday night: roll back to
tag `week1`, submit the early-submission agent with the new evidence and an
honest limitations list, and never hot-fix on Sunday.

---

## Document as limitation, do not build

One sentence each in `ARCHITECTURE.md` Known Limitations, `AUDIT.md` §9
and `README_AGENT_FORGE.md` Limitations (:214-254), with no future date,
written during Saturday's docs pass unless the linked item above landed.

- Owned hostname: the graded deployment uses the sslip.io name with valid
  TLS; owned DNS is a real-deployment item (`digitalocean.md:386-387`,
  ADR-0001:94-95, `README.md:16`, `SETUP.md:255`, `README_AGENT_FORGE.md:267`;
  split :267 into hostname, backup/rollback and egress rows).
- Agent egress: the pre-written risk-acceptance paragraph, unless restricted.
- 24 h retention: no sweeper runs; closed conversation rows and checkpoint
  threads persist for the environment's lifetime; `sweep()` exists with no
  caller; the TTL in ADR-0005 is a design target (fix `ARCHITECTURE.md:469`
  `purge()` to `sweep()`, :470, :741-742, ADR-0005:119, :141-142).
- Citation correctness: stays NOT MEASURED (`run.py:642`,
  `KEY_METRICS.md:85`); one sentence on the Week 2 gold `source_ids` plan.
- First-pass verifier rejections: the rejection-rule table lists only
  rejections that survived repair (`nodes.py:213-220`).
- Clinician validation: tick `USERS.md:417` (the rejected-use-case table
  exists) and state that the 90-second workflow, the three starter questions
  and the latency tolerance are hypotheses with no clinician interview held.
- Public `/metrics`: exposed at `/copilot-api/metrics` by choice on the demo
  host; PHI-free counters with bounded labels (ADR-0007 decision 6 status
  note, `AUDIT.md` §7.2, `ARCHITECTURE.md:624`, `metrics.py:1-3` docstring).
- Note coverage: Clinical Notes (`form_clinical_notes`) only; SOAP and other
  encounter forms are not read and the gap is not yet stated in the response
  (ARCH-MEDIUM-004; `counts.form_types_covered` is returned but not
  rendered); fix `README_AGENT_FORGE.md:246-247` and the
  `ClinicalNotesTool.php:6` docblock; do not add the line to
  `pack_limitations` before the final run.
- Fault injection on the demo host: on by default (`compose.yaml:143`)
  because the golden gate depends on it (`TOOL-OUTAGE-LABS-001`); the header
  affects only the caller's own turn and needs a valid ticket; a production
  deployment sets 0, after which those cases report NOT RUN. Do not change
  the compose value before Sunday.
- Agent-level denials: a denial at the agent (missing, bad, expired token,
  conversation mismatch) has no authenticated principal, so no OpenEMR audit
  row is written; the agent's JSON log and `/metrics` are the record. Move
  `ARCHITECTURE.md:859-862` into Known Limitations; one sentence in
  `docs/audit/compliance.md` §5.
- Contract version split: tool envelopes report 1.0.0 (`AbstractTool.php:23`,
  `gateway_client.py:26`, the seven fixtures) because tool records are
  unchanged; the turn contract is 1.2.0; the envelope version is recorded,
  not enforced; a response failing `ToolResponse` validation becomes
  `unavailable:contract_violation` (`gateway_client.py:55-57`). Fix the
  ADR-0004:159-161 and `ToolRegistry.php:37` "schema validation" wording.
- Per-conversation rate-limiter eviction: `api.py:29` never drops empty
  deques; note it.
- Unbounded container logs: only if the compose logging block did not ship.
- CSP on module assets, PHP JSON Schema validation, LLM-call and
  verification-result audit rows, at-rest encryption and KMS, BAAs: "not
  done for Week 1; residual risk, see AUDIT.md §9" (already at
  `ARCHITECTURE.md:70-80` and `AUDIT.md:861-870`).
- Deterministic note-versus-list detector, one-planning-round cap, Haiku
  for planning, module-versus-image CI symbol check (`ARCHITECTURE.md:855-858`),
  Bruno collection in CI (align `docs/api-collection/README.md:29-31` with
  `ARCHITECTURE.md:677-679` and :754-755): Week 2 or "what would you add
  next", not Sunday.

---

## Doc refresh at the final commit

Rows 1 to 18 are wrong today (Thursday); repeat rows 1 to 3 and do rows 19
to 30 on Sunday after the release run.

| # | File:line | Current text (gist) | Correct fact |
|---|---|---|---|
| 1 | `KEY_METRICS.md:26`, :76, :85, :91; `README_AGENT_FORGE.md:263`; `docs/REQUIREMENTS_TRACEABILITY.md:32`; `docs/PROJECT_PLAN.md:214-216`; `ARCHITECTURE.md:568-570`, :779-782; ADR-0004:174-177; `docs/audit/performance.md:254-256` | "No full run since the 45th case", "latest 1ddf824, p95 27.6 s", "528/528" | Latest full run `evals/results/2026-09-17T024919Z-a4a5856.md`: 45 ran, 44 passed, every blocking gate PASS including Golden set integrity 14/14 for the first time, citations 177/177 (528/528 stays as the repeat-3 history), model-backed p95 24.1 s, $0.0127 per turn; one miss `CONF-NOTE-VS-LIST-N-001` under the non-blocking task-success gate at 95% |
| 2 | `KEY_METRICS.md:76`; `README_AGENT_FORGE.md:263`; `docs/SUBMISSION_CHECKLIST.md:70-71`, :74; `docs/INTERVIEW_NOTES.md:247`; `AUDIT.md:742`; `docs/audit/data-quality.md:289`; `docs/audit/INTERVIEW_NOTES.md:132-137`, :283-284 | "one flaky model-recall case, MISS-AUTHOR-J-001" | Two recall cases flip run to run: `MISS-AUTHOR-J-001` (1ddf824, 69560f05), `CONF-NOTE-VS-LIST-N-001` (a4a5856); deterministic lines passed every time; task-success gate stayed 95% PASS |
| 3 | `docs/REQUIREMENTS_TRACEABILITY.md:32`; `docs/PROJECT_PLAN.md:188`; `docs/deployment/digitalocean.md:134` | "nine eval reports" | Eleven reports at HEAD (more after the release run) |
| 4 | `README_AGENT_FORGE.md:54` | AF-DQ-N "the answer cites both" | The note-versus-list conflict claim is model recall; missed once in a4a5856; AF-DQ-A2's amlodipine conflict is deterministic |
| 5 | `docs/SUBMISSION_CHECKLIST.md:119`, :105, :64, :8-15; `docs/REQUIREMENTS_TRACEABILITY.md:38`; `evals/README.md:14` | "[HAHAHA]"; no commit; "screenshot still to attach"; "GitHub not kept in sync"; "README.md untouched"; every run has JSON | Early submission e1dd331 / tag `week1` confirmed 2026-09-16 21:59 CT; screenshots in `docs/audit/evidence/observability/`; both remotes at e1dd331 with tag `week1`; `README.md` carries a 42-line challenge header; 69560f05 has Markdown only |
| 6 | `README.md:8-9`; `SETUP.md:249-250`; `docs/deployment/digitalocean.md:129-132`; `ARCHITECTURE.md:72`, :708-709; `docs/PRIOR_COHORT_LESSONS.md:19-21`, :51 | "tag v0.2.0-slice is live", "no tag since" | The 2026-09-16 deploy of commit e1dd331, tag `week1` (runtime directories unchanged since 831e1d8, 2026-09-16 11:51 PT) is live; verified by a4a5856 and the 21/21 Bruno run; no deploy digest recorded until Saturday's final deploy; the final tag replaces this Sunday |
| 7 | `docs/INTERVIEW_NOTES.md:218` | "renders ... under a CSP" | Renders through `textContent` and DOM APIs; a CSP on module assets is planned (SEC-MED-003), none set |
| 8 | ADR-0002:74-76; `AUDIT.md:741` plan cell | ViewEvent dispatched | ViewEvent dispatch planned, not implemented (ADR-0002:220-222) |
| 9 | ADR-0002:108; `evals/fixtures/cohort/README.md:92`; `ARCHITECTURE.md:225-232` | response "carries the parity limitation text" | Allowed, cited and audited; the parity limitation is stated in the README, ADR-0002 §4 and tagged on the conversation (`policy: parity-1`), not in the response |
| 10 | `ARCHITECTURE.md:469`, :470, :741-742; ADR-0005:119, :139-144 | `ConversationRepository::purge()`; 24 h retention under "implements" | Method is `sweep()` with no caller; retention is a design target (Known Limitations) |
| 11 | `KEY_METRICS.md:41`, :81; ADR-0002:88 | denial reason `unsupported_principal` | Emitted reasons: `missing_token`, `bad_token`, `token_expired`, `conversation_mismatch` (agent); `missing_token`, `bad_token`, `token_expired` (gateway) |
| 12 | ADR-0004:159-161; `ToolRegistry.php:37` | validates against `*_params.schema.json` | Hand-written allowlist and formats mirroring the exported schemas; schema-file validation planned (`ARCHITECTURE.md:398-401` is correct) |
| 13 | `docs/REQUIREMENTS_TRACEABILITY.md:25` | HIPAA-aware handling "implementation not started" | Implemented: projections and row caps, age-band context, PHI-free telemetry mask, PHI-free JSON logs, audit row per tool read and denial, file secrets; not implemented: LLM-call and verification audit events, 24 h purge, egress, KMS, BAAs; no HIPAA compliance claimed |
| 14 | `docs/REQUIREMENTS_TRACEABILITY.md:34`; `docs/SUBMISSION_CHECKLIST.md:84-85`; `ARCHITECTURE.md:558`, :629 | "readyz unrouted"; "tracer keys configured"; panel reads /ready | `/ready` probes the gateway (`ping.php`) and the LLM (`models.retrieve`); the tracer check is presence-only until the Friday probe lands (then Verified with the test name); the panel probes `/health` (`copilot.js:485`) |
| 15 | `ARCHITECTURE.md:482-487` | isolation invariants "(tested)" including fresh-conversation repeat and two users | Only cased invariants are tested; the two new cases land Friday or are listed as not automated |
| 16 | `ARCHITECTURE.md:438-439` | verifier resolves schemes "through a source registry" | Resolves through `EvidencePack.records` keyed by `source_id` (`agent/app/evidence.py:58-60`); a registry is the Week 2 extension point |
| 17 | `ARCHITECTURE.md:588-590` | gateway "emits one PSR-3 line per call with the correlation ID" | No PSR-3 logger; the id is in every audit row and the tool envelope; the module's three `error_log` calls are error paths |
| 18 | `ARCHITECTURE.md:840`, :859-862, :838-839; `README_AGENT_FORGE.md:246-247`; `docs/operations/langfuse-dashboard.md:56-60`; `ARCHITECTURE.md:624` | "Open Items Before the Vertical Slice (2026-09-15)"; fault injection "disabled outside the demo"; "SOAP"; eval scripts call the Langfuse API; /metrics "internal only" | Retitle "Open Items" with current states; fault injection on by default (`compose.yaml:143`); Clinical Notes only; no script calls the API; `/metrics` public by choice |
| 19 | `docs/INTERVIEW_NOTES.md:41-42`, :143-145, :275-276, :277-280, :113-114 | "streams in about 1 s"; alerts job present tense; rollback established; cost "acceptable against the projection" | TTFE not measured (retrieve node about 1 s in traces); alerts run on demand until the compose service lands; rollback rehearsed <date> or not; threshold $0.0223 with the measured margin |
| 20 | `KEY_METRICS.md:8`, :110; `README_AGENT_FORGE.md:265-267`; `ARCHITECTURE.md:576-578`; `AUDIT.md:335`, :344; `docs/audit/performance.md:107`, :135, :265-267; `docs/audit/architecture.md:357`; `docs/REQUIREMENTS_TRACEABILITY.md:17`, :35-36; `docs/SUBMISSION_CHECKLIST.md:127-128` | "target 2026-09-19", "not started" | Load-test and baseline report paths with p50/p95/p99, error rate, CPU and memory at 10 and 50 users; `KEY_METRICS.md:110-112` states whether the 30 s p95 and cost thresholds were confirmed or revised |
| 21 | `AI_COST_ANALYSIS.md:4`, :24, :31-41, :82-84, :102-109, :124-126; `README_AGENT_FORGE.md:122`; `docs/REQUIREMENTS_TRACEABILITY.md:37` | "through 2026-09-15"; 36 commits; "$0.20 measured"; "$1 to $15"; "none is set yet"; unmeasured node arithmetic; "scales linearly" | Recounted commits and hours through 2026-09-20; both Droplets' hours; eval-run spend from the scorecards; threshold $0.0223 with a 2x block; measured capacity; per-tier table |
| 22 | `evals/run.py:647` and every report line 23; `KEY_METRICS.md:27`, :74, :91; `README_AGENT_FORGE.md:266`; `evals/README.md:52`; `docs/DEMO_SCRIPT.md:26` | cost gate NOT CONFIGURED; "to be set"; "about two cents a turn" | Gate configured Thursday; "between one and two cents a turn" |
| 23 | `ARCHITECTURE.md:574-579`, :599-602; `KEY_METRICS.md:32-39`; `docs/REQUIREMENTS_TRACEABILITY.md:30`; `docs/SUBMISSION_CHECKLIST.md:61-64`; `docs/operations/langfuse-dashboard.md:20-30` | "worker count sized after the load test"; dashboard shows verification outcome | One asyncio process by design, scale by container; `copilot_turns_in_flight` is the queue depth; verification pass-rate and turn-error panels added Friday (or "pending" if not) |
| 24 | `ARCHITECTURE.md:606-612`, :78-80; ADR-0007:116-118; `docs/operations/alerts.md:141-145`, :201; `docs/REQUIREMENTS_TRACEABILITY.md:31` | alerts job "planned", forbidden counted as failures | Runs as the `alerts` compose service every 300 s; forbidden denials excluded; rehearsal log path |
| 25 | ADR-0005:139-140; `docs/api-collection/README.md:17-18` | "reused jti ... 403" verified; "bound to one turn" | Single use not enforced in Week 1; a ticket is valid for 90 s and outlives logout by at most that |
| 26 | ADR-0005:128-130, :143-144; `ARCHITECTURE.md:851`; `README_AGENT_FORGE.md:140` and `agent/README.md:32` | checkpoint-content test claimed / still to add; "60 passed" | Test name and the new pytest count |
| 27 | `docs/deployment/digitalocean.md:127-147`, :307-316, :381-387; `SETUP.md:239-240`, :255-257; `README.md:16-19`; `README_AGENT_FORGE.md:243-245`, :267; ADR-0001 status | "Current Deployment (2026-09-16)", "no backups", disposable-cycle recovery | Final tag, commit, image digests, rollback command, backup/restore/snapshot procedure, egress and hostname outcomes |
| 28 | `docs/SUBMISSION_CHECKLIST.md:86-92`, :123-137, :139-148; `docs/PROJECT_PLAN.md:199`, :218-245; `docs/REQUIREMENTS_TRACEABILITY.md:39-41` | pipeline 23777 on 3415bac; final section unticked; rows "pending / not started" | Final pipeline id; every line ticked with a timestamp or an explicit "not done"; final demo, interview and post links |
| 29 | `KEY_METRICS.md:26`; `ARCHITECTURE.md:565-567`; `docs/operations/alerts.md:32-33` | "for the early submission" latency wording | State whether the 30 s p95 is confirmed or revised for the final |
| 30 | All 202 "2026-09-16" status lines outside `evals/results` (`USERS.md`, `AUDIT.md` §2.2 and §9, seven ADR status notes, `INTERVIEW_NOTES.md:38`, `PROJECT_PLAN.md:202`, `langfuse-dashboard.md`, `evals/README.md:97-98`, `PRIOR_COHORT_LESSONS.md`) | dated Wednesday | Updated, or "unchanged as of 2026-09-20" |

---

## Numbers to have memorized

1. 45 cases, 44 passed, 1 non-blocking recall miss (`CONF-NOTE-VS-LIST-N-001`), every blocking gate PASS, Golden set integrity 14/14, citations 177/177 (`evals/results/2026-09-17T024919Z-a4a5856.md`).
2. Latency on 40 model-backed turns: p50 12.5 s, p95 24.1 s, p99 30.7 s; first turns p95 16.0 s, follow-ups p95 29.7 s; provisional thresholds warn 30 s, block 45 s (`KEY_METRICS.md:87`).
3. Cost: $0.0127 per model-backed turn at list price, 2.33 model calls, about 628 in / 1,172 out / 4,759 cache-read tokens; projection basis $0.0223, about $11 to $20 per physician per month at 880 turns (`AI_COST_ANALYSIS.md`).
4. Stability: 114/116 over 44 cases x 3 at 1ddf824; both flips were recall checks.
5. Suite shape: 14 golden, 4 holdout, 9 authorization cases, 11 categories, 26 cohort patients, 7 tools, 9 claim types, 60 pytest tests, 21 Bruno requests.
6. Repair rate 32.5% (13 of 40 turns), withheld 2.6%, claims per turn 3.75; 213 tool calls per full run, 7 unavailable of which 6 forbidden.
7. Audit: 4 of 310 service classes used, 12 chart sections, 1,045 SQL statements per dashboard load, 169 KB about 42K tokens for the five-year chart; the `aclCheckIssue` fail-open found on the first live role test (`AUDIT.md` §8).
8. Infrastructure: one s-2vcpu-4gb Droplet at $0.03571 per hour since 2026-09-15 19:12 UTC, CI runner $0.00893 per hour since 2026-09-16, Apache prefork `MaxRequestWorkers` 250, `tool_concurrency` 6, gateway timeout 2.0 s, daily halt 2,000,000 tokens (about 1,100 turns), 10 turns per minute per conversation. Fill in the 10- and 50-user p95, error rate and peak CPU/memory from Saturday's report before both AI interviews.

---

## Dropped as already done or out of scope

- README grader pointer: `README.md:1-22` already opens with the challenge banner linking `README_AGENT_FORGE.md`, the live URL and `SETUP.md`; only line 8 is stale (row 6).
- "Sync the GitHub fork": both remotes are at e1dd331 with tag `week1`; only the checklist sentence is wrong (row 5).
- Terraform state and plan files committed: all gitignored and untracked; only the workstation copies need backing up.
- "Rotate the GitLab PAT before the Sunday push" as P0: the URL-embedded token is valid to 2026-10-14, so pushes work; kept as a P1 hygiene item.
- Summary-gate and hedge-canary "add" items: `verify_summary` and the near-miss measure already exist; only the canary's false positives remain (P2, deferred).
- Langfuse v2 API migration: no eval script calls the endpoint; one line in the handoff note.
- Installing the alerts cron, resizing the Droplet, changing `tool_concurrency`, adding a global turn semaphore, re-provisioning or running `destroy.sh` / `smoke-cycle.sh` on 137.184.4.22 before the load test: each touches the early-submission deployment without a baseline; the compose service replaces the cron.
- Wiring `fault == 'tracer'` into telemetry, the agent-side checkpoint deleter, a parity LimitationKind, `unsupported_principal` as a new reason, Haiku for planning, first-pass rejection capture, gold source ids, five new golden cases, a second manual CI job, single-use tickets, TTFE `--stream`, `INDEX.md`, the Week 2 gate recipe: Week 2 scope.
- Root-causing the "no cited record mentions the medication" rejection: not recoverable from results today (successful repairs erase their trigger); reframed as the Saturday note.
- Re-proposing SMART, care-relationship authorization or a different runtime: settled by ADR-0002/0003/0004.
- Fixing OpenEMR itself (`aclCheckIssue` fail-open, `readyz` routing, prefork sizing): project rule; designed around and documented.
