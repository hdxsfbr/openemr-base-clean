<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

require_once dirname(__DIR__) . '/src/Document/DocumentPorts.php';
require_once dirname(__DIR__) . '/src/Document/DocumentLifecycleException.php';
require_once dirname(__DIR__) . '/src/Document/Review/ReviewPorts.php';
require_once dirname(__DIR__) . '/src/Document/Review/ReviewPromotionWorkflow.php';

use DateTimeImmutable;
use OpenEMR\Modules\Copilot\Document\AuditPort;
use OpenEMR\Modules\Copilot\Document\AuthorizationPort;
use OpenEMR\Modules\Copilot\Document\ClockPort;
use OpenEMR\Modules\Copilot\Document\DocumentContext;
use OpenEMR\Modules\Copilot\Document\Review\ReviewPromotionWorkflow;
use OpenEMR\Modules\Copilot\Document\Review\ReviewRepositoryPort;
use Opis\JsonSchema\Validator;
use PHPUnit\Framework\TestCase;

final class ReviewPromotionTest extends TestCase
{
    public function testPhysicianApprovalCreatesAnAppendOnlyReviewBoundToExactEvidence(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $workflow = $this->workflow($repository);

        $review = $workflow->review([
            'idempotency_key' => '0a22fe14-f6a1-43cf-a96f-3f8b1b792a41',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'field_id' => 'analyte.potassium.value',
            'action' => 'approve',
        ], 'corr-review-0001');

        self::assertSame('approved', $review['decision']);
        self::assertSame(['33333333-3333-4333-8333-333333333333'], $review['evidence_ids']);
        self::assertSame(['kind' => 'quantity', 'value' => '4.2'], $review['proposed_value']);
        self::assertSame($review['proposed_value'], $review['final_value']);
        self::assertSame('physician-demo', $review['reviewed_by']);
        self::assertSame('created', $review['idempotency_outcome']);
        self::assertCount(1, $repository->reviews);
        self::assertCount(1, $repository->outbox);
    }

    public function testReviewRetryReturnsTheSamePublicReviewWithoutAnotherWrite(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $workflow = $this->workflow($repository);
        $command = [
            'idempotency_key' => '7df8f9a4-3288-4b6f-8514-6e106918f71e',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'field_id' => 'analyte.potassium.value',
            'action' => 'approve',
        ];

        $created = $workflow->review($command, 'corr-review-retry-1');
        $replayed = $workflow->review($command, 'corr-review-retry-2');

        self::assertSame($created['review_id'], $replayed['review_id']);
        self::assertSame('replayed', $replayed['idempotency_outcome']);
        self::assertSame([], array_intersect(['site_id', 'pid'], array_keys($replayed)));
        self::assertCount(1, $repository->reviews);
        self::assertCount(1, $repository->outbox);
    }

    public function testCorrectionIsAppendOnlyAndAnIdempotencyKeyCannotChangeItsValue(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $workflow = $this->workflow($repository);
        $workflow->review([
            'idempotency_key' => '1ea56856-46cb-47d2-86b0-0046832a82bd',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'field_id' => 'analyte.potassium.value',
            'action' => 'approve',
        ], 'corr-review-correct-1');
        $command = [
            'idempotency_key' => 'ad3386d5-6378-4d2e-bc31-90b345cd89ba',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'field_id' => 'analyte.potassium.value',
            'action' => 'correct',
            'corrected_value' => ['kind' => 'measurement', 'value' => ['kind' => 'quantity', 'value' => '4.4']],
            'reason' => 'Verified against the synthetic source region.',
        ];

        $corrected = $workflow->review($command, 'corr-review-correct-2');
        self::assertSame('corrected', $corrected['decision']);
        self::assertSame(['kind' => 'quantity', 'value' => '4.4'], $corrected['final_value']);
        self::assertNotNull($corrected['supersedes_review_id']);
        self::assertCount(2, $repository->reviews);

        $this->expectExceptionObject(new \OpenEMR\Modules\Copilot\Document\DocumentLifecycleException(
            'conflict',
            false,
            'The idempotency key was used for another review.',
            409
        ));
        $workflow->review(array_replace($command, [
            'corrected_value' => ['kind' => 'measurement', 'value' => ['kind' => 'quantity', 'value' => '9.9']],
        ]), 'corr-review-correct-3');
    }

    public function testCompleteCurrentLabReviewsPromoteOnceWithDeterministicProvenance(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $workflow = $this->workflow($repository);
        $reviewIds = [];
        foreach ([
            ['collection_date', '41891c15-c766-47d1-8b90-159af346be47'],
            ['analyte.potassium.test_name', 'd5947ed8-bd51-414b-840b-40b400b7a766'],
            ['analyte.potassium.value', '325aee0a-814c-436e-8724-b62226a893d6'],
        ] as [$fieldId, $key]) {
            $reviewIds[] = $workflow->review([
                'idempotency_key' => $key,
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'field_id' => $fieldId,
                'action' => 'approve',
            ], 'corr-promote-review')['review_id'];
        }

        $created = $workflow->promote([
            'idempotency_key' => 'f8af939c-86b4-4f30-87ac-1c7f678efb23',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'source_content_sha256' => str_repeat('a', 64),
            'target_type' => 'lab_report',
            'review_ids' => array_reverse($reviewIds),
        ], 'corr-promote-0001');
        $replayed = $workflow->promote([
            'idempotency_key' => 'f8af939c-86b4-4f30-87ac-1c7f678efb23',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'source_content_sha256' => str_repeat('a', 64),
            'target_type' => 'lab_report',
            'review_ids' => $reviewIds,
        ], 'corr-promote-0002');

        self::assertSame('created', $created['outcome']);
        self::assertSame('replayed', $replayed['outcome']);
        self::assertSame($created['target_record_id'], $replayed['target_record_id']);
        self::assertCount(1, $repository->records);
        $record = array_values($repository->records)[0];
        self::assertSame('active', $record['record_json']['status']);
        self::assertSame('2026-09-20', $record['record_json']['collection_date']['value']);
        self::assertSame(['kind' => 'quantity', 'value' => '4.2'], $record['record_json']['analytes'][0]['value']['value']);
        self::assertSame($created['review_set_sha256'], $record['record_json']['provenance']['review_set_sha256']);
        self::assertMatchesRegularExpression('/^[0-9a-f]{64}$/', $record['deterministic_promotion_key']);
        $this->assertRecordMatchesSchema($record['record_json'], 'reviewed_lab_report.schema.json');
        self::assertCount(4, $repository->outbox);
    }

    public function testReviewedIntakePromotesEveryCollectionWithoutWritingNativeLists(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedIntakeExtraction();
        $workflow = $this->workflow($repository);
        $reviewIds = [];
        $fieldIds = array_map(static fn(array $fact): string => $fact['field_id'], array_values($repository->facts));
        foreach ($fieldIds as $index => $fieldId) {
            $reviewIds[] = $workflow->review([
                'idempotency_key' => sprintf('00000000-0000-4000-8000-%012d', $index + 1),
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'field_id' => $fieldId,
                'action' => 'approve',
            ], 'corr-intake-review')['review_id'];
        }

        $response = $workflow->promote([
            'idempotency_key' => 'b9e3aa8e-793b-4643-a2ec-eeab75870179',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'source_content_sha256' => str_repeat('b', 64),
            'target_type' => 'intake_response',
            'review_ids' => $reviewIds,
        ], 'corr-intake-promote');

        $record = array_values($repository->records)[0]['record_json'];
        self::assertSame('intake_response', $response['target_type']);
        self::assertSame('QuestionnaireResponse', $record['resource_type']);
        self::assertSame('Patient/patient-demo-42', $record['subject']);
        self::assertSame([
            'demographics-given-name',
            'demographics-date-of-birth',
            'chief-concern',
            'medication-name',
            'allergy-substance',
            'family-history-relationship',
            'family-history-condition',
            'family-history-onset-age-years',
        ], array_column($record['items'], 'link_id'));
        self::assertSame('integer', $record['items'][7]['answer']['kind']);
        self::assertArrayNotHasKey('native_resource_id', $record);
        $this->assertRecordMatchesSchema($record, 'reviewed_intake_response.schema.json');
    }

    public function testAmendAndWithdrawCreateImmutableSuccessorVersionsWithReasons(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $workflow = $this->workflow($repository);
        $reviewIds = [];
        foreach (['collection_date', 'analyte.potassium.test_name', 'analyte.potassium.value'] as $index => $fieldId) {
            $reviewIds[] = $workflow->review([
                'idempotency_key' => sprintf('10000000-0000-4000-8000-%012d', $index + 1),
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'field_id' => $fieldId,
                'action' => 'approve',
            ], 'corr-revise-review')['review_id'];
        }
        $promotion = $workflow->promote([
            'idempotency_key' => 'c1be16f0-f9dd-4496-839b-2ef319a229dc',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'source_content_sha256' => str_repeat('a', 64),
            'target_type' => 'lab_report',
            'review_ids' => $reviewIds,
        ], 'corr-revise-promote');
        $corrected = $workflow->review([
            'idempotency_key' => '697c0fd1-1954-4655-86dd-00fb27ce0c63',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'field_id' => 'analyte.potassium.value',
            'action' => 'correct',
            'corrected_value' => ['kind' => 'measurement', 'value' => ['kind' => 'quantity', 'value' => '4.5']],
            'reason' => 'Synthetic source rechecked.',
        ], 'corr-revise-correct');
        $currentReviewIds = [$reviewIds[0], $reviewIds[1], $corrected['review_id']];

        $amended = $workflow->revise([
            'idempotency_key' => '8e245c3c-07df-47ab-b9ed-40657cfa961b',
            'record_id' => $promotion['target_record_id'],
            'expected_record_version' => 1,
            'action' => 'amend',
            'review_ids' => $currentReviewIds,
            'reason' => 'Physician corrected the synthetic result.',
        ], 'corr-revise-amend');
        $withdrawn = $workflow->revise([
            'idempotency_key' => 'b17edc16-d83a-4fea-9974-e7ee7620b1b8',
            'record_id' => $promotion['target_record_id'],
            'expected_record_version' => 2,
            'action' => 'withdraw',
            'reason' => 'Synthetic source was superseded.',
        ], 'corr-revise-withdraw');

        self::assertSame(['amended', 2], [$amended['status'], $amended['record_version']]);
        self::assertSame(['withdrawn', 3], [$withdrawn['status'], $withdrawn['record_version']]);
        self::assertCount(3, $repository->records);
        $versions = array_values($repository->records);
        self::assertSame('active', $versions[0]['record_json']['status']);
        self::assertSame(['kind' => 'quantity', 'value' => '4.5'], $versions[1]['record_json']['analytes'][0]['value']['value']);
        self::assertSame($versions[1]['record_json']['analytes'], $versions[2]['record_json']['analytes']);
        self::assertSame('withdraw', $versions[2]['record_json']['provenance']['action']);
        self::assertSame('Synthetic source was superseded.', $versions[2]['record_json']['lifecycle_reason']);
    }

    public function testOutboxFailureRollsBackTheReviewAndReturnsSafeUnavailable(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $repository->failOutbox = true;
        $workflow = $this->workflow($repository);

        try {
            $workflow->review([
                'idempotency_key' => 'ca88ca46-798a-4822-bac5-1846185bbf32',
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'field_id' => 'analyte.potassium.value',
                'action' => 'approve',
            ], 'corr-review-rollback');
            self::fail('A review cannot commit without its outbox event.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('unavailable', $exception->errorCode);
            self::assertTrue($exception->retryable);
            self::assertStringNotContainsString('synthetic', strtolower($exception->getMessage()));
        }
        self::assertCount(0, $repository->reviews);
        self::assertCount(0, $repository->outbox);
    }

    public function testCorrectedValueObjectKeyOrderDoesNotChangeItsContract(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $review = $this->workflow($repository)->review([
            'idempotency_key' => '60253090-9003-41d9-8b3b-c0be2229e8f6',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'field_id' => 'analyte.potassium.value',
            'action' => 'correct',
            'corrected_value' => ['value' => ['value' => '4.6', 'kind' => 'quantity'], 'kind' => 'measurement'],
            'reason' => 'Synthetic correction with reordered JSON keys.',
        ], 'corr-review-key-order');

        self::assertSame(['value' => '4.6', 'kind' => 'quantity'], $review['final_value']);
    }

    public function testPerfectExtractionConfidenceCannotReplaceCompletePhysicianReview(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $repository->facts[InMemoryReviewRepository::EXTRACTION_ID . '|analyte.potassium.value']['confidence'] = 1.0;
        $workflow = $this->workflow($repository);
        $review = $workflow->review([
            'idempotency_key' => 'd5a6bcfd-5e9b-4a6d-a78b-c91a1d393f5b',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'field_id' => 'analyte.potassium.value',
            'action' => 'approve',
        ], 'corr-confidence-review');

        try {
            $workflow->promote([
                'idempotency_key' => '8c31779c-7a70-48d3-b7b6-9ac0f64c34fa',
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'source_content_sha256' => str_repeat('a', 64),
                'target_type' => 'lab_report',
                'review_ids' => [$review['review_id']],
            ], 'corr-confidence-promote');
            self::fail('Confidence must never auto-approve unreviewed fields.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('review_required', $exception->errorCode);
        }
        self::assertCount(0, $repository->records);
        self::assertCount(1, $repository->outbox);
    }

    public function testRejectedFieldPreventsPromotionEvenWhenEveryFieldWasReviewed(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $workflow = $this->workflow($repository);
        $reviewIds = [];
        foreach (['collection_date', 'analyte.potassium.test_name'] as $index => $fieldId) {
            $reviewIds[] = $workflow->review([
                'idempotency_key' => sprintf('20000000-0000-4000-8000-%012d', $index + 1),
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'field_id' => $fieldId,
                'action' => 'approve',
            ], 'corr-rejected-review')['review_id'];
        }
        $rejected = $workflow->review([
            'idempotency_key' => '20000000-0000-4000-8000-000000000003',
            'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
            'expected_extraction_version' => 1,
            'field_id' => 'analyte.potassium.value',
            'action' => 'reject',
            'reason' => 'The synthetic value does not match its source region.',
        ], 'corr-rejected-review');
        $reviewIds[] = $rejected['review_id'];

        self::assertSame('rejected', $rejected['decision']);
        self::assertNull($rejected['final_value']);
        try {
            $workflow->promote([
                'idempotency_key' => '20000000-0000-4000-8000-000000000004',
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'source_content_sha256' => str_repeat('a', 64),
                'target_type' => 'lab_report',
                'review_ids' => $reviewIds,
            ], 'corr-rejected-promote');
            self::fail('A rejected proposed value must not be promoted.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('review_required', $exception->errorCode);
        }
        self::assertCount(0, $repository->records);
    }

    public function testStaleSourcePatientSwitchWrongTypeAndUnknownFieldsFailClosed(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $workflow = $this->workflow($repository);

        foreach ([
            [[
                'idempotency_key' => '26b5887f-890d-4b31-b7fd-f0a3f3f6aedc',
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 2,
                'field_id' => 'analyte.potassium.value',
                'action' => 'approve',
            ], 'stale_extraction'],
            [[
                'idempotency_key' => 'b79545f0-25cc-4944-b59f-6cdd4fb8d25d',
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'field_id' => 'analyte.potassium.value',
                'action' => 'correct',
                'corrected_value' => ['kind' => 'choice', 'value' => 'high'],
                'reason' => 'Wrong typed synthetic correction.',
            ], 'invalid_contract'],
            [[
                'idempotency_key' => '594c7f5e-2496-4b55-ab6f-c67b32b472e3',
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'field_id' => 'analyte.potassium.value',
                'action' => 'approve',
                'patient_id' => 99,
            ], 'invalid_contract'],
        ] as [$command, $code]) {
            try {
                $workflow->review($command, 'corr-negative-review');
                self::fail('The unsafe review command must fail closed.');
            } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
                self::assertSame($code, $exception->errorCode);
            }
        }

        $switched = new ReviewPromotionWorkflow(
            new ReviewFixedAuthorization(43),
            $repository,
            new ReviewRecordingAudit(),
            new ReviewFixedClock()
        );
        try {
            $switched->review([
                'idempotency_key' => 'dd459789-d8e4-4885-9031-50b4ff301207',
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'field_id' => 'analyte.potassium.value',
                'action' => 'approve',
            ], 'corr-patient-switch');
            self::fail('A changed active patient must fail closed.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('patient_context_changed', $exception->errorCode);
        }
        self::assertCount(0, $repository->reviews);
        self::assertCount(0, $repository->outbox);
    }

    public function testUnavailableMachineStateCannotBeAcceptedEvenWithAValue(): void
    {
        $repository = new InMemoryReviewRepository();
        $repository->seedLabExtraction();
        $repository->facts[InMemoryReviewRepository::EXTRACTION_ID . '|analyte.potassium.value']['state'] = 'unavailable';

        try {
            $this->workflow($repository)->review([
                'idempotency_key' => 'ae768ffe-03d5-414d-b184-132f8a05c5fd',
                'extraction_id' => InMemoryReviewRepository::EXTRACTION_ID,
                'expected_extraction_version' => 1,
                'field_id' => 'analyte.potassium.value',
                'action' => 'approve',
            ], 'corr-unavailable-field');
            self::fail('An unavailable machine result cannot become a reviewed fact.');
        } catch (\OpenEMR\Modules\Copilot\Document\DocumentLifecycleException $exception) {
            self::assertSame('review_required', $exception->errorCode);
        }
        self::assertCount(0, $repository->reviews);
    }

    private function workflow(InMemoryReviewRepository $repository): ReviewPromotionWorkflow
    {
        return new ReviewPromotionWorkflow(
            new ReviewFixedAuthorization(),
            $repository,
            new ReviewRecordingAudit(),
            new ReviewFixedClock()
        );
    }

    /** @param array<string, mixed> $record */
    private function assertRecordMatchesSchema(array $record, string $schemaName): void
    {
        $root = dirname(__DIR__, 5);
        $schema = json_decode((string) file_get_contents($root . '/contracts/schema/' . $schemaName));
        $payload = json_decode(json_encode($record, JSON_THROW_ON_ERROR));
        $validator = new Validator();
        $result = $validator->validate($payload, $schema);
        self::assertTrue($result->isValid(), 'Generated reviewed record did not match the exported schema.');
    }
}

final class InMemoryReviewRepository implements ReviewRepositoryPort
{
    public const EXTRACTION_ID = '11111111-1111-4111-8111-111111111111';
    public const SOURCE_ID = '22222222-2222-4222-8222-222222222222';

    /** @var array<string, array<string, mixed>> */
    public array $extractions = [];
    /** @var array<string, array<string, mixed>> */
    public array $facts = [];
    /** @var array<string, array<string, mixed>> */
    public array $reviews = [];
    /** @var array<string, array<string, mixed>> */
    public array $records = [];
    /** @var list<array<string, mixed>> */
    public array $outbox = [];
    public bool $failOutbox = false;

    public function seedLabExtraction(): void
    {
        $this->extractions[self::EXTRACTION_ID] = [
            'extraction_id' => self::EXTRACTION_ID,
            'extraction_version' => 1,
            'source_document_id' => self::SOURCE_ID,
            'source_content_sha256' => str_repeat('a', 64),
            'site_id' => 'default',
            'pid' => 42,
            'schema_name' => 'lab-report',
            'schema_version' => '1.0.0',
            'state' => 'schema_valid',
            'source' => [
                'source_document_id' => self::SOURCE_ID,
                'openemr_document_id' => '9001',
                'upload_intent_id' => '55555555-5555-4555-8555-555555555555',
                'document_type' => 'lab_report',
                'content_sha256' => str_repeat('a', 64),
                'byte_count' => 1000,
                'mime_type' => 'application/pdf',
                'page_count' => 1,
            ],
            'payload' => [
                'collection_date' => ['field_id' => 'collection_date', 'value' => '2026-09-20'],
                'analytes' => [[
                    'analyte_id' => '44444444-4444-4444-8444-444444444444',
                    'test_name' => ['field_id' => 'analyte.potassium.test_name', 'value' => 'Potassium'],
                    'value' => ['field_id' => 'analyte.potassium.value', 'value' => ['kind' => 'quantity', 'value' => '4.2']],
                ]],
            ],
        ];
        $this->facts[self::EXTRACTION_ID . '|collection_date'] = [
            'extraction_id' => self::EXTRACTION_ID,
            'field_id' => 'collection_date',
            'typed_value' => '2026-09-20',
            'evidence_ids' => ['66666666-6666-4666-8666-666666666666'],
            'state' => 'schema_valid',
        ];
        $this->facts[self::EXTRACTION_ID . '|analyte.potassium.test_name'] = [
            'extraction_id' => self::EXTRACTION_ID,
            'field_id' => 'analyte.potassium.test_name',
            'typed_value' => 'Potassium',
            'evidence_ids' => ['77777777-7777-4777-8777-777777777777'],
            'state' => 'schema_valid',
        ];
        $this->facts[self::EXTRACTION_ID . '|analyte.potassium.value'] = [
            'extraction_id' => self::EXTRACTION_ID,
            'field_id' => 'analyte.potassium.value',
            'typed_value' => ['kind' => 'quantity', 'value' => '4.2'],
            'evidence_ids' => ['33333333-3333-4333-8333-333333333333'],
            'state' => 'schema_valid',
        ];
    }

    public function seedIntakeExtraction(): void
    {
        $medicationId = '88888888-8888-4888-8888-888888888888';
        $allergyId = '99999999-9999-4999-8999-999999999999';
        $familyId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        $field = static fn(string $id, mixed $value): array => ['field_id' => $id, 'value' => $value];
        $payload = [
            'demographics' => [
                'given_name' => $field('demographics.given_name', 'Demo'),
                'date_of_birth' => $field('demographics.date_of_birth', '1980-01-02'),
            ],
            'chief_concern' => $field('chief_concern', 'Synthetic follow-up'),
            'medications' => [[
                'entry_id' => $medicationId,
                'name' => $field('medication.demo.name', 'Synthetic medicine'),
            ]],
            'allergies' => [[
                'entry_id' => $allergyId,
                'substance' => $field('allergy.demo.substance', 'Synthetic allergen'),
            ]],
            'family_history' => [[
                'entry_id' => $familyId,
                'relationship' => $field('family_history.demo.relationship', 'Parent'),
                'condition' => $field('family_history.demo.condition', 'Synthetic condition'),
                'onset_age_years' => $field('family_history.demo.onset_age_years', 55),
            ]],
        ];
        $this->extractions[self::EXTRACTION_ID] = [
            'extraction_id' => self::EXTRACTION_ID,
            'extraction_version' => 1,
            'source_document_id' => self::SOURCE_ID,
            'source_content_sha256' => str_repeat('b', 64),
            'site_id' => 'default',
            'pid' => 42,
            'schema_name' => 'intake-form',
            'schema_version' => '1.0.0',
            'state' => 'schema_valid',
            'source' => [
                'source_document_id' => self::SOURCE_ID,
                'openemr_document_id' => '9002',
                'upload_intent_id' => 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
                'document_type' => 'intake_form',
                'content_sha256' => str_repeat('b', 64),
                'byte_count' => 1200,
                'mime_type' => 'application/pdf',
                'page_count' => 1,
            ],
            'payload' => $payload,
        ];
        $this->facts = [];
        $evidence = ['cccccccc-cccc-4ccc-8ccc-cccccccccccc'];
        $walk = function (mixed $value) use (&$walk, $evidence): void {
            if (!is_array($value)) {
                return;
            }
            if (isset($value['field_id']) && array_key_exists('value', $value)) {
                $this->facts[self::EXTRACTION_ID . '|' . $value['field_id']] = [
                    'extraction_id' => self::EXTRACTION_ID,
                    'field_id' => $value['field_id'],
                    'typed_value' => $value['value'],
                    'evidence_ids' => $evidence,
                    'state' => 'schema_valid',
                ];
                return;
            }
            foreach ($value as $child) {
                $walk($child);
            }
        };
        $walk($payload);
    }

    public function transaction(callable $callback): mixed
    {
        $reviews = $this->reviews;
        $records = $this->records;
        $outbox = $this->outbox;
        try {
            return $callback();
        } catch (\Throwable $exception) {
            $this->reviews = $reviews;
            $this->records = $records;
            $this->outbox = $outbox;
            throw $exception;
        }
    }

    public function findReviewByIdempotencyKey(string $key): ?array
    {
        foreach ($this->reviews as $review) {
            if ($review['idempotency_key'] === $key) {
                return $review;
            }
        }
        return null;
    }

    public function findExtraction(string $extractionId): ?array
    {
        return $this->extractions[$extractionId] ?? null;
    }

    public function findProposedFact(string $extractionId, string $fieldId): ?array
    {
        return $this->facts[$extractionId . '|' . $fieldId] ?? null;
    }

    public function findCurrentReview(string $extractionId, string $fieldId): ?array
    {
        $current = null;
        foreach ($this->reviews as $review) {
            if ($review['extraction_id'] === $extractionId && $review['field_id'] === $fieldId) {
                $current = $review;
            }
        }
        return $current;
    }

    public function insertReview(array $review): void
    {
        $this->reviews[$review['review_id']] = $review;
    }

    public function appendOutbox(array $event): void
    {
        if ($this->failOutbox) {
            throw new \RuntimeException('synthetic outbox outage with private value');
        }
        $this->outbox[] = $event;
    }

    public function findRecordByActionIdempotencyKey(string $key): ?array
    {
        foreach ($this->records as $record) {
            if ($record['action_idempotency_key'] === $key) {
                return $record;
            }
        }
        return null;
    }

    public function findRecordByDeterministicKey(string $key): ?array
    {
        foreach ($this->records as $record) {
            if ($record['deterministic_promotion_key'] === $key) {
                return $record;
            }
        }
        return null;
    }

    public function findReviewsByIds(array $reviewIds): array
    {
        return array_values(array_intersect_key($this->reviews, array_flip($reviewIds)));
    }

    public function findCurrentReviewsForExtraction(string $extractionId): array
    {
        $superseded = [];
        foreach ($this->reviews as $review) {
            if ($review['supersedes_review_id'] !== null) {
                $superseded[$review['supersedes_review_id']] = true;
            }
        }
        return array_values(array_filter($this->reviews, static fn(array $review): bool =>
            $review['extraction_id'] === $extractionId && !isset($superseded[$review['review_id']])
        ));
    }

    public function insertRecord(array $record): void
    {
        $this->records[$record['record_id'] . '|' . $record['record_version']] = $record;
    }

    public function findLatestRecord(string $recordId): ?array
    {
        $matches = array_values(array_filter($this->records, static fn(array $record): bool => $record['record_id'] === $recordId));
        usort($matches, static fn(array $left, array $right): int => $right['record_version'] <=> $left['record_version']);
        return $matches[0] ?? null;
    }
}

final class ReviewFixedAuthorization implements AuthorizationPort
{
    public function __construct(private readonly int $pid = 42)
    {
    }

    public function authorize(string $operation, string $correlationId): DocumentContext
    {
        return new DocumentContext('default', 7, 'physician-demo', 'Default', $this->pid, 'patient-demo-' . $this->pid);
    }
}

final class ReviewRecordingAudit implements AuditPort
{
    /** @var list<array<string, mixed>> */
    public array $events = [];

    public function record(DocumentContext $context, string $operation, bool $success, string $reason, array $identifiers): void
    {
        $this->events[] = compact('operation', 'success', 'reason', 'identifiers');
    }
}

final class ReviewFixedClock implements ClockPort
{
    public function now(): DateTimeImmutable
    {
        return new DateTimeImmutable('2026-09-21T12:00:00Z');
    }
}
