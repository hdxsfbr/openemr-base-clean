<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

require_once dirname(__DIR__) . '/src/SourceReview/SourceReviewPorts.php';
require_once dirname(__DIR__) . '/src/SourceReview/SourceReviewException.php';
require_once dirname(__DIR__) . '/src/SourceReview/SourceReviewContext.php';
require_once dirname(__DIR__) . '/src/SourceReview/SourceReview.php';
require_once dirname(__DIR__) . '/src/SourceReview/SourceReviewHttp.php';

use OpenEMR\Modules\Copilot\SourceReview\CitationAuthorityPort;
use OpenEMR\Modules\Copilot\SourceReview\SourceReview;
use OpenEMR\Modules\Copilot\SourceReview\SourceReviewAuthorizationPort;
use OpenEMR\Modules\Copilot\SourceReview\SourceReviewContext;
use OpenEMR\Modules\Copilot\SourceReview\SourceReviewHttp;
use OpenEMR\Modules\Copilot\SourceReview\SourceViewAuthorityPort;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class SourceReviewTest extends TestCase
{
    public function testCorrectedDocumentOpensTheAuthorizedImmutablePageAndKeepsReviewedAndPrintedValuesDistinct(): void
    {
        $review = new SourceReview(
            new SourceReviewFixedAuthorization(),
            new SourceReviewFixedCitationAuthority(self::documentCitation()),
            new SourceReviewFixedViewAuthority(self::documentView()),
        );

        $opened = $review->open([
            'conversation_id' => str_repeat('a', 32),
            'turn_id' => str_repeat('b', 16),
            'citation_id' => 'citation-document-1',
        ], 'corr-source-0001');

        self::assertSame('available', $opened['status']);
        self::assertSame('patient_record', $opened['lane']);
        self::assertSame('Reviewed', $opened['source']['reviewed']['label']);
        self::assertSame('Never', $opened['source']['reviewed']['value']);
        self::assertSame('Printed', $opened['source']['printed']['label']);
        self::assertSame('Current', $opened['source']['printed']['value']);
        self::assertSame('corrected', $opened['source']['review_decision']);
        self::assertSame(2, $opened['source']['page_number']);
        self::assertSame(
            ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.08],
            $opened['source']['box']
        );
        self::assertSame(base64_encode('synthetic rendered page'), $opened['source']['page']['data_base64']);
    }

    public function testGuidelineEvidenceUsesItsOwnLaneAndTheFixedNoApplicabilityBoundary(): void
    {
        $quote = 'Screening decisions should use shared decision-making.';
        $citation = [
            'citation_id' => 'citation-guideline-1',
            'source_type' => 'guideline',
            'source_id' => 'guideline:corpus-2026:screening-guide:shared-decision',
            'title' => 'Synthetic screening guide',
            'page_or_section' => [
                'kind' => 'guideline_section',
                'section_path' => ['Screening', 'Shared decisions'],
                'chunk_ordinal' => 4,
            ],
            'field_or_chunk_id' => 'shared-decision',
            'quote_or_value' => ['kind' => 'exact_quote', 'quote' => $quote],
            'publisher' => 'Synthetic Clinical Society',
            'canonical_url' => 'https://example.test/guideline',
            'corpus_version' => 'corpus-2026',
            'source_sha256' => str_repeat('c', 64),
            'chunk_sha256' => hash('sha256', $quote),
        ];
        $view = [
            'source_type' => 'guideline',
            'source_id' => $citation['source_id'],
            'corpus_version' => 'corpus-2026',
            'active_corpus_version' => 'corpus-2026',
            'document_id' => 'screening-guide',
            'chunk_id' => 'shared-decision',
            'publisher' => 'Synthetic Clinical Society',
            'title' => 'Synthetic screening guide',
            'section_path' => ['Screening', 'Shared decisions'],
            'chunk_ordinal' => 4,
            'exact_text' => $quote,
            'source_sha256' => str_repeat('c', 64),
            'chunk_sha256' => hash('sha256', $quote),
            'canonical_url' => 'https://example.test/guideline',
            'status' => 'active',
        ];
        $review = new SourceReview(
            new SourceReviewFixedAuthorization(),
            new SourceReviewFixedCitationAuthority($citation),
            new SourceReviewFixedViewAuthority($view),
        );

        $opened = $review->open([
            'conversation_id' => str_repeat('a', 32),
            'turn_id' => str_repeat('b', 16),
            'citation_id' => 'citation-guideline-1',
        ], 'corr-source-0002');

        self::assertSame('guideline_evidence', $opened['lane']);
        self::assertSame($quote, $opened['source']['exact_excerpt']);
        self::assertSame(SourceReview::NO_APPLICABILITY, $opened['source']['boundary']);
        self::assertArrayNotHasKey('reviewed', $opened['source']);
    }

    public function testNativeRecordUsesOnlyTheResolverOwnedSameChartDestination(): void
    {
        $citation = [
            'citation_id' => 'citation-record-1',
            'source_type' => 'openemr_record',
            'source_id' => 'openemr:problems:17',
            'title' => 'Problem list entry',
            'page_or_section' => ['kind' => 'chart_section', 'section' => 'problems'],
            'field_or_chunk_id' => 'title',
            'quote_or_value' => ['kind' => 'record_value', 'value' => 'Synthetic condition'],
            'source_version' => '2026-09-21T18:00:00Z',
            'href' => '/interface/patient_file/summary/add_edit_issue.php?issue=17',
        ];
        $view = [
            'source_type' => 'openemr_record',
            'source_id' => 'openemr:problems:17',
            'chart_section' => 'problems',
            'record_label' => 'Problem list entry',
            'source_version' => '2026-09-21T18:00:00Z',
            'field_id' => 'title',
            'displayed_value' => 'Synthetic condition',
            'href' => '/interface/patient_file/summary/add_edit_issue.php?issue=17',
        ];
        $review = new SourceReview(
            new SourceReviewFixedAuthorization(),
            new SourceReviewFixedCitationAuthority($citation),
            new SourceReviewFixedViewAuthority($view),
        );

        $opened = $review->open([
            'conversation_id' => str_repeat('a', 32),
            'turn_id' => str_repeat('b', 16),
            'citation_id' => 'citation-record-1',
        ], 'corr-source-0003');

        self::assertSame('patient_record', $opened['lane']);
        self::assertSame($view['href'], $opened['source']['same_chart_href']);
        self::assertSame('Synthetic condition', $opened['source']['displayed_value']);
    }

    public function testUnavailableSourceReturnsATypedContentFreeLimitation(): void
    {
        $review = new SourceReview(
            new SourceReviewFixedAuthorization(),
            new SourceReviewFixedCitationAuthority(self::documentCitation()),
            new SourceReviewFixedViewAuthority(null),
        );

        $response = (new SourceReviewHttp($review))->handle([
            'conversation_id' => str_repeat('a', 32),
            'turn_id' => str_repeat('b', 16),
            'citation_id' => 'citation-document-1',
        ], 'corr-source-0004');

        self::assertSame(503, $response['http_status']);
        self::assertSame([
            'status' => 'unavailable',
            'code' => 'source_unavailable',
            'retryable' => true,
            'limitation' => 'This source cannot be opened right now. The verified answer remains available.',
            'correlation_id' => 'corr-source-0004',
        ], $response['body']);
        self::assertStringNotContainsString('Current', json_encode($response, JSON_THROW_ON_ERROR));
        self::assertStringNotContainsString('11111111', json_encode($response, JSON_THROW_ON_ERROR));
    }

    /** @return iterable<string, array{array<string, mixed>}> */
    public static function changedDocumentAuthorities(): iterable
    {
        $shifted = self::documentView();
        $shifted['evidence']['box']['x'] = 0.11;
        yield 'shifted box' => [$shifted];

        $changedPage = self::documentView();
        $changedPage['page']['bytes'] = 'changed rendered page';
        yield 'changed rendered-page hash' => [$changedPage];

        $stale = self::documentView();
        $stale['record_version'] = 4;
        yield 'stale record version' => [$stale];

        $withdrawn = self::documentView();
        $withdrawn['record_status'] = 'withdrawn';
        yield 'withdrawn record' => [$withdrawn];
    }

    /** @param array<string, mixed> $changed */
    #[DataProvider('changedDocumentAuthorities')]
    public function testChangedDocumentAuthorityFailsClosedWithoutPageOrClinicalText(array $changed): void
    {
        $review = new SourceReview(
            new SourceReviewFixedAuthorization(),
            new SourceReviewFixedCitationAuthority(self::documentCitation()),
            new SourceReviewFixedViewAuthority($changed),
        );

        $response = (new SourceReviewHttp($review))->handle([
            'conversation_id' => str_repeat('a', 32),
            'turn_id' => str_repeat('b', 16),
            'citation_id' => 'citation-document-1',
        ], 'corr-source-integrity');

        self::assertSame(409, $response['http_status']);
        self::assertSame('source_integrity_failed', $response['body']['code']);
        self::assertArrayNotHasKey('source', $response['body']);
        self::assertStringNotContainsString('Current', json_encode($response, JSON_THROW_ON_ERROR));
    }

    public function testBrowserCannotSmuggleHrefSourceMetadataOrPatientIdentity(): void
    {
        $authorization = new SourceReviewCountingAuthorization();
        $review = new SourceReview(
            $authorization,
            new SourceReviewFixedCitationAuthority(self::documentCitation()),
            new SourceReviewFixedViewAuthority(self::documentView()),
        );

        $response = (new SourceReviewHttp($review))->handle([
            'conversation_id' => str_repeat('a', 32),
            'turn_id' => str_repeat('b', 16),
            'citation_id' => 'citation-document-1',
            'href' => 'https://attacker.invalid/source',
            'patient_id' => 999,
            'box' => ['x' => 0, 'y' => 0, 'width' => 1, 'height' => 1],
        ], 'corr-source-smuggle');

        self::assertSame(422, $response['http_status']);
        self::assertSame('invalid_contract', $response['body']['code']);
        self::assertSame(0, $authorization->calls);
    }

    public function testEveryClickReauthorizesAndAuthorizationLossReturnsNoSource(): void
    {
        $authorization = new SourceReviewCountingAuthorization(1);
        $review = new SourceReview(
            $authorization,
            new SourceReviewFixedCitationAuthority(self::documentCitation()),
            new SourceReviewFixedViewAuthority(self::documentView()),
        );
        $http = new SourceReviewHttp($review);
        $request = [
            'conversation_id' => str_repeat('a', 32),
            'turn_id' => str_repeat('b', 16),
            'citation_id' => 'citation-document-1',
        ];

        self::assertSame(200, $http->handle($request, 'corr-source-first')['http_status']);
        $lost = $http->handle($request, 'corr-source-lost');

        self::assertSame(2, $authorization->calls);
        self::assertSame(403, $lost['http_status']);
        self::assertSame('forbidden', $lost['body']['code']);
        self::assertArrayNotHasKey('source', $lost['body']);
    }

    public function testUiContractKeepsLanesLabelsKeyboardAndThreeHundredTwentyPixelReflowVisible(): void
    {
        $root = dirname(__DIR__);
        $javascript = file_get_contents($root . '/public/assets/js/copilot.js');
        $css = file_get_contents($root . '/public/assets/css/copilot.css');
        self::assertIsString($javascript);
        self::assertIsString($css);

        self::assertStringContainsString('Patient record', $javascript);
        self::assertStringContainsString('Guideline evidence', $javascript);
        self::assertStringContainsString(SourceReview::NO_APPLICABILITY, $javascript);
        self::assertStringContainsString("source.reviewed.label + ': '", $javascript);
        self::assertStringContainsString("source.printed.label + ': '", $javascript);
        self::assertStringContainsString("event.key !== 'Escape'", $javascript);
        self::assertStringContainsString("data-citation-id", $javascript);
        self::assertStringNotContainsString('citation.href', $javascript);
        self::assertStringContainsString('@media (max-width: 320px)', $css);
        self::assertStringContainsString('min-height: 2.75rem', $css);
        self::assertStringContainsString('.copilot-region-focus', $css);
    }

    /** @return array<string, mixed> */
    private static function documentCitation(): array
    {
        return [
            'citation_id' => 'citation-document-1',
            'source_type' => 'reviewed_document',
            'source_id' => 'document:11111111-1111-4111-8111-111111111111:record:22222222-2222-4222-8222-222222222222:v:3:field:tobacco.status',
            'title' => 'Reviewed intake response',
            'page_or_section' => [
                'kind' => 'document_region',
                'page_number' => 2,
                'box' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.08],
            ],
            'field_or_chunk_id' => 'tobacco.status',
            'quote_or_value' => [
                'kind' => 'reviewed_document_value',
                'reviewed_value' => 'Never',
                'printed_quote' => 'Current',
                'review_decision' => 'corrected',
            ],
            'source_content_sha256' => str_repeat('a', 64),
            'rendered_page_sha256' => hash('sha256', 'synthetic rendered page'),
            'ocr_text_sha256' => hash('sha256', 'Current'),
            'record_id' => '22222222-2222-4222-8222-222222222222',
            'record_version' => 3,
            'review_id' => '33333333-3333-4333-8333-333333333333',
            'evidence_id' => '44444444-4444-4444-8444-444444444444',
        ];
    }

    /** @return array<string, mixed> */
    private static function documentView(): array
    {
        return [
            'source_type' => 'reviewed_document',
            'source_id' => self::documentCitation()['source_id'],
            'source_content_sha256' => str_repeat('a', 64),
            'record_id' => '22222222-2222-4222-8222-222222222222',
            'record_version' => 3,
            'record_status' => 'active',
            'field_id' => 'tobacco.status',
            'review_id' => '33333333-3333-4333-8333-333333333333',
            'review_decision' => 'corrected',
            'reviewed_value' => 'Never',
            'document_type' => 'Intake response',
            'page' => [
                'page_number' => 2,
                'media_type' => 'image/png',
                'bytes' => 'synthetic rendered page',
                'rendered_page_sha256' => hash('sha256', 'synthetic rendered page'),
                'ocr_text_sha256' => hash('sha256', 'Current'),
            ],
            'evidence' => [
                'evidence_id' => '44444444-4444-4444-8444-444444444444',
                'page_number' => 2,
                'box' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.08],
                'printed_quote' => 'Current',
            ],
        ];
    }
}

final class SourceReviewFixedAuthorization implements SourceReviewAuthorizationPort
{
    public function authorize(string $conversationId, string $turnId, string $correlationId): SourceReviewContext
    {
        return new SourceReviewContext('default', 7, 42, $conversationId, $turnId);
    }
}

final class SourceReviewCountingAuthorization implements SourceReviewAuthorizationPort
{
    public int $calls = 0;

    public function __construct(private readonly ?int $allowCalls = null)
    {
    }

    public function authorize(string $conversationId, string $turnId, string $correlationId): SourceReviewContext
    {
        $this->calls++;
        if ($this->allowCalls !== null && $this->calls > $this->allowCalls) {
            throw new \OpenEMR\Modules\Copilot\SourceReview\SourceReviewException(
                'forbidden',
                false,
                'Authorization was lost.',
                403
            );
        }
        return new SourceReviewContext('default', 7, 42, $conversationId, $turnId);
    }
}

final class SourceReviewFixedCitationAuthority implements CitationAuthorityPort
{
    /** @param array<string, mixed> $citation */
    public function __construct(private readonly array $citation)
    {
    }

    public function find(SourceReviewContext $context, string $citationId): ?array
    {
        return $citationId === $this->citation['citation_id'] ? $this->citation : null;
    }
}

final class SourceReviewFixedViewAuthority implements SourceViewAuthorityPort
{
    /** @param array<string, mixed>|null $view */
    public function __construct(private readonly ?array $view)
    {
    }

    public function resolve(SourceReviewContext $context, array $citation): ?array
    {
        return $this->view;
    }
}
