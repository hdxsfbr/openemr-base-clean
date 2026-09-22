<?php

/**
 * OpenEMR persistence adapter for append-only review and promotion records.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Review;

use OpenEMR\Common\Database\QueryUtils;
use Opis\JsonSchema\Validator;

final class OpenEmrReviewRepository implements ReviewRepositoryPort
{
    public function __construct(private readonly string $schemaDirectory)
    {
    }

    public function transaction(callable $callback): mixed
    {
        return QueryUtils::inTransaction($callback);
    }

    public function findReviewByIdempotencyKey(string $key): ?array
    {
        $row = $this->one($this->reviewSelect() . ' WHERE r.review_idempotency_key = ? LIMIT 1', [$key]);
        return $row === null ? null : $this->review($row);
    }

    public function findExtraction(string $extractionId): ?array
    {
        $row = $this->one(
            'SELECT e.*, u.site_id, u.pid, u.openemr_document_id, u.upload_intent_id, u.category, '
            . 'u.content_sha256, u.actual_byte_count, u.actual_mime_type, u.actual_page_count '
            . 'FROM copilot_document_extraction e JOIN copilot_document_upload u '
            . 'ON u.source_document_id = e.source_document_id WHERE e.extraction_id = ? LIMIT 1 FOR UPDATE',
            [$extractionId]
        );
        if ($row === null) {
            return null;
        }
        $envelope = $this->json((string) $row['extraction_json']);
        return [
            'extraction_id' => (string) $row['extraction_id'],
            'extraction_version' => (int) $row['extraction_version'],
            'source_document_id' => (string) $row['source_document_id'],
            'source_content_sha256' => (string) $row['content_sha256'],
            'site_id' => (string) $row['site_id'],
            'pid' => (int) $row['pid'],
            'schema_name' => (string) $row['schema_name'],
            'schema_version' => (string) $row['schema_version'],
            'state' => (string) $row['state'],
            'source' => $envelope['source'] ?? [
                'source_document_id' => (string) $row['source_document_id'],
                'openemr_document_id' => (string) $row['openemr_document_id'],
                'upload_intent_id' => (string) $row['upload_intent_id'],
                'document_type' => (string) $row['category'],
                'content_sha256' => (string) $row['content_sha256'],
                'byte_count' => (int) $row['actual_byte_count'],
                'mime_type' => (string) $row['actual_mime_type'],
                'page_count' => (int) $row['actual_page_count'],
            ],
            'payload' => $envelope['payload'] ?? [],
        ];
    }

    public function findProposedFact(string $extractionId, string $fieldId): ?array
    {
        $row = $this->one(
            'SELECT * FROM copilot_proposed_fact WHERE extraction_id = ? AND field_id = ? LIMIT 1 FOR UPDATE',
            [$extractionId, $fieldId]
        );
        if ($row === null) {
            return null;
        }
        $evidence = $this->json((string) $row['evidence_json']);
        $ids = [];
        foreach ($evidence as $item) {
            if (is_array($item) && is_string($item['evidence_id'] ?? null)) {
                $ids[] = $item['evidence_id'];
            } elseif (is_string($item)) {
                $ids[] = $item;
            }
        }
        return [
            'extraction_id' => (string) $row['extraction_id'],
            'field_id' => (string) $row['field_id'],
            'typed_value' => $row['typed_value_json'] === null ? null : $this->json((string) $row['typed_value_json']),
            'evidence_ids' => $ids,
            'state' => (string) $row['state'],
        ];
    }

    public function findCurrentReview(string $extractionId, string $fieldId): ?array
    {
        $row = $this->one(
            $this->reviewSelect() . ' LEFT JOIN copilot_fact_review newer ON newer.supersedes_review_id = r.review_id '
            . 'WHERE r.extraction_id = ? AND r.field_id = ? AND newer.review_id IS NULL '
            . 'ORDER BY r.reviewed_at DESC LIMIT 1',
            [$extractionId, $fieldId]
        );
        return $row === null ? null : $this->review($row);
    }

    public function insertReview(array $review): void
    {
        $stored = $review;
        unset($stored['site_id'], $stored['pid'], $stored['idempotency_outcome']);
        QueryUtils::sqlStatementThrowException(
            'INSERT INTO copilot_fact_review (review_id, review_idempotency_key, extraction_id, extraction_version, '
            . 'field_id, decision, review_json, supersedes_review_id, reviewed_by, reviewed_at) '
            . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                $review['review_id'], $review['idempotency_key'], $review['extraction_id'], $review['extraction_version'],
                $review['field_id'], $review['decision'], $this->encode($stored), $review['supersedes_review_id'],
                $review['reviewed_by'], $this->databaseTime($review['reviewed_at']),
            ]
        );
    }

    public function appendOutbox(array $event): void
    {
        QueryUtils::sqlStatementThrowException(
            'INSERT INTO copilot_action_outbox '
            . '(event_id, event_type, aggregate_id, site_id, pid, user_id, correlation_id, payload_json, created_at) '
            . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                $event['event_id'], $event['event_type'], $event['aggregate_id'], $event['site_id'],
                $event['pid'], $event['user_id'], $event['correlation_id'], $this->encode($event['payload']), $event['created_at'],
            ]
        );
    }

    public function findRecordByActionIdempotencyKey(string $key): ?array
    {
        $row = $this->one('SELECT * FROM copilot_promoted_record WHERE action_idempotency_key = ? LIMIT 1', [$key]);
        return $row === null ? null : $this->record($row);
    }

    public function findRecordByDeterministicKey(string $key): ?array
    {
        $row = $this->one('SELECT * FROM copilot_promoted_record WHERE deterministic_promotion_key = ? LIMIT 1', [$key]);
        return $row === null ? null : $this->record($row);
    }

    public function findReviewsByIds(array $reviewIds): array
    {
        if ($reviewIds === []) {
            return [];
        }
        $rows = QueryUtils::fetchRecords(
            $this->reviewSelect() . ' WHERE r.review_id IN (' . implode(',', array_fill(0, count($reviewIds), '?')) . ')',
            $reviewIds
        );
        return array_values(array_map(fn(array $row): array => $this->review($row), $rows));
    }

    public function findCurrentReviewsForExtraction(string $extractionId): array
    {
        $rows = QueryUtils::fetchRecords(
            $this->reviewSelect() . ' LEFT JOIN copilot_fact_review newer ON newer.supersedes_review_id = r.review_id '
            . 'WHERE r.extraction_id = ? AND newer.review_id IS NULL',
            [$extractionId]
        );
        return array_values(array_map(fn(array $row): array => $this->review($row), $rows));
    }

    public function insertRecord(array $record): void
    {
        $this->validateRecord($record['target_type'], $record['record_json']);
        QueryUtils::sqlStatementThrowException(
            'INSERT INTO copilot_promoted_record (record_id, record_version, target_type, status, action_id, '
            . 'action_idempotency_key, deterministic_promotion_key, review_set_sha256, source_content_sha256, '
            . 'source_document_id, extraction_id, extraction_version, site_id, pid, record_json, created_at) '
            . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                $record['record_id'], $record['record_version'], $record['target_type'], $record['status'],
                $record['action_id'], $record['action_idempotency_key'], $record['deterministic_promotion_key'],
                $record['review_set_sha256'], $record['source_content_sha256'], $record['source_document_id'],
                $record['extraction_id'], $record['extraction_version'], $record['site_id'], $record['pid'],
                $this->encode($record['record_json']), $record['created_at'],
            ]
        );
    }

    public function findLatestRecord(string $recordId): ?array
    {
        $row = $this->one(
            'SELECT * FROM copilot_promoted_record WHERE record_id = ? ORDER BY record_version DESC LIMIT 1 FOR UPDATE',
            [$recordId]
        );
        return $row === null ? null : $this->record($row);
    }

    private function reviewSelect(): string
    {
        return 'SELECT r.*, u.site_id, u.pid FROM copilot_fact_review r '
            . 'JOIN copilot_document_extraction e ON e.extraction_id = r.extraction_id '
            . 'JOIN copilot_document_upload u ON u.source_document_id = e.source_document_id';
    }

    /** @param array<string, mixed> $row @return array<string, mixed> */
    private function review(array $row): array
    {
        $review = $this->json((string) $row['review_json']);
        $review['idempotency_outcome'] = 'created';
        $review['site_id'] = (string) $row['site_id'];
        $review['pid'] = (int) $row['pid'];
        return $review;
    }

    /** @param array<string, mixed> $row @return array<string, mixed> */
    private function record(array $row): array
    {
        $recordJson = $this->json((string) $row['record_json']);
        $this->validateRecord((string) $row['target_type'], $recordJson);
        return [
            'record_id' => (string) $row['record_id'],
            'record_version' => (int) $row['record_version'],
            'target_type' => (string) $row['target_type'],
            'status' => (string) $row['status'],
            'action_id' => (string) $row['action_id'],
            'action_idempotency_key' => (string) $row['action_idempotency_key'],
            'deterministic_promotion_key' => (string) $row['deterministic_promotion_key'],
            'review_set_sha256' => (string) $row['review_set_sha256'],
            'source_content_sha256' => (string) $row['source_content_sha256'],
            'source_document_id' => (string) $row['source_document_id'],
            'extraction_id' => (string) $row['extraction_id'],
            'extraction_version' => (int) $row['extraction_version'],
            'site_id' => (string) $row['site_id'],
            'pid' => (int) $row['pid'],
            'record_json' => $recordJson,
            'created_at' => (string) $row['created_at'],
        ];
    }

    /** @param array<string, mixed> $record */
    private function validateRecord(string $targetType, array $record): void
    {
        $name = $targetType === 'lab_report' ? 'reviewed_lab_report.schema.json' : 'reviewed_intake_response.schema.json';
        $path = rtrim($this->schemaDirectory, '/') . '/' . $name;
        $schema = is_file($path) ? json_decode((string) file_get_contents($path)) : null;
        if (!is_object($schema)) {
            throw new \RuntimeException('Reviewed-record schema unavailable');
        }
        $validator = new Validator();
        $result = $validator->validate(json_decode($this->encode($record)), $schema);
        if (!$result->isValid()) {
            throw new \RuntimeException('Reviewed-record schema validation failed');
        }
    }

    /** @return array<string, mixed>|null */
    private function one(string $sql, array $parameters): ?array
    {
        $rows = QueryUtils::fetchRecords($sql, $parameters);
        return $rows[0] ?? null;
    }

    /** @return array<string, mixed> */
    private function json(string $json): array
    {
        $value = json_decode($json, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($value)) {
            throw new \RuntimeException('Stored review JSON is invalid');
        }
        return $value;
    }

    private function encode(array $value): string
    {
        return json_encode($value, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION);
    }

    private function databaseTime(string $iso): string
    {
        return (new \DateTimeImmutable($iso))->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d H:i:s');
    }
}
