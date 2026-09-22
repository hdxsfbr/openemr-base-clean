<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

use OpenEMR\Common\Database\QueryUtils;

final class OpenEmrExtractionSource implements ExtractionSourcePort
{
    public function read(array $job): string
    {
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
        $bytes = (new \Document((int) $documentId))->get_data();
        if (!is_string($bytes) || $bytes === '') {
            throw new \RuntimeException('OpenEMR document content unavailable');
        }
        return $bytes;
    }
}

