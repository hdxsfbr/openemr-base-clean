# Usage funnel: chart open, drawer open, first question

Three counters in the agent's Prometheus text (`/metrics`, read the same way
`docs/operations/alerts.md` reads it) answer one question before anything is
built on it: **would a precomputed UC-01 brief ever be seen?** Precompute pays
only if physicians open the drawer on most charts and open with the "what
changed" question. If they reach the drawer rarely, or open with a lab or
medication question, precompute spends model calls on answers nobody reads.

| Stage | Counter | Counted when |
|---|---|---|
| Chart opened with the panel | `copilot_panel_events_total{event="chart_open"}` | The panel script loads on a chart page and makes its reachability check (`/copilot-api/health?panel=chart_open`) |
| Drawer opened | `copilot_panel_events_total{event="drawer_open"}` | The drawer goes from closed to open (`/copilot-api/health?panel=drawer_open`), from the menu, the launch parameter, or a script |
| First question | `copilot_conversation_first_turn_total{turn_type="uc01_first"\|"followup"}` | A conversation's first answered turn, by how `classify` typed it: the UC-01 brief or anything else |

Read it as two ratios: `drawer_open / chart_open` (does the drawer get opened
at all) and `uc01_first / (uc01_first + followup)` (does a conversation open
with the brief). The second is also a Langfuse filter: traces whose
`correlation_id` ends in `.1`, grouped by the trace input's `turn_type`.

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
  trail is OpenEMR's log (`copilot-session-start`, `copilot-tool-read`).
- `chart_open` needs the agent to be reachable to be counted, and a chart kept
  open in two windows counts twice.
- Until real physicians use the deployment these numbers describe the
  developer and the graders. The point of shipping it now is that the numbers
  exist from the first real session on.
