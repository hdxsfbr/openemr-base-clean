# Slice 3A: approved guideline corpus and retrieval contracts

GitLab #40 implements the offline foundation for the future bounded
`evidence_retriever`; it does not implement retrieval, ranking, RRF, reranking,
source resolution, a UI lane, a worker, or a deployment flow.

## Approved input and rights boundary

The approved release input is exactly the eight-topic, 160-block USPSTF
snapshot already committed under `docs/research/week2-retrieval-benchmark/`.
`agent/guideline_corpus/approved_manifest.json` makes the approval explicit:
publisher, canonical HTTPS URL, jurisdiction, the snapshot and approval times,
source snapshot hash, the AHRQ reuse-notice basis, and the manual/offline-only
rules. Publication/review dates are recorded as absent rather than invented
because they were not retained by the frozen snapshot.

The manifest permits only attributed excerpts for this non-commercial,
synthetic-demo project. It prohibits automatic synchronization, patient-specific
publisher requests, unattributed redistribution, and runtime web retrieval.
No corpus or model material is downloaded by the builder or runtime path.

## Deterministic artifacts

`python -m app.guideline_corpus.build build --model-dir <preprovisioned-pinned-model-dir>`
normalizes NFC/line endings, preserves heading paths, applies the approved
160-word/single-sentence-overlap policy without crossing a heading block, and
writes these immutable artifacts:

- `chunks.jsonl`: exact chunks plus provenance, stable IDs/ordinals, source and
  chunk hashes.
- `sparse.sqlite`: SQLite FTS5 input over that exact ordered chunk set.
- `dense.faiss` and `dense.ids.json`: normalized 384-dimension BGE-small
  vectors and their identical ordered chunk IDs.
- `artifact-manifest.json`: hashes, byte sizes, source-manifest hash, pinned
  model/tokenizer/runtime revisions, and SQLite runtime.

`active.json` binds the approved corpus version to the immutable artifact
manifest. Validation rejects unknown/missing source fields, duplicate or
wrong-version source sets, content/source/artifact hash drift, malformed or
stale-at-approval provenance, unavailable/wrong-hash model artifacts, and
sparse/dense parity drift. Build output emits only status, counts, timings,
hash-derived artifacts, and byte sizes—never query, excerpt, or patient text.

Observed locally on 2026-09-22 with the pinned BGE model already provisioned:
160 chunks; `chunks.jsonl` 245,747 bytes; FTS5 253,952 bytes; FAISS 245,805
bytes; dense ID mapping 2,382 bytes; deterministic drift rebuild 7,739 ms.
These are local build observations, not deployed retrieval performance.

## Contracts

The versioned `3.0.0` Pydantic contracts export to `contracts/schema/`:
`EvidenceQuery`, `GuidelineCandidate`, `GuidelineExcerpt`,
`GuidelineCitation`, `GuidelineEvidenceClaim`, and the typed retrieval
limitation. `EvidenceQuery` accepts only finite approved concepts, one matching
topic filter, top-k 1–5, the single active corpus version, correlation/handoff
IDs, and a maximum 2-second deadline. It intentionally has no free-text query
field, patient selector, note/OCR/document field, or advice/dosing intent.

Guideline claims are their own `guideline_evidence` type and require a single
resolver-authored citation tied to one immutable `guideline:` source, exact
quote, section/chunk, hashes, publisher metadata, and corpus version. The
claim text has a deterministic publisher-plus-exact-quote template, preventing
model-authored applicability or advice framing. Resolver and verifier behavior
remain later Slice 3 work.

## Verification

From `agent/`:

```bash
.venv/bin/python -m app.guideline_corpus.build validate
.venv/bin/python -m app.guideline_corpus.build drift --model-dir <pinned-model-dir>
.venv/bin/python -m pytest -q tests/test_guideline_contracts.py tests/test_guideline_corpus.py
.venv/bin/python -m app.contracts.export --check
```

The artifact build needs a separately provisioned, hash-checked pinned BGE
model directory; it intentionally fails closed if that local prerequisite is
absent. It never falls back to a network fetch, another model, or a synthetic
vector approximation.
