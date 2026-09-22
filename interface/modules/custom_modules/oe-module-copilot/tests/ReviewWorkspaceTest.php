<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

require_once dirname(__DIR__) . '/src/Document/DocumentPorts.php';
require_once dirname(__DIR__) . '/src/Document/DocumentLifecycleException.php';
require_once dirname(__DIR__) . '/src/Document/Review/ReviewWorkspacePorts.php';
require_once dirname(__DIR__) . '/src/Document/Review/ReviewWorkspace.php';

use OpenEMR\Modules\Copilot\Document\AuditPort;
use OpenEMR\Modules\Copilot\Document\AuthorizationPort;
use OpenEMR\Modules\Copilot\Document\DocumentContext;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleException;
use OpenEMR\Modules\Copilot\Document\Review\ReviewSourcePort;
use OpenEMR\Modules\Copilot\Document\Review\ReviewWorkspace;
use OpenEMR\Modules\Copilot\Document\Review\ReviewWorkspaceRepositoryPort;
use PHPUnit\Framework\TestCase;

final class ReviewWorkspaceTest extends TestCase
{
    public function testLatestExtractionReadBackBlocksPromotionUntilEveryCurrentDecisionAcceptsAProposedValue(): void
    {
        $repository = ReviewWorkspaceRepository::withLabExtraction();
        $workspace = $this->workspace($repository);

        $pending = $workspace->read('corr-workspace-pending');

        self::assertSame('review_required', $pending['status']);
        self::assertSame(ReviewWorkspaceRepository::EXTRACTION_ID, $pending['extraction']['extraction_id']);
        self::assertSame(1, $pending['extraction']['extraction_version']);
        self::assertSame(str_repeat('a', 64), $pending['extraction']['source_content_sha256']);
        self::assertSame('pending', $pending['facts'][0]['current_decision']['decision']);
        self::assertSame('blocked', $pending['promotion']['state']);
        self::assertSame([], $pending['promotion']['review_ids']);

        $repository->reviews = [
            ReviewWorkspaceRepository::review('collection_date', '33333333-3333-4333-8333-333333333331'),
            ReviewWorkspaceRepository::review('analyte.potassium.value', '33333333-3333-4333-8333-333333333332'),
        ];
        $ready = $workspace->read('corr-workspace-ready');

        self::assertSame('ready_to_promote', $ready['status']);
        self::assertSame('ready', $ready['promotion']['state']);
        self::assertSame([
            '33333333-3333-4333-8333-333333333331',
            '33333333-3333-4333-8333-333333333332',
        ], $ready['promotion']['review_ids']);
        self::assertSame('approved', $ready['facts'][0]['current_decision']['decision']);
        self::assertSame(0, $repository->writes);
    }

    public function testPromotedRecordIsReadBackWithItsExactVersionAndNoAutonomousWrite(): void
    {
        $repository = ReviewWorkspaceRepository::withLabExtraction();
        $repository->reviews = [
            ReviewWorkspaceRepository::review('collection_date', '33333333-3333-4333-8333-333333333331'),
            ReviewWorkspaceRepository::review('analyte.potassium.value', '33333333-3333-4333-8333-333333333332'),
        ];
        $repository->record = [
            'record_id' => '44444444-4444-4444-8444-444444444444',
            'record_version' => 2,
            'target_type' => 'lab_report',
            'status' => 'amended',
            'review_set_sha256' => str_repeat('b', 64),
            'source_content_sha256' => str_repeat('a', 64),
            'source_document_id' => ReviewWorkspaceRepository::SOURCE_ID,
            'extraction_id' => ReviewWorkspaceRepository::EXTRACTION_ID,
            'extraction_version' => 1,
            'site_id' => 'default',
            'pid' => 42,
            'record_json' => ['record_id' => '44444444-4444-4444-8444-444444444444', 'record_version' => 2, 'status' => 'amended'],
        ];

        $readBack = $this->workspace($repository)->read('corr-workspace-promoted');

        self::assertSame('promoted', $readBack['status']);
        self::assertSame('promoted', $readBack['promotion']['state']);
        self::assertSame(2, $readBack['promotion']['current_record']['record_version']);
        self::assertSame('amended', $readBack['promotion']['current_record']['record']['status']);
        self::assertSame(0, $repository->writes);
    }

    public function testSourceClickRequiresExactCurrentIdentifiersVersionsAndHashesBeforeRendering(): void
    {
        $repository = ReviewWorkspaceRepository::withLabExtraction();
        $source = new ReviewWorkspaceSource();
        $workspace = $this->workspace($repository, $source);
        $request = [
            'extraction_id' => ReviewWorkspaceRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'source_document_id' => ReviewWorkspaceRepository::SOURCE_ID,
            'source_content_sha256' => str_repeat('a', 64),
            'field_id' => 'analyte.potassium.value',
            'evidence_id' => ReviewWorkspaceRepository::EVIDENCE_ID,
            'page_number' => 2,
            'rendered_page_sha256' => str_repeat('c', 64),
        ];

        $opened = $workspace->source($request, 'corr-workspace-source');

        self::assertSame('available', $opened['status']);
        self::assertSame('document_proposal', $opened['source']['source_type']);
        self::assertSame(['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.08], $opened['source']['box']);
        self::assertSame(base64_encode('synthetic page image'), $opened['source']['page']['data_base64']);
        self::assertSame(1, $source->calls);

        try {
            $workspace->source(array_replace($request, ['source_content_sha256' => str_repeat('f', 64)]), 'corr-stale-source');
            self::fail('A stale browser hash must fail before source bytes are read.');
        } catch (DocumentLifecycleException $exception) {
            self::assertSame('source_mismatch', $exception->errorCode);
        }
        self::assertSame(1, $source->calls);
    }

    public function testAuthorizationDenialOccursBeforeAnyReviewDataIsRead(): void
    {
        $repository = ReviewWorkspaceRepository::withLabExtraction();
        $workspace = new ReviewWorkspace(
            new ReviewWorkspaceAuthorization(false),
            $repository,
            new ReviewWorkspaceSource(),
            new ReviewWorkspaceAudit(),
        );

        try {
            $workspace->read('corr-workspace-denied');
            self::fail('An unauthorized browser must not receive review data.');
        } catch (DocumentLifecycleException $exception) {
            self::assertSame('forbidden', $exception->errorCode);
        }
        self::assertSame(0, $repository->reads);
        self::assertSame(0, $repository->writes);
    }

    private function workspace(
        ReviewWorkspaceRepository $repository,
        ?ReviewWorkspaceSource $source = null,
    ): ReviewWorkspace {
        return new ReviewWorkspace(
            new ReviewWorkspaceAuthorization(),
            $repository,
            $source ?? new ReviewWorkspaceSource(),
            new ReviewWorkspaceAudit(),
        );
    }
}

final class ReviewWorkspaceRepository implements ReviewWorkspaceRepositoryPort
{
    public const EXTRACTION_ID = '11111111-1111-4111-8111-111111111111';
    public const SOURCE_ID = '22222222-2222-4222-8222-222222222222';
    public const EVIDENCE_ID = '55555555-5555-4555-8555-555555555555';

    /** @var array<string, mixed>|null */
    public ?array $extraction = null;
    /** @var list<array<string, mixed>> */
    public array $facts = [];
    /** @var list<array<string, mixed>> */
    public array $reviews = [];
    /** @var array<string, mixed>|null */
    public ?array $record = null;
    public int $writes = 0;
    public int $reads = 0;

    public static function withLabExtraction(): self
    {
        $repository = new self();
        $repository->extraction = [
            'extraction_id' => self::EXTRACTION_ID,
            'extraction_version' => 1,
            'source_document_id' => self::SOURCE_ID,
            'source_content_sha256' => str_repeat('a', 64),
            'site_id' => 'default',
            'pid' => 42,
            'schema_name' => 'lab-report',
            'schema_version' => '1.0.0',
            'state' => 'review_required',
            'source' => [
                'source_document_id' => self::SOURCE_ID,
                'document_type' => 'lab_report',
                'content_sha256' => str_repeat('a', 64),
                'mime_type' => 'application/pdf',
                'page_count' => 2,
            ],
            'payload' => [],
        ];
        $repository->facts = [
            [
                'extraction_id' => self::EXTRACTION_ID,
                'field_id' => 'collection_date',
                'typed_value' => '2026-09-20',
                'state' => 'schema_valid',
                'evidence' => [[
                    'evidence_id' => '55555555-5555-4555-8555-555555555554',
                    'page_number' => 1,
                    'box' => ['x' => 0.1, 'y' => 0.1, 'width' => 0.2, 'height' => 0.05],
                    'printed_quote' => '2026-09-20',
                    'rendered_page_sha256' => str_repeat('d', 64),
                ]],
            ],
            [
                'extraction_id' => self::EXTRACTION_ID,
                'field_id' => 'analyte.potassium.value',
                'typed_value' => ['kind' => 'quantity', 'value' => '4.2'],
                'state' => 'review_required',
                'evidence' => [[
                    'evidence_id' => self::EVIDENCE_ID,
                    'page_number' => 2,
                    'box' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.08],
                    'printed_quote' => 'Potassium 4.2',
                    'rendered_page_sha256' => str_repeat('c', 64),
                ]],
            ],
        ];
        return $repository;
    }

    /** @return array<string, mixed> */
    public static function review(string $fieldId, string $reviewId): array
    {
        return [
            'review_id' => $reviewId,
            'extraction_id' => self::EXTRACTION_ID,
            'extraction_version' => 1,
            'field_id' => $fieldId,
            'proposed_value' => $fieldId === 'collection_date' ? '2026-09-20' : ['kind' => 'quantity', 'value' => '4.2'],
            'final_value' => $fieldId === 'collection_date' ? '2026-09-20' : ['kind' => 'quantity', 'value' => '4.2'],
            'evidence_ids' => [$fieldId === 'collection_date' ? '55555555-5555-4555-8555-555555555554' : self::EVIDENCE_ID],
            'decision' => 'approved',
            'reason' => null,
            'reviewed_by' => 'physician-demo',
            'reviewed_at' => '2026-09-21T12:00:00Z',
            'supersedes_review_id' => null,
            'site_id' => 'default',
            'pid' => 42,
        ];
    }

    public function findLatestExtractionForPatient(string $siteId, int $pid): ?array
    {
        $this->reads++;
        return $this->extraction;
    }

    public function findProposedFactsForExtraction(string $extractionId): array
    {
        return $this->facts;
    }

    public function findCurrentReviewsForExtraction(string $extractionId): array
    {
        return $this->reviews;
    }

    public function findLatestRecordForExtraction(string $extractionId): ?array
    {
        return $this->record;
    }
}

final class ReviewWorkspaceSource implements ReviewSourcePort
{
    public int $calls = 0;

    public function renderPage(string $sourceDocumentId, int $pageNumber, string $correlationId): array
    {
        $this->calls++;
        return [
            'source_document_id' => $sourceDocumentId,
            'content_sha256' => str_repeat('a', 64),
            'page_number' => $pageNumber,
            'media_type' => 'image/png',
            'bytes' => 'synthetic page image',
        ];
    }
}

final class ReviewWorkspaceAuthorization implements AuthorizationPort
{
    public function __construct(private readonly bool $allowed = true)
    {
    }

    public function authorize(string $operation, string $correlationId): DocumentContext
    {
        if (!$this->allowed) {
            throw new DocumentLifecycleException('forbidden', false, 'The document action is not authorized.', 403);
        }
        return new DocumentContext('default', 7, 'physician-demo', 'Default', 42, 'patient-demo-42');
    }
}

final class ReviewWorkspaceAudit implements AuditPort
{
    public function record(DocumentContext $context, string $operation, bool $success, string $reason, array $identifiers): void
    {
    }
}
