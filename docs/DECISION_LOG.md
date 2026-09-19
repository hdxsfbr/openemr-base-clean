# Decision Log

Ranked by impact on the project. Compiled from all Claude Code sessions under
`gauntletai/week1` (top level and `openemr-base-clean`, including worktrees),
2026-09-14 through 2026-09-19. Sessions that were pure lookups or recaps with
no new decisions (e.g. "GitLab repo URL," "Skill doctor," "System design
plan," "Clinical copilot overview") are omitted.

## Tier 1 — Foundational architecture (hardest to reverse, shaped everything downstream)

1. **In-process module gateway over SMART on FHIR/OAuth** (ADR-0003) — SMART
   would've cost 2-3 days of plumbing and ~1s vs 1-25ms latency; explicitly
   avoided the prior cohort's biggest time sink on a one-week build. Interface
   still designed "SMART-shaped" so the boundary can migrate later without
   touching the agent/verifier/evals.
2. **Chart-parity authorization over a stricter schedule/care-team rule**
   (ADR-0002, alternative recorded not built) — ships in ~1 day vs ~1 week;
   accepted because bulk-extraction risk is low with one patient per
   conversation.
3. **Vertical/Docker-only scaling architecture, rejecting OpenEMR's
   recommended horizontal scaling** — budget-driven; every later scaling test
   (droplet tiers, batching, FPM) builds on this topology rather than
   load-balancer/multi-node infra.
4. **LangGraph adopted from Week 1** (not deferred to Weeks 2-3) so the
   supervisor/worker, ingestion, and RAG work planned for later extends the
   same graph instead of replacing it.
5. **Break-glass users denied co-pilot access entirely, not gated** — PRD
   doesn't cover emergency access, and an AI summarizer would amplify
   bulk-browsing risk during an undetected break-glass session.

## Tier 2 — What "working" means (release-gate definition)

6. **Home-grown deterministic YAML+Python eval runner, rejecting
   promptfoo/DeepEval/Inspect/Ragas/Langfuse** — the system grades
   multi-step authorization/session behavior, not single-string I/O, and the
   PRD forbids LLM-as-judge in the pass rate.
7. **Release-gating metrics fixed**: 0% unsupported claims, ≥99% citation
   correctness, 0 authorization leakage, ≥90% task success, 100% uncertainty
   recall/safe degradation — each chosen to be hard to game.
8. **5-state gate vocabulary** (PASS/FAIL/NOT RUN/NOT MEASURED/NOT
   CONFIGURED), only PASS counts green; missing coverage = blocking, not
   silently skipped.
9. **Golden-set (14 must-pass) + 4-case holdout split**, deterministic-only
   grading; LLM-as-judge/rubric grading explicitly deferred past submission
   to avoid eval-overfitting.
10. **External code-review findings on the eval harness accepted wholesale**
    — required positive assertions per blocking case, relabeled "citation
    correctness" → "citation resolution" pending real gold IDs, required
    same-commit `--repeat 3` stability runs before trusting the gate table.

## Tier 3 — Scope & execution control

11. **Final push scoped to P0+P1 only**, with a hard never-cut list (rollback
    rehearsal, cost gate, freeze, Sunday submit) and explicit exclusions
    (model/prompt experiments, egress firewall, owned hostname) documented as
    limitations rather than built.
12. **7-workstream, milestone-gated (M1-M5) parallel-agent orchestration**
    with exclusive file ownership + a pending-delta protocol — prevents
    agents from clobbering shared docs.
13. **Rehearsal-first load testing**: isolated Terraform workspace never
    touching prod, free fault-mode sweeps to bracket ranges, real-model runs
    only at 2-3 candidate tiers — after discovering fault-mode silently
    skips real tool-gateway load.

## Tier 4 — Infra/deployment, evidence-driven corrections

14. **Dedicated $6/mo GitLab runner droplet, project-scoped** — isolates CI
    execution risk from both the live demo droplet and the personal
    workstation (Docker socket = root + live creds).
15. **Live-eval CI job kept manual, not automatic per push** — each run costs
    ~$0.55/~15min against the live deployment.
16. **PHP-FPM tuning hypothesis rejected outright** once live verification
    showed the container runs mod_php/Apache prefork, not FPM at all —
    decided on direct evidence over the earlier assumption.
17. **Tool-gateway batching accepted as a reliability fix, not a capacity
    fix** — real-model load data showed the ~10-user ceiling unchanged
    despite better failure quality; tier upgrade (vertical) confirmed as the
    actual next lever.
18. **DO droplet kept running through the interview window** at default size
    rather than smoke-test-and-destroy; destroyed immediately after since
    DigitalOcean has no pause — cost tradeoff made explicit each time.
19. **Co-pilot drawer session-pinning fix, found by live cross-window
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

## Tier 5 — Process, governance, submission logistics

20. Docs reorg: only PRD-named deliverables stay at repo root; self-authored
    planning docs moved to `docs/`.
21. GitHub fork treated as the PRD-required submission repo while GitLab
    stays the working system of record — flagged explicitly to avoid mixing
    the two up.
22. Evaluator access handled via sanitized screenshots + out-of-band
    credentials rather than live Langfuse viewer accounts (avoids
    email-invite friction and leaking PII in a trace view).
23. Declined to rewrite git history to strip AI-attribution trailers;
    standardized `Co-Authored-By` + `Assisted-by: Claude Code` on all commits
    going forward.
