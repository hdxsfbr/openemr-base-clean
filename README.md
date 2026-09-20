# AgentForge Clinical Co-Pilot — Challenge Submission

**Challenge README:** [README_AGENT_FORGE.md](README_AGENT_FORGE.md) is the
evaluator-facing README for the co-pilot (deployed URL, demo credentials,
architecture overview, test and eval commands, limitations). This file keeps
OpenEMR's own README below the deliverables table.

**Deployment:** commit `478f432` is live at
<https://openemr-137-184-4-22.sslip.io> on a single DigitalOcean Droplet,
deployed 2026-09-20 06:2x UTC. The submission tag `week1-final` sits a few
docs-only commits later; the runtime directories (`agent/`, the module,
`infra/`, the cohort fixtures) are byte-identical between the two, so the tag
and the running code differ only in documentation and eval results.

The runtime tree moved on after that release run, to carry the alerts fix
described below; a full single pass at the deployed commit re-verifies it —
`evals/results/2026-09-20T064022Z-4d2a9fd.md`: all 48 cases against the deployed tree, 48 passed, every blocking gate PASS, citations 206/206, p95 20.0 s, $0.0113 per model-backed turn, no 5xx.

Verified on that deployment: `/copilot-api/health` reports `0.3.0`,
`/copilot-api/ready` returns all five dependencies `ok` including the
observability tracer, and the release run
`evals/results/2026-09-20T051146Z-0f11642.md` executed all 48 cases three
times against it — 123 of 124 attempts passed, every blocking gate PASS,
golden set 29/29, citations 615/615 resolved, model-backed p95 15.8 s,
$0.0104 per turn, no 5xx. The one miss is a hedging-wording flip on a
holdout case that passed the other two attempts.

Running image digests:

| Service | Image |
| --- | --- |
| `openemr` | `sha256:bcb51bc519843c22e3fbac67972c5fb92d6501c86ad0767092bb47d395b802ab` |
| `agent` | `sha256:2debfe688abbe3d79fb54601a9a708753ee9cb65e7d3d4327bb4c4000e852063` |
| `alerts` | `sha256:f241b7762225d205ca8ee6523398a7e02865bf831d0072f00a7258f5afe2bb98` |
| `database` | `mariadb:11.8.8`, `sha256:24e76fcec8c003a0362d0dd53f4806e7e79458d7fdeaf47437760e19496f5a9c` |
| `caddy` | `caddy:2.10.2-alpine`, `sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d` |

`agent` and `alerts` run the same source from the same build; their digests
differ because the tag was rebuilt after the agent container was created.

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
