# Week 2 guideline-retrieval contract repair

**Date:** 2026-09-21
**Scope:** Primary-source review only; no patient data used. Facts below are
separate from the proposed evaluation and do not select a production stack.

## Verified facts

### USPSTF/AHRQ access, caching, versioning, and reuse

- The current Prevention TaskForce landing page describes a REST API returning
  USPSTF recommendation data as JSON and says access requires prior approval
  from AHRQ by emailing `uspstfpda@ahrq.gov` with contact information and the
  intended use. The detailed instructions additionally require an authorized
  token key. [USPSTF API landing page](https://www.uspreventiveservicestaskforce.org/apps/api.jsp),
  [AHRQ API instructions, p. 3](https://www.uspreventiveservicestaskforce.org/files/preventiontaskforce_data_api_wi.pdf)
- AHRQ explicitly recommends downloading and caching the entire JSON dataset
  locally, refreshing about weekly, and using `Last-Modified` and `ETag` to
  detect updates. Omitting a search parameter generally returns all values for
  that category, which supports a bounded offline snapshot rather than
  patient-specific API calls at query time. [AHRQ API instructions, pp. 3–4](https://www.uspreventiveservicestaskforce.org/files/preventiontaskforce_data_api_wi.pdf)
- The documented payload includes recommendation `id`, `grade`, `gradeVer`,
  `topicYear`, `uspstfAlias`, title, recommendation text, rationale, clinical
  considerations, discussion, keywords, and categories. The published schema
  does **not** document an immutable corpus-snapshot identifier or API semantic
  version. `ETag`, `Last-Modified`, retrieval time, the response hash, and the
  source fields therefore must be preserved by the consumer if an exact local
  corpus build is to be reproducible. The first sentence is sourced fact; the
  second is a design implication. [AHRQ API instructions, pp. 4–6](https://www.uspreventiveservicestaskforce.org/files/preventiontaskforce_data_api_wi.pdf)
- AHRQ permits reproduction, redistribution, public display, and incorporation
  of USPSTF work only under stated conditions. USPSTF text presented by a
  vendor must be verbatim and appropriately cited. Adaptations require a
  non-endorsement disclaimer; advertising or implied federal endorsement is
  prohibited; and reproduction for a fee, sale for profit, or incorporation
  into a profit-making venture requires express AHRQ permission. Quoted parts
  should cite the USPSTF page. API approval and reuse permission are separate
  questions. [USPSTF API landing page](https://www.uspreventiveservicestaskforce.org/apps/api.jsp),
  [AHRQ copyright notice](https://www.uspreventiveservicestaskforce.org/uspstf/recommendation-topics/copyright-notice)

### RRF is fusion, not an independent semantic reranker

The original RRF paper defines Reciprocal Rank Fusion as an unsupervised method
for **combining document rankings from multiple retrieval systems**. It scores
each document from its positions in the input rankings,
`sum(1 / (k + rank))`, using `k = 60` in the reported experiments. It does not
read the query or passage text and does not independently estimate their
relevance. Microsoft likewise describes RRF as merging multiple ranked result
sets and exposes a separate semantic-reranker score. RRF produces a new order,
but its pipeline role is rank fusion; it is not equivalent to a cross-encoder
that scores each query–passage pair.
[Cormack, Clarke, and Büttcher, SIGIR 2009](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf),
[Microsoft hybrid-search scoring](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)

### Concrete local CPU reranker candidate

`cross-encoder/ms-marco-MiniLM-L6-v2` is a concrete candidate for the missing
second-stage reranker:

- It is an English query–passage cross-encoder trained for MS MARCO passage
  ranking. It scores pairs, after which passages are sorted by score; this is
  the distinct reranking operation missing from RRF-only retrieval.
  [Official model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2)
- The publisher declares Apache-2.0 licensing, 22.7 million parameters, six
  transformer layers, a 384 hidden size, and at most 512 positions. The
  unquantized safetensors file is approximately 90.9 MB.
  [Model card and files](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2),
  [model configuration](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/raw/main/config.json)
- Sentence Transformers supports local PyTorch, ONNX Runtime, and OpenVINO
  execution for this exact model. Its documentation provides a CPU ONNX path
  (`sentence-transformers[onnx]`, `CPUExecutionProvider`) and dynamic int8 ONNX
  quantization intended to accelerate CPU inference without a calibration
  dataset. [Sentence Transformers efficiency guide](https://sbert.net/docs/cross_encoder/usage/efficiency.html)
- The model card reports NDCG@10 74.30, MRR@10 39.01, and 1,800 documents/s,
  but explicitly says that runtime was measured on a V100 GPU. Those numbers
  establish neither clinical-domain quality nor two-vCPU latency. The official
  Sentence Transformers CPU comparison used an i7-13700K, also not this
  deployment. Both are reference facts, not acceptance evidence.
  [Official pretrained-model table](https://sbert.net/docs/cross_encoder/pretrained_models.html),
  [backend benchmark method](https://sbert.net/docs/cross_encoder/usage/efficiency.html#benchmarks)

## Proposed evaluation before selection

The production target is the repository's shared `s-2vcpu-4gb` Droplet, where
OpenEMR and MariaDB already contend for CPU under load; a workstation-only
reranker benchmark cannot defend deployment. The following is proposed work,
not a measured result. [Deployment size](../../infra/digitalocean/variables.tf),
[existing capacity evidence](../../ARCHITECTURE.md)

1. Freeze the evidence: approved API response, response headers, retrieval
   timestamp, SHA-256, exact USPSTF source URLs, verbatim chunks, labeled
   synthetic queries/qrels, benchmark script, dependency lock, repository
   commit, model revision and artifact hash, CPU model/flags, and all runtime
   thread settings. Store no patient text.
2. Compare the same candidates and labels across: sparse retrieval; dense
   retrieval; RRF (`k = 60`); RRF followed by PyTorch-fp32 cross-encoding; and
   RRF followed by ONNX-int8 cross-encoding. Rerank a fixed fused depth (for
   example 20) and return a fixed top set (for example 5), so quality and cost
   comparisons are controlled.
3. Use clinician-reviewed synthetic queries covering direct matches,
   paraphrases, age/sex/risk qualifiers, negation, obsolete versus current
   recommendations, near-duplicate chunks, conflicting-looking passages, and
   true no-answer cases. Report candidate recall@20 before reranking and
   MRR@5/nDCG@5 plus no-answer false-positive rate after reranking. A reranker
   is defensible only if it improves the downstream ordering without hiding
   the sole supporting passage or turning no-answer cases into claims.
4. Measure on a disposable same-size Droplet with the real Compose workload:
   model-download/build time, service cold start, first-query latency, warmed
   p50/p95/p99 rerank and end-to-end retrieval latency, throughput and queueing
   at concurrency 1 and expected concurrent load, peak/container RSS, CPU
   seconds and CPU percentage, serialized model/index size, and OpenEMR,
   MariaDB, and agent error/latency deltas. Repeat enough times to report run
   variance, not one favorable sample.
5. Bound CPU behavior explicitly. ONNX Runtime defaults can use one intra-op
   thread per physical core and worker spinning consumes CPU cycles; test one-
   and two-thread configurations with spinning on and off, while recording the
   effect on co-located services. [ONNX Runtime thread-management documentation](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)
6. Predeclare the acceptance gate before looking at results: no safety-case or
   citation regression; a material ranking gain over RRF alone; retrieval that
   fits the project's first-useful-evidence latency budget; no healthy-stack
   failures; and enough CPU/RSS headroom for OpenEMR and MariaDB. If no tested
   cross-encoder satisfies all gates, retain the measured RRF baseline but
   record the PRD reranker requirement as blocked rather than calling fusion an
   equivalent reranker.

## Conclusion

A locally cached, versioned USPSTF corpus is supported by AHRQ's API guidance,
subject to access approval and the stated reuse constraints. RRF should remain
the sparse/dense fusion stage. `cross-encoder/ms-marco-MiniLM-L6-v2`, preferably
tested in both fp32 and ONNX-int8 forms, is a plausible local CPU reranker—but
only same-Droplet quality, latency, and contention evidence can justify making
it the Week 2 contract.
