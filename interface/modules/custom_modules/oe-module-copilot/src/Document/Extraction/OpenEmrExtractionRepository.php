<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

use OpenEMR\Common\Database\QueryUtils;

final class OpenEmrExtractionRepository implements ExtractionJobRepositoryPort, ExtractionNoncePort
{
    public function transaction(callable $action): mixed
    {
        return QueryUtils::inTransaction($action);
    }

    public function consume(string $nonce, \DateTimeImmutable $expiresAt): bool
    {
        QueryUtils::sqlStatementThrowException('DELETE FROM copilot_worker_nonce WHERE expires_at < NOW()');
        QueryUtils::sqlStatementThrowException(
            'INSERT IGNORE INTO copilot_worker_nonce (nonce, expires_at) VALUES (?, ?)',
            [$nonce, $this->databaseTime($expiresAt)]
        );
        return QueryUtils::affectedRows() === 1;
    }

    public function claim(string $workerId, string $leaseTokenHash, \DateTimeImmutable $expiresAt): ?array
    {
        $now = new \DateTimeImmutable('now', new \DateTimeZone('UTC'));
        $exhausted = $this->one(
            $this->selectJob() . " WHERE j.status = 'leased' AND j.lease_expires_at < ? AND j.attempt >= 2 "
            . 'ORDER BY j.created_at, j.job_id LIMIT 1 FOR UPDATE',
            [$this->databaseTime($now)]
        );
        if ($exhausted !== null) {
            QueryUtils::sqlStatementThrowException(
                "UPDATE copilot_extraction_job SET status = 'failed', limitation_code = 'deadline_exceeded', "
                . 'retryable = 0, completed_at = ? WHERE job_id = ?',
                [$this->databaseTime($now), $exhausted['job_id']]
            );
            $this->appendOutbox($exhausted, 'extraction.failed', (string) $exhausted['job_id'], $now);
        }
        $row = $this->one(
            $this->selectJob() . " WHERE (j.status = 'queued' OR (j.status = 'leased' AND j.lease_expires_at < ?)) "
            . 'AND j.attempt < 2 ORDER BY j.created_at, j.job_id LIMIT 1 FOR UPDATE',
            [$this->databaseTime($now)]
        );
        if ($row === null) {
            return null;
        }
        QueryUtils::sqlStatementThrowException(
            "UPDATE copilot_extraction_job SET status = 'leased', attempt = attempt + 1, worker_id = ?, "
            . 'lease_token_hash = ?, lease_expires_at = ?, claimed_at = NOW() WHERE job_id = ?',
            [$workerId, $leaseTokenHash, $this->databaseTime($expiresAt), $row['job_id']]
        );
        return $this->find((string) $row['job_id']);
    }

    public function find(string $jobId): ?array
    {
        $row = $this->one($this->selectJob() . ' WHERE j.job_id = ? LIMIT 1', [$jobId]);
        return $row === null ? null : $this->job($row);
    }

    public function complete(
        string $jobId,
        string $leaseTokenHash,
        array $envelope,
        array $facts,
        string $envelopeSha256,
        \DateTimeImmutable $completedAt,
    ): array {
        return $this->transaction(function () use (
            $jobId, $leaseTokenHash, $envelope, $facts, $envelopeSha256, $completedAt
        ): array {
            $row = $this->one($this->selectJob() . ' WHERE j.job_id = ? LIMIT 1 FOR UPDATE', [$jobId]);
            if ($row === null || !is_string($row['lease_token_hash'])
                || !hash_equals((string) $row['lease_token_hash'], $leaseTokenHash)) {
                throw new ExtractionGatewayException('unauthorized', false, 'Worker request denied.', 401);
            }
            if ($row['status'] === 'completed') {
                if (!hash_equals((string) $row['completion_sha256'], $envelopeSha256)) {
                    throw new ExtractionGatewayException('conflict', false, 'The job already has a different terminal result.', 409);
                }
                return ['extraction_id' => (string) $row['extraction_id'], 'outcome' => 'replayed'];
            }
            $this->assertActiveLease($row, $completedAt);
            $json = $this->encode($envelope);
            QueryUtils::sqlStatementThrowException(
                'INSERT INTO copilot_document_extraction (extraction_id, source_document_id, extraction_version, '
                . 'schema_name, schema_version, state, extraction_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                [
                    $envelope['extraction_id'], $row['source_document_id'], $envelope['extraction_version'],
                    $envelope['schema_name'], $envelope['schema_version'], $envelope['state'], $json,
                    $this->databaseTime(new \DateTimeImmutable($envelope['created_at'])),
                ]
            );
            foreach ($facts as $fact) {
                QueryUtils::sqlStatementThrowException(
                    'INSERT INTO copilot_proposed_fact (extraction_id, field_id, typed_value_json, evidence_json, state) '
                    . 'VALUES (?, ?, ?, ?, ?)',
                    [
                        $envelope['extraction_id'], $fact['field_id'],
                        $fact['typed_value'] === null ? null : $this->encodeValue($fact['typed_value']),
                        $this->encode($fact['evidence']), $fact['state'],
                    ]
                );
            }
            QueryUtils::sqlStatementThrowException(
                "UPDATE copilot_extraction_job SET status = 'completed', completion_sha256 = ?, extraction_id = ?, "
                . 'completed_at = ? WHERE job_id = ?',
                [$envelopeSha256, $envelope['extraction_id'], $this->databaseTime($completedAt), $jobId]
            );
            $this->appendOutbox($row, 'extraction.completed', (string) $envelope['extraction_id'], $completedAt);
            return ['extraction_id' => (string) $envelope['extraction_id'], 'outcome' => 'created'];
        });
    }

    public function terminate(
        string $operation,
        string $jobId,
        string $leaseTokenHash,
        string $reasonCode,
        bool $retryable,
        string $requestSha256,
        \DateTimeImmutable $terminalAt,
    ): array {
        return $this->transaction(function () use (
            $operation, $jobId, $leaseTokenHash, $reasonCode, $retryable, $requestSha256, $terminalAt
        ): array {
            $row = $this->one($this->selectJob() . ' WHERE j.job_id = ? LIMIT 1 FOR UPDATE', [$jobId]);
            if ($row === null || !is_string($row['lease_token_hash'])
                || !hash_equals((string) $row['lease_token_hash'], $leaseTokenHash)) {
                throw new ExtractionGatewayException('unauthorized', false, 'Worker request denied.', 401);
            }
            $status = $operation === 'fail' ? 'failed' : 'canceled';
            if (in_array($row['status'], ['failed', 'canceled'], true)) {
                if ($row['status'] !== $status || !hash_equals((string) $row['terminal_sha256'], $requestSha256)) {
                    throw new ExtractionGatewayException('conflict', false, 'The job already has a different terminal result.', 409);
                }
                return ['job_id' => $jobId, 'status' => $status, 'outcome' => 'replayed'];
            }
            $this->assertActiveLease($row, $terminalAt);
            QueryUtils::sqlStatementThrowException(
                "UPDATE copilot_extraction_job SET status = ?, limitation_code = ?, retryable = ?, terminal_sha256 = ?, "
                . 'completed_at = ? WHERE job_id = ?',
                [$status, $reasonCode, $retryable ? 1 : 0, $requestSha256, $this->databaseTime($terminalAt), $jobId]
            );
            $this->appendOutbox($row, 'extraction.' . $status, $jobId, $terminalAt);
            return ['job_id' => $jobId, 'status' => $status, 'outcome' => 'created'];
        });
    }

    /** @param array<string, mixed> $row */
    private function assertActiveLease(array $row, \DateTimeImmutable $now): void
    {
        $expiry = is_string($row['lease_expires_at']) ? new \DateTimeImmutable($row['lease_expires_at'], new \DateTimeZone('UTC')) : null;
        if ($row['status'] !== 'leased' || $expiry === null || $expiry < $now) {
            throw new ExtractionGatewayException('stale_lease', true, 'The extraction lease expired.', 409);
        }
    }

    /** @param array<string, mixed> $row */
    private function appendOutbox(array $row, string $type, string $aggregateId, \DateTimeImmutable $at): void
    {
        QueryUtils::sqlStatementThrowException(
            'INSERT INTO copilot_action_outbox (event_id, event_type, aggregate_id, site_id, pid, user_id, '
            . 'correlation_id, payload_json, created_at) VALUES (UUID(), ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                $type, $aggregateId, $row['site_id'], $row['pid'], $row['created_by'], $row['correlation_id'],
                $this->encode(['job_id' => $row['job_id'], 'handoff_id' => $row['handoff_id']]),
                $this->databaseTime($at),
            ]
        );
    }

    private function selectJob(): string
    {
        return 'SELECT j.*, u.site_id, u.pid, u.user_id AS created_by, u.openemr_document_id, u.upload_intent_id, '
            . 'u.category, u.content_sha256, u.actual_byte_count, u.actual_mime_type, u.actual_page_count '
            . 'FROM copilot_extraction_job j JOIN copilot_document_upload u ON u.source_document_id = j.source_document_id';
    }

    /** @param array<string, mixed> $row @return array<string, mixed> */
    private function job(array $row): array
    {
        return [
            'job_id' => (string) $row['job_id'],
            'handoff_id' => (string) $row['handoff_id'],
            'correlation_id' => (string) $row['correlation_id'],
            'extraction_version' => (int) $row['extraction_version'],
            'attempt' => (int) $row['attempt'],
            'status' => (string) $row['status'],
            'worker_id' => $row['worker_id'] === null ? null : (string) $row['worker_id'],
            'lease_token_hash' => $row['lease_token_hash'] === null ? null : (string) $row['lease_token_hash'],
            'lease_expires_at' => $row['lease_expires_at'] === null ? null : new \DateTimeImmutable((string) $row['lease_expires_at'], new \DateTimeZone('UTC')),
            'completion_sha256' => $row['completion_sha256'] === null ? null : (string) $row['completion_sha256'],
            'terminal_sha256' => $row['terminal_sha256'] === null ? null : (string) $row['terminal_sha256'],
            'extraction_id' => $row['extraction_id'] === null ? null : (string) $row['extraction_id'],
            'source' => [
                'source_document_id' => (string) $row['source_document_id'],
                'openemr_document_id' => (string) $row['openemr_document_id'],
                'upload_intent_id' => (string) $row['upload_intent_id'],
                'document_type' => (string) $row['category'],
                'content_sha256' => (string) $row['content_sha256'],
                'byte_count' => (int) $row['actual_byte_count'],
                'mime_type' => (string) $row['actual_mime_type'],
                'page_count' => (int) $row['actual_page_count'],
            ],
            'site_id' => (string) $row['site_id'],
            'pid' => (int) $row['pid'],
            'created_by' => (int) $row['created_by'],
        ];
    }

    /** @return array<string, mixed>|null */
    private function one(string $sql, array $parameters): ?array
    {
        $rows = QueryUtils::fetchRecords($sql, $parameters);
        return $rows[0] ?? null;
    }

    private function encode(array $value): string
    {
        return json_encode($value, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION);
    }

    private function encodeValue(mixed $value): string
    {
        return json_encode($value, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION);
    }

    private function databaseTime(\DateTimeImmutable $time): string
    {
        return $time->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d H:i:s');
    }
}
