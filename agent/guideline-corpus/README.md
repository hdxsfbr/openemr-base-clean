# Guideline corpus build slot

The deployment script copies the reviewed `corpus.jsonl` and `manifest.json`
from `docs/research/week2-retrieval-benchmark/` into this image-build directory.
The empty slot keeps ordinary agent image builds valid while guideline
readiness remains disabled unless those exact hash-checked artifacts and the
pinned local models are present.
