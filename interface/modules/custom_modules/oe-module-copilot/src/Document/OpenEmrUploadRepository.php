<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

use OpenEMR\Common\Database\QueryUtils;

final class OpenEmrUploadRepository implements UploadRepositoryPort
{
    public function transaction(callable $action): mixed
    {
        return QueryUtils::inTransaction($action);
    }

    public function findIntentByKey(string $siteId, int $pid, string $category, string $idempotencyKey): ?array
    {
        $row = $this->one(
            'SELECT * FROM copilot_document_upload WHERE site_id = ? AND pid = ? AND category = ? '
            . 'AND upload_request_idempotency_key = ? LIMIT 1',
            [$siteId, $pid, $category, $idempotencyKey]
        );
        return $row === null ? null : $this->intent($row);
    }

    public function insertIntent(array $intent): void
    {
        QueryUtils::sqlStatementThrowException(
            'INSERT INTO copilot_document_upload '
            . '(upload_intent_id, site_id, pid, user_id, category, upload_request_idempotency_key, '
            . 'original_filename, declared_mime_type, declared_byte_count, declared_page_count, token_hash, '
            . 'expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
            . 'ON DUPLICATE KEY UPDATE upload_intent_id = upload_intent_id',
            [
                $intent['upload_intent_id'], $intent['site_id'], $intent['pid'], $intent['user_id'],
                $intent['category'], $intent['idempotency_key'], $intent['original_filename'],
                $intent['declared_mime_type'], $intent['declared_byte_count'], $intent['declared_page_count'],
                $intent['token_hash'], $this->databaseTime($intent['expires_at']), $intent['created_at'],
            ]
        );
    }

    public function findIntent(string $intentId): ?array
    {
        $row = $this->one('SELECT * FROM copilot_document_upload WHERE upload_intent_id = ? LIMIT 1', [$intentId]);
        return $row === null ? null : $this->intent($row);
    }

    public function completeIntent(string $intentId, array $source): bool
    {
        QueryUtils::sqlStatementThrowException(
            'UPDATE copilot_document_upload SET source_document_id = ?, openemr_document_id = ?, '
            . 'content_sha256 = ?, actual_byte_count = ?, actual_mime_type = ?, actual_page_count = ?, completed_at = NOW() '
            . 'WHERE upload_intent_id = ? AND source_document_id IS NULL',
            [
                $source['source_document_id'], $source['openemr_document_id'], $source['content_sha256'],
                $source['byte_count'], $source['mime_type'], $source['page_count'], $intentId,
            ]
        );
        $completed = QueryUtils::affectedRows() === 1;
        if ($completed) {
            QueryUtils::sqlStatementThrowException(
                'INSERT INTO copilot_extraction_job (job_id, source_document_id, extraction_version, handoff_id, '
                . 'correlation_id, status) VALUES (UUID(), ?, 1, UUID(), ?, \'queued\') '
                . 'ON DUPLICATE KEY UPDATE job_id = job_id',
                [$source['source_document_id'], $source['correlation_id']]
            );
        }
        return $completed;
    }

    public function findSource(string $sourceDocumentId): ?array
    {
        $row = $this->one(
            'SELECT * FROM copilot_document_upload WHERE source_document_id = ? AND completed_at IS NOT NULL LIMIT 1',
            [$sourceDocumentId]
        );
        return $row === null ? null : $this->source($row);
    }

    public function findDuplicateSourceIds(string $siteId, int $pid, string $sha256, string $exceptIntentId): array
    {
        $rows = QueryUtils::fetchRecords(
            'SELECT source_document_id FROM copilot_document_upload WHERE site_id = ? AND pid = ? '
            . 'AND content_sha256 = ? AND upload_intent_id <> ? AND source_document_id IS NOT NULL '
            . 'ORDER BY completed_at DESC LIMIT 10',
            [$siteId, $pid, $sha256, $exceptIntentId]
        );
        return array_values(array_map(static fn(array $row): string => (string) $row['source_document_id'], $rows));
    }

    public function appendOutbox(array $event): void
    {
        QueryUtils::sqlStatementThrowException(
            'INSERT INTO copilot_action_outbox '
            . '(event_id, event_type, aggregate_id, site_id, pid, user_id, correlation_id, payload_json, created_at) '
            . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                $event['event_id'], $event['event_type'], $event['aggregate_id'], $event['site_id'],
                $event['pid'], $event['user_id'], $event['correlation_id'], '{}', $event['created_at'],
            ]
        );
    }

    /** @return array<string, mixed>|null */
    private function one(string $sql, array $parameters): ?array
    {
        $rows = QueryUtils::fetchRecords($sql, $parameters);
        return $rows[0] ?? null;
    }

    /** @param array<string, mixed> $row @return array<string, mixed> */
    private function intent(array $row): array
    {
        return [
            'upload_intent_id' => (string) $row['upload_intent_id'],
            'site_id' => (string) $row['site_id'],
            'pid' => (int) $row['pid'],
            'user_id' => (int) $row['user_id'],
            'category' => (string) $row['category'],
            'idempotency_key' => (string) $row['upload_request_idempotency_key'],
            'original_filename' => (string) $row['original_filename'],
            'declared_mime_type' => (string) $row['declared_mime_type'],
            'declared_byte_count' => (int) $row['declared_byte_count'],
            'declared_page_count' => (int) $row['declared_page_count'],
            'token_hash' => (string) $row['token_hash'],
            'expires_at' => (new \DateTimeImmutable((string) $row['expires_at'], new \DateTimeZone('UTC')))->format('Y-m-d\TH:i:s\Z'),
            'created_at' => (string) $row['created_at'],
            'source_document_id' => $row['source_document_id'] === null ? null : (string) $row['source_document_id'],
        ];
    }

    /** @param array<string, mixed> $row @return array<string, mixed> */
    private function source(array $row): array
    {
        return [
            'source_document_id' => (string) $row['source_document_id'],
            'openemr_document_id' => (string) $row['openemr_document_id'],
            'upload_intent_id' => (string) $row['upload_intent_id'],
            'document_type' => (string) $row['category'],
            'content_sha256' => (string) $row['content_sha256'],
            'byte_count' => (int) $row['actual_byte_count'],
            'mime_type' => (string) $row['actual_mime_type'],
            'page_count' => (int) $row['actual_page_count'],
            'site_id' => (string) $row['site_id'],
            'pid' => (int) $row['pid'],
            'created_by' => (int) $row['user_id'],
        ];
    }

    private function databaseTime(string $iso): string
    {
        return (new \DateTimeImmutable($iso))->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d H:i:s');
    }
}
