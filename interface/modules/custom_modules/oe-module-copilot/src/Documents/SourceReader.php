<?php

/** @package OpenEMR */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Documents;

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Modules\Copilot\Gateway\AuthorizedPatientContext;
use OpenEMR\Modules\Copilot\Gateway\GatewayDenied;

/** Internal token-authenticated read seam for the later intake-extractor worker. */
final class SourceReader
{
    /** @return array{source: array<string, mixed>, bytes: string} @throws GatewayDenied */
    public function read(AuthorizedPatientContext $ctx, string $sourceId): array
    {
        if (!$ctx->allows('labs') || !AclMain::aclCheckCore('patients', 'docs', $ctx->username)) {
            throw new GatewayDenied('document_acl', 403);
        }
        $source = (new SourceDocumentRepository())->findSource($sourceId);
        if ($source === null || $source['site_id'] !== $ctx->siteId || (int) $source['pid'] !== $ctx->pid) {
            throw new GatewayDenied('source_not_found', 404);
        }
        $row = QueryUtils::fetchRecords(
            'SELECT id, foreign_id, hash, deleted, mimetype FROM documents WHERE id = ? AND foreign_id = ?',
            [(int) $source['native_document_id'], $ctx->pid]
        );
        if (
            count($row) !== 1 || (int) $row[0]['deleted'] !== 0 || $row[0]['hash'] !== $source['content_hash']
            || $row[0]['mimetype'] !== $source['mime_type']
        ) {
            throw new GatewayDenied('source_integrity', 409);
        }
        // `Document::get_data()` is the supported storage/decryption seam and
        // does not depend on a browser CSRF key. Authorization and patient
        // binding were already rechecked above, before this storage read.
        $bytes = (new \Document((int) $source['native_document_id']))->get_data();
        if (!is_string($bytes) || hash('sha3-512', $bytes) !== $source['content_hash']) {
            throw new GatewayDenied('source_integrity', 409);
        }
        return ['source' => $source, 'bytes' => $bytes];
    }

}
