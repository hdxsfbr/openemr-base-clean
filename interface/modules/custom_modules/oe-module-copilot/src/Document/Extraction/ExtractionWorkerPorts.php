<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

interface ExtractionNoncePort
{
    public function consume(string $nonce, \DateTimeImmutable $expiresAt): bool;
}

interface ExtractionClockPort
{
    public function now(): \DateTimeImmutable;
}

interface ExtractionJobRepositoryPort
{
    public function transaction(callable $action): mixed;

    /** @return array<string, mixed>|null */
    public function claim(string $workerId, string $leaseTokenHash, \DateTimeImmutable $expiresAt): ?array;

    /** @return array<string, mixed>|null */
    public function find(string $jobId): ?array;

    /**
     * @param array<string, mixed> $envelope
     * @param list<array<string, mixed>> $facts
     * @return array{extraction_id: string, outcome: string}
     */
    public function complete(
        string $jobId,
        string $leaseTokenHash,
        array $envelope,
        array $facts,
        string $envelopeSha256,
        \DateTimeImmutable $completedAt,
    ): array;

    /** @return array{job_id: string, status: string, outcome: string} */
    public function terminate(
        string $operation,
        string $jobId,
        string $leaseTokenHash,
        string $reasonCode,
        bool $retryable,
        string $requestSha256,
        \DateTimeImmutable $terminalAt,
    ): array;
}

interface ExtractionSourcePort
{
    /** @param array<string, mixed> $job */
    public function read(array $job): string;
}

interface ExtractionAuditPort
{
    /** @param array<string, scalar|null> $identifiers */
    public function record(string $operation, string $outcome, array $identifiers): void;
}

interface ExtractionEnvelopeValidatorPort
{
    /** @param array<string, mixed> $envelope @return list<array<string, mixed>> */
    public function validateAndFlatten(array $envelope): array;
}
