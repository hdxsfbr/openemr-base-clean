# Social Post (LinkedIn and X)

Published by the owner after the final video is uploaded (plan M5, "Owner-only":
Saturday night or Sunday 06:00 PT, with the 20 to 30 s clip). Replace
`<final video URL>` in both versions before posting. Links go to the public
GitHub fork only; the lab GitLab is login-only and is never linked. Every
number below exists today and is cited to
`evals/results/2026-09-20T051146Z-0f11642.md` (48 cases x 3 attempts, 123 of
124 passed, golden 29/29, citations 615/615, p95 15.8 s, $0.0104 per
model-backed turn). If the
release run at the final commit changes them, update the numbers here from
that report before posting; never round a number up.

The audit lesson is true as written: OpenEMR's `AclMain::aclCheckIssue()`
returns true whenever the issue-type table is not loaded at page scope, which
is the case in the gateway's session-less request. On 2026-09-15 the first
live role test showed Front Office receiving problems and allergies through
the co-pilot. The gateway now reads `issue_types.aco_spec` itself and fails
closed when a spec is missing
(`interface/modules/custom_modules/oe-module-copilot/src/Gateway/ContextBuilder.php`,
`sectionMatrix()`, comment at lines 94 to 100; commit `2dc51a0`). It is
recorded in `AUDIT.md` under the SEC-HIGH-001 remediation row and in section
9, Residual Risk.

## LinkedIn

90 seconds between patient rooms. That is the window a physician has to
remember what changed since the last visit, and it is where I spent Week 1
of @GauntletAI.

What I built: a read-only co-pilot that lives inside the OpenEMR chart. It
retrieves the chart through OpenEMR's own access checks, the model writes
claims, and a deterministic verifier checks every claim against the retrieved
records before anything renders. Every statement cites a chart record, and
the citation opens the record. Missing data stays "not documented", never
"none". Dosing questions are out of scope by design.

Numbers from the tracked release run at commit 0f11642, every case run three
times against the live deployment:
- 48 eval cases in three tiers, 123 of 124 attempts passed; the golden set 29/29
- 615 of 615 citations resolved to a retrieved record
- p95 latency 15.8 s per model-backed turn
- $0.0104 per turn at list price
- load tested at 10 and 50 concurrent users, with the ceiling measured in
  OpenEMR's own Apache and MariaDB rather than in the agent

The audit lesson I keep: OpenEMR's issue-section ACL helper,
AclMain::aclCheckIssue(), fails open when its type table is not loaded at page
scope, which is exactly the case in a session-less gateway request. The first
live role test caught Front Office receiving problems and allergies. The
gateway now reads the same issue_types.aco_spec the chart uses and fails
closed. Read the framework's helpers before trusting them.

Synthetic cohort only; no real patient data anywhere. Code and audit:
https://github.com/hdxsfbr/openemr-base-clean
Demo: <final video URL>

## X

<!-- x-start -->
90 seconds between patient rooms. Read-only OpenEMR co-pilot: every claim cites a chart record and a deterministic verifier checks it. 48 evals x3, 615/615 citations resolved, 1.04 cents/turn. @GauntletAI https://github.com/hdxsfbr/openemr-base-clean <final video URL>
<!-- x-end -->

Character count commands (run from the repository root). The markers are
matched as whole lines, so the commands do not count themselves. The first
prints the raw count of the text above, placeholder included; it must be
under 280, and it stays under 280 with a 28-character `https://youtu.be/...`
link in place of the 17-character placeholder. The second prints the count X
applies (every URL, and the placeholder standing in for one, weighs 23
characters under t.co wrapping); that is the governing number for a longer
link such as `https://www.youtube.com/watch?v=...`. Re-run both after
replacing the placeholder.

```bash
sed -n '/^<!-- x-start -->$/,/^<!-- x-end -->$/p' docs/SOCIAL_POST.md | sed '1d;$d' | tr -d '\n' | wc -m
sed -n '/^<!-- x-start -->$/,/^<!-- x-end -->$/p' docs/SOCIAL_POST.md | sed '1d;$d' | tr -d '\n' | sed -E 's#https?://[^ ]+#XXXXXXXXXXXXXXXXXXXXXXX#g; s#<final video URL>#XXXXXXXXXXXXXXXXXXXXXXX#' | wc -m
```
