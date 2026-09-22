# Slice 3C: bounded evidence-retriever worker

Slice 3C wraps the Slice 3B local engine in the transport-neutral
`EvidenceRetrieverWorker`. It is the UC-06 worker seam only: it adds no
supervisor routing, authenticated HTTP endpoint, patient retrieval, resolver,
verifier, UI, persistence, database credential, web client, or retry path.

`invoke()` validates the closed `EvidenceQuery` before calling the engine. It
returns a versioned `EvidenceWorkerResult` containing either exact active-corpus
excerpts or one typed limitation. Patient/raw chart, note, OCR, prompt, unknown
field/version/concept, excessive top-k, diagnosis/treatment/dosing/advice, and
applicability fields fail validation before `engine.retrieve()` is invoked.

The worker holds one in-memory handoff state. It permits no retry, commits one
terminal result, and rechecks cancellation or staleness immediately before a
success is committed. Duplicate handoffs are not dispatched. A timeout,
cancellation, stale/duplicate handoff, no result, unavailable engine stage,
wrong/integrity-failed corpus, or malformed engine output returns zero excerpts
and a typed limitation. The later authenticated supervisor owns authorization,
dispatch, and any persistence; its direct integration seam is this strict
worker method, not a network endpoint.

Terminal events record only correlation/handoff IDs, finite intent/topic,
contract/worker/model/artifact revisions, candidate/hit counts, bounded stage
timings, status/limitation, and `not_run` eval outcome. IDs are intentionally
not Prometheus labels. Query text, excerpts, source IDs, patient data,
prompts, model output, embeddings, and exception text are excluded from logs,
metrics, and spans.

## Local verification (2026-09-22)

```bash
cd agent
.venv/bin/python -m pytest -q tests/test_evidence_retriever_worker.py \
  tests/test_guideline_retriever.py tests/test_guideline_contracts.py \
  tests/test_document_metrics.py tests/test_telemetry.py
.venv/bin/python -m app.contracts.export --check
.venv/bin/python -m app.guideline_benchmark \
  --embedding-model-dir .guideline_models/bge \
  --reranker-model-dir .guideline_models/reranker --repeat 1 \
  --output /tmp/issue42-benchmark.json
```

Observed: 64 focused tests passed; the only warnings were four existing
FAISS/NumPy deprecations. Contract export checked 22 schemas. The real pinned
model benchmark (eight finite synthetic topics, one repeat) passed with top-one
topic accuracy and exact-hash preservation both 1.0; total p50/p95 were
197.02/281.57 ms on the 32-logical-CPU local host (not deployment evidence).

The full agent suite was started once but did not produce a final result from
this execution environment after roughly 30 seconds, consistent with the
known TestClient stall recorded by #40/#41; it was not repeated. No Compose
file changed, so Compose validation and deployed smoke are not applicable to
this worker-only slice. The two-vCPU co-located deployment, authorization
route, resolver/verifier/UI, and final 50-case release gate remain later work.
