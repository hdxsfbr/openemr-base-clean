# `copilot-model-disclosure` rows read back from the deployment (2026-09-19)

Commit `12cd849`, pipeline 24160, deployed 2026-09-19 about 22:02 UTC. Two turns
were asked in the drawer on synthetic patient AF-DQ-A2 (pid 900001) as
`challenge-admin`: the medication starter chip (a follow-up, one retrieval
batch) and "What changed since the last visit?" (UC-01, two batches). Then,
read-only, on the Droplet:

```bash
cd /opt/agentforge && docker compose exec -T database sh -c \
  'mariadb -uroot -p"$(cat /run/secrets/mysql_root_password)" "$MARIADB_DATABASE" -t' <<'SQL'
SELECT date, event, user, patient_id, success, CONVERT(FROM_BASE64(comments) USING utf8mb4) AS detail
FROM log WHERE event = 'copilot-model-disclosure' ORDER BY date DESC LIMIT 6;
SQL
```

| date (UTC) | user | patient_id | success | detail |
|---|---|---|---|---|
| 2026-09-19 22:07:10 | challenge-admin | 900001 | 1 | `{"provider":"anthropic","model":"claude-sonnet-5","tools":"encounters,patient_context","records":4,"conversation_id":"018765daf19b27dd7ab2e3b8053225fe","turn_id":"c499d5fb8b0cb244","correlation_id":"4af1344a3a5c5e6e.2"}` |
| 2026-09-19 22:07:10 | challenge-admin | 900001 | 1 | `{"provider":"anthropic","model":"claude-sonnet-5","tools":"problems,medications,lab_results,clinical_notes","records":10,"conversation_id":"018765daf19b27dd7ab2e3b8053225fe","turn_id":"c499d5fb8b0cb244","correlation_id":"4af1344a3a5c5e6e.2"}` |
| 2026-09-19 22:06:21 | challenge-admin | 900001 | 1 | `{"provider":"anthropic","model":"claude-sonnet-5","tools":"medications,problems,clinical_notes","records":9,"conversation_id":"018765daf19b27dd7ab2e3b8053225fe","turn_id":"b27ae29ee4e40a4b","correlation_id":"4af1344a3a5c5e6e.1"}` |

What the rows show:

- One row per retrieval batch of a model-backed turn: one for the follow-up,
  two for the UC-01 first turn.
- The counts match the other two records of the same turns. The drawer said
  "Retrieved 9 chart record(s)" for the first turn, and its Langfuse trace
  (`3ac569e84210291d0cdc515e0f2effcc`) has three tool observations with
  `record_count` 3 each. The second turn's trace
  (`aa412f65f183535cd541059e77e91325`) has encounters 3, patient_context 1,
  problems 3, medications 3, lab_results 3, clinical_notes 1, and allergies
  `empty`.
- A tool that returned no records is not listed: `allergies` answered `empty`
  in the second batch and is absent from its row. Nothing was disclosed from
  it.
- Identifiers and counts only: no record, prompt, or response text. The
  `correlation_id` is the `ref` under the answer in the drawer and the
  `metadata.correlation_id` filter in Langfuse, so the audit row, the trace,
  and what the physician saw join on one value.
- In the same 90 minutes the log held 18 `copilot-tool-read` rows and 2
  `copilot-session-start` rows: the per-tool read rows are still written, and
  the disclosure rows are in addition to them.

Not shown here: the fail-closed branch (the row cannot be written, so every
tool of the batch answers `audit_unavailable`). It mirrors the branch
`copilot-tool-read` has had since 2026-09-15 and has not been exercised in the
deployment.
