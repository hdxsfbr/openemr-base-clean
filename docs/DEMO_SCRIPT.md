# Demo Script (3 to 5 minutes), final recording

Recorded by the owner after the M5 release run (`docs/FINAL_PUSH_PLAN.md`,
MILESTONE M5 step 3), Saturday evening. Every proof point in
`docs/SUBMISSION_CHECKLIST.md` "Demo Proof Points" appears once, in this
order. Times are targets.

Early-submission recording (2026-09-16): <https://youtu.be/oxm9xqJpiY8>.

**Placeholders.** Every `<pending M4>` number — load, baselines, the alerts
rehearsal, the rollback rehearsal — is filled in below as of 2026-09-20 and is
safe to read aloud. `<pending M5>` is a number the release run at the frozen
commit produces (plan M5 steps 3 and 4), and those are the only ones left. No placeholder is read aloud: if the number does not
exist at recording time, say "not measured" on camera. Never guess. Numbers
without a placeholder exist today and are cited to
`evals/results/2026-09-17T024919Z-a4a5856.md`.

Before recording: log in as `audit-physician` in one tab, open AF-DQ-A2
(pid 900001), and have Langfuse open in a second tab with the project's
trace list filtered to the last hour. Keep a terminal ready with
`ssh deployer@137.184.4.22`, and a second terminal in the frozen worktree
(`/tmp/final`, plan M5 step 2) showing `git rev-parse HEAD`; that commit
stays on screen for the whole opener and the whole close.

**The tag.** `week1-final` is created on `main` after the merge (plan M5
step 7.5), which is after this recording, and it points at the merge commit;
the tag's own annotation message (`git tag -a ... -m`) names the frozen sha,
the merge commit's message does not. So `git describe --tags --exact-match`
fails in the frozen worktree and is not shown. On camera the commit is the
identity; the tag is named only as "the submission tag `week1-final` on
`main`, whose tag message names this commit". If the recording slips until
after step 7.5, add a third terminal on the `main` checkout showing
`git describe --tags --exact-match` = `week1-final` and keep it on screen too.

| Time | On screen | Say | Proof point |
| --- | --- | --- | --- |
| 0:00 | Terminal: `git rev-parse HEAD` = `<pending M5>` in `/tmp/final`; `README.md` challenge header | "Since the early submission on the sixteenth, same read-only co-pilot, more evidence. Commit `<pending M5>` is what is deployed and what you are seeing; the submission tag `week1-final` on `main` names it." Then the code lines: say only those whose stream landed per `docs/_status/week1-final-push.md` and whose change is in the frozen commit; strike the rest before recording: "The readiness probe now reaches the tracer instead of assuming it (A1). Queue depth, verification outcome, and tool-failure reasons are exported (A2, A3, A5). Dependencies are pinned (A6). An alerts service evaluates the metrics every five minutes (I1)." Then the evidence lines, gated on the M4 evidence itself, not on stream status: say "Backup and rollback were rehearsed on a throwaway host" only if the Timings table in `docs/deployment/digitalocean.md` "Rehearsal Runbook" has T4 and T6 filled in (plan M4 step 2); say "Load at ten and fifty users is measured" only if `docs/audit/evidence/performance/load-test-2026-09-18.md` exists with both levels (plan M4 steps 3 and 4). Otherwise strike the line; never say "rehearsed" or "measured" for a step that slipped. | context; commit and tag |
| 0:30 | Open the AF-DQ-A2 dashboard and let it load, then click the **Clinical Copilot** menu item; the drawer opens on a brief that is already finished, or on its last progress step | "Physician, 90 seconds before a visit. The brief starts when the chart opens, so it is waiting instead of being typed for. It retrieves six sections through OpenEMR's own access checks, the model writes claims, and a deterministic verifier checks every one against the records before anything renders." *(If the brief is prepared on open, do not say "nothing is retrieved until I ask": it is retrieved under the same session, ticket, ACL and audit path as a click, one chart, the one on screen. With `COPILOT_BRIEF_ON_OPEN=off` the original click flow and that line both come back.)* | normal sourced workflow; no wait at the moment of need |
| 0:55 | Answer: narrative summary, one compact collapsed **Sources & details** control, "Verified" badge | "The answer stays readable; the supporting records and limitations are one click away." | progressive disclosure |
| 1:05 | Expand **Sources & details** and click a citation on the amlodipine conflict; the medication opens in OpenEMR | "Citations open the original record. This one is a conflict: end date and activity flag disagree, and it says so instead of guessing." | per-claim citation; click-through to source; conflict state |
| 1:25 | Click a follow-up chip such as "Was the amlodipine status change documented in a note?" | "Follow-ups keep the window and chain more tools: this one planned a note search." | multi-turn, more than one tool |
| 1:45 | Switch to AF-DQ-I (pid 900012), ask the first question; point at "Allergies not documented" | "Missing data stays missing. This chart has no allergy review, so the answer says not documented, not 'no allergies'." | honest missing-data response |
| 2:05 | Log in as `audit-frontdesk` in another window, open AF-DQ-A2, ask the first question | "Front Office sees demographics in the chart and nothing clinical. The gateway denies each section before any model call, and the audit log records it." | authorization denial before LLM |
| 2:30 | Terminal: run the Bruno "Tool outage" request, or curl with `X-Copilot-Fault: tool:lab_results` | "Fault injection: the lab tool is down. The section is marked unavailable, nothing claims labs are absent, and the rest of the brief still renders." | visible partial behavior during a tool failure |
| 2:50 | Expand **Sources & details**, copy the `ref` from its evidence line, and paste it into the Langfuse search | "One correlation id runs the whole path: drawer, ticket, gateway audit rows, agent logs, and this trace with nested tool, narrate, verify, and repair spans, token counts, and cost. No PHI in the trace." | correlation id through observability |
| 3:15 | `evals/results/<pending M5: final release-run report>.md`, release-gate table at the top; beside it `evals/results/<final>-vs-a4a5856.md` from `evals/compare.py` | "Release run at the final commit, every live case three times: `<pending M5>` of `<pending M5>` attempts passed, golden set `<pending M5>` of 14, citations `<pending M5>` resolved, blocking gates `<pending M5>`. The baseline this push started from, a4a5856: 45 cases ran, 44 passed, golden 14 of 14, 177 of 177 citations resolved." (10 s) | eval results |
| 3:25 | `docs/audit/evidence/performance/load-test-2026-09-18.md` and `baseline-2026-09-18.md` | "Ten users: turn p50 18.8 s, p95 45.0 s, p99 45.1 s, error rate 10 percent — both failures 504s on the heaviest chart. Fifty users: p50 8.3 s, p95 43.8 s, p99 45.0 s, error rate 5.6 percent, and the status share is the real story: 18 percent complete, 76 percent partial. Latency alone is gamed by falling back early, so we report the share. The control run with the model faulted out reproduced the same shape at zero model calls, which puts the ceiling in OpenEMR's Apache and MariaDB, not in the agent: at fifty users both peak over a full vCPU — openemr 103 percent, database 111 percent — while the agent never passes 44. Idle baseline on the same Droplet is under 7 percent CPU and 1.2 GB. Memory was never the constraint." (15 s) | load, latency, baselines |
| 3:40 | `docs/operations/alerts.md` "Alert 1: turn latency"; terminal: `ssh deployer@137.184.4.22 'cd /opt/agentforge && docker compose logs --tail 5 alerts'` (if I1 did not land, run `python -m app.alerts` once per that document's "Running the job" and show its output) | "Alert 1: p95 turn latency over a five-minute window warns above 30 seconds, pages above 45, or when p99 passes 60. The alerts service evaluates the agent's metrics every five minutes; this is its output, one heartbeat line when nothing fires, one JSON line per alert: `{"event": "alert", "name": "tool_failure_rate", "severity": "page", "message": "Tool medications returned unavailable on 100.00% of 5 calls; a service path is broken.", "threshold": 0.5, "value": 1.0}` — that one is real, fired against the live agent with five injected tool faults, and the denominator matches exactly." (10 s) | alert rule and alerts service |
| 3:50 | `docs/deployment/digitalocean.md` rehearsal section with the recorded timings | "On a throwaway Droplet we deployed clean, rolled back to tag `week1` in 2 minutes 36 seconds, rolled forward in 1 minute 13, and restored from an encrypted backup in 3 minutes 19, then destroyed it the same day. The restore was proven to actually restore: a conversation created after the backup came back unknown afterwards." (5 s) | rollback rehearsal |
| 3:55 | `AI_COST_ANALYSIS.md` per-turn table, then the release-run gate table's "Cost per verified turn" row | "1.27 cents per model-backed turn at list price in the eval mix, about 51 cents for the whole 45-case run. The release gate compares the final run against the basis written in the cost analysis; at the final commit it reads `<pending M5: threshold and state, PASS, warn with risk acceptance, or block, from the release-run gate table>`. The daily halt stops spend at 2,000,000 input-plus-output tokens; at a4a5856's 1,800 tokens per turn, that is about 1,100 turns." (10 s; the turn count is derived, not reported anywhere: 2,000,000 / (628 in + 1,172 out) = 1,111, from the a4a5856 "Tokens per turn" row, and the halt counts input plus output only, `agent/app/model.py` `Usage.total`) | cost with the gate's real state |
| 4:05 | Back on the drawer; terminal with the commit still visible (and the tag, only if it exists at recording time, see "The tag" above) | "Read-only, cited, verified, audited, and honest about what the chart does not say. Commit `<pending M5>`; submission tag `week1-final` on `main`." | close; commit and tag |

Cuts if over time: drop the follow-up chip (1:25), then the AF-DQ-I switch
(1:45). Never cut the eval, load, alerts, rollback, or cost rows, and never
take the commit off screen for the opener and the close.

Evidence to keep alongside the video: the release-run results file and its
`evals/compare.py` output against `2026-09-17T024919Z-a4a5856.json`, the
load-driver JSON under `evals/load/results/` with both baseline reports, the
alerts rehearsal log, the Langfuse trace URL for the demonstrated ref (private
project; screenshot for evaluators without access), `git rev-parse HEAD` in
`/tmp/final` at recording time, and, once plan M5 step 7.5 has run,
`git rev-parse week1-final^{commit}` on `main` with the tag message that
names the frozen sha.
