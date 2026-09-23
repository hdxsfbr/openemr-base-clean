# Bounded OpenRouter PDF client: one live smoke run (2026-09-22)

GitLab #51 (child of #50) added `agent/app/openrouter_client.py`: a small
injectable client that sends authorized PDF bytes to a pinned OpenRouter
model with a requested JSON schema and returns a typed result. It is not
wired into `intake_extractor` yet (#52-#54). This records the one live run
against the real OpenRouter API required by #51's "Done when" list, using the
owner-provided local key at `~/.config/agentforge/openrouter_api_key`
(`AGENTS.md`).

## Setup

A one-page synthetic PDF was built with Pillow (`Image.save(..., "PDF")`) from
a rendered bitmap: "AgentForge Synthetic Lab Report", `Test: Hemoglobin A1c`,
`Value: 6.1 %`, `Reference range: 4.0-5.6 %`, `Collection date: 2026-09-10`,
`Flag: abnormal`. This produces a real, valid PDF with **no text layer** — a
raster page, the same shape as a scanned lab report, not the fixed `Tj`-string
byte blobs `test_intake_extractor.py` and the current `intake_extractor.py`
parser use (those are not valid renderable PDFs; a real PDF-consuming API
cannot read them). Model: `google/gemini-2.5-flash` (`openrouter_model_id`),
requested via OpenRouter's `file-parser` plugin. No PDF bytes, extracted
text, or prompts were logged; only status/reason/usage counts, matching the
client's logging discipline.

## What the response actually contained

**Engine `pdf-text`** (the code default; reads the PDF's existing text layer,
no OCR cost): `status: ok`, every field `null`, `evidence: []`. The synthetic
page has no text layer, so there was nothing to extract — the plugin does not
fall back to OCR or vision on its own.

**Engine `native`** (page images passed directly to the model's own vision
input, no OpenRouter-side OCR step): `status: ok`, all six fields correctly
extracted (`test_name: "Hemoglobin A1c"`, `value: "6.1"`, `unit: "%"`,
`reference_range: "4.0-5.6%"`, `collection_date: "2026-09-10"`,
`abnormal_flag: "abnormal"`). Every evidence entry named `page: 1` correctly,
but **every `bounding_box` came back as an empty object `{}`**, even though
the schema required the field and the prompt explicitly asked for a
normalized `left`/`top`/`width`/`height` box. The model supplied a page
number but never real box geometry, on a request built specifically to make
that easy (one short line of text per field, a nearly empty page).

## What this does and does not change

This **confirms** ADR-0009's decision 3 (OCR then bounded vision retry) and
its "Vision-model-only extraction" alternative's rejection reason ("weak
character-level provenance"), rather than replacing it: page-level attribution
is available from a vision-capable model call; pixel-accurate bounding boxes
are not, at least not from this model/engine/prompt. ADR-0009's field-evidence
requirement (decision 6) for a normalized bounding box on every proposed fact
will need to come from the deterministic local OCR/render step's own page
geometry (as decision 3 already assumes), not from asking the OpenRouter-side
model to report one. This client's job stays what #51 scoped it as: a bounded
transport that returns whatever structured output the pinned model gives back
for a requested schema, verified deterministically by its caller — never a
source of grounding on its own.

It also confirms the `pdf-text` engine is unsuitable as the sole path once
lab/intake documents are scanned images rather than text-layer PDFs (#53/#54):
whichever task wires this client into `intake_extractor` will need to choose
an engine (or a local-OCR to `native`-vision fallback) per the actual document
shape, not assume `pdf-text` alone. That engine selection strategy is
out of scope for #51 and is left to #52-#54.

## Not run

No failure-path live call (rate limit, malformed model output, network
failure) — those are exercised by `agent/tests/test_openrouter_client.py`
against a mocked transport, per #51's "no live API calls in CI" requirement.
No lab/intake schema, no multi-result contract, no page/box verification
logic — all out of scope for #51.
