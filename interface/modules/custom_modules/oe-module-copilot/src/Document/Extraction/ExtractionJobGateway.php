<?php

/**
 * Narrow application boundary used by the internal intake-extractor worker.
 * It leases a browser-authorized source and verifies OpenEMR bytes before they
 * cross the internal endpoint. It never accepts a patient or document choice.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

final class ExtractionJobGateway
{
    public const LEASE_SECONDS = 95;

    public function __construct(
        private readonly ExtractionJobRepositoryPort $jobs,
        private readonly ExtractionSourcePort $sources,
        private readonly ExtractionAuditPort $audit,
        private readonly ExtractionClockPort $clock,
        private readonly ExtractionEnvelopeValidatorPort $validator,
    ) {
    }

    /** @param array<string, mixed> $command @return array{extraction_id: string, outcome: string} */
    public function complete(array $command): array
    {
        if (!$this->hasExactKeys($command, ['job_id', 'lease_token', 'envelope'])
            || !self::isUuid($command['job_id'] ?? null)
            || !is_string($command['lease_token'] ?? null)
            || preg_match('/^[A-Za-z0-9_-]{43}$/', $command['lease_token']) !== 1
            || !is_array($command['envelope'] ?? null)) {
            throw new ExtractionGatewayException('invalid_contract', false, 'The completion request is invalid.', 422);
        }
        $job = $this->jobs->find($command['job_id']);
        if ($job === null || !is_string($job['lease_token_hash'] ?? null)
            || !hash_equals($job['lease_token_hash'], hash('sha256', $command['lease_token']))) {
            throw new ExtractionGatewayException('unauthorized', false, 'Worker request denied.', 401);
        }
        $envelope = $command['envelope'];
        if (($envelope['extraction_version'] ?? null) !== $job['extraction_version']
            || !$this->sameSource($job['source'], $envelope['source'] ?? null)) {
            throw new ExtractionGatewayException('source_mismatch', false, 'The extraction source does not match its job.', 409);
        }
        if (($job['status'] ?? null) === 'leased'
            && $job['lease_expires_at'] instanceof \DateTimeImmutable
            && $job['lease_expires_at'] < $this->clock->now()) {
            throw new ExtractionGatewayException('stale_lease', true, 'The extraction lease expired.', 409);
        }
        $facts = $this->validator->validateAndFlatten($envelope);
        $canonical = $this->canonicalJson($envelope);
        $result = $this->jobs->complete(
            $command['job_id'],
            hash('sha256', $command['lease_token']),
            $envelope,
            $facts,
            hash('sha256', $canonical),
            $this->clock->now()
        );
        $this->audit->record('complete', $result['outcome'], $this->identifiers($job) + [
            'extraction_id' => (string) $result['extraction_id'],
        ]);
        return $result;
    }

    /** @param array<string, mixed> $command @return array{job_id: string, status: string, outcome: string} */
    public function fail(array $command): array
    {
        if (!$this->hasExactKeys($command, ['job_id', 'lease_token', 'limitation_code', 'retryable'])
            || !in_array($command['limitation_code'] ?? null, [
                'deadline_exceeded', 'render_failed', 'ocr_failed', 'provider_unavailable',
                'schema_failed', 'source_unavailable', 'internal_error',
            ], true)
            || !is_bool($command['retryable'] ?? null)) {
            throw new ExtractionGatewayException('invalid_contract', false, 'The failure request is invalid.', 422);
        }
        return $this->terminate('fail', $command, $command['limitation_code'], $command['retryable']);
    }

    /** @param array<string, mixed> $command @return array{job_id: string, status: string, outcome: string} */
    public function cancel(array $command): array
    {
        if (!$this->hasExactKeys($command, ['job_id', 'lease_token', 'reason_code'])
            || !in_array($command['reason_code'] ?? null, ['worker_canceled', 'deadline_exceeded', 'shutdown'], true)) {
            throw new ExtractionGatewayException('invalid_contract', false, 'The cancellation request is invalid.', 422);
        }
        return $this->terminate('cancel', $command, $command['reason_code'], false);
    }

    /** @param array<string, mixed> $command @return array<string, mixed>|null */
    public function claim(array $command): ?array
    {
        if (array_keys($command) !== ['worker_id']
            || !is_string($command['worker_id'])
            || preg_match('/^[A-Za-z0-9._-]{8,64}$/', $command['worker_id']) !== 1) {
            throw new ExtractionGatewayException('invalid_contract', false, 'The claim request is invalid.', 422);
        }
        $leaseToken = self::token();
        $now = $this->clock->now();
        $job = $this->jobs->transaction(fn(): ?array => $this->jobs->claim(
            $command['worker_id'],
            hash('sha256', $leaseToken),
            $now->modify('+' . self::LEASE_SECONDS . ' seconds')
        ));
        if ($job === null) {
            return null;
        }

        $identifiers = $this->identifiers($job);
        try {
            // Audit must commit before Document::get_data() decrypts the source.
            $this->audit->record('claim', 'lease_acquired', $identifiers);
        } catch (\Throwable $exception) {
            throw new ExtractionGatewayException('unavailable', true, 'Source access could not be audited.', 503);
        }
        try {
            $bytes = $this->sources->read($job);
        } catch (\Throwable $exception) {
            throw new ExtractionGatewayException('unavailable', true, 'The source document is unavailable.', 503);
        }
        if (!hash_equals((string) $job['source']['content_sha256'], hash('sha256', $bytes))
            || strlen($bytes) !== (int) $job['source']['byte_count']) {
            $this->audit->record('claim', 'source_mismatch', $identifiers);
            throw new ExtractionGatewayException('source_mismatch', false, 'The immutable source no longer matches.', 409);
        }

        return [
            'job_id' => $job['job_id'],
            'handoff_id' => $job['handoff_id'],
            'correlation_id' => $job['correlation_id'],
            'attempt' => $job['attempt'],
            'extraction_version' => $job['extraction_version'],
            'lease_token' => $leaseToken,
            'lease_expires_at' => $now->modify('+' . self::LEASE_SECONDS . ' seconds')->format('Y-m-d\TH:i:s\Z'),
            'source' => $job['source'],
            'content_base64' => base64_encode($bytes),
        ];
    }

    /** @param array<string, mixed> $job @return array<string, scalar|null> */
    private function identifiers(array $job): array
    {
        return [
            'job_id' => (string) $job['job_id'],
            'handoff_id' => (string) $job['handoff_id'],
            'correlation_id' => (string) $job['correlation_id'],
            'source_document_id' => (string) $job['source']['source_document_id'],
            'attempt' => (int) $job['attempt'],
            'pid' => (int) $job['pid'],
        ];
    }

    private static function token(): string
    {
        return rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');
    }

    /** @param array<string, mixed> $actual @param list<string> $expected */
    private function hasExactKeys(array $actual, array $expected): bool
    {
        $keys = array_keys($actual);
        sort($keys);
        sort($expected);
        return $keys === $expected;
    }

    private static function isUuid(mixed $value): bool
    {
        return is_string($value)
            && preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $value) === 1;
    }

    private function sameSource(array $expected, mixed $actual): bool
    {
        return is_array($actual) && hash_equals($this->canonicalJson($expected), $this->canonicalJson($actual));
    }

    private function canonicalJson(mixed $value): string
    {
        $normalize = function (mixed $item) use (&$normalize): mixed {
            if (!is_array($item)) {
                return $item;
            }
            if (!array_is_list($item)) {
                ksort($item);
            }
            foreach ($item as $key => $child) {
                $item[$key] = $normalize($child);
            }
            return $item;
        };
        return json_encode($normalize($value), JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION);
    }

    /**
     * @param array<string, mixed> $command
     * @return array{job_id: string, status: string, outcome: string}
     */
    private function terminate(string $operation, array $command, string $reasonCode, bool $retryable): array
    {
        if (!self::isUuid($command['job_id'] ?? null)
            || !is_string($command['lease_token'] ?? null)
            || preg_match('/^[A-Za-z0-9_-]{43}$/', $command['lease_token']) !== 1) {
            throw new ExtractionGatewayException('invalid_contract', false, 'The terminal request is invalid.', 422);
        }
        $job = $this->jobs->find($command['job_id']);
        $leaseHash = hash('sha256', $command['lease_token']);
        if ($job === null || !is_string($job['lease_token_hash'] ?? null)
            || !hash_equals($job['lease_token_hash'], $leaseHash)) {
            throw new ExtractionGatewayException('unauthorized', false, 'Worker request denied.', 401);
        }
        $result = $this->jobs->terminate(
            $operation,
            $command['job_id'],
            $leaseHash,
            $reasonCode,
            $retryable,
            hash('sha256', $this->canonicalJson($command)),
            $this->clock->now()
        );
        $this->audit->record($operation, $result['outcome'], $this->identifiers($job) + [
            'limitation_code' => $reasonCode,
            'retryable' => $retryable,
        ]);
        return $result;
    }
}
