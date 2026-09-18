# AgentForge Clinical Co-Pilot — Challenge Submission

**Challenge README:** [README_AGENT_FORGE.md](README_AGENT_FORGE.md) is the
evaluator-facing README for the co-pilot (deployed URL, demo credentials,
architecture overview, test and eval commands, limitations). This file keeps
OpenEMR's own README below the deliverables table.

**Deployment:** commit `e1dd331`, tag `week1`, is live at
<https://openemr-137-184-4-22.sslip.io> on a single DigitalOcean Droplet
(deployed 2026-09-16; `/copilot-api/health` and `/copilot-api/ready` answered
200 that day, and the deployment was exercised end to end on
2026-09-17 by the eval run `evals/results/2026-09-17T024919Z-a4a5856.md`,
45 cases, 44 passed, every blocking gate PASS, plus the 21/21 Bruno collection
run of 2026-09-16).
No runtime directory changed between `831e1d8` and `e1dd331`, so the running
code is the same as at `831e1d8`. The older `v0.2.0-slice` tag is not what is
deployed, and `c7253ed` is the `week1` tag object, not a commit sha. No image
digest has been recorded for this deploy yet.
It runs the project's own OpenEMR image carrying the co-pilot module behind a
deny-by-default Caddy path allowlist, as the audit required before an
evaluator deployment (`AUDIT.md` SEC-HIGH-500; runbook sections "Current
Deployment" and "Before the Evaluator Deployment" in
[docs/deployment/digitalocean.md](docs/deployment/digitalocean.md)). The
`sslip.io` hostname is disposable and an owned hostname is still pending. The
Droplet is disposable too: `infra/digitalocean/destroy.sh` tears it down and
`infra/digitalocean/tf.sh apply` plus `infra/digitalocean/deploy.sh`
re-provision it; the 2026-09-14 smoke test and audit probe cycles are recorded
in the runbook.

**Setup:** see [SETUP.md](SETUP.md) for the local stack, demo data, audit test
users, and the synthetic cohort (`evals/fixtures/cohort/`).

## Submission Deliverables

These are the exact, root-level, PRD-required artifacts. Everything else in this
repository — `docs/PROJECT_PLAN.md`, `docs/SUBMISSION_CHECKLIST.md`,
`docs/REQUIREMENTS_TRACEABILITY.md`, `docs/adr/`, `SETUP.md`, and OpenEMR's own
upstream docs below (`CONTRIBUTING.md`, `CHANGELOG.md`, etc.) — is internal
working documentation, not a graded deliverable.

| File | Requirement |
| --- | --- |
| [AUDIT.md](AUDIT.md) | Security, performance, architecture, data-quality, and compliance audit |
| [USERS.md](USERS.md) / [USER.md](USER.md) | Target user, workflow, and use cases |
| [ARCHITECTURE.md](ARCHITECTURE.md) | AI integration plan, framework choices, verification strategy |
| [KEY_METRICS.md](KEY_METRICS.md) | Product-success metrics and rationale |
| [AI_COST_ANALYSIS.md](AI_COST_ANALYSIS.md) | Actual + projected cost analysis |

---

[![Syntax Status](https://github.com/openemr/openemr/actions/workflows/syntax.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/syntax.yml)
[![Styling Status](https://github.com/openemr/openemr/actions/workflows/styling.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/styling.yml)
[![Testing Status](https://github.com/openemr/openemr/actions/workflows/test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/test.yml)
[![JS Unit Testing Status](https://github.com/openemr/openemr/actions/workflows/js-test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/js-test.yml)
[![PHPStan](https://github.com/openemr/openemr/actions/workflows/phpstan.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/phpstan.yml)
[![Rector](https://github.com/openemr/openemr/actions/workflows/rector.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/rector.yml)
[![ShellCheck](https://github.com/openemr/openemr/actions/workflows/shellcheck.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/shellcheck.yml)
[![Docker Compose Linting](https://github.com/openemr/openemr/actions/workflows/docker-compose-lint.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/docker-compose-lint.yml)
[![Dockerfile Linting](https://github.com/openemr/openemr/actions/workflows/docker-lint-hadolint.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/docker-lint-hadolint.yml)
[![Isolated Tests](https://github.com/openemr/openemr/actions/workflows/isolated-tests.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/isolated-tests.yml)
[![Inferno Certification Test](https://github.com/openemr/openemr/actions/workflows/inferno-test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/inferno-test.yml)
[![Composer Checks](https://github.com/openemr/openemr/actions/workflows/composer.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/composer.yml)
[![Composer Require Checker](https://github.com/openemr/openemr/actions/workflows/composer-require-checker.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/composer-require-checker.yml)
[![API Docs Freshness Checks](https://github.com/openemr/openemr/actions/workflows/api-docs.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/api-docs.yml)
[![codecov](https://codecov.io/gh/openemr/openemr/graph/badge.svg?token=7Eu3U1Ozdq)](https://codecov.io/gh/openemr/openemr)

[![Backers on Open Collective](https://opencollective.com/openemr/backers/badge.svg)](#backers) [![Sponsors on Open Collective](https://opencollective.com/openemr/sponsors/badge.svg)](#sponsors)

# OpenEMR

[OpenEMR](https://open-emr.org) is a Free and Open Source electronic health records and medical practice management application. It features fully integrated electronic health records, practice management, scheduling, electronic billing, internationalization, free support, a vibrant community, and a whole lot more. It runs on Windows, Linux, Mac OS X, and many other platforms.

### Contributing

OpenEMR is a leader in healthcare open source software and comprises a large and diverse community of software developers, medical providers and educators with a very healthy mix of both volunteers and professionals. [Join us and learn how to start contributing today!](https://open-emr.org/wiki/index.php/FAQ#How_do_I_begin_to_volunteer_for_the_OpenEMR_project.3F)

> Already comfortable with git? Check out [CONTRIBUTING.md](CONTRIBUTING.md) for quick setup instructions and requirements for contributing to OpenEMR by resolving a bug or adding an awesome feature 😊.

### Support

Community and Professional support can be found [here](https://open-emr.org/wiki/index.php/OpenEMR_Support_Guide).

Extensive documentation and forums can be found on the [OpenEMR website](https://open-emr.org) that can help you to become more familiar about the project 📖.

### Reporting Issues and Bugs

Report these on the [Issue Tracker](https://github.com/openemr/openemr/issues). If you are unsure if it is an issue/bug, then always feel free to use the [Forum](https://community.open-emr.org/) and [Chat](https://www.open-emr.org/chat/) to discuss about the issue 🪲.

### Reporting Security Vulnerabilities

Check out [SECURITY.md](.github/SECURITY.md)

### API

Check out [API_README.md](API_README.md)

### Docker

Check out [DOCKER_README.md](DOCKER_README.md)

### FHIR

Check out [FHIR_README.md](FHIR_README.md)

### For Developers

If using OpenEMR directly from the code repository, then the following commands will build OpenEMR (Node.js version 24.* is required) :

```shell
composer install --no-dev
npm install
npm run build
composer dump-autoload -o
```

### Contributors

This project exists thanks to all the people who have contributed. [[Contribute]](CONTRIBUTING.md).
<a href="https://github.com/openemr/openemr/graphs/contributors"><img src="https://opencollective.com/openemr/contributors.svg?width=890" /></a>


### Sponsors

Thanks to our [ONC Certification Major Sponsors](https://www.open-emr.org/wiki/index.php/OpenEMR_Certification_Stage_III_Meaningful_Use#Major_sponsors)!


### License

[GNU GPL](LICENSE)
