# ADR-0010: Bounded local retrieval for guideline evidence

- **Status:** Accepted 2026-09-21; supersedes the earlier RRF-only draft
- **Date:** 2026-09-21
- **Owners:** Andre Batista (guideline corpus and evidence retrieval)
- **Related requirements:** Week 2 PRD Stage 2 and Core Agent Requirements 3,
  5, and 7; sparse+dense retrieval, an equivalent reranker, grounded evidence
  metadata, observability, and no raw PHI in logs.
- **Related use cases:** UC-02 guideline-evidence follow-up scheduled for Week
  2; evidence supporting a document-derived finding.
- **Related decisions:** ADR-0002 (patient boundary), ADR-0006 (verification),
  ADR-0007 (telemetry), ADR-0009 (patient-document evidence).

## Context

The primary-care workflow needs a small, inspectable guideline corpus rather
than open-web medical search. Hosted reranking would create another egress
boundary, and the existing two-vCPU deployment is CPU-constrained. The first
toy benchmark proved only that several implementations ran. Independent review
also found that reciprocal-rank fusion is fusion, not the distinct reranking
stage required by the PRD.

The repaired, executable benchmark freezes 160 chunks, 32 synthetic queries,
model revisions and hashes, dependencies, host facts, quality, CPU, memory,
index size, and concurrency in
`docs/research/week2-retrieval-benchmark-2026-09-21.md`.

## Decision

1. **Finite corpus.** Week 2 core uses exactly the eight USPSTF topics in the
   versioned manifest under `docs/research/week2-retrieval-benchmark/`:
   abdominal aortic aneurysm, breast, cervical, colorectal and lung cancer
   screening, childhood high BMI, adult hypertension screening, and adult/
   pregnancy tobacco cessation. CDC and other publishers are deferred.
2. **Rights and source path.** Verbatim attributed excerpts are permitted under
   the recorded AHRQ reuse notice for this non-commercial demo. Automated
   production sync through the Prevention TaskForce API is disabled until AHRQ
   grants the required API approval/token. After approval, fetch the complete
   snapshot at most weekly with `ETag`/`Last-Modified`; never make a
   patient-specific publisher request.
3. **Versioning and activation.** A candidate corpus records publisher fields,
   canonical URL, retrieval time, HTTP validators, exact source and chunk
   hashes, rights basis, parser/chunker version, embedding revision, and index
   build ID. Validation builds immutable artifacts before an atomic active-
   version pointer swap. Failed refresh retains the prior version. A snapshot
   older than 14 days is visibly stale and produces no new guideline claim
   until refreshed or explicitly re-approved for the demo.
4. **Chunking.** Parse only the publisher page's main content. Preserve heading
   paths; never cross a heading boundary; group sentences to a 160-word target
   with one-sentence overlap, require at least 40 words, and cap each topic at
   20 chunks. Preserve exact text, section path, ordinal, URL, and content hash.
5. **Query contract.** The local evidence worker accepts a strict
   `EvidenceQuery`: the physician question, bounded clinical concepts needed
   for retrieval, allowed intent, active corpus version, and optional topic/
   population filters. It rejects patient identifiers, document text, OCR,
   raw notes, diagnosis/treatment requests, and medication dosing requests.
   Any chart-derived concepts remain local and are never logged as content.
6. **Sparse and dense retrieval.** SQLite FTS5/BM25 and the pinned
   `BAAI/bge-small-en-v1.5` ONNX model each retrieve 20 candidates over the
   same active chunk set. Dense vectors use exact FAISS `IndexFlatIP`, the
   pinned revision/hash in the benchmark, normalized 384-dimensional vectors,
   and the frozen query prefix. TF-IDF/SVD remains a benchmark control only.
7. **Fusion and reranking.** Deduplicate by chunk ID and fuse ranks with RRF
   `k=60`, keeping 20. Rerank those candidates with the pinned quantized ONNX
   `cross-encoder/ms-marco-MiniLM-L6-v2` revision/hash and return at most five.
   Use two intra-op threads, one inter-op thread, disabled CPU arenas/patterns,
   384-token truncation, and batches of four. Lexical reranking is rejected by
   measured quality; hosted reranking is not authorized.
8. **Evidence payload.** Every result carries exact text, source title,
   publisher, jurisdiction, canonical URL, publication/topic metadata, section
   path, corpus version, chunk ID, source/chunk hashes, retrieval ranks/scores,
   model/index revisions, and retrieval status. Scores are diagnostics, not
   clinical evidence.
9. **No-result and failure behavior.** Disallowed intent is a safe refusal
   before retrieval. The benchmark's provisional reranker threshold
   (`-2.960404384881258`) is version-bound and may only suppress results; it
   never authorizes a claim. No candidate above threshold yields an explicit
   no-evidence limitation. Missing/stale corpus, failed sparse or dense leg,
   unavailable reranker, version mismatch, or a 2 s local retrieval deadline
   yields `guideline_retrieval_unavailable` and no guideline claim. There is no
   retry inside a physician turn; refresh/build retries occur only offline.
10. **Release gate.** The frozen pipeline is the implementation choice, but
    deployment remains blocked until the operations ticket measures it beside
    OpenEMR/MariaDB on a two-vCPU/4-GiB disposable host, and the eval ticket
    adds clinician-reviewed relevance and safety cases. A failed gate disables
    guideline claims rather than substituting RRF-only output.

## Alternatives Considered

### Hosted Cohere reranking

- Benefits: avoids local inference CPU and supplies a purpose-built reranker.
- Costs and risks: patient-derived queries create an unapproved egress/BAA
  boundary and an additional outage/cost dependency.
- Reason rejected: no covered contract authorizes this data flow.

### RRF-only retrieval

- Benefits: fastest and simplest local path.
- Costs and risks: RRF combines input rankings but does not independently score
  query-passage relevance; it does not satisfy the PRD's reranker requirement.
- Reason rejected: retained only as a degraded benchmark control.

### TF-IDF/SVD dense vectors and lexical reranking

- Benefits: extremely small and fast.
- Costs and risks: the dense leg is a lexical latent-space proxy, and lexical
  reranking reduced MRR, nDCG, and top-one topic accuracy on the repaired set.
- Reason rejected: BGE plus the cross-encoder is both more defensible and
  empirically stronger.

### LanceDB or Qdrant

- Benefits: packaged hybrid indexing and larger-scale features.
- Costs and risks: unnecessary service/dependency surface for 160 chunks and a
  sub-megabyte exact index.
- Reason rejected: exact local search is sufficient at the bounded scale.

## Consequences

### Positive

- The pipeline now meets the explicit sparse+dense-plus-rerank requirement.
- Patient-derived queries and public evidence stay inside the approved local
  boundary.
- Every corpus/model/index change is identifiable and reproducibly evaluated.

### Negative and residual risk

- The models add about 149 MiB of files and the benchmark process peaked near
  482 MiB RSS; shared-host CPU contention is still unmeasured.
- The labels prove topic retrieval, not clinical correctness, and are not yet
  clinician-reviewed.
- The corpus covers preventive guidance only; unrelated or treatment-oriented
  questions must visibly refuse or report no evidence.
- AHRQ API approval remains an external prerequisite for automated refresh.

## Verification

- Run the frozen benchmark offline and assert input/model hashes, sparse/dense
  recall, independent reranker execution, abstention cases, artifact sizes,
  CPU/RSS, and one/ten-worker latency.
- On the disposable deployment, enforce the 2 s deadline and measure p50/p95/
  p99, CPU, RSS, queueing, and OpenEMR/MariaDB latency/error deltas.
- Contract tests reject PHI-bearing/raw-document query fields and disallowed
  diagnosis/treatment/dosing intent.
- Citation tests resolve exact displayed text from the active corpus version;
  stale, missing, mismatched, and unavailable states render no guideline claim.
- Corpus activation tests prove atomic swap, rollback, and continued service on
  a failed candidate refresh.

## Revisit Triggers

- The two-vCPU deployment gate fails latency, memory, or healthy-stack limits.
- Clinician-reviewed evals show no meaningful reranker benefit or unsafe
  no-answer behavior.
- The corpus grows beyond cheap exact search, AHRQ terms/access change, or an
  approved covered hosted reranker becomes available.
