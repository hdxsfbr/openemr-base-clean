# Usage funnel: chart open, brief prepared, drawer open, first question

Four counters in the agent's Prometheus text (`/metrics`, read the same way
`docs/operations/alerts.md` reads it) answer one question: **is the
precomputed UC-01 brief seen?** The brief pays only if physicians open the
drawer on most charts and open with the "what changed" question. If they reach
the drawer rarely, or open with a lab or medication question, it spends model
calls on answers nobody reads.

The first three counters were built (2026-09-19) to decide whether to
precompute at all. The decision was yes, so the same counters now measure what
it costs: `brief_started` against `drawer_open` is the waste rate.

| Stage | Counter | Counted when |
|---|---|---|
| Chart opened with the panel | `copilot_panel_events_total{event="chart_open"}` | The panel script loads on a chart page and makes its reachability check (`/copilot-api/health?panel=chart_open`) |
| Brief prepared for it | `copilot_panel_events_total{event="brief_started"}` | The panel starts the UC-01 brief for a chart being opened, because `session.php` answered `brief_on_open` (`BriefPolicy`, module 0.5.0, ADR-0003 amendment) |
| Drawer opened | `copilot_panel_events_total{event="drawer_open"}` | The drawer goes from closed to open (`/copilot-api/health?panel=drawer_open`), from the menu, the launch parameter, or a script |
| First question | `copilot_conversation_first_turn_total{turn_type="uc01_first"\|"followup"}` | A conversation's first answered turn, by how `classify` typed it: the UC-01 brief or anything else |

Read it as three ratios:

- `brief_started / chart_open` — how often the policy fires. It is ~1 in mode
  `always` (what the demo Droplet's compose file sets), and in mode
  `visit_today` (the module's default) it is the share of opened charts that
  are patients being seen today.
- `drawer_open / brief_started` — **the waste rate.** Every brief without a
  drawer open is about $0.011 of model spend (the live-suite average per
  model-backed turn, `evals/results/2026-09-19T230512Z-f4f69ab4.md`; the cost
  of a brief alone is not measured), its `copilot-tool-read` rows and two
  `copilot-model-disclosure` rows (one per retrieval batch of a UC-01 first
  turn), and the tool fan-out, for an answer nobody read. Sustained low, the
  answer is mode `visit_today`, then mode `off`.
- `uc01_first / (uc01_first + followup)` — does a conversation open with the
  brief. Now near 1 wherever the brief is prepared, since the brief *is* the
  first turn; it stays interesting in mode `off`. It is also a Langfuse filter:
  traces whose `correlation_id` ends in `.1`, grouped by the trace input's
  `turn_type`.

## What it carries

The event name and nothing else: no user, patient, conversation, or chart
data, and the label sets are closed (`PANEL_EVENTS`, `FIRST_TURN_TYPES` in
`agent/app/metrics.py`); any other `panel=` value is ignored. Each counted
panel event also writes one JSON log line (`"msg": "panel event: drawer_open"`,
`"component": "funnel"`).

## Limits

- The counters are in-process: they restart at zero with the agent (every
  deploy). Take deltas between two scrapes, as the load driver and the alert
  job do, or sum the log lines.
- `/health` is unauthenticated, so a panel event can be inflated by anyone who
  can reach the edge. It is a product question, not an audit trail: the audit
  trail is OpenEMR's log (`copilot-session-start`, `copilot-tool-read`,
  `copilot-model-disclosure`). For the same reason `brief_started` is the
  panel's report that it started a brief, not proof that a turn ran; the turn
  counters and the audit rows are that.
- `chart_open` needs the agent to be reachable to be counted, and a chart kept
  open in two windows counts twice. A reload of the same chart counts another
  `chart_open`, and within 60 seconds does *not* count another `brief_started`
  (the panel's per-tab guard), so the waste rate is read over a session, not
  off two adjacent events.
- Until real physicians use the deployment these numbers describe the
  developer and the graders. The point of shipping it now is that the numbers
  exist from the first real session on. As of 2026-09-20 no funnel reading is
  recorded: `docs/audit/evidence/performance/brief-on-open-2026-09-20.md`
  section 9 lists `brief_started` against `drawer_open` over a session as
  still to record.
