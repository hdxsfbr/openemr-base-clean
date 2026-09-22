<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

require_once dirname(__DIR__) . '/src/Document/Extraction/ExtractionWorkerPorts.php';
require_once dirname(__DIR__) . '/src/Document/Extraction/ExtractionGatewayException.php';
require_once dirname(__DIR__) . '/src/Document/Extraction/ExtractionWorkerAuthenticator.php';
require_once dirname(__DIR__) . '/src/Document/Extraction/ExtractionJobGateway.php';
require_once dirname(__DIR__) . '/src/Document/Extraction/StrictExtractionEnvelopeValidator.php';
require_once dirname(__DIR__) . '/src/Document/Extraction/ExtractionWorkerHttp.php';

use DateTimeImmutable;
use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionGatewayException;
use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionNoncePort;
use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionAuditPort;
use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionClockPort;
use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionJobGateway;
use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionJobRepositoryPort;
use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionSourcePort;
use OpenEMR\Modules\Copilot\Document\Extraction\StrictExtractionEnvelopeValidator;
use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionWorkerAuthenticator;
use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionWorkerHttp;
use PHPUnit\Framework\TestCase;

final class ExtractionWorkerGatewayTest extends TestCase
{
    public function testClaimReturnsOnlyTheLeasedAuthorizedSourceAfterAuditAndIntegrityCheck(): void
    {
        $bytes = '%PDF-synthetic-source%%EOF';
        $repository = new MemoryExtractionJobs($this->queuedJob($bytes));
        $source = new MemoryExtractionSource($bytes);
        $audit = new MemoryExtractionAudit();
        $source->audit = $audit;
        $gateway = $this->gateway($repository, $source, $audit);

        $response = $gateway->claim(['worker_id' => 'intake-extractor-01']);

        self::assertSame(base64_encode($bytes), $response['content_base64']);
        self::assertSame('22222222-2222-4222-8222-222222222222', $response['job_id']);
        self::assertSame('33333333-3333-4333-8333-333333333333', $response['handoff_id']);
        self::assertSame('corr-upload-0001', $response['correlation_id']);
        self::assertSame('lab_report', $response['source']['document_type']);
        self::assertTrue($source->auditObservedBeforeRead);
        self::assertSame('claim', $audit->events[0]['operation']);
        self::assertSame('lease_acquired', $audit->events[0]['outcome']);
        self::assertStringNotContainsString($bytes, json_encode($audit->events, JSON_THROW_ON_ERROR));
    }

    public function testClaimRejectsChangedOpenEmrBytesAndAuditsOnlyIdentifiers(): void
    {
        $expected = '%PDF-synthetic-source%%EOF';
        $changed = $expected . '-changed';
        $repository = new MemoryExtractionJobs($this->queuedJob($expected));
        $audit = new MemoryExtractionAudit();
        $gateway = $this->gateway($repository, new MemoryExtractionSource($changed), $audit);

        $this->assertGatewayError('source_mismatch', fn() => $gateway->claim(['worker_id' => 'intake-extractor-01']));

        self::assertSame('source_mismatch', $audit->events[array_key_last($audit->events)]['outcome']);
        self::assertStringNotContainsString($changed, json_encode($audit->events, JSON_THROW_ON_ERROR));
    }

    public function testAStaleLeaseIsRetriedOnceThenBecomesTerminal(): void
    {
        $bytes = '%PDF-synthetic-source%%EOF';
        $repository = new MemoryExtractionJobs($this->queuedJob($bytes));
        $clock = new FixedExtractionClock();
        $gateway = $this->gateway($repository, new MemoryExtractionSource($bytes), new MemoryExtractionAudit(), $clock);

        $first = $gateway->claim(['worker_id' => 'intake-extractor-01']);
        $clock->time = $clock->time->modify('+96 seconds');
        $second = $gateway->claim(['worker_id' => 'intake-extractor-01']);
        $clock->time = $clock->time->modify('+96 seconds');
        $third = $gateway->claim(['worker_id' => 'intake-extractor-01']);

        self::assertSame(1, $first['attempt']);
        self::assertSame(2, $second['attempt']);
        self::assertNull($third);
        self::assertSame('failed', $repository->job['status']);
        self::assertSame('deadline_exceeded', $repository->job['limitation_code']);
    }

    public function testCompleteAtomicallyPersistsStrictEnvelopeAndReplaysOneExtraction(): void
    {
        $bytes = '%PDF-synthetic-source%%EOF';
        $repository = new MemoryExtractionJobs($this->queuedJob($bytes));
        $gateway = $this->gateway($repository, new MemoryExtractionSource($bytes), new MemoryExtractionAudit());
        $claim = $gateway->claim(['worker_id' => 'intake-extractor-01']);
        self::assertNotNull($claim);
        $envelope = $this->validLabEnvelope($claim['source']);
        $command = [
            'job_id' => $claim['job_id'],
            'lease_token' => $claim['lease_token'],
            'envelope' => $envelope,
        ];

        $created = $gateway->complete($command);
        $replayed = $gateway->complete($command);

        self::assertSame('created', $created['outcome']);
        self::assertSame('replayed', $replayed['outcome']);
        self::assertSame($envelope['extraction_id'], $created['extraction_id']);
        self::assertCount(1, $repository->extractions);
        self::assertCount(3, $repository->facts);
        self::assertSame(
            ['collection_date', 'glucose.test_name', 'glucose.value'],
            array_column($repository->facts, 'field_id')
        );
    }

    public function testCompletePersistsAValidIntakeEnvelopeForTheReviewWorkspace(): void
    {
        $bytes = "\x89PNG\r\n\x1a\nsynthetic-sourceIEND\xaeB`\x82";
        $job = $this->queuedJob($bytes);
        $job['source']['document_type'] = 'intake_form';
        $job['source']['mime_type'] = 'image/png';
        $repository = new MemoryExtractionJobs($job);
        $gateway = $this->gateway($repository, new MemoryExtractionSource($bytes), new MemoryExtractionAudit());
        $claim = $gateway->claim(['worker_id' => 'intake-extractor-01']);

        $result = $gateway->complete([
            'job_id' => $claim['job_id'],
            'lease_token' => $claim['lease_token'],
            'envelope' => $this->validIntakeEnvelope($claim['source']),
        ]);

        self::assertSame('created', $result['outcome']);
        self::assertSame('chief_concern', $repository->facts[0]['field_id']);
        self::assertCount(1, $repository->extractions);
    }

    public function testCompleteRejectsSourceMismatchMalformedEnvelopeStaleLeaseAndDifferentDuplicate(): void
    {
        $bytes = '%PDF-synthetic-source%%EOF';

        $sourceMismatch = new MemoryExtractionJobs($this->queuedJob($bytes));
        $gateway = $this->gateway($sourceMismatch, new MemoryExtractionSource($bytes), new MemoryExtractionAudit());
        $claim = $gateway->claim(['worker_id' => 'intake-extractor-01']);
        $envelope = $this->validLabEnvelope($claim['source']);
        $envelope['source']['content_sha256'] = str_repeat('f', 64);
        $this->assertGatewayError('source_mismatch', fn() => $gateway->complete([
            'job_id' => $claim['job_id'], 'lease_token' => $claim['lease_token'], 'envelope' => $envelope,
        ]));
        self::assertCount(0, $sourceMismatch->extractions);

        $malformed = $this->validLabEnvelope($claim['source']);
        unset($malformed['payload']);
        $this->assertGatewayError('invalid_contract', fn() => $gateway->complete([
            'job_id' => $claim['job_id'], 'lease_token' => $claim['lease_token'], 'envelope' => $malformed,
        ]));
        self::assertCount(0, $sourceMismatch->extractions);

        $semanticMismatch = $this->validLabEnvelope($claim['source']);
        $semanticMismatch['payload']['collection_date']['evidence'] = [];
        $this->assertGatewayError('invalid_contract', fn() => $gateway->complete([
            'job_id' => $claim['job_id'], 'lease_token' => $claim['lease_token'], 'envelope' => $semanticMismatch,
        ]));

        $stale = new MemoryExtractionJobs($this->queuedJob($bytes));
        $clock = new FixedExtractionClock();
        $staleGateway = $this->gateway($stale, new MemoryExtractionSource($bytes), new MemoryExtractionAudit(), $clock);
        $staleClaim = $staleGateway->claim(['worker_id' => 'intake-extractor-01']);
        $clock->time = $clock->time->modify('+96 seconds');
        $this->assertGatewayError('stale_lease', fn() => $staleGateway->complete([
            'job_id' => $staleClaim['job_id'],
            'lease_token' => $staleClaim['lease_token'],
            'envelope' => $this->validLabEnvelope($staleClaim['source']),
        ]));

        $duplicate = new MemoryExtractionJobs($this->queuedJob($bytes));
        $duplicateGateway = $this->gateway($duplicate, new MemoryExtractionSource($bytes), new MemoryExtractionAudit());
        $duplicateClaim = $duplicateGateway->claim(['worker_id' => 'intake-extractor-01']);
        $first = $this->validLabEnvelope($duplicateClaim['source']);
        $duplicateGateway->complete([
            'job_id' => $duplicateClaim['job_id'], 'lease_token' => $duplicateClaim['lease_token'], 'envelope' => $first,
        ]);
        $first['created_at'] = '2026-09-21T12:00:31Z';
        $this->assertGatewayError('conflict', fn() => $duplicateGateway->complete([
            'job_id' => $duplicateClaim['job_id'], 'lease_token' => $duplicateClaim['lease_token'], 'envelope' => $first,
        ]));
        self::assertCount(1, $duplicate->extractions);
    }

    public function testFailAndCancelAreTerminalIdempotentAndNeverPersistContent(): void
    {
        foreach (['fail', 'cancel'] as $operation) {
            $bytes = '%PDF-private-synthetic-marker%%EOF';
            $repository = new MemoryExtractionJobs($this->queuedJob($bytes));
            $audit = new MemoryExtractionAudit();
            $gateway = $this->gateway($repository, new MemoryExtractionSource($bytes), $audit);
            $claim = $gateway->claim(['worker_id' => 'intake-extractor-01']);
            $command = $operation === 'fail'
                ? ['job_id' => $claim['job_id'], 'lease_token' => $claim['lease_token'], 'limitation_code' => 'ocr_failed', 'retryable' => false]
                : ['job_id' => $claim['job_id'], 'lease_token' => $claim['lease_token'], 'reason_code' => 'worker_canceled'];

            $created = $gateway->{$operation}($command);
            $replayed = $gateway->{$operation}($command);

            self::assertSame($operation === 'fail' ? 'failed' : 'canceled', $created['status']);
            self::assertSame('created', $created['outcome']);
            self::assertSame('replayed', $replayed['outcome']);
            self::assertStringNotContainsString('private-synthetic-marker', json_encode([
                $repository->job, $audit->events,
            ], JSON_THROW_ON_ERROR));
        }
    }

    public function testWorkerAuthenticationRejectsMissingBadAndReplayedSignatures(): void
    {
        $nonces = new MemoryExtractionNonces();
        $auth = new ExtractionWorkerAuthenticator(
            str_repeat('s', 64),
            $nonces,
            static fn(): DateTimeImmutable => new DateTimeImmutable('2026-09-21T12:00:00Z')
        );
        $raw = '{"operation":"claim","worker_id":"worker-01"}';

        foreach ([[], $this->signedHeaders('wrong-secret', $raw)] as $headers) {
            try {
                $auth->authenticate($headers, 'POST', '/gateway/extraction.php', $raw);
                self::fail('Missing and invalid worker signatures must fail closed.');
            } catch (ExtractionGatewayException $exception) {
                self::assertSame('unauthorized', $exception->errorCode);
            }
        }

        $headers = $this->signedHeaders(str_repeat('s', 64), $raw);
        $auth->authenticate($headers, 'POST', '/gateway/extraction.php', $raw);
        try {
            $auth->authenticate($headers, 'POST', '/gateway/extraction.php', $raw);
            self::fail('A signed request nonce must be single-use.');
        } catch (ExtractionGatewayException $exception) {
            self::assertSame('unauthorized', $exception->errorCode);
        }
    }

    public function testHttpBoundaryIsInternalOnlyAndErrorsNeverEchoRequestContent(): void
    {
        $bytes = '%PDF-private-synthetic-marker%%EOF';
        $repository = new MemoryExtractionJobs($this->queuedJob($bytes));
        $gateway = $this->gateway($repository, new MemoryExtractionSource($bytes), new MemoryExtractionAudit());
        $secret = str_repeat('s', 64);
        $raw = '{"operation":"claim","command":{"worker_id":"private-synthetic-marker"},"extra":true}';

        $external = (new ExtractionWorkerHttp(
            new ExtractionWorkerAuthenticator($secret, new MemoryExtractionNonces(), static fn(): DateTimeImmutable => new DateTimeImmutable('2026-09-21T12:00:00Z')),
            $gateway
        ))->handle('POST', '/gateway/extraction.php', '203.0.113.10', $this->signedHeaders($secret, $raw), $raw, 'corr-http-0001');
        self::assertSame(401, $external['status']);

        $internal = (new ExtractionWorkerHttp(
            new ExtractionWorkerAuthenticator($secret, new MemoryExtractionNonces(), static fn(): DateTimeImmutable => new DateTimeImmutable('2026-09-21T12:00:00Z')),
            $gateway
        ))->handle('POST', '/gateway/extraction.php', '10.0.0.7', $this->signedHeaders($secret, $raw), $raw, 'corr-http-0001');
        self::assertSame(422, $internal['status']);
        self::assertSame(['code', 'correlation_id', 'retryable', 'limitation'], array_keys($internal['body']));
        self::assertStringNotContainsString('private-synthetic-marker', json_encode($internal['body'], JSON_THROW_ON_ERROR));
    }

    /** @return array<string, string> */
    private function signedHeaders(string $secret, string $body): array
    {
        $timestamp = '1789992000';
        $nonce = '0123456789abcdef0123456789abcdef';
        $canonical = "copilot-extraction-v1\n{$timestamp}\n{$nonce}\nPOST\n/gateway/extraction.php\n" . hash('sha256', $body);
        $key = hash_hmac('sha256', 'copilot-extraction-worker-v1', $secret, true);
        return [
            'x-copilot-worker-timestamp' => $timestamp,
            'x-copilot-worker-nonce' => $nonce,
            'x-copilot-worker-signature' => hash_hmac('sha256', $canonical, $key),
        ];
    }

    /** @return array<string, mixed> */
    private function queuedJob(string $bytes): array
    {
        return [
            'job_id' => '22222222-2222-4222-8222-222222222222',
            'handoff_id' => '33333333-3333-4333-8333-333333333333',
            'correlation_id' => 'corr-upload-0001',
            'extraction_version' => 1,
            'attempt' => 0,
            'status' => 'queued',
            'source' => [
                'source_document_id' => '11111111-1111-4111-8111-111111111111',
                'openemr_document_id' => '71',
                'upload_intent_id' => '44444444-4444-4444-8444-444444444444',
                'document_type' => 'lab_report',
                'content_sha256' => hash('sha256', $bytes),
                'byte_count' => strlen($bytes),
                'mime_type' => 'application/pdf',
                'page_count' => 1,
            ],
            'site_id' => 'default',
            'pid' => 42,
            'created_by' => 7,
        ];
    }

    private function gateway(
        MemoryExtractionJobs $repository,
        MemoryExtractionSource $source,
        MemoryExtractionAudit $audit,
        ?FixedExtractionClock $clock = null,
    ): ExtractionJobGateway {
        return new ExtractionJobGateway(
            $repository,
            $source,
            $audit,
            $clock ?? new FixedExtractionClock(),
            new StrictExtractionEnvelopeValidator(dirname(__DIR__, 5) . '/contracts/schema')
        );
    }

    private function assertGatewayError(string $code, callable $action): void
    {
        try {
            $action();
            self::fail('Expected extraction gateway error: ' . $code);
        } catch (ExtractionGatewayException $exception) {
            self::assertSame($code, $exception->errorCode);
            self::assertStringNotContainsString('synthetic', $exception->getMessage());
        }
    }

    /** @param array<string, mixed> $source @return array<string, mixed> */
    private function validLabEnvelope(array $source): array
    {
        $text = '2026-09-20 Glucose 101';
        $textHash = hash('sha256', $text);
        $pageHash = str_repeat('a', 64);
        $evidence = static fn(string $id, int $start, int $end, string $quote): array => [
            'evidence_id' => $id,
            'page_number' => 1,
            'box' => ['x' => 0.1, 'y' => 0.1, 'width' => 0.2, 'height' => 0.05],
            'printed_quote' => $quote,
            'ocr_span_start' => $start,
            'ocr_span_end' => $end,
            'ocr_text_sha256' => $textHash,
            'rendered_page_sha256' => $pageHash,
            'confidence' => 0.95,
            'validation' => ['valid'],
        ];
        return [
            'extraction_id' => '55555555-5555-4555-8555-555555555555',
            'extraction_version' => 1,
            'schema_name' => 'lab-report',
            'schema_version' => '1.0.0',
            'source' => $source,
            'state' => 'schema_valid',
            'created_at' => '2026-09-21T12:00:30Z',
            'ocr_pages' => [[
                'page_number' => 1,
                'text' => $text,
                'text_sha256' => $textHash,
                'rendered_page_sha256' => $pageHash,
                'renderer_version' => 'poppler-24.02',
                'preprocessing_version' => 'agentforge-1',
                'tokens' => [],
            ]],
            'payload' => [
                'collection_date' => [
                    'field_id' => 'collection_date', 'value' => '2026-09-20', 'state' => 'schema_valid',
                    'evidence' => [$evidence('66666666-6666-4666-8666-666666666666', 0, 10, '2026-09-20')],
                ],
                'analytes' => [[
                    'analyte_id' => '77777777-7777-4777-8777-777777777777',
                    'test_name' => [
                        'field_id' => 'glucose.test_name', 'value' => 'Glucose', 'state' => 'schema_valid',
                        'evidence' => [$evidence('88888888-8888-4888-8888-888888888888', 11, 18, 'Glucose')],
                    ],
                    'value' => [
                        'field_id' => 'glucose.value', 'value' => ['kind' => 'quantity', 'value' => 101],
                        'state' => 'schema_valid',
                        'evidence' => [$evidence('99999999-9999-4999-8999-999999999999', 19, 22, '101')],
                    ],
                ]],
            ],
        ];
    }

    /** @param array<string, mixed> $source @return array<string, mixed> */
    private function validIntakeEnvelope(array $source): array
    {
        $text = 'Routine follow-up';
        $textHash = hash('sha256', $text);
        $pageHash = str_repeat('b', 64);
        return [
            'extraction_id' => 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'extraction_version' => 1,
            'schema_name' => 'intake-form',
            'schema_version' => '1.0.0',
            'source' => $source,
            'state' => 'schema_valid',
            'created_at' => '2026-09-21T12:00:30Z',
            'ocr_pages' => [[
                'page_number' => 1,
                'text' => $text,
                'text_sha256' => $textHash,
                'rendered_page_sha256' => $pageHash,
                'renderer_version' => 'imagemagick-7',
                'preprocessing_version' => 'agentforge-1',
                'tokens' => [],
            ]],
            'payload' => [
                'demographics' => [],
                'chief_concern' => [
                    'field_id' => 'chief_concern',
                    'value' => $text,
                    'state' => 'schema_valid',
                    'evidence' => [[
                        'evidence_id' => 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
                        'page_number' => 1,
                        'box' => ['x' => 0.1, 'y' => 0.1, 'width' => 0.4, 'height' => 0.05],
                        'printed_quote' => $text,
                        'ocr_span_start' => 0,
                        'ocr_span_end' => strlen($text),
                        'ocr_text_sha256' => $textHash,
                        'rendered_page_sha256' => $pageHash,
                        'confidence' => 0.91,
                        'validation' => ['valid'],
                    ]],
                ],
                'medications' => [],
                'allergies' => [],
                'family_history' => [],
            ],
        ];
    }
}

final class MemoryExtractionNonces implements ExtractionNoncePort
{
    /** @var array<string, true> */
    private array $used = [];

    public function consume(string $nonce, DateTimeImmutable $expiresAt): bool
    {
        if (isset($this->used[$nonce])) {
            return false;
        }
        $this->used[$nonce] = true;
        return true;
    }
}

final class FixedExtractionClock implements ExtractionClockPort
{
    public DateTimeImmutable $time;

    public function __construct()
    {
        $this->time = new DateTimeImmutable('2026-09-21T12:00:00Z');
    }

    public function now(): DateTimeImmutable
    {
        return $this->time;
    }
}

final class MemoryExtractionJobs implements ExtractionJobRepositoryPort
{
    /** @var list<array<string, mixed>> */
    public array $extractions = [];
    /** @var list<array<string, mixed>> */
    public array $facts = [];
    /** @param array<string, mixed> $job */
    public function __construct(public array $job)
    {
    }

    public function transaction(callable $action): mixed
    {
        return $action();
    }

    public function claim(string $workerId, string $leaseTokenHash, DateTimeImmutable $expiresAt): ?array
    {
        $now = $expiresAt->modify('-' . ExtractionJobGateway::LEASE_SECONDS . ' seconds');
        if ($this->job['status'] === 'leased' && $this->job['lease_expires_at'] < $now) {
            if ($this->job['attempt'] >= 2) {
                $this->job['status'] = 'failed';
                $this->job['limitation_code'] = 'deadline_exceeded';
                return null;
            }
        } elseif ($this->job['status'] !== 'queued') {
            return null;
        }
        $this->job['status'] = 'leased';
        $this->job['worker_id'] = $workerId;
        $this->job['lease_token_hash'] = $leaseTokenHash;
        $this->job['lease_expires_at'] = $expiresAt;
        $this->job['attempt']++;
        return $this->job;
    }

    public function find(string $jobId): ?array
    {
        return $this->job['job_id'] === $jobId ? $this->job : null;
    }

    public function complete(
        string $jobId,
        string $leaseTokenHash,
        array $envelope,
        array $facts,
        string $envelopeSha256,
        DateTimeImmutable $completedAt,
    ): array {
        if ($this->job['job_id'] !== $jobId || !hash_equals($this->job['lease_token_hash'], $leaseTokenHash)) {
            throw new ExtractionGatewayException('unauthorized', false, 'Worker request denied.', 401);
        }
        if ($this->job['status'] === 'completed') {
            if (!hash_equals($this->job['completion_sha256'], $envelopeSha256)) {
                throw new ExtractionGatewayException('conflict', false, 'The job already has a different terminal result.', 409);
            }
            return ['extraction_id' => $this->job['extraction_id'], 'outcome' => 'replayed'];
        }
        if ($this->job['lease_expires_at'] < $completedAt) {
            throw new ExtractionGatewayException('stale_lease', true, 'The extraction lease expired.', 409);
        }
        $this->extractions[] = $envelope;
        $this->facts = $facts;
        $this->job['status'] = 'completed';
        $this->job['completion_sha256'] = $envelopeSha256;
        $this->job['extraction_id'] = $envelope['extraction_id'];
        return ['extraction_id' => $envelope['extraction_id'], 'outcome' => 'created'];
    }

    public function terminate(
        string $operation,
        string $jobId,
        string $leaseTokenHash,
        string $reasonCode,
        bool $retryable,
        string $requestSha256,
        DateTimeImmutable $terminalAt,
    ): array {
        if ($this->job['job_id'] !== $jobId || !hash_equals($this->job['lease_token_hash'], $leaseTokenHash)) {
            throw new ExtractionGatewayException('unauthorized', false, 'Worker request denied.', 401);
        }
        $status = $operation === 'fail' ? 'failed' : 'canceled';
        if (in_array($this->job['status'], ['failed', 'canceled'], true)) {
            if ($this->job['status'] !== $status || !hash_equals($this->job['terminal_sha256'], $requestSha256)) {
                throw new ExtractionGatewayException('conflict', false, 'The job already has a different terminal result.', 409);
            }
            return ['job_id' => $jobId, 'status' => $status, 'outcome' => 'replayed'];
        }
        if ($this->job['lease_expires_at'] < $terminalAt) {
            throw new ExtractionGatewayException('stale_lease', true, 'The extraction lease expired.', 409);
        }
        $this->job['status'] = $status;
        $this->job['terminal_sha256'] = $requestSha256;
        $this->job['limitation_code'] = $reasonCode;
        $this->job['retryable'] = $retryable;
        return ['job_id' => $jobId, 'status' => $status, 'outcome' => 'created'];
    }
}

final class MemoryExtractionSource implements ExtractionSourcePort
{
    public ?MemoryExtractionAudit $audit = null;
    public bool $auditObservedBeforeRead = false;

    public function __construct(private readonly string $bytes)
    {
    }

    public function read(array $job): string
    {
        $this->auditObservedBeforeRead = $this->audit !== null && $this->audit->events !== [];
        return $this->bytes;
    }
}

final class MemoryExtractionAudit implements ExtractionAuditPort
{
    /** @var list<array<string, mixed>> */
    public array $events = [];

    public function record(string $operation, string $outcome, array $identifiers): void
    {
        $this->events[] = ['operation' => $operation, 'outcome' => $outcome] + $identifiers;
    }
}
