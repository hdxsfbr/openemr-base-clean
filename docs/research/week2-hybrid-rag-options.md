# Week 2 hybrid retrieval, reranking, and guideline-source options

**Research date:** 2026-09-21

**Decision ticket:** “Research bounded hybrid retrieval, reranking, and guideline-source options”

**Status:** decision support only; this note does not select the final corpus or stack

## Question and boundary

What do primary sources establish about viable clinical-guideline corpora,
their reuse and update constraints, sparse plus dense retrieval, reranking,
and components that can run with the existing single-Droplet deployment?

The Week 2 PRD requires a small clinical-guideline corpus, keyword plus dense
retrieval, reranking, source metadata, and grounded snippets. The existing
product narrows that further:

- guideline evidence serves the already-defined primary-care follow-up use
  case, especially “what does the guideline say about this value?”, not an
  open-ended medical knowledge assistant ([`USERS.md`](../../USERS.md));
- every displayed guideline claim must resolve to evidence retrieved in that
  turn and pass deterministic verification; the reserved `guideline:` source
  scheme and `guideline_reference` claim type are prose seams, not implemented
  code ([Week 2 handoff](../WEEK2_HANDOFF.md#seams-what-is-code-and-what-is-prose),
  [`ARCHITECTURE.md`](../../ARCHITECTURE.md#canonical-contracts));
- the current host is 2 shared vCPU / 4 GiB. Measurements found CPU, not RAM,
  was already the capacity constraint: at 10 concurrent users OpenEMR and the
  database peaked at 51.9% and 91.0% of one core before later batching work;
  at 50 users both exceeded one full core. The worst measured memory
  low-water mark still left 2,389 MiB available
  ([resource baseline](../audit/evidence/performance/baseline-2026-09-18.md),
  [tier comparison](../audit/evidence/performance/droplet-tier-comparison-2026-09-18.md));
- the agent currently has no embedding, vector-store, ONNX, Torch, Cohere, or
  reranker dependency. Any option adds build, patching, and cold-start surface;
- only synthetic/demo data may be used, but the architecture still needs a
  defensible production boundary. Demo-only data is not a reason to normalize
  an unsafe future PHI path.

## Decision-relevant findings

1. **USPSTF is the strongest core source for this user, but it is not a complete
   lab-management corpus.** Its official API is explicitly built for primary
   care, returns structured recommendation, population, grade, topic year,
   canonical alias, keyword, and category fields, and supports `ETag` and
   `Last-Modified`. AHRQ recommends a locally cached full snapshot refreshed
   about weekly. Access requires approval and the reuse notice constrains
   modification and commercial use
   ([API overview](https://www.uspreventiveservicestaskforce.org/apps/api.jsp),
   [API instructions](https://www.uspreventiveservicestaskforce.org/files/preventiontaskforce_data_api_wi.pdf),
   [reuse notice](https://www.uspreventiveservicestaskforce.org/uspstf/recommendation-topics/copyright-notice)).
2. **CDC can supplement bounded public-health topics, but not as an unversioned
   scrape.** Most CDC material is public domain, subject to page-specific
   exceptions, attribution, a non-endorsement disclaimer, no substantive
   alteration, and a statement that it is freely available. CDC warns that
   many pages are continuously updated and recommends linking rather than
   stale republication
   ([CDC agency-material policy](https://www.cdc.gov/other/agencymaterials.html)).
3. **NICE has the cleanest syndication/update channel but is not a no-friction
   US demo source.** Its API provides guidance in JSON/XML/HTML and supports
   licensed caching and updates. Access requires an organization, approved
   use, a licence, accepted security certification, and explicit approval for
   AI use; AI training is prohibited. NICE currently says international use
   may carry fees, while its detailed guide lists £40,000 for a 12-month
   overseas pilot and per year for a full licence
   ([syndication page](https://www.nice.org.uk/reusing-our-content/nice-syndication-api),
   [API guide](https://www.nice.org.uk/corporate/ecd10/chapter/introduction),
   [terms](https://www.nice.org.uk/terms-and-conditions)).
4. **The small-corpus scale does not require a distributed vector database.**
   At a planning ceiling of 10,000 chunks and 384-dimensional `float32`
   embeddings, the raw vector matrix is only 15,360,000 bytes (about 14.6 MiB).
   This arithmetic excludes indexes, metadata, model weights, and runtime
   overhead, but it means exact dense search is a credible baseline that must
   be measured before an ANN service is justified.
5. **Hosted Cohere reranking is operationally small but creates a new clinical
   data boundary.** Cohere's current Rerank API accepts a query and candidate
   document strings. One billable search covers one query and up to 100
   documents; documents over 500 tokens may be split for billing. Trial keys
   are not permitted for production. More importantly, Cohere's Trust Center
   says its BAA applies only to custom-model development and does **not** cover
   hosted SaaS; enterprise customers should not submit PHI to SaaS
   ([Rerank API](https://docs.cohere.com/reference/rerank),
   [pricing](https://cohere.com/pricing),
   [Trust Center](https://trustcenter.cohere.com/?format=html)).
6. **A local small encoder and local cross-encoder are technically plausible,
   but their clinical quality and CPU latency are unproven.**
   `BAAI/bge-small-en-v1.5` is MIT-licensed, has 33.4M parameters, emits
   384-dimensional vectors, and has a 512-token sequence length. The
   Apache-2.0 `cross-encoder/ms-marco-MiniLM-L6-v2` has 22.7M parameters and
   was trained on MS MARCO, not clinical guidelines. Sentence Transformers
   supports CPU ONNX and int8 export, but its documentation explicitly says
   backend performance can reverse by model and workload and must be measured
   ([BGE model card](https://huggingface.co/BAAI/bge-small-en-v1.5),
   [MiniLM reranker card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2),
   [CrossEncoder efficiency guide](https://www.sbert.net/docs/cross_encoder/usage/efficiency.html)).

## Corpus options

| Source | Fit and machine-readable grounding | Reuse and update facts | Operational effect | Decision caveat |
| --- | --- | --- | --- | --- |
| **USPSTF Prevention TaskForce API** | Best match to a US primary-care clinician. Structured fields include recommendation ID, text, grade/version, target sex/age range, service frequency and risk fields; general records include topic year, canonical alias/URL, title, clinical considerations, discussion, keywords, and categories. | Prior approval/token required. AHRQ recommends caching the whole JSON set and refreshing about weekly using `ETag`/`Last-Modified`. Work may be reproduced unchanged with citation, but not sold or incorporated into a profit-making venture without written permission. | One scheduled public-data sync; no request-time publisher dependency. Exact API payload can be retained as provenance. | Preventive services are narrower than all abnormal-lab or chief-concern questions. Generated summaries may be “adaptations”; keep retrieved evidence verbatim and obtain legal review before commercial use. |
| **Curated CDC pages/publications** | Useful supplement for explicitly selected public-health topics. Canonical URL, page heading, section path, and retrieved text can support chunk-level citations. | Most content is public domain, but exceptions exist. Reuse requires attribution, a disclaimer, no substantive change, and a statement that the source is free. CDC says many online publications change continuously and warns against stale copies. | A small allowlisted fetcher and per-page diff job; no broad crawler. Store response validators when present plus hash and fetch time. | Page metadata/versioning is less uniform than USPSTF. Each page needs a rights check; extracted third-party content must be excluded. |
| **NICE syndication API** | Quality-assured guidance feed in HTML, Atom, JSON, or XML; strong publisher-controlled update mechanism. | Licence and API key required. AI use must be declared and approved; training on content is prohibited. The guide recommends refreshes at agreed intervals and currently lists substantial international fees. | Another external credential, sync adapter, licence record, and renewal/update process. | Technically sound but legally/administratively blocked for this US one-week effort unless the owner already has written approval and accepts fees. Do not scrape the public site as a workaround. |

### Corpus composition rule to carry into the final decision

Start from a named, finite manifest, not “the web”: topic, publisher document
identifier, canonical URL, included sections, jurisdiction, intended use, and
rights basis. A source enters an active corpus version only after its rights,
scope, and parsing checks pass. A source update creates a candidate corpus
version; it does not silently overwrite what prior answers cited.

This preserves a distinction the user needs to see:

- **patient-record evidence** says what was measured or documented for this
  chart;
- **guideline evidence** says what a named publisher wrote for a population,
  jurisdiction, and publication version;
- neither one is automatically a patient-specific recommendation.

## Minimum source and chunk contract

The retrieval backend should not define citation identity. All backend options
can emit the same canonical record, which the source registry resolves:

```text
GuidelineSource
  corpus_version
  publisher
  jurisdiction
  document_id
  document_title
  canonical_url
  publication_or_topic_date
  publisher_version_fields       # e.g. gradeVer/topicYear where present
  retrieved_at
  upstream_etag
  upstream_last_modified
  content_sha256
  rights_basis
  attribution_notice
  supersedes_document_id?
  active

GuidelineChunk
  source_id                      # guideline:{document_id}:{version}:{chunk_id}
  document_id
  section_id
  section_heading_path
  page_or_section
  chunk_ordinal
  exact_text
  exact_text_sha256
  embedding_model_revision
  index_build_id
```

`exact_text` is the evidence object. Sparse score, dense score, fused rank,
reranker score, and model names are retrieval diagnostics, not citation facts.
A deterministic verifier can therefore require that `quote_or_value` is an
exact normalized substring of the resolved, active chunk and that the cited
corpus version was in the turn's evidence pack. It must not infer clinical
truth from a high relevance score.

For USPSTF, the API's topic year and grade version are publisher fields, while
the response `ETag`/`Last-Modified` identifies the fetched dataset state. A
content hash fills the gap where a publisher has no immutable per-document
version. CDC sources require the same hash because “last reviewed” metadata is
not uniform. These are provenance controls proposed here, not publisher claims.

## Sparse plus dense retrieval

The first-stage experiment should be bounded and backend-neutral:

1. Validate one strict `EvidenceQuery` with generic clinical concepts and
   filters such as jurisdiction, publisher, active corpus version, topic, and
   population fields. Never accept a patient identifier.
2. Run sparse and dense legs over the same active chunk set, each with a fixed
   candidate cap (a reasonable starting experiment is top 20 per leg).
3. Fuse by rank, deduplicate by `source_id`, and retain each leg's score and
   rank. RRF is an appropriate untuned baseline because it combines positions
   rather than incomparable BM25 and cosine magnitudes; Qdrant's documentation
   specifically calls RRF its safe default when there is no tuning set
   ([hybrid-query guide](https://qdrant.tech/documentation/search/hybrid-queries/)).
4. Rerank no more than the fused top 20 and return only the top 3–5 grounded
   chunks to the answer model. These values are benchmark starting bounds, not
   chosen production constants.
5. If either leg or reranking fails, return an explicit degraded retrieval
   status. Do not turn a sparse-only or dense-only result into “no guideline
   evidence exists.”

SQLite FTS5 already supplies full-text search, BM25 ranking, and snippets and
is part of SQLite's amalgamation. Its BM25 score is inverted so numerically
lower is better, a detail adapters must normalize before diagnostics are
compared ([FTS5 documentation](https://www.sqlite.org/fts5.html)). SQLite itself
is public domain ([copyright statement](https://www.sqlite.org/copyright.html)).

## Deployable retrieval-store options

| Option | Grounding metadata | PHI egress | Operational dependencies | CPU, memory, and latency posture | Cost and offline testability |
| --- | --- | --- | --- | --- | --- |
| **SQLite FTS5 + exact NumPy or Faiss `Flat` dense search** | Canonical source/chunk tables stay in SQLite; the dense index contains only vectors plus stable integer-to-`source_id` mapping. Application code performs RRF and filters. | None after model artifacts are present. Query and corpus stay inside the agent container. | Smallest surface: existing SQLite plus NumPy, or one new native Faiss dependency. Faiss is MIT-licensed. Backup is an SQLite file plus a rebuildable dense index. | Exact scan is credible at the small-corpus ceiling. Faiss says `Flat` is the exact baseline and that all Faiss indexes are stored in RAM; its guide recommends direct computation when there will be relatively few searches. A 10k × 384 float32 matrix is about 14.6 MiB before index/runtime overhead. | No per-query vendor charge. Fully offline after pinning model artifacts. Hand-written fusion, locking, migrations, and index rebuild/atomic-swap logic are the main engineering cost. ([Faiss guide](https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index), [license](https://github.com/facebookresearch/faiss/blob/main/LICENSE)) |
| **LanceDB OSS embedded** | One local table can hold text, vectors, and metadata; supports SQL filters, BM25 FTS, vector search, hybrid query builders, RRF, and data versioning. | None for local OSS use. | New Apache-2.0 native Python/Rust/Arrow dependency, but no service, port, or credential. Its versioning is useful for rollback, though the application still owns publisher provenance. | Removes application-level vector plumbing. Actual process RSS, cold start, FTS-index build time, and concurrent-write behavior on this image are unmeasured. | No local licence/API fee and can run offline. Larger dependency and newer API surface than SQLite require a pin and clean-image rehearsal. ([project](https://github.com/lancedb/lancedb), [Python hybrid API](https://lancedb.github.io/lancedb/python/python/)) |
| **Qdrant single-node sidecar** | JSON payloads, payload indexes/filters, named sparse and dense vectors, hybrid prefetch, and RRF/DBSF are built in. | None when self-hosted on the internal Compose network. | New Apache-2.0 service, storage volume, health/readiness, internal auth/TLS decision, backup/snapshot, resource limits, and upgrade procedure. The local quickstart warns it starts with no auth or encryption, so it must never be exposed at Caddy or on a public port. | Qdrant publishes explicit sizing formulas. Raw dense storage is points × dimensions × bytes; HNSW and sparse indexes add memory/disk. For this small corpus, data size is modest, but process/service overhead and CPU contention are unmeasured. | No software fee self-hosted and supports offline operation. Highest operating surface; strongest built-in path if the corpus or filtering complexity outgrows the embedded candidates. ([hybrid queries](https://qdrant.tech/documentation/search/hybrid-queries/), [capacity planning](https://qdrant.tech/documentation/capacity-planning/), [quickstart security warning](https://qdrant.tech/documentation/quick-start/), [license](https://github.com/qdrant/qdrant)) |

All three can satisfy the same citation contract. The differentiator for this
week is not theoretical scale; it is measured retrieval quality, CPU latency
under the shared-host workload, implementation risk, and recoverability.

## Embedding and reranking options

### Local dense embedding baseline

`BAAI/bge-small-en-v1.5` is a concrete local baseline, not a decision. Its
model card reports 33.4M parameters, 384 dimensions, a 512-token sequence
limit, and an MIT licence; it advises evaluating whether a short-query
instruction helps on the task. At float32, parameters alone imply roughly
127 MiB of weights; int8 would have a theoretical weight-only floor around
32 MiB. Tokenizer state, activations, allocator, and runtime add to both, so
these are not RSS predictions. Pin the exact model revision and artifact
hash rather than the mutable model name.

### Reranker comparison

| Reranker | Grounding and egress | Dependencies and resource posture | Latency/cost | Offline quality testing |
| --- | --- | --- | --- | --- |
| **Cohere hosted `rerank-v4.0-fast` or pinned `rerank-v3.5`** | Sends query plus candidate guideline text outside the Droplet. Public guideline chunks are not PHI; a chart-derived query can be. Cohere says hosted SaaS is outside its BAA, so this path must reject patient-derived content unless an approved contract explicitly covers the deployed service. | SDK/API key, timeout/circuit breaker, new egress destination, audit disclosure, quota and deprecation monitoring. No local inference CPU. | Network-dependent and unmeasured on this host. API is billed per search; one unit is one query with up to 100 documents, with long-document splitting. Current public pricing should be captured at decision time. A dedicated Rerank 3.5 Model Vault is listed at $3,250/month or $5/hour, far outside the current $24/month host profile. | Adapter behavior can be mocked offline, but model ranking cannot. Golden retrieval cases need an explicit live-provider job and frozen result metadata. Cohere has already retired v2 models, so model ID is a versioned dependency. ([models](https://docs.cohere.com/docs/rerank), [API](https://docs.cohere.com/reference/rerank), [pricing](https://cohere.com/pricing), [deprecations](https://docs.cohere.com/docs/deprecations), [Trust Center](https://trustcenter.cohere.com/?format=html)) |
| **Local Sentence Transformers CrossEncoder with `ms-marco-MiniLM-L6-v2`** | Query and candidate text remain local. Scores only rank evidence; exact chunk text and provenance still drive citations. | Apache-2.0 model, 22.7M parameters. PyTorch is the default but is heavy; ONNX Runtime/OpenVINO and int8 export are supported CPU paths. Pin runtime, model revision, and exported artifact hash. | No API fee or network hop, but consumes scarce CPU on the same host as OpenEMR/MariaDB. Parameter-only float32 weight size is about 87 MiB; actual RSS and top-20 latency are unmeasured. | Entire pipeline can run offline after artifacts are built. Main risk is domain shift: the model card says it was trained on MS MARCO, so clinical-guideline relevance must be established by the project's own labelled retrieval set. ([model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2), [efficiency guide](https://www.sbert.net/docs/cross_encoder/usage/efficiency.html)) |
| **RRF-only degraded mode** | No extra content boundary; preserves source metadata exactly. | No model/runtime beyond the two retrievers. | Cheapest and most deterministic. It is fusion, not a learned semantic reranker, so it should not be claimed as “Cohere equivalent” without quality evidence. | Fully offline and an essential control arm/fallback. It establishes whether a learned reranker materially improves the golden set before adding its dependency. |

The local model cards report benchmark throughput on hardware unlike this
Droplet (the MiniLM card's throughput table uses a V100 GPU), so those numbers
must not be used as the production latency estimate.

## PHI and trust-boundary consequences

The safe rule is data-flow based, not vendor-name based:

- the corpus sync processes public publisher content and never patient data;
- local retrieval may consume an authorized, patient-bound question, but its
  request/result must remain in the existing correlation, timeout, audit, and
  telemetry controls;
- a hosted embedding or rerank request is a new model disclosure and egress
  event even if the downstream answer model is already approved;
- stripping name/MRN is not enough to declare a patient-derived clinical query
  non-PHI. Unless an approved de-identification policy or covered contract says
  otherwise, route such a query only to local components;
- never send an entire patient document or extracted intake/lab payload to the
  guideline retriever. Query construction should project only the bounded
  clinical concepts needed for evidence search;
- no raw query, snippet, or scores belong in ordinary logs or hosted traces.

These controls do not make the system HIPAA compliant; they preserve the
repository's existing “HIPAA-minded, demo-data-only” posture.

## Cost and capacity model

The options move cost between three places:

1. **Host compute.** Embedded search has no per-query fee, but local embedding
   and cross-encoding use the two CPU cores already identified as the
   concurrency ceiling. If measured contention forces the documented first
   resize, the host changes from 2 vCPU / 4 GiB to 4 vCPU / 8 GiB and the
   repository's recorded monthly cap doubles from $24 to $48
   ([deployment runbook](../deployment/digitalocean.md#cost-controlled-smoke-test)).
2. **Provider calls.** Cohere API cost scales with search units and makes
   failure/latency dependent on another provider. Trial keys are free but
   rate-limited and not authorized for production; a current production quote
   or console price is a decision prerequisite.
3. **Engineering/operations.** SQLite/Faiss has the least deployment surface
   but more application-owned fusion/index code. LanceDB moves that code into
   one embedded dependency. Qdrant moves it into a separately operated
   service. These costs should be judged against a corpus small enough for
   exact search, not against hypothetical web scale.

No external source supplies trustworthy latency or RSS for this exact image,
CPU, corpus, and concurrent OpenEMR load. Those remain measurements, not facts
that research can settle.

## Offline testability and selection experiment

The final decision can be made with one fixed experiment rather than framework
preference:

### Frozen inputs

- one rights-reviewed corpus manifest and immutable snapshot;
- deterministic chunker version and expected chunk hashes;
- 15–20 synthetic, non-PHI evidence queries spanning exact terms, synonyms,
  abbreviations, population qualifiers, version conflicts, out-of-corpus
  questions, and prompt-injection text inside a guideline chunk;
- human-labelled relevant `source_id`s, including at least one hard negative
  from the same document;
- separate tuning and holdout queries; do not tune on the holdout.

### Compare the same candidate bounds

- sparse only;
- dense only;
- sparse+dense RRF;
- RRF plus local cross-encoder;
- RRF plus hosted Cohere only if the input is synthetic and the account/data
  path is approved.

Report recall@20 before reranking, MRR/nDCG and citation-source correctness at
the final top 3–5, abstention on no-answer cases, p50/p95 stage latency, peak
RSS/CPU, cold start, index-build time, artifact size, provider cost, and
degraded-mode behavior. Run local candidates on the actual 2-vCPU/4-GiB image
at idle and alongside the existing 1- and 10-user load scenarios. Averages
alone are insufficient because the current system's risk is tail latency and
CPU contention.

### CI split

- **Always-offline:** schema/provenance validation, chunk hashes, FTS queries,
  deterministic fake embeddings, fusion, source resolution, exact-quote
  verifier, no-PHI logs, failure injection, and golden manifest integrity.
- **Artifact-backed offline integration:** pinned local encoder/reranker
  artifacts included in or cached for the image; no runtime model download.
- **Optional live provider:** hosted rerank quality, timeout, rate limit, and
  cost metadata, clearly reported as not run when credentials are absent.

Corpus updates and model/index changes must run the retrieval set before an
atomic active-version switch. Keep the prior corpus/index available for
rollback. Never let a failed sync leave a partially updated active index.

## Facts the final architecture ticket still has to decide

This research intentionally leaves the final choice open. The owner/architecture
decision needs these measured or approved facts:

1. Which named USPSTF topics and CDC supplements cover the selected Week 2
   demo cases without turning the product into general medical search?
2. Has AHRQ approved API access, and is the intended current/future use within
   the USPSTF notice? Is NICE explicitly excluded unless licensed?
3. Does exact embedded search meet recall and p95 on the frozen set, or does an
   integrated store/service earn its added surface?
4. Does the local cross-encoder materially beat RRF on holdout cases within the
   shared-host CPU budget?
5. If hosted Cohere is considered, what exact non-PHI query contract or
   covered enterprise agreement permits it, what model ID is pinned, and what
   current price/timeout/fallback is accepted?
6. What corpus refresh cadence, approval step, stale-source behavior, and
   rollback window will be committed to the runbook?

Until those facts exist, the defensible outcome is a bounded bake-off among
the local embedded candidates and the hosted rerank variant—not a final stack
selection from documentation alone.
