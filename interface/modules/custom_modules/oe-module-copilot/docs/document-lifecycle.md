# Document lifecycle setup and verification

Module version 0.6.0 adds the Week 2 C1/C2 document boundary. It supports a
patient-bound laboratory PDF and intake PDF/PNG/JPEG workflow. The browser
never sends a patient identifier. OpenEMR's current session, open chart,
`patients|docs` ACL, squad restriction, and break-glass state are evaluated on
every intent, content upload, and source read.

## Runtime requirements

- Keep OpenEMR `drive_encryption` enabled. The module refuses to store a source
  when encrypted document storage is disabled.
- Keep `secure_upload` and the site's file allowlist enabled. The module calls
  OpenEMR's `isWhiteFile()` boundary before reading upload content; site malware
  filter listeners therefore remain authoritative and scanner errors fail
  closed.
- Set PHP `upload_max_filesize` above 20 MiB and `post_max_size` high enough for
  the multipart envelope. Module validation still enforces 20 MiB/20 pages for
  lab PDFs and 10 MiB/10 pages for intake forms.
- Optionally set `COPILOT_UPLOAD_SECRET_FILE` to a root-managed, Apache-readable
  file containing at least 32 random bytes. Otherwise a mode-0600 secret is
  created under the site's protected `documents/copilot` directory.

The upload endpoints are session- and CSRF-authenticated:

- `POST public/api/documents.php/upload-intents`
- `POST public/api/documents.php/upload-intents/{intent_uuid}/content`

Only the second request is multipart. Its accepted fields are exactly
`csrf_token`, `upload_token`, and one file named `content`. Neither endpoint
accepts a site, patient, user, storage path, or OpenEMR document identifier.

## Storage ownership and recovery

OpenEMR `Document::createDocument()` owns encrypted bytes and path generation.
The module stores only immutable identifiers, measured metadata, and SHA-256 in
`copilot_document_upload`. A mapping/outbox transaction failure marks the newly
created OpenEMR document deleted before returning a generic `unavailable`
limitation. No document bytes, decrypted fragments, client filenames, or
storage paths are written to module logs or audit comments.

Run an install/upgrade/rollback rehearsal against a disposable MariaDB schema:

```sh
mariadb openemr_test < sql/install.sql
mariadb openemr_test < sql/install.sql
mariadb openemr_test < sql/upgrade_0.6.0.sql
mariadb openemr_test < sql/uninstall.sql
```

The second install and the upgrade are intentionally idempotent. After
uninstall, no `copilot_%` table should remain.
