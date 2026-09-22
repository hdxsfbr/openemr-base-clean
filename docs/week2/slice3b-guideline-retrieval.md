# Slice 3B: local hybrid retrieval and reranking

Slice 3B implements the local retrieval engine only. It does not add a worker,
endpoint, authorization route, resolver, verifier, UI lane, or deployment.

`agent/app/guideline_retriever.py` validates the active pointer and all corpus
artifacts before loading. It runs SQLite FTS5/BM25 and BGE-small `IndexFlatIP`
over the identical active chunks, combines ranks with deduplicated RRF
(`k=60`, 20 candidates), and independently reranks those candidates with the
quantized MiniLM cross-encoder before returning at most five unchanged chunks.
An empty successful search is a no-evidence result; a leg exception, corrupt or
wrong artifact, stale corpus, reranker failure, model/tokenizer hash mismatch,
or deadline breach is `RetrievalUnavailable` and returns no excerpt.

The engine accepts the strict `EvidenceQuery` from Slice 3A. It does not accept
or log physician question text, patient data, notes, OCR, excerpts, or source
identifiers. The only text passed to local models is one of the reviewed fixed
topic probes selected from finite contract concepts. Prompt-like corpus text is
data, never instructions.

## Setup-only model provisioning

Model download is an explicit setup/build operation, never a runtime action:

```bash
cd agent
python scripts/provision_guideline_models.py --destination .guideline_models
sha256sum .guideline_models/bge/onnx/model.onnx \
  .guideline_models/bge/tokenizer.json \
  .guideline_models/reranker/onnx/model_quint8_avx2.onnx \
  .guideline_models/reranker/tokenizer.json
```

The ignored destination contains BGE `5c38ec7…38267a` model
`828e1496…940cf35`, its tokenizer `d241a60d…1f9e5c66`, MiniLM
`233902d…bee0a` model `c80a8b34…461bf9`, and its now-explicitly-pinned
tokenizer `d241a60d…1f9e5c66`. The provisioner atomically replaces a file only
after checking its full SHA-256. The runtime never imports it, never calls
Hugging Face, and fails closed when these files are absent or altered.

## Benchmark evidence

The committed synthetic benchmark result is
`docs/research/week2-retrieval-benchmark/engine-results-2026-09-22.json`.
It exercised all eight finite topics three times (24 successful cases) on the
same pinned active corpus. It recorded top-one topic accuracy 1.0 and exact
chunk-hash preservation 1.0. Local total p50/p95 were 183.42/267.11 ms;
per-stage p95 was sparse 0.53 ms, dense 10.26 ms, fusion 0.03 ms, and rerank
259.92 ms. This passes the 1.5-second retrieval p95 target on the observed
32-logical-CPU host, while retaining the two-second per-query hard deadline.
Peak process RSS was 476,909,568 bytes. These host-local measurements do not
replace the later co-located deployment gate.

Reproduce offline after setup:

```bash
cd agent
.venv/bin/python -m app.guideline_benchmark \
  --embedding-model-dir .guideline_models/bge \
  --reranker-model-dir .guideline_models/reranker \
  --repeat 3 \
  --output ../docs/research/week2-retrieval-benchmark/engine-results-2026-09-22.json
```

The existing frozen research benchmark remains the independently judged
32-query quality benchmark (including raw synthetic research prompts outside
the runtime contract). The new engine benchmark measures the actual bounded
contract path and has no patient data.

## Verification

```bash
cd agent
.venv/bin/python -m pytest -q tests/test_guideline_retriever.py \
  tests/test_guideline_corpus.py tests/test_guideline_contracts.py
.venv/bin/python -m app.contracts.export --check
```

The retriever tests cover lexical-only and semantic-only hits, deduplication,
RRF and reranker ordering/ties, top-k, unchanged source/hash metadata,
no-result, reranker outage, stale/corrupt artifacts, deadline, absent models,
and the privacy canary. They use injected deterministic test components; the
benchmark above exercises the real pinned BGE and MiniLM artifacts.
