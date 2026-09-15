# Runnable API Collection (Bruno)

The PRD requires a runnable collection graders can drive without reading
source. This folder is a [Bruno](https://www.usebruno.com/) collection: open
it in the Bruno app, or run it headlessly:

```bash
npm install -g @usebruno/cli
cd docs/api-collection && bru run --env deployed --env-var DEMO_PASSWORD="$(ssh deployer@<droplet-ip> cat /opt/agentforge/secrets/demo_user_password)"
```

The demo clinician password is generated on the deployment host
(`docs/deployment/digitalocean.md`, "Manual Cycle"); never commit it.

Folders run in order. Folder 1 performs the same handshake the panel does
(login, open chart, CSRF, start conversation, ticket); every turn request in
folders 2 and 3 mints a fresh ticket in its pre-request script, because a
ticket lives 90 seconds and is bound to one turn. Folder 3 holds the failure
examples (missing and tampered tokens, a patient id in tool parameters, model
and tool outages through fault injection, a closed conversation, a Front
Office login). Folder 4 checks `/health` and `/ready`.

Without a model key on the target, the turns return `status: fallback` with
the deterministic, source-cited record brief; the assertions allow that so the
collection is runnable before the key is configured.
