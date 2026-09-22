<?php

/**
 * Authenticated, immutable source-document lifecycle for Week 2 C1/C2.
 * The browser never supplies a site or patient identifier. Every operation
 * obtains a fresh server-side context before an upload is read or a stored
 * document is opened.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

final class DocumentLifecycle
{
    public const OP_UPLOAD = 'upload';
    public const OP_SOURCE_READ = 'source_read';
    public const INTENT_TTL_SECONDS = 900;
    private const TOKEN_VERSION = 1;

    public function __construct(
        private readonly AuthorizationPort $authorization,
        private readonly UploadRepositoryPort $repository,
        private readonly DocumentStorePort $documents,
        private readonly MalwareScannerPort $scanner,
        private readonly AuditPort $audit,
        private readonly ClockPort $clock,
        private readonly string $tokenSecret,
    ) {
        if (strlen($tokenSecret) < 32) {
            throw new \InvalidArgumentException('Upload token secret must be at least 32 bytes.');
        }
    }

    /**
     * @param array<string, mixed> $command
     * @return array{upload_intent_id: string, upload_token: string, expires_at: string, outcome: string}
     */
    public function createUploadIntent(array $command, string $correlationId): array
    {
        $context = $this->authorization->authorize(self::OP_UPLOAD, $correlationId);
        try {
            $this->validateIntentCommand($command);
        } catch (DocumentLifecycleException $exception) {
            $this->auditOrFail($context, 'upload_intent', false, $exception->errorCode, [
                'correlation_id' => $correlationId,
            ]);
            throw $exception;
        }

        $now = $this->clock->now();
        $candidate = [
            'upload_intent_id' => self::uuid(),
            'site_id' => $context->siteId,
            'pid' => $context->pid,
            'user_id' => $context->userId,
            'category' => $command['category'],
            'idempotency_key' => $command['idempotency_key'],
            'original_filename' => $command['original_filename'],
            'declared_mime_type' => $command['mime_type'],
            'declared_byte_count' => $command['byte_count'],
            'declared_page_count' => $command['page_count'],
            'expires_at' => $now->modify('+' . self::INTENT_TTL_SECONDS . ' seconds')->format('Y-m-d\TH:i:s\Z'),
            'created_at' => $now->format('Y-m-d H:i:s'),
            'source_document_id' => null,
        ];
        $candidate['token_hash'] = hash('sha256', $this->tokenFor($candidate));

        [$intent, $outcome] = $this->repository->transaction(function () use ($candidate, $context, $command, $correlationId): array {
            $existing = $this->repository->findIntentByKey(
                $context->siteId,
                $context->pid,
                $command['category'],
                $command['idempotency_key']
            );
            if ($existing !== null) {
                return [$existing, 'replayed'];
            }
            $this->repository->insertIntent($candidate);
            // The production insert uses the unique key as the race arbiter.
            // Re-read so a concurrent winner is replayed instead of duplicated.
            $resolved = $this->repository->findIntentByKey(
                $context->siteId,
                $context->pid,
                $command['category'],
                $command['idempotency_key']
            ) ?? $candidate;
            if ($resolved['upload_intent_id'] !== $candidate['upload_intent_id']) {
                return [$resolved, 'replayed'];
            }
            $this->repository->appendOutbox($this->outbox(
                $context,
                'upload_intent.created',
                (string) $candidate['upload_intent_id'],
                $correlationId
            ));
            return [$candidate, 'created'];
        });

        $this->auditOrFail($context, 'upload_intent', true, $outcome, [
            'upload_intent_id' => $intent['upload_intent_id'],
            'category' => $intent['category'],
            'correlation_id' => $correlationId,
        ]);

        return $this->intentResponse($intent, $outcome);
    }

    /**
     * @return array{source: array<string, mixed>, outcome: string, warnings: list<array<string, mixed>>}
     */
    public function uploadContent(
        string $intentId,
        string $uploadToken,
        UploadFilePort $file,
        string $correlationId,
    ): array {
        // Authorization is deliberately first: no file bytes, MIME, malware
        // scan, or OpenEMR document access occurs before this fresh check.
        $context = $this->authorization->authorize(self::OP_UPLOAD, $correlationId);
        $intent = $this->repository->findIntent($intentId);
        try {
            $this->assertIntentAccess($intent, $context, $uploadToken);
        } catch (DocumentLifecycleException $exception) {
            $this->denied($context, 'upload_content', $exception->errorCode, $intentId, $correlationId);
            throw $exception;
        }

        $maximum = $intent['category'] === 'lab_report' ? 20_971_520 : 10_485_760;
        try {
            if (!$this->scanner->isClean($file)) {
                throw new DocumentLifecycleException('invalid_contract', false, 'The uploaded file was rejected.', 422);
            }
            $bytes = $file->read($maximum + 1);
            $actual = $this->inspect($bytes, (string) $intent['category']);
            $this->assertUploadMatchesIntent($intent, $file, $actual);
        } catch (DocumentLifecycleException $exception) {
            $this->denied($context, 'upload_content', $exception->errorCode, $intentId, $correlationId);
            throw $exception;
        } catch (\Throwable $exception) {
            $this->denied($context, 'upload_content', 'unavailable', $intentId, $correlationId);
            throw new DocumentLifecycleException('unavailable', true, 'The uploaded file could not be inspected.', 503);
        }

        if (is_string($intent['source_document_id'] ?? null) && $intent['source_document_id'] !== '') {
            $source = $this->repository->findSource($intent['source_document_id']);
            if ($source === null || !hash_equals((string) $source['content_sha256'], $actual['content_sha256'])) {
                $this->denied($context, 'upload_content', 'source_mismatch', $intentId, $correlationId);
                throw new DocumentLifecycleException('source_mismatch', false, 'The immutable source no longer matches.', 409);
            }
            $this->auditOrFail($context, 'upload_content', true, 'replayed', [
                'upload_intent_id' => $intentId,
                'source_document_id' => $source['source_document_id'],
                'correlation_id' => $correlationId,
            ]);
            return ['source' => $this->publicSource($source), 'outcome' => 'replayed', 'warnings' => []];
        }

        $duplicates = $this->repository->findDuplicateSourceIds(
            $context->siteId,
            $context->pid,
            $actual['content_sha256'],
            $intentId
        );
        $this->auditOrFail($context, 'upload_content', true, 'authorized', [
            'upload_intent_id' => $intentId,
            'category' => $intent['category'],
            'duplicate_count' => count($duplicates),
            'correlation_id' => $correlationId,
        ]);

        $safeFilename = $intent['category'] . '-' . $intentId . $actual['extension'];
        $openEmrDocumentId = $this->documents->store(
            $context,
            (string) $intent['category'],
            $safeFilename,
            $actual['mime_type'],
            $bytes
        );
        $source = [
            'source_document_id' => self::uuid(),
            'openemr_document_id' => $openEmrDocumentId,
            'upload_intent_id' => $intentId,
            'document_type' => $intent['category'],
            'content_sha256' => $actual['content_sha256'],
            'byte_count' => $actual['byte_count'],
            'mime_type' => $actual['mime_type'],
            'page_count' => $actual['page_count'],
            'site_id' => $context->siteId,
            'pid' => $context->pid,
            'created_by' => $context->userId,
        ];

        try {
            $this->repository->transaction(function () use ($intentId, $source, $context, $correlationId): void {
                if (!$this->repository->completeIntent($intentId, $source)) {
                    throw new DocumentLifecycleException('conflict', true, 'The upload intent completed concurrently.', 409);
                }
                $this->repository->appendOutbox($this->outbox(
                    $context,
                    'upload_content.created',
                    (string) $source['source_document_id'],
                    $correlationId
                ));
            });
        } catch (DocumentLifecycleException $exception) {
            $this->documents->remove($context, $openEmrDocumentId);
            if ($exception->errorCode === 'conflict') {
                $currentIntent = $this->repository->findIntent($intentId);
                $currentSource = is_string($currentIntent['source_document_id'] ?? null)
                    ? $this->repository->findSource($currentIntent['source_document_id'])
                    : null;
                if ($currentSource !== null
                    && hash_equals((string) $currentSource['content_sha256'], $actual['content_sha256'])) {
                    return ['source' => $this->publicSource($currentSource), 'outcome' => 'replayed', 'warnings' => []];
                }
            }
            throw $exception;
        } catch (\Throwable $exception) {
            // Compensate the OpenEMR-owned blob if the immutable mapping could
            // not commit. Never include storage errors or bytes in the response.
            $this->documents->remove($context, $openEmrDocumentId);
            throw new DocumentLifecycleException('unavailable', true, 'The source could not be recorded.', 503);
        }

        $warnings = [];
        if ($duplicates !== []) {
            $warnings[] = [
                'code' => 'duplicate_content',
                'matching_source_document_ids' => array_slice(array_values(array_unique($duplicates)), 0, 10),
                'message' => 'This file matches an existing source for the open patient.',
            ];
        }
        return ['source' => $this->publicSource($source), 'outcome' => 'created', 'warnings' => $warnings];
    }

    /**
     * Internal source read for extraction/review workers. HTTP handlers must
     * not serialize `bytes`; callers receive them only after the live chart
     * binding is reauthorized, the access audit succeeds, and the stored hash
     * is verified against the immutable source mapping.
     *
     * @return array{source: array<string, mixed>, bytes: string}
     */
    public function readSource(string $sourceDocumentId, string $correlationId): array
    {
        $context = $this->authorization->authorize(self::OP_SOURCE_READ, $correlationId);
        $source = self::isUuid($sourceDocumentId) ? $this->repository->findSource($sourceDocumentId) : null;
        if ($source === null) {
            $this->auditOrFail($context, 'source_read', false, 'not_found', [
                'source_document_id' => $sourceDocumentId,
                'correlation_id' => $correlationId,
            ]);
            throw new DocumentLifecycleException('not_found', false, 'The source document was not found.', 404);
        }
        if ($source['site_id'] !== $context->siteId || (int) $source['pid'] !== $context->pid) {
            $this->auditOrFail($context, 'source_read', false, 'patient_context_changed', [
                'source_document_id' => $sourceDocumentId,
                'correlation_id' => $correlationId,
            ]);
            throw new DocumentLifecycleException('patient_context_changed', false, 'The open patient changed.', 409);
        }

        try {
            // This must remain before Document::get_data(): the upstream read
            // decrypts bytes, and audit failure is a hard stop.
            $this->audit->record($context, 'source_read', true, 'authorized', [
                'source_document_id' => $sourceDocumentId,
                'correlation_id' => $correlationId,
            ]);
        } catch (\Throwable $exception) {
            throw new DocumentLifecycleException('unavailable', true, 'Source access could not be audited.', 503);
        }

        try {
            $bytes = $this->documents->read($context, (string) $source['openemr_document_id']);
        } catch (\Throwable $exception) {
            throw new DocumentLifecycleException('unavailable', true, 'The source document is unavailable.', 503);
        }
        if (!hash_equals((string) $source['content_sha256'], hash('sha256', $bytes))) {
            throw new DocumentLifecycleException('source_mismatch', false, 'The immutable source no longer matches.', 409);
        }
        return ['source' => $this->publicSource($source), 'bytes' => $bytes];
    }

    /** @param array<string, mixed> $command */
    private function validateIntentCommand(array $command): void
    {
        $required = ['idempotency_key', 'category', 'original_filename', 'mime_type', 'byte_count', 'page_count'];
        $actualKeys = array_keys($command);
        sort($actualKeys);
        $expectedKeys = $required;
        sort($expectedKeys);
        if ($actualKeys !== $expectedKeys
            || !self::isUuid($command['idempotency_key'] ?? null)
            || !in_array($command['category'] ?? null, ['lab_report', 'intake_form'], true)
            || !is_string($command['original_filename'] ?? null)
            || strlen($command['original_filename']) < 1
            || strlen($command['original_filename']) > 255
            || basename(str_replace('\\', '/', $command['original_filename'])) !== $command['original_filename']
            || in_array($command['original_filename'], ['.', '..'], true)
            || str_contains($command['original_filename'], "\0")
            || preg_match('/[\x00-\x1f\x7f]/', $command['original_filename']) === 1
            || !is_string($command['mime_type'] ?? null)
            || !is_int($command['byte_count'] ?? null)
            || !is_int($command['page_count'] ?? null)) {
            throw new DocumentLifecycleException('invalid_contract', false, 'The upload request is invalid.', 422);
        }
        $this->assertLimits(
            $command['category'],
            $command['mime_type'],
            $command['byte_count'],
            $command['page_count']
        );
    }

    /** @return array{mime_type: string, byte_count: int, page_count: int, content_sha256: string, extension: string} */
    private function inspect(string $bytes, string $category): array
    {
        $byteCount = strlen($bytes);
        $mime = '';
        $pages = 0;
        $extension = '';
        if (str_starts_with($bytes, '%PDF-') && preg_match('/%%EOF\s*\z/s', $bytes) === 1) {
            $blocked = preg_match('/\/(?:JavaScript|JS|Launch|EmbeddedFile|RichMedia|OpenAction|AA)\b/', $bytes) === 1;
            $pages = preg_match_all('/\/Type\s*\/Page\b/', $bytes);
            if (!$blocked && str_contains($bytes, '/Type /Catalog') && str_contains($bytes, '/Type /Pages')) {
                $mime = 'application/pdf';
                $extension = '.pdf';
            }
        } elseif (str_starts_with($bytes, "\x89PNG\r\n\x1a\n") && str_ends_with($bytes, "IEND\xaeB`\x82")) {
            $image = @getimagesizefromstring($bytes);
            if (is_array($image) && ($image['mime'] ?? null) === 'image/png' && $this->safeImageDimensions($image)) {
                $mime = 'image/png';
                $pages = 1;
                $extension = '.png';
            }
        } elseif (str_starts_with($bytes, "\xff\xd8\xff") && str_ends_with($bytes, "\xff\xd9")) {
            $image = @getimagesizefromstring($bytes);
            if (is_array($image) && ($image['mime'] ?? null) === 'image/jpeg' && $this->safeImageDimensions($image)) {
                $mime = 'image/jpeg';
                $pages = 1;
                $extension = '.jpg';
            }
        }
        if ($mime === '' || $pages < 1) {
            throw new DocumentLifecycleException('invalid_contract', false, 'The uploaded file type is not supported.', 422);
        }
        $this->assertLimits($category, $mime, $byteCount, $pages);
        return [
            'mime_type' => $mime,
            'byte_count' => $byteCount,
            'page_count' => $pages,
            'content_sha256' => hash('sha256', $bytes),
            'extension' => $extension,
        ];
    }

    private function assertLimits(string $category, string $mime, int $bytes, int $pages): void
    {
        $valid = $category === 'lab_report'
            ? $mime === 'application/pdf' && $bytes > 0 && $bytes <= 20_971_520 && $pages >= 1 && $pages <= 20
            : in_array($mime, ['application/pdf', 'image/png', 'image/jpeg'], true)
                && $bytes > 0 && $bytes <= 10_485_760 && $pages >= 1 && $pages <= 10
                && ($mime === 'application/pdf' || $pages === 1);
        if (!$valid) {
            throw new DocumentLifecycleException('invalid_contract', false, 'The upload exceeds the permitted type or size limits.', 422);
        }
    }

    /** @param array<int|string, mixed> $image */
    private function safeImageDimensions(array $image): bool
    {
        $width = (int) ($image[0] ?? 0);
        $height = (int) ($image[1] ?? 0);
        return $width > 0 && $height > 0 && $width <= 20_000 && $height <= 20_000
            && ($width * $height) <= 100_000_000;
    }

    /** @param array<string, mixed>|null $intent */
    private function assertIntentAccess(?array $intent, DocumentContext $context, string $token): void
    {
        if ($intent === null) {
            throw new DocumentLifecycleException('not_found', false, 'The upload intent was not found.', 404);
        }
        if ($intent['site_id'] !== $context->siteId || (int) $intent['pid'] !== $context->pid) {
            throw new DocumentLifecycleException('patient_context_changed', false, 'The open patient changed.', 409);
        }
        if ((int) $intent['user_id'] !== $context->userId
            || !hash_equals((string) $intent['token_hash'], hash('sha256', $token))
            || !hash_equals($this->tokenFor($intent), $token)) {
            throw new DocumentLifecycleException('forbidden', false, 'The upload intent is not authorized.', 403);
        }
        if ($this->clock->now() > new \DateTimeImmutable((string) $intent['expires_at'])) {
            throw new DocumentLifecycleException('forbidden', false, 'The upload intent expired.', 403);
        }
    }

    /** @param array<string, mixed> $intent @param array<string, mixed> $actual */
    private function assertUploadMatchesIntent(array $intent, UploadFilePort $file, array $actual): void
    {
        if ($file->clientFilename() !== $intent['original_filename']
            || $actual['mime_type'] !== $intent['declared_mime_type']
            || $actual['byte_count'] !== (int) $intent['declared_byte_count']
            || $actual['page_count'] !== (int) $intent['declared_page_count']) {
            throw new DocumentLifecycleException('invalid_contract', false, 'The uploaded file does not match its intent.', 422);
        }
    }

    /** @param array<string, mixed> $intent @return array<string, string> */
    private function intentResponse(array $intent, string $outcome): array
    {
        return [
            'upload_intent_id' => (string) $intent['upload_intent_id'],
            'upload_token' => $this->tokenFor($intent),
            'expires_at' => (string) $intent['expires_at'],
            'outcome' => $outcome,
        ];
    }

    /** @param array<string, mixed> $intent */
    private function tokenFor(array $intent): string
    {
        $payload = json_encode([
            'v' => self::TOKEN_VERSION,
            'intent' => $intent['upload_intent_id'],
            'site' => $intent['site_id'],
            'pid' => $intent['pid'],
            'user' => $intent['user_id'],
            'exp' => $intent['expires_at'],
        ], JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
        // Return only the authenticator. The signed material remains server
        // side so the opaque browser token cannot reveal site, user, or pid.
        return self::base64Url(hash_hmac('sha256', $payload, $this->tokenSecret, true));
    }

    /** @param array<string, mixed> $source @return array<string, mixed> */
    private function publicSource(array $source): array
    {
        return array_intersect_key($source, array_flip([
            'source_document_id',
            'openemr_document_id',
            'upload_intent_id',
            'document_type',
            'content_sha256',
            'byte_count',
            'mime_type',
            'page_count',
        ]));
    }

    /** @return array<string, mixed> */
    private function outbox(DocumentContext $context, string $event, string $aggregateId, string $correlationId): array
    {
        return [
            'event_id' => self::uuid(),
            'event_type' => $event,
            'aggregate_id' => $aggregateId,
            'site_id' => $context->siteId,
            'pid' => $context->pid,
            'user_id' => $context->userId,
            'correlation_id' => $correlationId,
            'created_at' => $this->clock->now()->format('Y-m-d H:i:s'),
        ];
    }

    private function denied(
        DocumentContext $context,
        string $operation,
        string $reason,
        string $intentId,
        string $correlationId,
    ): void {
        $this->auditOrFail($context, $operation, false, $reason, [
            'upload_intent_id' => $intentId,
            'correlation_id' => $correlationId,
        ]);
    }

    /** @param array<string, scalar|null> $identifiers */
    private function auditOrFail(
        DocumentContext $context,
        string $operation,
        bool $success,
        string $reason,
        array $identifiers,
    ): void {
        try {
            $this->audit->record($context, $operation, $success, $reason, $identifiers);
        } catch (\Throwable $exception) {
            throw new DocumentLifecycleException('unavailable', true, 'The action could not be audited.', 503);
        }
    }

    private static function isUuid(mixed $value): bool
    {
        return is_string($value)
            && preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $value) === 1;
    }

    private static function uuid(): string
    {
        $bytes = random_bytes(16);
        $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
        $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
        $hex = bin2hex($bytes);
        return substr($hex, 0, 8) . '-' . substr($hex, 8, 4) . '-' . substr($hex, 12, 4)
            . '-' . substr($hex, 16, 4) . '-' . substr($hex, 20);
    }

    private static function base64Url(string $value): string
    {
        return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
    }
}
