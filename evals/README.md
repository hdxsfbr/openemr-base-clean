# Clinical Co-Pilot Evaluation Suite

The eval suite is a product specification expressed as executable evidence. A
case belongs here only when it protects a boundary, invariant, or known
regression risk. Happy-path demonstrations alone do not satisfy the project
requirements.

## Planned Layout

```text
evals/
  cases/          # Machine-readable versioned cases
  fixtures/       # Synthetic/demo patient records and injected failures
  rubrics/        # Deterministic and human scoring definitions
  results/        # Versioned summaries; no secrets or PHI
  README.md
```

Directories should be added with the implementation that defines their format;
we will not preserve empty directory placeholders.

The case format is designed to be the Week 2 golden set and the Week 3
attack corpus without change: one YAML file per case with a stable id
(`UC01-AF-DQ-A2-001`), the metadata below, deterministic assertions on
structured output (claim types, source ids, typed facts, status flags,
absence states), boolean rubrics for human review, and LLM-judge results
recorded in a separate field and never mixed into the pass rate. The eval
client drives the deployed agent API headlessly through the same handshake
as the Bruno collection (`ARCHITECTURE.md`), which is also the path an
adversarial platform uses.

`fixtures/cohort/` now exists: the deterministic synthetic cohort
`af-cohort-v1`, 26 fictional patients mapped to the missing-data,
conflicting, lab-constraint, untrusted-content, orphan-row, and authorization
categories below. See [`fixtures/cohort/README.md`](fixtures/cohort/README.md).
Case, rubric, and result formats are still to be defined.

## Required Case Metadata

Every case must record:

- Stable case ID and descriptive name.
- Linked user/use case, if applicable.
- Boundary, invariant, or regression risk being protected.
- Synthetic patient and authorized user/role context.
- Conversation turns and injected dependency behavior.
- Expected tools and tools that must not be called.
- Required claims, forbidden claims, and expected source references.
- Expected verification, authorization, and degradation outcomes.
- Deterministic pass/fail checks and any human-scored rubric.

## Initial Test Matrix

| Category | Cases to implement | Failure guarded against |
| --- | --- | --- |
| Authorization | Wrong patient, insufficient role, forged patient ID, follow-up patient switch, expired delegation | PHI entering model context or response without permission |
| Citation invariant | Missing citation, wrong record, wrong patient, unrelated source, altered value/date/unit | Citation theater and unsupported clinical claims |
| Missing data | Empty chart, no prior visit, undocumented medication indication, unavailable note | Hallucinating completeness or causality |
| Conflicting/stale data | Active and inactive duplicates, contradictory notes, stale medication, late lab correction | Flattening ambiguity into false certainty |
| Lab constraints | Missing range, missing unit, incompatible units, nonnumeric value | Invalid comparisons or abnormality claims |
| Conversation isolation | Two users, two tabs, two patients, long follow-up chain | Cross-user/patient context leakage |
| Untrusted record content | Prompt injection in a note or free-text field | Clinical data changing system policy or revealing secrets |
| Tool failure | Timeout, 500, malformed schema, partial result, retry exhaustion | Silent omission or fabricated absence |
| Model failure | Timeout, refusal, malformed structured output, unsupported source ID | Rendering unverified raw model output |
| Observability | Missing correlation ID, trace backend unavailable, prohibited PHI field | Untraceable requests or privacy leakage |
| Regression | One case for every discovered production/eval bug | Reintroduction of previously fixed behavior |

## Result Reporting

Each run should record commit, environment, model, prompt/tool/verifier versions,
dataset version, timestamp, sample size, pass rate by category, unsupported-claim
rate, citation correctness, authorization leakage, latency distribution, token
usage, and cost.

Evaluator-facing results must distinguish deterministic assertions, model-based
judging, and human review. Never report a single aggregate score without the
safety-category breakdown.

## CI and Deployment Gates

Thresholds live in `KEY_METRICS.md`, "Decision Thresholds": release gates,
runtime alerts, and where risk acceptance is allowed. Authorization leakage,
displayed unsupported claims, uncertainty recall on safety cases, and safe
degradation are always release-blocking. A release run executes the whole
suite; the deterministic subset (authorization, citation invariant, tool and
model failure, isolation) runs on every change to the gateway, tools,
verifier, or prompt, and the model-backed subset runs before each deploy.
GitLab CI carries this from Week 1: a pipeline skeleton with `git diff
--check`, contract-schema validation, and the deterministic subset against
the local stack, so Week 2's PR-blocking gate is a threshold change, not new
infrastructure.
