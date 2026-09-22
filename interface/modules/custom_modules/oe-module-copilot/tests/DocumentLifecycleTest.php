<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

require_once dirname(__DIR__) . '/src/Document/DocumentPorts.php';
require_once dirname(__DIR__) . '/src/Document/DocumentLifecycleException.php';
require_once dirname(__DIR__) . '/src/Document/DocumentLifecycle.php';

use DateTimeImmutable;
use OpenEMR\Modules\Copilot\Document\AuditPort;
use OpenEMR\Modules\Copilot\Document\AuthorizationPort;
use OpenEMR\Modules\Copilot\Document\ClockPort;
use OpenEMR\Modules\Copilot\Document\DocumentContext;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycle;
use OpenEMR\Modules\Copilot\Document\DocumentStorePort;
use OpenEMR\Modules\Copilot\Document\MalwareScannerPort;
use OpenEMR\Modules\Copilot\Document\UploadFilePort;
use OpenEMR\Modules\Copilot\Document\UploadRepositoryPort;
use PHPUnit\Framework\TestCase;

final class DocumentLifecycleTest extends TestCase
{
    public function testAuthenticatedLabUploadCreatesOneOpenEmrDocumentAndSameIntentReplays(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $lifecycle = $this->lifecycle($repository, $documents);
        $command = [
            'idempotency_key' => '2da77a86-6d38-4c16-8c93-6668bc080873',
            'category' => 'lab_report',
            'original_filename' => 'synthetic-lab.pdf',
            'mime_type' => 'application/pdf',
            'byte_count' => strlen(self::onePagePdf()),
            'page_count' => 1,
        ];

        $intent = $lifecycle->createUploadIntent($command, 'corr-lab-0001');
        $intentReplay = $lifecycle->createUploadIntent($command, 'corr-lab-0001-retry');
        $created = $lifecycle->uploadContent(
            $intentReplay['upload_intent_id'],
            $intentReplay['upload_token'],
            new MemoryUploadFile('synthetic-lab.pdf', self::onePagePdf()),
            'corr-lab-0002'
        );
        $replayed = $lifecycle->uploadContent(
            $intent['upload_intent_id'],
            $intent['upload_token'],
            new MemoryUploadFile('synthetic-lab.pdf', self::onePagePdf()),
            'corr-lab-0003'
        );

        self::assertSame('created', $intent['outcome']);
        self::assertSame('replayed', $intentReplay['outcome']);
        self::assertSame($intent['upload_token'], $intentReplay['upload_token']);
        self::assertStringNotContainsString('.', $intent['upload_token']);
        self::assertNull(json_decode((string) base64_decode(strtr($intent['upload_token'], '-_', '+/'), true), true));
        self::assertSame('created', $created['outcome']);
        self::assertSame('replayed', $replayed['outcome']);
        self::assertSame($created['source'], $replayed['source']);
        self::assertCount(1, $documents->stored);
        self::assertCount(1, $repository->sources);
    }

    public function testSourceReadReauthorizesAuditsBeforeContentAndVerifiesHash(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $audit = new RecordingAudit();
        $documents->audit = $audit;
        $lifecycle = $this->lifecycle($repository, $documents, audit: $audit);
        $source = $this->uploadLab($lifecycle);

        $result = $lifecycle->readSource($source['source_document_id'], 'corr-read-0001');

        self::assertSame(self::onePagePdf(), $result['bytes']);
        self::assertSame($source, $result['source']);
        self::assertSame('source_read', $audit->events[array_key_last($audit->events)]['operation']);
        self::assertTrue($documents->auditObservedBeforeRead);
    }

    public function testSourceReadFailsClosedAfterPatientSwitch(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $source = $this->uploadLab($this->lifecycle($repository, $documents));
        $audit = new RecordingAudit();
        $switched = $this->lifecycle(
            $repository,
            $documents,
            new FixedAuthorization(pid: 43, patientUuid: 'patient-uuid-43'),
            $audit
        );

        try {
            $switched->readSource($source['source_document_id'], 'corr-read-switch');
            self::fail('A source from the prior chart must not be read.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('patient_context_changed', $exception->errorCode);
        }
        self::assertSame(0, $documents->reads);
        self::assertFalse($audit->events[0]['success']);
    }

    public function testMismatchedOrPolyglotContentIsRejectedAndAuditedWithoutStorage(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $audit = new RecordingAudit();
        $lifecycle = $this->lifecycle($repository, $documents, audit: $audit);
        $declared = self::onePagePdf();
        $intent = $this->createLabIntent($lifecycle, $declared);
        $polyglot = $declared . "<script>synthetic-marker</script>";

        try {
            $lifecycle->uploadContent(
                $intent['upload_intent_id'],
                $intent['upload_token'],
                new MemoryUploadFile('synthetic-lab.pdf', $polyglot),
                'corr-polyglot-0001'
            );
            self::fail('Polyglot content must fail closed.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('invalid_contract', $exception->errorCode);
        }

        self::assertSame('upload_content', $audit->events[array_key_last($audit->events)]['operation']);
        self::assertFalse($audit->events[array_key_last($audit->events)]['success']);
        self::assertCount(0, $documents->stored);
        self::assertCount(0, $repository->sources);
    }

    public function testPatientSwitchFailsBeforeAnyUploadByteIsRead(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $audit = new RecordingAudit();
        $creator = $this->lifecycle($repository, $documents, audit: $audit);
        $intent = $this->createLabIntent($creator, self::onePagePdf());
        $file = new MemoryUploadFile('synthetic-lab.pdf', self::onePagePdf());
        $switched = $this->lifecycle(
            $repository,
            $documents,
            new FixedAuthorization(pid: 43, patientUuid: 'patient-uuid-43'),
            $audit
        );

        try {
            $switched->uploadContent($intent['upload_intent_id'], $intent['upload_token'], $file, 'corr-switch-0001');
            self::fail('A changed open patient must fail closed.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('patient_context_changed', $exception->errorCode);
        }

        self::assertSame(0, $file->reads);
        self::assertFalse($audit->events[array_key_last($audit->events)]['success']);
        self::assertCount(0, $documents->stored);
    }

    public function testIntentContractIgnoresJsonKeyOrderButRejectsPatientAndPathFields(): void
    {
        $audit = new RecordingAudit();
        $lifecycle = $this->lifecycle(new InMemoryUploadRepository(), new InMemoryDocumentStore(), audit: $audit);
        $bytes = self::onePagePdf();
        $reordered = [
            'page_count' => 1,
            'mime_type' => 'application/pdf',
            'category' => 'lab_report',
            'byte_count' => strlen($bytes),
            'original_filename' => 'synthetic-lab.pdf',
            'idempotency_key' => '1e6261c4-5d79-4aa5-a17a-09fd258b9394',
        ];

        $created = $lifecycle->createUploadIntent($reordered, 'corr-order-0001');
        self::assertSame('created', $created['outcome']);

        foreach ([
            $reordered + ['patient_id' => 999],
            array_replace($reordered, ['original_filename' => '../../synthetic-lab.pdf']),
            array_replace($reordered, ['original_filename' => '..\\synthetic-lab.pdf']),
        ] as $invalid) {
            try {
                $lifecycle->createUploadIntent($invalid, 'corr-invalid-0001');
                self::fail('Browser patient selection and path-like filenames must be rejected.');
            } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
                self::assertSame('invalid_contract', $exception->errorCode);
            }
        }
        self::assertSame('upload_intent', $audit->events[array_key_last($audit->events)]['operation']);
        self::assertFalse($audit->events[array_key_last($audit->events)]['success']);
    }

    public function testSameBytesUnderNewIntentCreatesNewSourceWithDuplicateWarning(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $lifecycle = $this->lifecycle($repository, $documents);
        $first = $this->uploadLab($lifecycle);
        $secondResponse = $this->uploadLabResponse($lifecycle, 'a6a41cd5-bb7d-4209-90b3-680f6961aaaf');
        $second = $secondResponse['source'];
        $secondIntent = $repository->intents[$second['upload_intent_id']];
        $replayed = $lifecycle->uploadContent(
            $secondIntent['upload_intent_id'],
            $lifecycle->createUploadIntent([
                'idempotency_key' => 'a6a41cd5-bb7d-4209-90b3-680f6961aaaf',
                'category' => 'lab_report',
                'original_filename' => 'synthetic-lab.pdf',
                'mime_type' => 'application/pdf',
                'byte_count' => strlen(self::onePagePdf()),
                'page_count' => 1,
            ], 'corr-dupe-replay')['upload_token'],
            new MemoryUploadFile('synthetic-lab.pdf', self::onePagePdf()),
            'corr-dupe-replay'
        );

        self::assertNotSame($first['source_document_id'], $second['source_document_id']);
        self::assertSame('duplicate_content', $secondResponse['warnings'][0]['code']);
        self::assertSame([$first['source_document_id']], $secondResponse['warnings'][0]['matching_source_document_ids']);
        self::assertCount(2, $documents->stored);
        self::assertSame('replayed', $replayed['outcome']);
    }

    public function testMalwareRejectionDoesNotReadOrStoreUploadBytes(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $audit = new RecordingAudit();
        $lifecycle = $this->lifecycle($repository, $documents, audit: $audit, scanner: new RejectingScanner());
        $intent = $this->createLabIntent($lifecycle, self::onePagePdf());
        $file = new MemoryUploadFile('synthetic-lab.pdf', self::onePagePdf());

        try {
            $lifecycle->uploadContent($intent['upload_intent_id'], $intent['upload_token'], $file, 'corr-malware-0001');
            self::fail('A scanner rejection must fail closed.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('invalid_contract', $exception->errorCode);
        }

        self::assertSame(0, $file->reads);
        self::assertFalse($audit->events[array_key_last($audit->events)]['success']);
        self::assertCount(0, $documents->stored);
    }

    public function testSourceHashMismatchAndAuditFailureNeverReturnContent(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $audit = new ToggleAudit();
        $lifecycle = $this->lifecycle($repository, $documents, audit: $audit);
        $source = $this->uploadLab($lifecycle);
        $documents->stored[$source['openemr_document_id']] = self::onePagePdf() . 'tampered';

        try {
            $lifecycle->readSource($source['source_document_id'], 'corr-hash-0001');
            self::fail('A changed OpenEMR document must not be returned.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('source_mismatch', $exception->errorCode);
        }

        $documents->stored[$source['openemr_document_id']] = self::onePagePdf();
        $audit->fail = true;
        $readsBefore = $documents->reads;
        try {
            $lifecycle->readSource($source['source_document_id'], 'corr-audit-0001');
            self::fail('An audit outage must stop before decrypted content is read.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('unavailable', $exception->errorCode);
        }
        self::assertSame($readsBefore, $documents->reads);
    }

    public function testStructurallyInvalidJpegIsRejectedDespiteMagicBytes(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $lifecycle = $this->lifecycle($repository, $documents);
        $bytes = "\xff\xd8\xffsynthetic-corrupt\xff\xd9";
        $intent = $lifecycle->createUploadIntent([
            'idempotency_key' => 'bc9713ae-e54e-4ce5-a538-742688b29976',
            'category' => 'intake_form',
            'original_filename' => 'synthetic-intake.jpg',
            'mime_type' => 'image/jpeg',
            'byte_count' => strlen($bytes),
            'page_count' => 1,
        ], 'corr-jpeg-0001');

        try {
            $lifecycle->uploadContent(
                $intent['upload_intent_id'],
                $intent['upload_token'],
                new MemoryUploadFile('synthetic-intake.jpg', $bytes),
                'corr-jpeg-0002'
            );
            self::fail('Magic bytes alone must not make an image valid.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('invalid_contract', $exception->errorCode);
        }
        self::assertCount(0, $documents->stored);
    }

    public function testIntakeUploadAcceptsOnlyMeasuredPdfPngAndJpegSources(): void
    {
        $cases = [
            ['d60ebc85-d4cc-4b3d-b7b7-840c69307a99', 'intake.pdf', 'application/pdf', self::onePagePdf()],
            ['b9b2dfa2-7d0d-4be2-9555-8b32b61ef50d', 'intake.png', 'image/png', self::onePixelPng()],
            ['142406ac-e27a-40a6-876a-85f50e067415', 'intake.jpg', 'image/jpeg', self::onePixelJpeg()],
        ];

        foreach ($cases as [$key, $name, $mime, $bytes]) {
            $repository = new InMemoryUploadRepository();
            $documents = new InMemoryDocumentStore();
            $lifecycle = $this->lifecycle($repository, $documents);
            $intent = $lifecycle->createUploadIntent([
                'idempotency_key' => $key,
                'category' => 'intake_form',
                'original_filename' => $name,
                'mime_type' => $mime,
                'byte_count' => strlen($bytes),
                'page_count' => 1,
            ], 'corr-intake-0001');

            $response = $lifecycle->uploadContent(
                $intent['upload_intent_id'],
                $intent['upload_token'],
                new MemoryUploadFile($name, $bytes),
                'corr-intake-0002'
            );

            self::assertSame('intake_form', $response['source']['document_type']);
            self::assertSame($mime, $response['source']['mime_type']);
            self::assertSame(1, $response['source']['page_count']);
        }
    }

    public function testDeclaredSizeTypeAndPageLimitsFailBeforePermanentStorage(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $lifecycle = $this->lifecycle($repository, $documents);
        $base = [
            'idempotency_key' => 'b005dc99-76f3-4059-829a-c408f5c28697',
            'category' => 'intake_form',
            'original_filename' => 'intake.pdf',
            'mime_type' => 'application/pdf',
            'byte_count' => 100,
            'page_count' => 1,
        ];
        $invalid = [
            array_replace($base, ['byte_count' => 10_485_761]),
            array_replace($base, ['page_count' => 11]),
            array_replace($base, ['mime_type' => 'image/jpeg', 'page_count' => 2]),
            array_replace($base, ['category' => 'lab_report', 'mime_type' => 'image/png']),
        ];

        foreach ($invalid as $command) {
            try {
                $lifecycle->createUploadIntent($command, 'corr-limit-0001');
                self::fail('The declared source limit must fail closed.');
            } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
                self::assertSame('invalid_contract', $exception->errorCode);
            }
        }
        self::assertCount(0, $documents->stored);
    }

    public function testUploadAuditFailureStopsBeforeOpenEmrStorage(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $audit = new ToggleAudit();
        $lifecycle = $this->lifecycle($repository, $documents, audit: $audit);
        $intent = $this->createLabIntent($lifecycle, self::onePagePdf());
        $audit->fail = true;

        try {
            $lifecycle->uploadContent(
                $intent['upload_intent_id'],
                $intent['upload_token'],
                new MemoryUploadFile('synthetic-lab.pdf', self::onePagePdf()),
                'corr-upload-audit-fail'
            );
            self::fail('OpenEMR storage must not run when the access audit fails.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('unavailable', $exception->errorCode);
        }
        self::assertCount(0, $documents->stored);
    }

    public function testMappingTransactionFailureCompensatesOpenEmrDocument(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $lifecycle = $this->lifecycle($repository, $documents);
        $intent = $this->createLabIntent($lifecycle, self::onePagePdf());
        $repository->failOutbox = true;

        try {
            $lifecycle->uploadContent(
                $intent['upload_intent_id'],
                $intent['upload_token'],
                new MemoryUploadFile('synthetic-lab.pdf', self::onePagePdf()),
                'corr-transaction-fail'
            );
            self::fail('A partial mapping transaction must not leave a usable source.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('unavailable', $exception->errorCode);
        }
        self::assertCount(0, $documents->stored);
        self::assertCount(0, $repository->sources);
        self::assertNull($repository->intents[$intent['upload_intent_id']]['source_document_id']);
    }

    public function testAuditAndOutboxNeverContainSourceBytesOrClientFilename(): void
    {
        $repository = new InMemoryUploadRepository();
        $documents = new InMemoryDocumentStore();
        $audit = new RecordingAudit();
        $lifecycle = $this->lifecycle($repository, $documents, audit: $audit);

        $this->uploadLab($lifecycle);

        $recorded = json_encode(['audit' => $audit->events, 'outbox' => $repository->outbox], JSON_THROW_ON_ERROR);
        self::assertStringNotContainsString('%PDF', $recorded);
        self::assertStringNotContainsString('synthetic-lab.pdf', $recorded);
        self::assertStringNotContainsString('3 0 obj', $recorded);
    }

    private function lifecycle(
        InMemoryUploadRepository $repository,
        InMemoryDocumentStore $documents,
        ?AuthorizationPort $authorization = null,
        ?AuditPort $audit = null,
        ?MalwareScannerPort $scanner = null,
    ): DocumentLifecycle {
        return new DocumentLifecycle(
            $authorization ?? new AllowAuthorization(),
            $repository,
            $documents,
            $scanner ?? new CleanScanner(),
            $audit ?? new RecordingAudit(),
            new FixedClock(),
            'synthetic-test-secret-with-at-least-thirty-two-bytes'
        );
    }

    /** @return array<string, mixed> */
    private function uploadLab(DocumentLifecycle $lifecycle, ?string $idempotencyKey = null): array
    {
        return $this->uploadLabResponse($lifecycle, $idempotencyKey)['source'];
    }

    /** @return array<string, mixed> */
    private function uploadLabResponse(DocumentLifecycle $lifecycle, ?string $idempotencyKey = null): array
    {
        $bytes = self::onePagePdf();
        $intent = $this->createLabIntent($lifecycle, $bytes, $idempotencyKey);
        return $lifecycle->uploadContent(
            $intent['upload_intent_id'],
            $intent['upload_token'],
            new MemoryUploadFile('synthetic-lab.pdf', $bytes),
            'corr-upload-0002'
        );
    }

    /** @return array<string, mixed> */
    private function createLabIntent(
        DocumentLifecycle $lifecycle,
        string $bytes,
        ?string $idempotencyKey = null,
    ): array {
        return $lifecycle->createUploadIntent([
            'idempotency_key' => $idempotencyKey ?? '2da77a86-6d38-4c16-8c93-6668bc080873',
            'category' => 'lab_report',
            'original_filename' => 'synthetic-lab.pdf',
            'mime_type' => 'application/pdf',
            'byte_count' => strlen($bytes),
            'page_count' => 1,
        ], 'corr-upload-0001');
    }

    private static function onePagePdf(): string
    {
        return "%PDF-1.4\n1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj\n"
            . "2 0 obj<</Type /Pages /Kids[3 0 R] /Count 1>>endobj\n"
            . "3 0 obj<</Type /Page /Parent 2 0 R>>endobj\n%%EOF\n";
    }

    private static function onePixelPng(): string
    {
        return (string) base64_decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', true);
    }

    private static function onePixelJpeg(): string
    {
        return (string) base64_decode('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9k=', true);
    }
}

final class AllowAuthorization implements AuthorizationPort
{
    public function authorize(string $operation, string $correlationId): DocumentContext
    {
        return new DocumentContext('default', 7, 'synthetic-physician', 'Physicians', 42, 'patient-uuid-42');
    }
}

final class FixedAuthorization implements AuthorizationPort
{
    public function __construct(
        private readonly int $pid = 42,
        private readonly string $patientUuid = 'patient-uuid-42',
    ) {
    }

    public function authorize(string $operation, string $correlationId): DocumentContext
    {
        return new DocumentContext('default', 7, 'synthetic-physician', 'Physicians', $this->pid, $this->patientUuid);
    }
}

final class InMemoryUploadRepository implements UploadRepositoryPort
{
    /** @var array<string, array<string, mixed>> */
    public array $intents = [];
    /** @var array<string, array<string, mixed>> */
    public array $sources = [];
    /** @var list<array<string, mixed>> */
    public array $outbox = [];
    public bool $failOutbox = false;

    public function transaction(callable $action): mixed
    {
        $intents = $this->intents;
        $sources = $this->sources;
        $outbox = $this->outbox;
        try {
            return $action();
        } catch (\Throwable $exception) {
            $this->intents = $intents;
            $this->sources = $sources;
            $this->outbox = $outbox;
            throw $exception;
        }
    }

    public function findIntentByKey(string $siteId, int $pid, string $category, string $idempotencyKey): ?array
    {
        foreach ($this->intents as $intent) {
            if ($intent['site_id'] === $siteId && $intent['pid'] === $pid
                && $intent['category'] === $category && $intent['idempotency_key'] === $idempotencyKey) {
                return $intent;
            }
        }
        return null;
    }

    public function insertIntent(array $intent): void
    {
        $this->intents[$intent['upload_intent_id']] = $intent;
    }

    public function findIntent(string $intentId): ?array
    {
        return $this->intents[$intentId] ?? null;
    }

    public function completeIntent(string $intentId, array $source): bool
    {
        if (($this->intents[$intentId]['source_document_id'] ?? null) !== null) {
            return false;
        }
        $this->sources[$source['source_document_id']] = $source;
        $this->intents[$intentId]['source_document_id'] = $source['source_document_id'];
        return true;
    }

    public function findSource(string $sourceDocumentId): ?array
    {
        return $this->sources[$sourceDocumentId] ?? null;
    }

    public function findDuplicateSourceIds(string $siteId, int $pid, string $sha256, string $exceptIntentId): array
    {
        $matches = [];
        foreach ($this->sources as $source) {
            if ($source['site_id'] === $siteId && (int) $source['pid'] === $pid
                && $source['content_sha256'] === $sha256 && $source['upload_intent_id'] !== $exceptIntentId) {
                $matches[] = $source['source_document_id'];
            }
        }
        return array_slice($matches, 0, 10);
    }

    public function appendOutbox(array $event): void
    {
        if ($this->failOutbox) {
            throw new \RuntimeException('synthetic outbox failure');
        }
        $this->outbox[] = $event;
    }
}

final class InMemoryDocumentStore implements DocumentStorePort
{
    /** @var array<string, string> */
    public array $stored = [];
    public ?RecordingAudit $audit = null;
    public bool $auditObservedBeforeRead = false;
    public int $reads = 0;

    public function store(DocumentContext $context, string $category, string $filename, string $mimeType, string $bytes): string
    {
        $id = (string) (count($this->stored) + 100);
        $this->stored[$id] = $bytes;
        return $id;
    }

    public function read(DocumentContext $context, string $openEmrDocumentId): string
    {
        ++$this->reads;
        $last = $this->audit?->events[array_key_last($this->audit->events)] ?? null;
        $this->auditObservedBeforeRead = ($last['operation'] ?? null) === 'source_read';
        return $this->stored[$openEmrDocumentId];
    }

    public function remove(DocumentContext $context, string $openEmrDocumentId): void
    {
        unset($this->stored[$openEmrDocumentId]);
    }
}

final class MemoryUploadFile implements UploadFilePort
{
    public int $reads = 0;

    public function __construct(private readonly string $name, private readonly string $bytes)
    {
    }

    public function clientFilename(): string
    {
        return $this->name;
    }

    public function read(int $maximumBytes): string
    {
        ++$this->reads;
        return $this->bytes;
    }

    public function scannerPath(): ?string
    {
        return null;
    }
}

final class CleanScanner implements MalwareScannerPort
{
    public function isClean(UploadFilePort $file): bool
    {
        return true;
    }
}

final class RejectingScanner implements MalwareScannerPort
{
    public function isClean(UploadFilePort $file): bool
    {
        return false;
    }
}

final class RecordingAudit implements AuditPort
{
    /** @var list<array<string, mixed>> */
    public array $events = [];

    public function record(DocumentContext $context, string $operation, bool $success, string $reason, array $identifiers): void
    {
        $this->events[] = compact('operation', 'success', 'reason', 'identifiers');
    }
}

final class ToggleAudit implements AuditPort
{
    public bool $fail = false;

    public function record(DocumentContext $context, string $operation, bool $success, string $reason, array $identifiers): void
    {
        if ($this->fail) {
            throw new \RuntimeException('synthetic audit outage');
        }
    }
}

final class FixedClock implements ClockPort
{
    public function now(): DateTimeImmutable
    {
        return new DateTimeImmutable('2026-09-21T18:00:00Z');
    }
}
