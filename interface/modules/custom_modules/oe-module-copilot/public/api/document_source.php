<?php

/** Reauthorize and open one immutable document source for a preview citation. @package OpenEMR */

require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Modules\Copilot\Documents\SourceDocumentRepository;
use OpenEMR\Modules\Copilot\Documents\UploadContext;
use OpenEMR\Modules\Copilot\Gateway\Audit;
use OpenEMR\Modules\Copilot\Gateway\GatewayDenied;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
try {
    $ctx = UploadContext::fromSession($correlationId);
    $sourceId = (string) ($_GET['source_id'] ?? '');
    $source = (new SourceDocumentRepository())->findSource($sourceId);
    if ($source === null || $source['site_id'] !== $ctx->siteId || (int) $source['pid'] !== $ctx->pid) {
        throw new GatewayDenied('source_not_found', 404);
    }
    $rows = QueryUtils::fetchRecords(
        'SELECT id, foreign_id, hash, deleted, mimetype FROM documents WHERE id = ? AND foreign_id = ?',
        [(int) $source['native_document_id'], $ctx->pid]
    );
    if (count($rows) !== 1 || (int) $rows[0]['deleted'] !== 0 || $rows[0]['hash'] !== $source['content_hash'] || $rows[0]['mimetype'] !== 'application/pdf') {
        throw new GatewayDenied('source_integrity', 409);
    }
    $bytes = (new \Document((int) $source['native_document_id']))->get_data();
    if (!is_string($bytes) || hash('sha3-512', $bytes) !== $source['content_hash']) {
        throw new GatewayDenied('source_integrity', 409);
    }
    Audit::event('copilot-document-source-open', $ctx->username, $ctx->groupName, true, $ctx->pid, [
        'source_id' => $sourceId, 'correlation_id' => $correlationId,
    ]);
    header('Content-Type: application/pdf');
    header('Content-Disposition: inline; filename="agentforge-lab.pdf"');
    header('Cache-Control: no-store');
    header('X-Correlation-Id: ' . $correlationId);
    echo $bytes;
} catch (GatewayDenied $denied) {
    Audit::denied(null, null, null, $denied->reason, ['stage' => 'document_source_open', 'correlation_id' => $correlationId]);
    Json::error($denied->httpStatus, 'unauthorized', 'Request denied.', $correlationId);
} catch (\Throwable) {
    Audit::denied(null, null, null, 'source_unavailable', ['stage' => 'document_source_open', 'correlation_id' => $correlationId]);
    Json::error(503, 'dependency_unavailable', 'Source temporarily unavailable.', $correlationId);
}
