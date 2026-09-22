<?php

/** @package OpenEMR */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Documents;

use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Uuid\UuidRegistry;

/** Persistent intent-to-source mapping. No document content or extracted value is stored here. */
final class SourceDocumentRepository
{
    public const DOCUMENT_TYPES = ['lab_pdf', 'intake_form'];

    /** @return array{contract_version: string, intent_id: string, document_type: string, status: string} */
    public function createIntent(UploadContext $ctx, string $documentType): array
    {
        if (!self::supportsDocumentType($documentType)) {
            throw new SourceUploadException('invalid_file');
        }
        $intentId = bin2hex(random_bytes(16));
        QueryUtils::sqlInsert(
            'INSERT INTO copilot_source_upload_intent '
            . '(id, site_id, user_id, pid, document_type, state, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, NOW(), DATE_ADD(NOW(), INTERVAL 15 MINUTE))',
            [$intentId, $ctx->siteId, $ctx->userId, $ctx->pid, $documentType, 'pending']
        );
        return ['contract_version' => '2.0.0', 'intent_id' => $intentId, 'document_type' => $documentType, 'status' => 'pending'];
    }

    public static function supportsDocumentType(string $documentType): bool
    {
        return in_array($documentType, self::DOCUMENT_TYPES, true);
    }

    /** @return array<string, mixed>|null */
    public function findIntent(string $intentId): ?array
    {
        if (!preg_match('/^[a-f0-9]{32}$/', $intentId)) {
            return null;
        }
        $rows = QueryUtils::fetchRecords('SELECT * FROM copilot_source_upload_intent WHERE id = ?', [$intentId]);
        return $rows[0] ?? null;
    }

    /** @return array<string, mixed>|null */
    public function findSource(string $sourceId): ?array
    {
        if (!preg_match('/^document:[a-f0-9]{32}$/', $sourceId)) {
            return null;
        }
        $rows = QueryUtils::fetchRecords('SELECT * FROM copilot_source_document WHERE source_id = ?', [$sourceId]);
        return $rows[0] ?? null;
    }

    /** @return array<string, mixed>|null */
    public function sourceForIntent(string $intentId): ?array
    {
        $rows = QueryUtils::fetchRecords('SELECT s.* FROM copilot_source_document s JOIN copilot_source_upload_intent i ON i.source_id = s.source_id WHERE i.id = ?', [$intentId]);
        return $rows[0] ?? null;
    }

    /** @throws SourceUploadException */
    public function assertIntentUsable(UploadContext $ctx, string $intentId): void
    {
        $intent = $this->findIntent($intentId);
        if ($intent === null) {
            throw new SourceUploadException('duplicate_or_replay');
        }
        if (
            $intent['site_id'] !== $ctx->siteId || (int) $intent['user_id'] !== $ctx->userId
            || (int) $intent['pid'] !== $ctx->pid || !self::supportsDocumentType((string) $intent['document_type'])
        ) {
            throw new SourceUploadException('duplicate_or_replay');
        }
        if (strtotime((string) $intent['expires_at']) < time() && $intent['state'] !== 'stored') {
            throw new SourceUploadException('duplicate_or_replay');
        }
        if ($intent['state'] === 'processing') {
            throw new SourceUploadException('duplicate_or_replay');
        }
    }

    /** Claim a pending intent atomically, so two same-intent POSTs cannot both create documents. */
    private function claimIntent(UploadContext $ctx, string $intentId, string $expectedDocumentType): string
    {
        QueryUtils::sqlStatementThrowException('START TRANSACTION');
        try {
            if (!preg_match('/^[a-f0-9]{32}$/', $intentId)) {
                throw new SourceUploadException('duplicate_or_replay');
            }
            $rows = QueryUtils::fetchRecords('SELECT * FROM copilot_source_upload_intent WHERE id = ? FOR UPDATE', [$intentId]);
            $intent = $rows[0] ?? null;
            if (
                $intent === null || $intent['site_id'] !== $ctx->siteId || (int) $intent['user_id'] !== $ctx->userId
                || (int) $intent['pid'] !== $ctx->pid || !self::supportsDocumentType((string) $intent['document_type'])
                || $intent['document_type'] !== $expectedDocumentType
                || $intent['state'] !== 'pending' || strtotime((string) $intent['expires_at']) < time()
            ) {
                throw new SourceUploadException('duplicate_or_replay');
            }
            QueryUtils::sqlStatementThrowException('UPDATE copilot_source_upload_intent SET state = ? WHERE id = ?', ['processing', $intentId]);
            QueryUtils::sqlStatementThrowException('COMMIT');
            return (string) $intent['document_type'];
        } catch (\Throwable $e) {
            QueryUtils::sqlStatementThrowException('ROLLBACK');
            if ($e instanceof SourceUploadException) {
                throw $e;
            }
            throw new SourceUploadException('storage_unavailable');
        }
    }

    /** @param array{document_type: string, mime_type: string, byte_size: int, page_count: int, content_hash: string} $file */
    public function store(UploadContext $ctx, string $intentId, array $file, string $bytes): array
    {
        $existing = $this->sourceForIntent($intentId);
        if ($existing !== null) {
            return $existing;
        }
        $documentType = $this->claimIntent($ctx, $intentId, (string) ($file['document_type'] ?? ''));

        try {
            $category = QueryUtils::fetchRecords('SELECT id FROM categories WHERE name = ? AND aco_spec = ? LIMIT 1', ['AgentForge Lab Uploads', 'patients|docs']);
            if (count($category) !== 1) {
                throw new SourceUploadException('storage_unavailable');
            }
            $document = new \Document();
            // Filename is module-owned and carries no original filename or patient identifier.
            $filename = $documentType === 'intake_form' ? 'agentforge-intake.pdf' : 'agentforge-lab.pdf';
            $error = $document->createDocument($ctx->pid, (int) $category[0]['id'], $filename, $file['mime_type'], $bytes);
            if ($error !== '') {
                throw new SourceUploadException('storage_unavailable');
            }
            $documentId = (int) $document->get_id();
            $uuid = UuidRegistry::uuidToString($document->get_uuid());
            if ($documentId <= 0 || !preg_match('/^[a-f0-9-]{36}$/', $uuid)) {
                throw new SourceUploadException('storage_unavailable');
            }
            $sourceId = 'document:' . bin2hex(random_bytes(16));
            QueryUtils::sqlInsert(
                'INSERT INTO copilot_source_document '
                . '(source_id, site_id, pid, native_document_id, native_document_uuid, content_hash, document_type, mime_type, byte_size, page_count, version, created_at) '
                . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NOW())',
                [$sourceId, $ctx->siteId, $ctx->pid, $documentId, $uuid, $file['content_hash'], $documentType, $file['mime_type'], $file['byte_size'], $file['page_count']]
            );
            QueryUtils::sqlStatementThrowException('UPDATE copilot_source_upload_intent SET state = ?, source_id = ?, completed_at = NOW() WHERE id = ?', ['stored', $sourceId, $intentId]);
            return $this->findSource($sourceId) ?? throw new SourceUploadException('storage_unavailable');
        } catch (SourceUploadException $e) {
            // Once claimed, a storage error remains terminal for this intent. Retrying a
            // possibly-successful native document write would otherwise create a duplicate.
            QueryUtils::sqlStatementThrowException('UPDATE copilot_source_upload_intent SET state = ? WHERE id = ? AND state = ?', ['failed', $intentId, 'processing']);
            throw $e;
        } catch (\Throwable $e) {
            QueryUtils::sqlStatementThrowException('UPDATE copilot_source_upload_intent SET state = ? WHERE id = ? AND state = ?', ['failed', $intentId, 'processing']);
            throw new SourceUploadException('storage_unavailable');
        }
    }

    /** @return array<string, mixed> */
    public static function publicSource(array $source): array
    {
        return [
            'source_id' => $source['source_id'],
            'native_document_uuid' => $source['native_document_uuid'],
            'content_hash' => $source['content_hash'],
            'version' => 1,
            'document_type' => $source['document_type'],
            'mime_type' => $source['mime_type'],
            'byte_size' => (int) $source['byte_size'],
            'page_count' => (int) $source['page_count'],
        ];
    }
}
