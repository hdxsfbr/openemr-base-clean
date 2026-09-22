<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Core\OEGlobalsBag;

final class OpenEmrDocumentStore implements DocumentStorePort
{
    public function store(DocumentContext $context, string $category, string $filename, string $mimeType, string $bytes): string
    {
        if (!OEGlobalsBag::getInstance()->getBoolean('drive_encryption')) {
            throw new \RuntimeException('Encrypted OpenEMR document storage is required');
        }
        $categoryName = $category === 'lab_report' ? 'Lab Report' : 'Medical Record';
        $rows = QueryUtils::fetchRecords(
            'SELECT id FROM categories WHERE name = ? AND aco_spec = ? ORDER BY id LIMIT 1',
            [$categoryName, 'patients|docs']
        );
        $categoryId = (int) ($rows[0]['id'] ?? 0);
        if ($categoryId <= 0) {
            throw new \RuntimeException('OpenEMR document category unavailable');
        }
        $document = new \Document();
        $error = $document->createDocument(
            (string) $context->pid,
            $categoryId,
            $filename,
            $mimeType,
            $bytes,
            '',
            1,
            $context->userId
        );
        if ($error !== '') {
            throw new \RuntimeException('OpenEMR document storage failed');
        }
        return (string) $document->get_id();
    }

    public function read(DocumentContext $context, string $openEmrDocumentId): string
    {
        if (preg_match('/^[1-9][0-9]{0,18}$/', $openEmrDocumentId) !== 1) {
            throw new \RuntimeException('Invalid OpenEMR document identifier');
        }
        $rows = QueryUtils::fetchRecords(
            'SELECT id FROM documents WHERE id = ? AND foreign_id = ? AND deleted = 0 LIMIT 1',
            [(int) $openEmrDocumentId, $context->pid]
        );
        if (count($rows) !== 1) {
            throw new \RuntimeException('OpenEMR document unavailable');
        }
        $bytes = (new \Document((int) $openEmrDocumentId))->get_data();
        if (!is_string($bytes) || $bytes === '') {
            throw new \RuntimeException('OpenEMR document content unavailable');
        }
        return $bytes;
    }

    public function remove(DocumentContext $context, string $openEmrDocumentId): void
    {
        if (preg_match('/^[1-9][0-9]{0,18}$/', $openEmrDocumentId) !== 1) {
            return;
        }
        QueryUtils::sqlStatementThrowException(
            'UPDATE documents SET deleted = 1 WHERE id = ? AND foreign_id = ?',
            [(int) $openEmrDocumentId, $context->pid]
        );
    }
}
