# Brief on chart open, verified on the deployment (2026-09-20)

Commit `789114a`, pipeline 24190, module 0.5.0, deployed 2026-09-20 about
00:30 UTC. The change is ADR-0003's amendment: the panel starts the UC-01
brief as a chart loads instead of waiting to be clicked, with `BriefPolicy`
deciding server-side.

The Droplet's date is 2026-09-20 UTC while the cohort is seeded at
`DEMO_ANCHOR=2026-09-15`, which is why `visit_today` has nothing to fire on
until visits are added (below).

## 1. The policy decision, read from the deployment

Driven the way `evals/run.py` drives a live session: log in, open a chart
(`demographics.php?set_pid=`), then read the module's `session.php`. Mode was
`always`, which was the default `789114a` shipped; the default became
`visit_today` later the same day (section 4).

| Who | Chart | `chart_open` | `brief_on_open` | Expected |
|---|---|---|---|---|
| `audit-physician` | none open | false | **false** | no chart, no brief |
| `audit-physician` | 900001 (AF-DQ-A2) | true | **true** | brief |
| `audit-physician` | 900018 (AF-DQ-N) | true | **true** | brief |
| `audit-physician` | 900023 (AF-HEAVY) | true | **true** | brief |
| `audit-frontdesk` | 900001 (AF-DQ-A2) | true | **false** | no clinical section, no brief |

The front-desk row is the one worth keeping. Without the ACL gate in
`BriefPolicy::hasClinicalAccess`, every chart that role opened would have
started a turn that the gateway then denied section by section, writing a
`copilot-denied` row and spending a model call per chart open. The panel is
rendered for that role (`panel=True` in both cases) and the drawer still
works if they click; it just is not prepared for them.

## 2. Appointments on the Droplet before the change

```
SELECT CURDATE() AS today, MAX(pc_eventDate) AS newest_appt FROM openemr_postcalendar_events;
+------------+-------------+
| today      | newest_appt |
| 2026-09-20 | 2026-09-15  |
+------------+-------------+
SELECT COUNT(*) FROM openemr_postcalendar_events WHERE pc_eventDate = CURDATE();  -- 0
```

On a cohort seeded at a fixed anchor, `visit_today` is indistinguishable from
`off` — which is why `789114a` shipped `always` and why this had to be fixed
before the default could change.

Two visits were then added for today so the mode has something to fire on.
They were created through OpenEMR's own calendar form (POST
`add_edit_event.php?eid=0`, `form_action=save`, as the browser posts it) under
an `audit-physician` login, not by writing to the table, so the rows carry
whatever the application sets:

| pc_eid | pc_pid | patient | date | start | status | provider | category |
|---|---|---|---|---|---|---|---|
| 9100000 | 900018 | AF-DQ-N | 2026-09-20 | 09:00 | `-` | 6 | 5 (Office Visit) |
| 9100001 | 900001 | AF-DQ-A2 | 2026-09-20 | 09:15 | `-` | 6 | 5 (Office Visit) |

AF-HEAVY (900023) was deliberately left off today's schedule as the negative
case. Both visits are booked under `audit-physician`, while the browser test
runs as `challenge-admin`: the policy accepts a visit with any provider, on
the reasoning that the physician opening the chart may be covering for the one
it is booked under, so both charts still prepare a brief for that user. The
appointment status is `-` (none), which does not trip OpenEMR's
`auto_create_new_encounters`, so no encounter was created and no clinical row
changed.

## 3. Deployed asset

`GET /interface/modules/custom_modules/oe-module-copilot/public/assets/js/copilot.js?v=0.5.0`
returns HTTP 200, 36,958 bytes, containing `maybeStartBrief`, `brief_on_open`
and `brief_started` — so the deploy carried the new panel, and the version
bump busts the browser cache for `0.4.4`.

## 4. `visit_today` as the default

Commit `4127593`, pipeline 24198, deployed 2026-09-20. The container carries
the setting (`docker compose exec openemr printenv COPILOT_BRIEF_ON_OPEN` →
`visit_today`), and the same session.php probe as section 1:

| Who | Chart | Visit today? | `brief_on_open` | Expected |
|---|---|---|---|---|
| `audit-physician` | 900001 (AF-DQ-A2) | yes | **true** | brief |
| `audit-physician` | 900018 (AF-DQ-N) | yes | **true** | brief |
| `audit-physician` | 900023 (AF-HEAVY) | **no** | **false** | no visit, no brief |
| `audit-physician` | none open | — | false | no chart, no brief |
| `audit-frontdesk` | 900001 (AF-DQ-A2) | yes | **false** | no clinical section, no brief |

The last row is the interaction worth keeping: the patient is being seen
today, and the role gate still refuses. The two conditions are `&&`, not a
precedence question.

**What this does not prove.** Both the compose file and `BriefPolicy`'s own
fallback now say `visit_today`, so the behaviour above is the same whether
PHP read the environment variable or fell back. `printenv` shows the variable
in the container, and mod_php inherits the container environment, but no test
here distinguishes the two paths. It would matter the first time someone sets
`always` or `off` on a deployment and expects it to take effect; the way to
settle it then is to set the value and watch `brief_on_open` change for a
patient with no visit today.

## 5. The brief itself, end to end

The sequence `maybeStartBrief()` fires, driven directly against the
deployment on AF-DQ-A2 (900001): `session.php` → `conversation.resume` →
`conversation.start` → `ticket.php` → `POST /v1/conversations/{id}/turns` with
the UC-01 starter question.

```
pid 900001: brief_on_open=True
HTTP 200 in 14620 ms | ref 9fcb6a7309c22b96.1
turn_type=uc01_first status=complete basis=model claims=7 withheld=0 repair=False
```

> Since the last visit, Hyperlipidemia was added to the problem list on
> 2026-09-01 and Metformin 500 mg twice daily was started on 2026-08-26.
> Amlodipine 5 mg has an end date of 2026-08-26 but remains listed as active,
> a status conflict. Hemoglobin A1c resulted 6.8% (down from 7.4%) and LDL
> cholesterol resulted 162 mg/dL, both flagged abnormal on 2026-09-01.

One sample, not a distribution: 14.6 s sits above the suite's 9.2 s first-turn
p50 (`evals/results/2026-09-19T230512Z-f4f69ab4.md`) and well under its 24.8 s
p95, on a cold conversation. The point is not the number but who waits for it:
under the old flow those 14.6 s were spent by a physician watching a progress
line, and they are now spent while the chart page is still rendering. Nothing
else about the turn changed — same classification (`uc01_first`), same
retrieval, same verifier, and the model's summary passed the gate with nothing
withheld.

## 6. Still to record

Everything above was driven server-side. What no check here covers is the
panel's own JavaScript — that `maybeStartBrief()` fires on chart load, renders
under the "Pre-visit brief" header rather than as a question the physician did
not type, and that the drawer opens on a finished answer. The sequence it
fires is verified (section 5); the wiring that fires it is not. That needs a
browser on a chart with a visit today, and it is the one open item.

- `brief_started` against `drawer_open` in `/metrics` over a session, once
  there are real sessions to count.
- Whether `visit_today` is the right default against a real schedule, rather
  than the two visits added here.
