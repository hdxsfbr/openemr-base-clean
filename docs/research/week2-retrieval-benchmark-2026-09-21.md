# Week 2 bounded retrieval benchmark

Date: 2026-09-21
Purpose: reproducible evidence for Wayfinder ticket [Benchmark bounded hybrid
retrieval and reranking candidates](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/work_items/15).
Status: repaired benchmark evidence; deployment contention remains for the
operations-budget ticket.

## Reproducible artifacts

The executable benchmark and frozen inputs are in
[`docs/research/week2-retrieval-benchmark/`](week2-retrieval-benchmark/README.md):

- `manifest.json`: exact eight-topic USPSTF source manifest, reuse notice, and
  deterministic heading-aware chunking contract.
- `corpus.jsonl`: 160 verbatim, attributed evidence chunks; SHA-256
  `b4d8dcbf3151c871ec46c43f25cc73a014ed3e3a20bd89a63ab6713c006c3e03`.
- `queries.jsonl`: 32 synthetic queries—24 positive topic queries and eight
  no-answer/safe-refusal controls, split before measurement into dev and
  holdout; SHA-256
  `27c33979d46bde6b2b57a6ac2cc95c988bddf7d169e014755092e825d0678e55`.
- `benchmark.py`, pinned `requirements.txt`, and measured `results.json`.

For all 160 final results (five results for each of 32 queries), the benchmark
also compares exact text, chunk/content identity, corpus version, publisher,
jurisdiction, retrieval date, topic, title, URL, and heading path after the
complete retrieve/fuse/rerank projection. The required-field preservation rate
was 1.000 with zero mismatches; the aggregate and failure list are retained in
`results.json`.

The final run was executed without network access to source pages or models:

```bash
HF_HUB_OFFLINE=1 python \
  docs/research/week2-retrieval-benchmark/benchmark.py \
  --offline --iterations 3
```

The executable fails before measurement unless the frozen manifest, corpus,
query set, BGE model, and reranker model match their committed expected
SHA-256 values; hashes are asserted, not merely reported.

The benchmark contains no patient data. USPSTF excerpts remain verbatim and
cited under the [AHRQ reuse
notice](https://www.uspreventiveservicestaskforce.org/uspstf/recommendation-topics/copyright-notice).
The production API path still requires prior AHRQ approval; that prerequisite
is recorded in the companion [primary-source repair
note](week2-retrieval-contract-repair-2026-09-21.md).

## Frozen pipeline

1. SQLite FTS5/BM25 sparse retrieval, top 20.
2. `BAAI/bge-small-en-v1.5` ONNX embeddings, exact FAISS `IndexFlatIP`, top
   20. Model revision
   `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`; artifact SHA-256
   `828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35`.
3. Reciprocal-rank fusion with `k=60`, deduplicated to 20 candidates.
4. `cross-encoder/ms-marco-MiniLM-L6-v2` quantized ONNX AVX2 reranking over
   those 20 candidates, returning five. Model revision
   `233902d25c440f23af6f7d6e94d2946bac0bee0a`; artifact SHA-256
   `c80a8b34256ea453093d612e3ac48d3d965a0c0a48c7906709af8b8e28461bf9`.

Both ONNX sessions use two intra-op threads, one inter-op thread, disabled CPU
memory arenas, disabled memory patterns, 384-token truncation, and bounded
batches. The earlier TF-IDF/SVD dense path and lexical reranker remain control
arms; neither is selected for production.

## Measured quality and warm latency

The labels identify the expected publisher topic, not clinical correctness.
They are synthetic and were not clinician-reviewed.

| Candidate | Recall@20 | MRR | nDCG@5 | Top-1 topic | p50 | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SQLite FTS5 sparse | 1.000 | 0.844 | 0.742 | 0.750 | 0.16 ms | 0.22 ms |
| TF-IDF/SVD FAISS control | 1.000 | 0.918 | 0.841 | 0.875 | 0.34 ms | 0.37 ms |
| BGE-small exact FAISS | 1.000 | 1.000 | 0.983 | 1.000 | 6.15 ms | 7.61 ms |
| Sparse + BGE RRF | 1.000 | 1.000 | 0.932 | 1.000 | 6.19 ms | 7.42 ms |
| RRF + lexical rerank control | 1.000 | 0.910 | 0.815 | 0.833 | 6.69 ms | 7.96 ms |
| RRF + ONNX cross-encoder | 1.000 | 1.000 | 0.963 | 1.000 | 172.65 ms | 277.73 ms |

The cross-encoder is a genuine second-stage reranker; RRF remains the fusion
stage. It restored stronger top-five ordering than RRF alone while preserving
perfect topic recall and top-one accuracy on this small set. The lexical
reranker degraded quality and is rejected.

The dev-selected cross-encoder threshold produced 11/12 correct holdout
answer/no-answer decisions. The miss was the treatment-oriented query “What
drug dose should be started to treat hypertension?”, which correctly matches
the hypertension topic lexically but is outside the product's allowed intent.
The score threshold therefore cannot be a safety boundary. Deterministic intent
rules must refuse diagnosis, treatment, and dosing before retrieval, and a
below-threshold result produces an explicit retrieval limitation.

## Build, memory, size, and concurrency

The final host-local run used Python 3.13.2 on an Intel i9-14900KF with 24
physical/32 logical CPUs and 31.1 GiB RAM. It is intentionally not represented
as the two-vCPU deployment.

- Corpus/index build: 7.38 s wall, 17.85 CPU-s; the two-thread limit consumed
  about 2.42 cores during build.
- Cold model session load: 131.62 ms BGE and 51.82 ms reranker; first rerank
  168.26 ms.
- Peak process RSS: 507,514,880 bytes (484.0 MiB), including Python and all
  libraries/models; incremental BGE session RSS was about 179.2 MiB.
- Model files: 126.9 MiB BGE and 22.1 MiB reranker.
- Indexes: 240 KiB BGE FAISS, 248 KiB SQLite sparse, and 40 KiB control FAISS.
- One-worker p95: sparse 0.23 ms, BGE dense 7.28 ms, complete
  retrieve/fuse/rerank pipeline 287.36 ms.
- Ten-worker p95: sparse 3.09 ms, BGE dense 22.69 ms, complete
  retrieve/fuse/rerank pipeline 1,994.66 ms.

The ten-worker complete-pipeline result is only about 5 ms below the proposed
2 s local retrieval deadline even on this much larger host. It is evidence for
keeping the two-vCPU shared-deployment test as a hard release gate, not
evidence that the production budget is already satisfied.

The build, query CPU, artifact sizes, dependency versions, model hashes, exact
per-query reranker scores, and full concurrency results are preserved in
`results.json` rather than reconstructed from rounded values in this report.

## Decision support and remaining limitation

The repaired evidence supports a local, inspectable pipeline of FTS5 plus
BGE-small exact FAISS, RRF fusion, and MiniLM ONNX cross-encoder reranking. It
meets the PRD's sparse+dense-plus-rerank shape without external patient-query
egress and fits the measured host-local latency and memory envelope.

It does **not** establish clinical relevance or shared-host capacity. Before
release, the operations-budget ticket must rerun the frozen pipeline on a
disposable two-vCPU/4-GiB host alongside OpenEMR and MariaDB, and the eval-gate
ticket must add clinician-reviewed relevance, negation, obsolete/current,
conflict, and safe-refusal cases. If those gates fail, the system must report
retrieval unavailable or degraded; it must not relabel RRF as an equivalent
reranker or silently emit a guideline claim.
