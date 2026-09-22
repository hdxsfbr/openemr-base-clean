<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Modules\Copilot\Document\DocumentAuthorization;
use OpenEMR\Modules\Copilot\Document\OpenEmrDocumentAudit;
use OpenEMR\Modules\Copilot\Document\WorkerAccessSnapshot;

final class OpenEmrExtractionSource implements ExtractionSourcePort
{
    public function read(array $job): string
    {
        $correlationId = (string) ($job['correlation_id'] ?? '');
        $context = (new DocumentAuthorization(
            new WorkerAccessSnapshot($job),
            new OpenEmrDocumentAudit()
        ))->authorize('source_read', $correlationId);
        if ($context->siteId !== (string) ($job['site_id'] ?? '') || $context->pid !== (int) ($job['pid'] ?? 0)) {
            throw new \RuntimeException('Worker document context mismatch');
        }
        $documentId = (string) ($job['source']['openemr_document_id'] ?? '');
        if (preg_match('/^[1-9][0-9]{0,18}$/', $documentId) !== 1) {
            throw new \RuntimeException('Invalid OpenEMR document identifier');
        }
        $rows = QueryUtils::fetchRecords(
            'SELECT id FROM documents WHERE id = ? AND foreign_id = ? AND deleted = 0 LIMIT 1',
            [(int) $documentId, (int) $job['pid']]
        );
        if (count($rows) !== 1) {
            throw new \RuntimeException('OpenEMR document unavailable');
        }
        try {
            // Audit success must commit after the live authorization recheck
            // and before Document::get_data() decrypts the source bytes.
            (new OpenEmrDocumentAudit())->record($context, 'source_read', true, 'worker_authorized', [
                'correlation_id' => $correlationId,
                'source_document_id' => (string) ($job['source']['source_document_id'] ?? ''),
                'job_id' => (string) ($job['job_id'] ?? ''),
            ]);
        } catch (\Throwable $exception) {
            throw new \RuntimeException('Worker source audit unavailable', 0, $exception);
        }
        $bytes = (new \Document((int) $documentId))->get_data();
        if (!is_string($bytes) || $bytes === '') {
            throw new \RuntimeException('OpenEMR document content unavailable');
        }
        return $bytes;
    }
}
