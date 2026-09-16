# Correlation ID Walkthrough

One identifier follows a turn from the panel to every log that records it.
This page shows the path with a real turn from the eval run of 2026-09-16
(case `CIT-UC01-A2-001`, synthetic patient AF-DQ-A2, user `audit-physician`).

## Shape

`<conversation correlation>.<turn number>`, for example `75a29aa756c7985f.1`.

- The conversation part is minted by the module when a conversation starts
  (`public/api/conversation.php`) and stored on the binding row.
- The turn number is appended by the ticket endpoint (`public/api/ticket.php`)
  each time a ticket is minted, so every turn has its own id and the
  conversation is recoverable from the prefix.
- The panel shows it as `ref 75a29aa756c7985f.1` in the meta line under each
  answer and sends it as `X-Correlation-Id` and in the turn body.

## Where it appears

| Hop | Where to look | What the eval turn showed |
| --- | --- | --- |
| Panel | Meta line under the answer: `ref 75a29aa756c7985f.1` | Same value the runner captured from the `X-Correlation-Id` response header |
| Module audit rows | OpenEMR `log` table; the JSON in `comments` (base64) carries `correlation_id` | `copilot-session-start` 1 row, `copilot-tool-read` 7 rows (one per tool call, written before data leaves) |
| Agent logs | JSON lines on the agent container's stdout, field `correlation_id`, one per graph node | `authorize`, `classify`, `retrieve`, `narrate`, `verify` (twice), `repair`, `render` (twice) with `duration_ms` each |
| Agent API | `X-Correlation-Id` response header and `correlation_id` in the turn body | Both equal the ticket's id (`OBS-CORRELATION-001` asserts this) |
| Langfuse | Trace `copilot.turn`, session id = conversation id, tags `copilot` plus the turn type (`uc01_first` or `followup`, set as `langfuse_tags` in `agent/app/telemetry.py`); the correlation id is in the trace metadata | Trace `921f44e1de3dc19deb130609664fa3bc`: 19 observations (node spans plus `narrate` and `repair` generations), cost $0.028, latency 21.2 s, no PHI in inputs or outputs (masked). Turns since commit `74a1bf6` (2026-09-15) also carry one `tool`-type observation per gateway call, so a comparable trace now has more observations than this one |

## Commands

Agent logs for one turn, on the Droplet:

```bash
cd /opt/agentforge && docker compose logs agent | grep 75a29aa756c7985f.1
```

Audit rows for one turn (read-only; the root password is a Docker secret
inside the database container):

```bash
cd /opt/agentforge && docker compose exec -T database sh -c \
  'mariadb -uroot -p"$(cat /run/secrets/mysql_root_password)" "$MARIADB_DATABASE" \
   -e "SELECT date, event, user FROM log WHERE FROM_BASE64(comments) LIKE '"'"'%75a29aa756c7985f%'"'"' ORDER BY date"'
```

Langfuse, from any machine with the project keys (never paste the keys):

```bash
curl -s -u "$(cat ~/.config/agentforge/langfuse_public_key):$(cat ~/.config/agentforge/langfuse_secret_key)" \
  "https://us.cloud.langfuse.com/api/public/traces?limit=50" | grep -o '75a29aa756c7985f[^"]*'
```

Or search the trace list in the Langfuse UI for the id.

## What the id does not carry

No user id, no patient id, no chart content. The audit row holds the user
and patient on the OpenEMR side; the Langfuse trace holds the conversation
id and masked node inputs and outputs. Joining the two needs access to both
systems, which is the intended boundary (ADR-0007).
