# Internal extraction worker gateway

`public/gateway/extraction.php` is an internal-network-only endpoint. It has no
browser session and gives the worker no database access. The endpoint reuses
the bytes in `COPILOT_DELEGATION_SECRET_FILE`, but derives a purpose-separated
HMAC key for extraction requests.

Every request is `POST` JSON with exactly:

```json
{"operation":"claim|complete|fail|cancel","command":{}}
```

The request headers are `X-Copilot-Worker-Timestamp` (Unix seconds),
`X-Copilot-Worker-Nonce` (32 lowercase hexadecimal characters), and
`X-Copilot-Worker-Signature` (lowercase HMAC-SHA256 hexadecimal). The nonce is
single-use and the timestamp has a 60-second skew limit. Derive the signing key
as `HMAC-SHA256(secret, "copilot-extraction-worker-v1")`, then sign:

```text
copilot-extraction-v1\n
<timestamp>\n
<nonce>\n
POST\n
/gateway/extraction.php\n
<lowercase SHA-256 hex of the exact request body bytes>
```

The claim command is `{"worker_id":"intake-extractor-01"}`. An idle claim
returns `{"status":"idle"}`. A leased job returns job, handoff, correlation,
attempt, extraction-version, lease-token, lease-expiry, exact
`SourceDocumentRef`, and `content_base64` fields.

The complete command is `{"job_id":"<uuid>","lease_token":"<opaque>",
"envelope":<strict LabExtractionEnvelope or IntakeExtractionEnvelope>}`.
The module verifies the lease, exact source identity/hash, exported JSON
Schema, OCR/evidence integrity, and unique field IDs. It then atomically writes
one immutable extraction, its flattened proposed facts, the completed job, and
an identifiers-only outbox event. An exact retry returns `outcome=replayed`;
a different terminal body conflicts.

The fail command adds `limitation_code` and `retryable`; cancel adds one of
`worker_canceled`, `deadline_exceeded`, or `shutdown` as `reason_code`. Both are
terminal and idempotent. Error envelopes contain only `code`, `correlation_id`,
`retryable`, and `limitation`. Document bytes, OCR, extracted values, and
evidence quotes never enter errors, audit comments, or ordinary logs.
