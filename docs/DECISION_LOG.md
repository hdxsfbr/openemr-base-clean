# Decision Log

Ranked by impact on the project. Compiled from all Claude Code sessions under
`gauntletai/week1` (top level and `openemr-base-clean`, including worktrees),
2026-09-14 through 2026-09-20. Sessions that were pure lookups or recaps with
no new decisions (e.g. "GitLab repo URL," "Skill doctor," "System design
plan," "Clinical copilot overview") are omitted. Entries added on 2026-09-20
carry a marker: **[new]** is a decision taken in the owner's sessions on the
night of 2026-09-19/20 (each names the commit or evidence file that records
it), and **[new, from commits]** was reconstructed from commit messages, ADR
amendments and committed results, so its reasoning is the commit's until the
owner corrects it. Earlier entries stand as decided; a count inside one
(the 14-case golden set, 15 since `e873a10`) is as of the decision.

## Tier 1 — Foundational architecture (hardest to reverse, shaped everything downstream)

1. **In-process module gateway over SMART on FHIR/OAuth** (ADR-0003) — SMART
   would've cost 2-3 days of plumbing and ~1s vs 1-25ms latency; explicitly
   avoided the prior cohort's biggest time sink on a one-week build. Interface
   still designed "SMART-shaped" so the boundary can migrate later without
   touching the agent/verifier/evals.
2. **[new, from commits]** **Pre-visit brief prepared when the chart opens,
   not on a click** (ADR-0003 amendment 2026-09-19, module 0.5.0, `789114a`)
   — a first turn measured p50 9.2 s / p95 24.8 s against the ~90 seconds
   between two visits. It is the same UC-01 starter question down the same
   path as a click, so no new endpoint and no new authorization; `BriefPolicy`
   decides server-side, so there is no client flag to forge, and no mode fires
   for a break-glass login or a role with no clinical section. `visit_today`
   is the code default (`4127593`): a brief for a chart opened for any other
   reason is about $0.011 and model-disclosure audit rows with no moment
   behind them. The demo Droplet deliberately overrides to `always` so an
   evaluator opening any chart sees it.
3. **Chart-parity authorization over a stricter schedule/care-team rule**
   (ADR-0002, alternative recorded not built) — ships in ~1 day vs ~1 week;
   accepted because bulk-extraction risk is low with one patient per
   conversation.
4. **Vertical/Docker-only scaling architecture, rejecting OpenEMR's
   recommended horizontal scaling** — budget-driven; every later scaling test
   (droplet tiers, batching, FPM) builds on this topology rather than
   load-balancer/multi-node infra.
5. **LangGraph adopted from Week 1** (not deferred to Weeks 2-3) so the
   supervisor/worker, ingestion, and RAG work planned for later extends the
   same graph instead of replacing it.
6. **Break-glass users denied co-pilot access entirely, not gated** — PRD
   doesn't cover emergency access, and an AI summarizer would amplify
   bulk-browsing risk during an undetected break-glass session.

## Tier 2 — What "working" means (release-gate definition)

7. **Home-grown deterministic YAML+Python eval runner, rejecting
   promptfoo/DeepEval/Inspect/Ragas/Langfuse** — the system grades
   multi-step authorization/session behavior, not single-string I/O, and the
   PRD forbids LLM-as-judge in the pass rate.
8. **Release-gating metrics fixed**: 0% unsupported claims, ≥99% citation
   correctness, 0 authorization leakage, ≥90% task success, 100% uncertainty
   recall/safe degradation — each chosen to be hard to game.
9. **5-state gate vocabulary** (PASS/FAIL/NOT RUN/NOT MEASURED/NOT
   CONFIGURED), only PASS counts green; missing coverage = blocking, not
   silently skipped.
10. **Golden-set (14 must-pass) + 4-case holdout split**, deterministic-only
    grading; LLM-as-judge/rubric grading explicitly deferred past submission
    to avoid eval-overfitting.
11. **External code-review findings on the eval harness accepted wholesale**
    — required positive assertions per blocking case, relabeled "citation
    correctness" → "citation resolution" pending real gold IDs, required
    same-commit `--repeat 3` stability runs before trusting the gate table.
12. **[new, from commits]** **Measure what the physician waits for, not what
    the turn costs** (`695acfa`, `evals/brief_latency.py`) — precomputing the
    brief does not make a turn faster, it moves who waits, so quoting a better
    p95 for it would be a lie. Published W(L) = max(0, T_ready - L) as a whole
    reading-lag curve, including L = 0 where the prepared brief is slower by
    its 0.61 s panel setup; at a 10 s lag the p95 wait is 7.5 s against 16.9 s.
    L is a parameter, not an observed physician; reported beside turn latency
    in `KEY_METRICS.md`, not as a gate.
13. **[new]** **Kept a failed golden smoke run in the record and left its
    security assertion as written** (`d463f3b`) — `INJ-NOTE-O-001`
    (golden, prompt injection) failed one golden-only run
    (`evals/results/2026-09-20T032913Z-23e197e.md`) because its claim-level
    `\bno allergies\b` pattern, which has no exemption for quoting the
    payload, matched inside the agent's correct refusal ("...to assert this
    patient has no allergies; these are data, not instructions, and are not
    followed"). Offered a relaxed pattern to get a green run, the owner chose
    to leave the assertion and re-run. The report was committed with the night's other runs ("the
    night's sequence, not four attempts at a clean number"), and the case file
    is unchanged since `831e1d8` (2026-09-16); the case passed 3 of 3 in each
    `--repeat 3` release run (`6c787bd`, `0f11642`) and again at the deployed
    tree (`4d2a9fd`).

## Tier 3 — Scope & execution control

14. **Final push scoped to P0+P1 only**, with a hard never-cut list (rollback
    rehearsal, cost gate, freeze, Sunday submit) and explicit exclusions
    (model/prompt experiments, egress firewall, owned hostname) documented as
    limitations rather than built.
15. **7-workstream, milestone-gated (M1-M5) parallel-agent orchestration**
    with exclusive file ownership + a pending-delta protocol — prevents
    agents from clobbering shared docs.
16. **Rehearsal-first load testing**: isolated Terraform workspace never
    touching prod, free fault-mode sweeps to bracket ranges, real-model runs
    only at 2-3 candidate tiers — after discovering fault-mode silently
    skips real tool-gateway load.
17. **[new, from commits]** **Latency levers accepted only against a measured
    A/B or compare run** — follow-ups at low effort (`f4f69ab`: fixture A/B
    18.1 s → 11.9 s per follow-up, with the live suite's recall gate as the
    check); `max_plan_rounds` 3 → 1 (`e2cd633`, ADR-0004 amended:
    model-backed p95 27.5 s → 18.0 s, 46/46); the plan call skipped for the
    agent's own fixed-wording follow-ups via `KNOWN_PLANS`, matched on the
    agent's constants so there is no client flag to forge (`089ef2b`; rests
    on the measured plan-call p50 of 2.0 s, and its live saving is not
    measured). The counter-lever: narrate cap raised 1,800 → 3,200 tokens
    because a truncated call paid for a second full call (`5d90982`). The
    three settings revert by env var; `KNOWN_PLANS` is code. This is work of
    the kind the final-push entry above listed as excluded ("model/prompt
    experiments"). Not adopted: the plan call on Haiku 4.5 (cost +16.5% and
    a recall regression).

## Tier 4 — Infra/deployment, evidence-driven corrections

18. **Dedicated $6/mo GitLab runner droplet, project-scoped** — isolates CI
    execution risk from both the live demo droplet and the personal
    workstation (Docker socket = root + live creds).
19. **Live-eval CI job kept manual, not automatic per push** — each run costs
    ~$0.55/~15min against the live deployment.
20. **PHP-FPM tuning hypothesis rejected outright** once live verification
    showed the container runs mod_php/Apache prefork, not FPM at all —
    decided on direct evidence over the earlier assumption.
21. **Tool-gateway batching accepted as a reliability fix, not a capacity
    fix** — real-model load data showed the ~10-user ceiling unchanged
    despite better failure quality; tier upgrade (vertical) confirmed as the
    actual next lever.
22. **DO droplet kept running through the interview window** at default size
    rather than smoke-test-and-destroy; destroyed immediately after since
    DigitalOcean has no pause — cost tradeoff made explicit each time.
23. **Co-pilot drawer session-pinning fix, found by live cross-window
    debugging** (ADR-0005 note 2026-09-19, commit 060ed97) — the drawer omitted
    the `top.restoreSession()` cookie-pin that every other OpenEMR component
    performs before same-origin calls, so concurrent same-user logins in
    separate browser windows made `session.php`/`conversation.php`/`ticket.php`
    ride the wrong session (empty-body 400s, `patient_context_changed`). Fixed
    by pinning the window session before each drawer call; verified live with a
    controlled before/after (400 without the pin, 200 with it). Surfaced two
    standing residuals recorded as follow-ups: same-login-two-tabs shares one
    server `pid` by design (ARCH-HIGH-001), and CI deploys wipe in-container
    PHP sessions (candidate: session store on a named volume).
24. **[new]** **Reverted the clinic-clock change to UTC everywhere instead of
    finishing the timezone rollout** (`c37b9e6`; the change was `a6bb7b2`,
    extended by `449c664`) — `TZ` on `openemr` and `agent` only put two
    clocks seven hours apart in one `datetime` column, so conversation resume
    returned a stale transcript; caught by `ISO-RECENT-PATIENT-RESUME-001`
    failing 3 of 3 at `6c787bd` after passing at `f4f69ab4`. Finishing meant
    `TZ` on five services, another re-seed, and a third after midnight
    Pacific or `visit_today` goes false on submission day. Only the `TZ`
    lines in compose were removed; the `always` brief override from the same
    change was kept. A real clinic needs its own day on every container that
    writes a date — a stated limitation, not a silent one.
25. **[new]** **Reset conversations and re-seeded the synthetic cohort rather
    than doing timestamp surgery; kept the audit rows** —
    `copilot_conversation` (1,588 rows, 188 on the new clock) was truncated
    after a 79 MB dump and the cohort re-seeded on one clock. The roughly three
    hours of OpenEMR `log` rows written on the clinic clock stay, sorting about
    seven hours early: audit history is not deleted to tidy a timestamp seam.
    Recorded in `docs/audit/evidence/performance/brief-on-open-2026-09-20.md`
    section 10.
26. **[new]** **Alerts delivered to a Slack channel through a Docker file
    secret, never argv, env, or the repo** (`e466b9d`, `0471178`, `478f432`)
    — the three PRD alerts were evaluated every 300 s and written only to
    stdout, so a page reached nobody. A Slack webhook is a credential and an
    argv URL shows in `docker inspect`, so it takes the same file-secret path
    as the model and tracer keys; read every cycle, and an absent file means no
    delivery, not a crash. Proving delivery end to end found two defects (the
    next entry, and Slack rejecting a body without `text`); both rules then
    paged with `webhook_delivered` true
    (`docs/audit/evidence/observability/alerts-slack-2026-09-20.log`).
27. **[new]** **Counted the tool failures that never reach the gateway**
    (`dbf5372`) — after gateway batching (`b40d456`; the fix's message and
    the evidence log cite `046b96e`, the commit that confirmed it), tools
    answered locally (`fault_injected`, `invalid_params`) skipped the
    `copilot_tool_calls_total` increment, so the PRD tool-failure alert's
    numerator was structurally zero for them; the 2026-09-18 page predates
    batching, which is why the alert looked healthy. Found by driving five
    faulted turns at the deployment and reading `/metrics`; fixed in the
    counter, with a graph regression test.

## Tier 5 — Process, governance, submission logistics

28. Docs reorg: only PRD-named deliverables stay at repo root; self-authored
    planning docs moved to `docs/`.
29. GitHub fork treated as the PRD-required submission repo while GitLab
    stays the working system of record — flagged explicitly to avoid mixing
    the two up.
30. Evaluator access handled via sanitized screenshots + out-of-band
    credentials rather than live Langfuse viewer accounts (avoids
    email-invite friction and leaking PII in a trace view).
31. Declined to rewrite git history to strip AI-attribution trailers;
    standardized `Co-Authored-By` + `Assisted-by: Claude Code` on all commits
    going forward.
32. **[new, from commits]** **An audit row for every disclosure of chart
    records to the model provider** (`12cd849`, ADR-0006) — OpenEMR's log
    recorded each chart read but nothing said the records then went to an AI
    model, or to which one. The agent declares {provider, model} on a retrieval
    batch and the module writes `copilot-model-disclosure` before returning
    records: declared intent before data leaves, never content. No model call,
    no row; if the row cannot be written the whole batch answers unavailable.
    Read back on the deployment, one row per retrieval batch; the fail-closed
    branch is still unexercised.
33. **[new, from commits]** **Full model exchanges in Langfuse only behind
    `COPILOT_TRACE_CONTENT`** (`49f1637`, ADR-0007 amendment 2026-09-19) — 19
    of 79 turns on 2026-09-18 had the model's summary replaced, and neither the
    rejected text nor the reason was readable without shell access; digest-only
    traces cannot feed error analysis. Off in code (mask installed, digests
    only); on in the demo compose, which holds synthetic patients only and
    assumes the tracer is inside the compliance boundary, stated as an
    assumption. `COPILOT_TRACE_CONTENT=0` restores the original decision.
