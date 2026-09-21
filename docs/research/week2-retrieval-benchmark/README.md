# Reproducing the Week 2 retrieval benchmark

This directory freezes the source manifest, synthetic queries, derived corpus,
executable benchmark, dependency versions, and measured JSON result used by the
Week 2 retrieval decision. It contains no patient data.

The concurrency section measures sparse retrieval, dense retrieval, and the
complete sparse + dense + RRF + cross-encoder path with one and ten workers.
These are host-local engineering measurements, not substitutes for the
required two-vCPU shared-deployment release run.

The executable also projects the final five results into their citation
payload and compares every text and metadata field byte-for-byte with the
frozen corpus/manifest. The aggregate count, preservation rate, and any
field-level failures are recorded in `results.json`.

The corpus excerpts are reproduced verbatim with source URLs under the
[USPSTF reuse notice](https://www.uspreventiveservicestaskforce.org/uspstf/recommendation-topics/copyright-notice).
Do not edit the excerpts. The benchmark is evidence for this non-commercial
project and must not be treated as a general content-redistribution package.

Create an isolated environment and install the pinned packages:

```bash
python -m venv /tmp/week2-retrieval-benchmark
/tmp/week2-retrieval-benchmark/bin/pip install -r docs/research/week2-retrieval-benchmark/requirements.txt
```

Re-run entirely from the frozen corpus and a previously cached model:

```bash
/tmp/week2-retrieval-benchmark/bin/python \
  docs/research/week2-retrieval-benchmark/benchmark.py --offline
```

An offline run fails before measurement if the manifest, corpus, query set, or
either pinned ONNX model differs from the expected SHA-256. Refresh mode is the
only path that intentionally creates a new corpus; adopting its new hash
requires review and an explicit constant update.

Refresh the publisher-derived corpus intentionally, creating a new corpus hash
that requires review before replacing the committed result:

```bash
/tmp/week2-retrieval-benchmark/bin/python \
  docs/research/week2-retrieval-benchmark/benchmark.py --refresh-corpus
```

The local reranker is the Apache-2.0
`cross-encoder/ms-marco-MiniLM-L6-v2` ONNX AVX2 artifact pinned to Hugging Face
revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`. First use downloads it into
the normal Hugging Face cache; `--offline` fails if that pinned artifact is not
already present.

The neural dense leg uses the MIT-licensed `BAAI/bge-small-en-v1.5` ONNX
artifact pinned to revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`.
The earlier TF-IDF/SVD vectors remain in the benchmark only as a non-neural
control and are not the proposed production dense retriever.
