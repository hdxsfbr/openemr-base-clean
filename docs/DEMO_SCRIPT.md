# Demo Script (3 to 5 minutes), final recording

For the owner to record (still open as of 2026-09-20), after the M5 release
run (`docs/FINAL_PUSH_PLAN.md`, MILESTONE M5 step 3) and the single-pass
re-verification at the deployed tree. Every proof point in
`docs/SUBMISSION_CHECKLIST.md` "Demo Proof Points" appears once, in this
order. Times are targets.

Early-submission recording (2026-09-16): <https://youtu.be/oxm9xqJpiY8>.

**Placeholders: none left.** Every number in this script is measured and
recorded as of 2026-09-20 — load and baselines from 2026-09-18, the alerts and
rollback rehearsals from the same day, and the Slack alert delivery, the
release run (`evals/results/2026-09-20T051146Z-0f11642.md`) and the single
pass at the deployed tree (`evals/results/2026-09-20T064022Z-4d2a9fd.md`)
from 2026-09-20. The baseline the release run is compared against is
`evals/results/2026-09-17T024919Z-a4a5856.md`. Read them as written. If a
number here disagrees with what is on screen while recording, stop and fix
the script rather than saying the screen's number. For anything that has no
number, say "not measured" on camera. Never guess.

Before recording: log in as `audit-physician` in one tab, open AF-DQ-A2
(pid 900001), and have Langfuse open in a second tab with the project's
trace list filtered to the last hour. Keep a terminal ready with
`ssh deployer@137.184.4.22`, and a second terminal in the repository checkout
on `main` showing the two identity commands below; their output stays on
screen for the whole opener and the whole close.

```bash
git log -1 --format=%h -- agent interface/modules/custom_modules/oe-module-copilot infra ':!*.md'   # 478f432
git tag -n3 week1-final   # the tag message names 478f432 as the deployed tree
```

**The commit and the tag.** The deployed runtime tree is `478f432`, the last
commit that touches anything but Markdown under `agent/`, the module, or
`infra/`. Every commit after it changes only docs and eval results, so
whichever of them was deployed last (by hand, or by `deploy:production` in
`.gitlab-ci.yml`, which runs on every push to `main`), the running code is
`478f432`'s: the first command keeps printing `478f432`, and
`git diff --stat 478f432 week1-final -- agent interface/modules/custom_modules/oe-module-copilot infra evals/cases evals/fixtures ':!*.md'`
prints nothing. The `':!*.md'` pathspec keeps a docs edit under `agent/`
(`agent/README.md`) from reading as a runtime change. `week1-final` is an
annotated tag on `main`, created 2026-09-20; its message reads "Deployed tree
= 478f432 ... this tag differs only in docs and eval results. Pipeline 24351
green." As of this edit it points at `ebaae17`. `git describe --tags
--exact-match` prints `week1-final` only while `main` HEAD is the tagged
commit, and any later docs-only commit (the one carrying this edit included)
moves HEAD past it, so show the tag by name with `git tag -n3`, not with
`describe`. If the tag is moved forward over later docs-only commits, its sha
changes and its message must still name `478f432`.

| Time | On screen | Say | Proof point |
| --- | --- | --- | --- |
| 0:00 | Terminal on `main` with the two identity commands from "Before recording": runtime-tree commit `478f432`, and `git tag -n3 week1-final`; `README.md` challenge header | "Since the early submission on the sixteenth, same read-only co-pilot, more evidence. The deployed runtime tree is commit `478f432`, and that is what you are seeing; the submission tag `week1-final` sits a few commits later and differs only in docs and eval results, so the code that runs is byte-identical." Then the code lines. Each of these landed (`docs/_status/week1-final-push.md`, WS-AGENT and WS-INFRA rows) and is in the deployed tree, so say all of them: "The readiness probe now reaches the tracer instead of assuming it (A1). Queue depth, verification outcome, and tool-failure reasons are exported (A2, A3, A5). Dependencies are pinned (A6). An alerts service evaluates the metrics every five minutes (I1)." Then the evidence lines. Both conditions are met (the Timings table in `docs/deployment/digitalocean.md` "Rehearsal Runbook" has T4 and T6 filled in, rehearsed 2026-09-18, and `docs/audit/evidence/performance/load-test-2026-09-18.md` has both levels), so say both: "Backup and rollback were rehearsed on a throwaway host. Load at ten and fifty users is measured." | context; commit and tag |
| 0:30 | Open the AF-DQ-A2 dashboard and let it load, then click the **Clinical Copilot** menu item; the drawer opens on a brief that is already finished, or on its last progress step | "Physician, 90 seconds before a visit. The brief starts when the chart opens, so it is waiting instead of being typed for. It retrieves six sections through OpenEMR's own access checks, the model writes claims, and a deterministic verifier checks every one against the records before anything renders." *(The Droplet's compose file sets `COPILOT_BRIEF_ON_OPEN=always`, a demo-box override; the module's own default is `visit_today`, a brief only for a chart with a visit today. On AF-DQ-A2 a brief took 17.5 s p50, 19.0 s at most, from chart open — three briefs, `docs/audit/evidence/performance/brief-latency-2026-09-19.md` — so give the dashboard about 20 s before opening the drawer. A retake does not get a new brief by waiting a minute or using a new tab: a chart whose conversation had a turn in the last 30 minutes (`ConversationRepository::IDLE_MINUTES`) restores that transcript on open, under an "Earlier in this session" divider with the brief drawn as a typed question, and the panel has no control that ends a conversation. The set-up step above opens AF-DQ-A2 and so starts its brief; either keep that page loaded and only open the drawer on camera, or leave the chart alone for 30 minutes first. Separately, one tab starts at most one brief per 60 s, on any chart. Do not say "nothing is retrieved until I ask": it is retrieved under the same session, ticket, ACL and audit path as a click, one chart, the one on screen. With `COPILOT_BRIEF_ON_OPEN=off` the original click flow and that line both come back.)* | normal sourced workflow; no wait at the moment of need |
| 0:55 | Answer: narrative summary, one compact collapsed **Sources & details** control, "Verified" badge | "The answer stays readable; the supporting records and limitations are one click away." | progressive disclosure |
| 1:05 | Expand **Sources & details** and click a citation on the amlodipine conflict; the medication opens in OpenEMR | "Citations open the original record. This one is a conflict: end date and activity flag disagree, and it says so instead of guessing." | per-claim citation; click-through to source; conflict state |
| 1:25 | Click a follow-up chip such as "Was the amlodipine status change documented in a note?" | "Follow-ups keep the window and chain more tools: this one planned a note search." | multi-turn, more than one tool |
| 1:45 | Switch to AF-DQ-I (pid 900012); with the brief prepared on open the first question is already asked, so give the chart about 10 s (6.6 s p50 on this chart, same evidence file) and open the drawer, or ask the first question if the drawer opens empty (`COPILOT_BRIEF_ON_OPEN=off`, or this tab started the AF-DQ-A2 brief less than 60 s earlier: the guard is per tab, not per chart); point at "Allergies not documented" | "Missing data stays missing. This chart has no allergy review, so the answer says not documented, not 'no allergies'." | honest missing-data response |
| 2:05 | Log in as `audit-frontdesk` in another window, open AF-DQ-A2, ask the first question | "Front Office sees demographics in the chart and nothing clinical. The gateway denies each section before any model call, and the audit log records it." | authorization denial before LLM |
| 2:30 | Terminal: run the Bruno "Tool outage" request, or curl with `X-Copilot-Fault: tool:lab_results` | "Fault injection: the lab tool is down. The section is marked unavailable, nothing claims labs are absent, and the rest of the brief still renders." | visible partial behavior during a tool failure |
| 2:50 | Expand **Sources & details**, copy the `ref` from its evidence line, and paste it into the Langfuse search | "One correlation id runs the whole path: drawer, ticket, gateway audit rows, agent logs, and this trace with nested tool, narrate, verify, and repair spans, token counts, and cost. This demo box captures prompt and answer content on the trace for error analysis, synthetic patients only; the code default masks every payload to a digest." *(The Droplet's compose file sets `COPILOT_TRACE_CONTENT=1`, ADR-0007 amendment 2026-09-19, so the trace on screen shows the evidence pack and the model's output. Do not say "no content leaves the agent" over that picture; that is the masked default, `COPILOT_TRACE_CONTENT=0`. If the trace on screen shows digests instead, say "payloads are masked to digests" and drop the content sentence.)* | correlation id through observability |
| 3:15 | `evals/results/2026-09-20T051146Z-0f11642.md`, release-gate table at the top; beside it `evals/results/2026-09-20T051146Z-0f11642-vs-a4a5856.md` from `evals/compare.py`; then the gate table of `evals/results/2026-09-20T064022Z-4d2a9fd.md` | "Release run, all 48 cases, every live case three times: 123 of 124 attempts passed, the golden set 29 of 29 attempts, 615 of 615 citations resolved, every blocking gate PASS. Against the early-submission baseline: p95 twenty-four seconds down to sixteen, task success ninety-five percent to a hundred, cost 1.27 cents a turn down to 1.04. The one miss is a holdout case where the model called a duplicate medication a duplicate instead of a possible one — the hedging rule caught it, and it passed the other two attempts. The alert fixes shipped after that run, so a full single pass re-verified the deployed tree: 48 of 48, every blocking gate PASS." (10 s; the release run executed when `c37b9e6` was deployed, runtime byte-identical to `0f11642`; the single pass is labelled `4d2a9fd`, runtime byte-identical to `478f432`. Do not call the release run "at the final commit" or "at the deployed tree". The baseline's 1.27 cents is the figure `a4a5856` printed, which is what the compare file on screen shows; recomputed after the 2026-09-17 pricing fix it is $0.0139, `evals/README.md`.) | eval results |
| 3:25 | `docs/audit/evidence/performance/load-test-2026-09-18.md` and `baseline-2026-09-18.md` | "Ten users: turn p50 18.8 s, p95 45.0 s, p99 45.1 s, error rate 10 percent — both failures 504s on the heaviest chart. Fifty users: p50 8.3 s, p95 43.8 s, p99 45.0 s, error rate 5.6 percent, and the status share is the real story: 18 percent complete, 76 percent partial. Latency alone is gamed by falling back early, so we report the share. The control run with the model faulted out reproduced the same shape at zero model calls, which puts the ceiling in OpenEMR's Apache and MariaDB, not in the agent: at fifty users both peak over a full vCPU — openemr 103 percent, database 111 percent — while the agent peaks at 44. Idle baseline on the same Droplet: OpenEMR and the database under 7 percent CPU, 1.2 GB of memory in use. Memory was never the constraint." (15 s) | load, latency, baselines |
| 3:40 | `docs/operations/alerts.md` "Alert 1: turn latency"; terminal: `ssh deployer@137.184.4.22 'cd /opt/agentforge && docker compose logs --tail 5 alerts'`; then `docs/audit/evidence/observability/alerts-slack-2026-09-20.log`, "Result" | "Alert 1: p95 turn latency over a five-minute window warns above 30 seconds, pages above 45, or when p99 passes 60. The alerts service evaluates the agent's metrics every five minutes; this is its output, one heartbeat line when nothing fires, one JSON line per alert: `{"event": "alert", "name": "tool_failure_rate", "severity": "page", "message": "Tool medications returned unavailable on 100.00% of 5 calls; a service path is broken.", "threshold": 0.5, "value": 1.0}` — that one is real, fired against the live agent with five injected tool faults, and the denominator matches exactly. Delivery is real too: run again during the final push, the same fault reached the owner's Slack channel as a page, through a webhook read from a Docker secret." (10 s; the quoted JSON line is abridged from the 2026-09-18 rehearsal, `docs/audit/evidence/observability/alerts-rehearsal-2026-09-18.log` line 39, with `rate_window_seconds` and `ts` left out. Never put the webhook URL or `/run/secrets/slack_alert_webhook`'s contents on screen.) | alert rule, alerts service, and delivery |
| 3:50 | `docs/deployment/digitalocean.md` rehearsal section with the recorded timings | "On a throwaway Droplet we deployed clean, rolled back to tag `week1` in 2 minutes 36 seconds, rolled forward in 1 minute 13, and restored from an encrypted backup in about 3 minutes 19, then destroyed it the same day. The restore was proven to actually restore: a conversation created after the backup came back unknown afterwards." (5 s) | rollback rehearsal |
| 3:55 | `AI_COST_ANALYSIS.md` per-turn table, then the release-run gate table's "Cost per verified turn" row | "1.04 cents per model-backed turn at list price in the release run's eval mix, 1.13 in the single pass at the deployed tree. The release gate compares each run against the basis written in the cost analysis; both read PASS, against a 2.23-cent projection. The daily halt stops spend at 2,000,000 input-plus-output tokens; at a4a5856's 1,800 tokens per turn, that is about 1,100 turns." (10 s; the turn count is derived, not reported anywhere: 2,000,000 / (628 in + 1,172 out) = 1,111, from the a4a5856 "Tokens per turn" row, and the halt counts input plus output only, `agent/app/model.py` `Usage.total`) | cost with the gate's real state |
| 4:05 | Back on the drawer; terminal with the commit and the tag still visible (see "The commit and the tag" above) | "Read-only, cited, verified, audited, and honest about what the chart does not say. Runtime tree `478f432` deployed; submission tag `week1-final` on `main`." | close; commit and tag |

Cuts if over time: drop the follow-up chip (1:25), then the AF-DQ-I switch
(1:45). Never cut the eval, load, alerts, rollback, or cost rows, and never
take the commit off screen for the opener and the close.

Evidence to keep alongside the video: the release-run results file and its
`evals/compare.py` output against `2026-09-17T024919Z-a4a5856.json`, the
single-pass results file at the deployed tree, the load-driver JSON under
`evals/load/results/` with both baseline reports, the alerts rehearsal log
and the Slack delivery log, the Langfuse trace URL for the demonstrated ref
(private project; screenshot for evaluators without access), and the output
of the two identity commands at recording time together with
`git rev-parse week1-final^{commit}` on `main`, whose tag message names
`478f432`.
