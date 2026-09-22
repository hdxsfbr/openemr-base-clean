<?php

/**
 * Physician-only review and reviewed-record lifecycle boundary.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Review;

use OpenEMR\Modules\Copilot\Document\AuditPort;
use OpenEMR\Modules\Copilot\Document\AuthorizationPort;
use OpenEMR\Modules\Copilot\Document\ClockPort;
use OpenEMR\Modules\Copilot\Document\DocumentContext;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleException;

final class ReviewPromotionWorkflow
{
    public function __construct(
        private readonly AuthorizationPort $authorization,
        private readonly ReviewRepositoryPort $repository,
        private readonly AuditPort $audit,
        private readonly ClockPort $clock,
    ) {
    }

    /** @param array<string, mixed> $command @return array<string, mixed> */
    public function review(array $command, string $correlationId): array
    {
        $context = $this->authorization->authorize('review', $correlationId);
        $this->validateReviewCommand($command);

        return $this->atomic(function () use ($command, $correlationId, $context): array {
            $existing = $this->repository->findReviewByIdempotencyKey($command['idempotency_key']);
            if ($existing !== null) {
                $this->assertReviewReplayMatches($existing, $command);
                $this->assertContext($context, $existing);
                $existing['idempotency_outcome'] = 'replayed';
                return $this->publicReview($existing);
            }

            $extraction = $this->repository->findExtraction($command['extraction_id']);
            if ($extraction === null) {
                throw $this->failure('not_found', 'The extraction was not found.', 404);
            }
            $existing = $this->repository->findReviewByIdempotencyKey($command['idempotency_key']);
            if ($existing !== null) {
                $this->assertReviewReplayMatches($existing, $command);
                $this->assertContext($context, $existing);
                $existing['idempotency_outcome'] = 'replayed';
                return $this->publicReview($existing);
            }
            $this->assertContext($context, $extraction);
            if ((int) $extraction['extraction_version'] !== $command['expected_extraction_version']) {
                throw $this->failure('stale_extraction', 'The extraction version has changed.', 409);
            }

            $fact = $this->repository->findProposedFact($command['extraction_id'], $command['field_id']);
            if ($fact === null) {
                throw $this->failure('not_found', 'The proposed field was not found.', 404);
            }
            $this->validateDecisionAgainstFact($command, $fact);
            $prior = $this->repository->findCurrentReview($command['extraction_id'], $command['field_id']);
            $now = $this->clock->now();
            $review = [
                'review_id' => self::uuid(),
                'idempotency_key' => $command['idempotency_key'],
                'extraction_id' => $command['extraction_id'],
                'extraction_version' => $command['expected_extraction_version'],
                'field_id' => $command['field_id'],
                'proposed_value' => $fact['typed_value'],
                'final_value' => $this->finalValue($command, $fact),
                'evidence_ids' => array_values($fact['evidence_ids']),
                'decision' => $command['action'] === 'approve' ? 'approved' : ($command['action'] === 'correct' ? 'corrected' : 'rejected'),
                'reason' => $command['reason'] ?? null,
                'reviewed_by' => $context->username,
                'reviewed_at' => $now->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d\TH:i:s\Z'),
                'supersedes_review_id' => $prior['review_id'] ?? null,
                'idempotency_outcome' => 'created',
                // Server-only context used by persistence and replay checks.
                'site_id' => $context->siteId,
                'pid' => $context->pid,
            ];
            $this->repository->insertReview($review);
            $this->repository->appendOutbox([
                'event_id' => self::uuid(),
                'event_type' => 'document_fact_reviewed',
                'aggregate_id' => $review['review_id'],
                'site_id' => $context->siteId,
                'pid' => $context->pid,
                'user_id' => $context->userId,
                'correlation_id' => $correlationId,
                'payload' => [
                    'review_id' => $review['review_id'],
                    'extraction_id' => $review['extraction_id'],
                    'extraction_version' => $review['extraction_version'],
                    'field_id' => $review['field_id'],
                    'decision' => $review['decision'],
                ],
                'created_at' => $now->format('Y-m-d H:i:s'),
            ]);
            $this->audit->record($context, 'review', true, 'created', [
                'correlation_id' => $correlationId,
                'review_id' => $review['review_id'],
                'extraction_id' => $review['extraction_id'],
                'field_id' => $review['field_id'],
            ]);

            return $this->publicReview($review);
        });
    }

    /** @param array<string, mixed> $command @return array<string, mixed> */
    public function promote(array $command, string $correlationId): array
    {
        $context = $this->authorization->authorize('promotion', $correlationId);
        $this->validatePromoteCommand($command);

        return $this->atomic(function () use ($command, $correlationId, $context): array {
            $existing = $this->repository->findRecordByActionIdempotencyKey($command['idempotency_key']);
            if ($existing !== null) {
                $this->assertPromotionReplayMatches($existing, $command, $context);
                return $this->promotionResponse($existing, 'replayed');
            }

            $extraction = $this->repository->findExtraction($command['extraction_id']);
            if ($extraction === null) {
                throw $this->failure('not_found', 'The extraction was not found.', 404);
            }
            $existing = $this->repository->findRecordByActionIdempotencyKey($command['idempotency_key']);
            if ($existing !== null) {
                $this->assertPromotionReplayMatches($existing, $command, $context);
                return $this->promotionResponse($existing, 'replayed');
            }
            $this->assertContext($context, $extraction);
            if ((int) $extraction['extraction_version'] !== $command['expected_extraction_version']) {
                throw $this->failure('stale_extraction', 'The extraction version has changed.', 409);
            }
            if (!hash_equals((string) $extraction['source_content_sha256'], $command['source_content_sha256'])) {
                throw $this->failure('source_mismatch', 'The source content has changed.', 409);
            }
            $expectedTarget = $extraction['schema_name'] === 'lab-report' ? 'lab_report' : 'intake_response';
            if ($expectedTarget !== $command['target_type']) {
                throw $this->failure('source_mismatch', 'The target does not match the extraction.', 409);
            }

            $reviews = $this->repository->findReviewsByIds($command['review_ids']);
            $current = $this->repository->findCurrentReviewsForExtraction($command['extraction_id']);
            $this->validatePromotionReviews($command, $extraction, $reviews, $current);
            usort($reviews, static fn(array $left, array $right): int => strcmp($left['review_id'], $right['review_id']));
            $reviewIds = array_column($reviews, 'review_id');
            $reviewSetHash = hash('sha256', implode("\n", $reviewIds));
            $deterministicKey = hash('sha256', implode('|', [
                $context->siteId,
                (string) $context->pid,
                $extraction['source_document_id'],
                $extraction['source_content_sha256'],
                (string) $extraction['extraction_version'],
                $command['target_type'],
                $reviewSetHash,
            ]));
            $sameTarget = $this->repository->findRecordByDeterministicKey($deterministicKey);
            if ($sameTarget !== null) {
                return $this->promotionResponse($sameTarget, 'replayed');
            }

            $now = $this->clock->now()->setTimezone(new \DateTimeZone('UTC'));
            $recordId = self::uuid();
            $promotionId = self::uuid();
            $byField = [];
            foreach ($reviews as $review) {
                $byField[$review['field_id']] = $review;
            }
            $provenance = [
                'action_id' => $promotionId,
                'action' => 'promote',
                'action_idempotency_key' => $command['idempotency_key'],
                'review_set_sha256' => $reviewSetHash,
                'source_content_sha256' => $extraction['source_content_sha256'],
                'extraction_id' => $extraction['extraction_id'],
                'extraction_version' => (int) $extraction['extraction_version'],
                'acted_by' => $context->username,
                'acted_at' => $now->format('Y-m-d\TH:i:s\Z'),
                'correlation_id' => $correlationId,
            ];
            $recordJson = $this->buildRecord($recordId, $extraction, $byField, $context, $now, $provenance);
            $record = [
                'record_id' => $recordId,
                'record_version' => 1,
                'target_type' => $command['target_type'],
                'status' => $command['target_type'] === 'lab_report' ? 'active' : 'completed',
                'action_id' => $promotionId,
                'action_idempotency_key' => $command['idempotency_key'],
                'deterministic_promotion_key' => $deterministicKey,
                'review_set_sha256' => $reviewSetHash,
                'source_content_sha256' => $extraction['source_content_sha256'],
                'source_document_id' => $extraction['source_document_id'],
                'extraction_id' => $extraction['extraction_id'],
                'extraction_version' => (int) $extraction['extraction_version'],
                'site_id' => $context->siteId,
                'pid' => $context->pid,
                'record_json' => $recordJson,
                'created_at' => $now->format('Y-m-d H:i:s'),
            ];
            $this->repository->insertRecord($record);
            $this->repository->appendOutbox($this->recordEvent(
                'reviewed_document_promoted',
                $promotionId,
                $recordId,
                $record,
                $context,
                $correlationId,
                $now
            ));
            $this->audit->record($context, 'promotion', true, 'created', [
                'correlation_id' => $correlationId,
                'action_id' => $promotionId,
                'record_id' => $recordId,
                'record_version' => 1,
                'extraction_id' => $extraction['extraction_id'],
            ]);
            return $this->promotionResponse($record, 'created');
        });
    }

    /** @param array<string, mixed> $command @return array<string, mixed> */
    public function revise(array $command, string $correlationId): array
    {
        $this->validateReviseCommand($command);
        $operation = $command['action'] === 'amend' ? 'amendment' : 'withdrawal';
        $context = $this->authorization->authorize($operation, $correlationId);

        return $this->atomic(function () use ($command, $correlationId, $context, $operation): array {
            $existing = $this->repository->findRecordByActionIdempotencyKey($command['idempotency_key']);
            if ($existing !== null) {
                $this->assertRevisionReplayMatches($existing, $command, $context);
                return $this->revisionResponse($existing, 'replayed');
            }
            $prior = $this->repository->findLatestRecord($command['record_id']);
            if ($prior === null) {
                throw $this->failure('not_found', 'The reviewed record was not found.', 404);
            }
            $existing = $this->repository->findRecordByActionIdempotencyKey($command['idempotency_key']);
            if ($existing !== null) {
                $this->assertRevisionReplayMatches($existing, $command, $context);
                return $this->revisionResponse($existing, 'replayed');
            }
            $this->assertContext($context, $prior);
            if ((int) $prior['record_version'] !== $command['expected_record_version']) {
                throw $this->failure('conflict', 'The reviewed record version has changed.', 409);
            }
            if (in_array($prior['status'], ['withdrawn', 'stopped'], true)) {
                throw $this->failure('conflict', 'A withdrawn reviewed record is terminal.', 409);
            }
            $extraction = $this->repository->findExtraction($prior['extraction_id']);
            if ($extraction === null) {
                throw $this->failure('unavailable', 'The source extraction is unavailable.', 503);
            }
            $nextVersion = (int) $prior['record_version'] + 1;
            $now = $this->clock->now()->setTimezone(new \DateTimeZone('UTC'));
            $actionId = self::uuid();
            if ($command['action'] === 'amend') {
                $reviews = $this->repository->findReviewsByIds($command['review_ids']);
                $current = $this->repository->findCurrentReviewsForExtraction($prior['extraction_id']);
                $promotionShape = [
                    'extraction_id' => $prior['extraction_id'],
                    'expected_extraction_version' => (int) $prior['extraction_version'],
                    'review_ids' => $command['review_ids'],
                ];
                $this->validatePromotionReviews($promotionShape, $extraction, $reviews, $current);
                usort($reviews, static fn(array $left, array $right): int => strcmp($left['review_id'], $right['review_id']));
                $reviewSetHash = hash('sha256', implode("\n", array_column($reviews, 'review_id')));
                $byField = [];
                foreach ($reviews as $review) {
                    $byField[$review['field_id']] = $review;
                }
            } else {
                $reviewSetHash = $prior['review_set_sha256'];
                $byField = [];
            }
            $provenance = [
                'action_id' => $actionId,
                'action' => $command['action'],
                'action_idempotency_key' => $command['idempotency_key'],
                'review_set_sha256' => $reviewSetHash,
                'source_content_sha256' => $prior['source_content_sha256'],
                'extraction_id' => $prior['extraction_id'],
                'extraction_version' => (int) $prior['extraction_version'],
                'acted_by' => $context->username,
                'acted_at' => $now->format('Y-m-d\TH:i:s\Z'),
                'correlation_id' => $correlationId,
            ];
            if ($command['action'] === 'amend') {
                $recordJson = $this->buildRecord($prior['record_id'], $extraction, $byField, $context, $now, $provenance);
                $status = 'amended';
            } else {
                $recordJson = $prior['record_json'];
                $recordJson['provenance'] = $provenance;
                $status = $prior['target_type'] === 'lab_report' ? 'withdrawn' : 'stopped';
            }
            $recordJson['record_version'] = $nextVersion;
            $recordJson['status'] = $status;
            $recordJson['supersedes_record_id'] = $prior['record_id'];
            $recordJson['lifecycle_reason'] = $command['reason'];
            $recordJson['review_ids'] = $command['action'] === 'amend' ? $this->sortedReviewIds($byField) : $prior['record_json']['review_ids'];
            $record = [
                'record_id' => $prior['record_id'],
                'record_version' => $nextVersion,
                'target_type' => $prior['target_type'],
                'status' => $status,
                'action_id' => $actionId,
                'action_idempotency_key' => $command['idempotency_key'],
                'deterministic_promotion_key' => hash('sha256', $prior['deterministic_promotion_key'] . '|' . $command['action'] . '|' . $nextVersion . '|' . $reviewSetHash),
                'review_set_sha256' => $reviewSetHash,
                'source_content_sha256' => $prior['source_content_sha256'],
                'source_document_id' => $prior['source_document_id'],
                'extraction_id' => $prior['extraction_id'],
                'extraction_version' => (int) $prior['extraction_version'],
                'site_id' => $context->siteId,
                'pid' => $context->pid,
                'record_json' => $recordJson,
                'created_at' => $now->format('Y-m-d H:i:s'),
            ];
            $this->repository->insertRecord($record);
            $this->repository->appendOutbox($this->recordEvent(
                $command['action'] === 'amend' ? 'reviewed_document_amended' : 'reviewed_document_withdrawn',
                $actionId,
                $record['record_id'],
                $record,
                $context,
                $correlationId,
                $now
            ));
            $this->audit->record($context, $operation, true, 'created', [
                'correlation_id' => $correlationId,
                'action_id' => $actionId,
                'record_id' => $record['record_id'],
                'record_version' => $nextVersion,
            ]);
            return $this->revisionResponse($record, 'created');
        });
    }

    /** @param array<string, mixed> $command */
    private function validateReviseCommand(array $command): void
    {
        $base = ['idempotency_key', 'record_id', 'expected_record_version', 'action', 'reason'];
        if (!$this->hasExactRequired($command, $base)
            || array_diff(array_keys($command), [...$base, 'review_ids']) !== []
            || !self::isUuid($command['idempotency_key']) || !self::isUuid($command['record_id'])
            || !is_int($command['expected_record_version']) || $command['expected_record_version'] < 1
            || !in_array($command['action'], ['amend', 'withdraw'], true)
            || !is_string($command['reason']) || strlen($command['reason']) < 1 || strlen($command['reason']) > 500
        ) {
            throw $this->failure('invalid_contract', 'The revision command is invalid.', 422);
        }
        if ($command['action'] === 'amend') {
            if (!isset($command['review_ids']) || !is_array($command['review_ids']) || count($command['review_ids']) < 1
                || count($command['review_ids']) > 1201 || count(array_unique($command['review_ids'])) !== count($command['review_ids'])
                || count(array_filter($command['review_ids'], [self::class, 'isUuid'])) !== count($command['review_ids'])) {
                throw $this->failure('invalid_contract', 'An amendment requires a complete review set.', 422);
            }
        } elseif (array_key_exists('review_ids', $command)) {
            throw $this->failure('invalid_contract', 'A withdrawal cannot select reviews.', 422);
        }
    }

    /** @param array<string, mixed> $record @param array<string, mixed> $command */
    private function assertRevisionReplayMatches(array $record, array $command, DocumentContext $context): void
    {
        $this->assertContext($context, $record);
        $expectedVersion = $command['expected_record_version'] + 1;
        if ($record['record_id'] !== $command['record_id'] || (int) $record['record_version'] !== $expectedVersion
            || ($record['record_json']['provenance']['action'] ?? null) !== $command['action']
            || ($record['record_json']['lifecycle_reason'] ?? null) !== $command['reason']) {
            throw $this->failure('conflict', 'The idempotency key was used for another action.', 409);
        }
        if ($command['action'] === 'amend') {
            $ids = $command['review_ids'];
            sort($ids);
            if ($record['review_set_sha256'] !== hash('sha256', implode("\n", $ids))) {
                throw $this->failure('conflict', 'The idempotency key was used for another review set.', 409);
            }
        }
    }

    /** @param array<string, mixed> $record @return array<string, mixed> */
    private function revisionResponse(array $record, string $outcome): array
    {
        return [
            'action_id' => $record['action_id'],
            'record_id' => $record['record_id'],
            'record_version' => (int) $record['record_version'],
            'status' => $record['status'],
            'review_set_sha256' => $record['review_set_sha256'],
            'outcome' => $outcome,
        ];
    }

    /** @param array<string, mixed> $command */
    private function validatePromoteCommand(array $command): void
    {
        $keys = ['idempotency_key', 'extraction_id', 'expected_extraction_version', 'source_content_sha256', 'target_type', 'review_ids'];
        $actual = array_keys($command);
        sort($keys);
        sort($actual);
        if ($actual !== $keys || !self::isUuid($command['idempotency_key']) || !self::isUuid($command['extraction_id'])
            || !is_int($command['expected_extraction_version']) || $command['expected_extraction_version'] < 1
            || !is_string($command['source_content_sha256']) || preg_match('/^[0-9a-f]{64}$/', $command['source_content_sha256']) !== 1
            || !in_array($command['target_type'], ['lab_report', 'intake_response'], true)
            || !is_array($command['review_ids']) || count($command['review_ids']) < 1 || count($command['review_ids']) > 1201
            || count(array_unique($command['review_ids'])) !== count($command['review_ids'])
            || count(array_filter($command['review_ids'], [self::class, 'isUuid'])) !== count($command['review_ids'])
        ) {
            throw $this->failure('invalid_contract', 'The promotion command is invalid.', 422);
        }
    }

    /** @param array<string, mixed> $command @param array<string, mixed> $extraction @param list<array<string, mixed>> $reviews @param list<array<string, mixed>> $current */
    private function validatePromotionReviews(array $command, array $extraction, array $reviews, array $current): void
    {
        if (count($reviews) !== count($command['review_ids'])) {
            throw $this->failure('review_required', 'The complete current review set is required.', 409);
        }
        $requested = $command['review_ids'];
        $currentIds = array_column($current, 'review_id');
        sort($requested);
        sort($currentIds);
        if ($requested !== $currentIds) {
            throw $this->failure('review_required', 'The complete current review set is required.', 409);
        }
        $byField = [];
        foreach ($reviews as $review) {
            if ($review['extraction_id'] !== $command['extraction_id']
                || (int) $review['extraction_version'] !== $command['expected_extraction_version']
                || ($review['site_id'] ?? null) !== $extraction['site_id']
                || (int) ($review['pid'] ?? 0) !== (int) $extraction['pid']
            ) {
                throw $this->failure('source_mismatch', 'A review belongs to another source.', 409);
            }
            $byField[$review['field_id']] = $review;
        }
        foreach ($this->proposedFields($extraction['payload']) as $field) {
            if (($field['value'] ?? null) === null) {
                continue;
            }
            $review = $byField[$field['field_id']] ?? null;
            if ($review === null || !in_array($review['decision'], ['approved', 'corrected'], true) || $review['final_value'] === null) {
                throw $this->failure('review_required', 'Every proposed value requires a current physician acceptance.', 409);
            }
        }
    }

    /** @param array<string, mixed> $record @param array<string, mixed> $command */
    private function assertPromotionReplayMatches(array $record, array $command, DocumentContext $context): void
    {
        $this->assertContext($context, $record);
        $ids = $command['review_ids'];
        sort($ids);
        $hash = hash('sha256', implode("\n", $ids));
        if ($record['extraction_id'] !== $command['extraction_id']
            || (int) $record['extraction_version'] !== $command['expected_extraction_version']
            || $record['source_content_sha256'] !== $command['source_content_sha256']
            || $record['target_type'] !== $command['target_type']
            || $record['review_set_sha256'] !== $hash
        ) {
            throw $this->failure('conflict', 'The idempotency key was used for another action.', 409);
        }
    }

    /** @param array<string, mixed> $record @return array<string, mixed> */
    private function promotionResponse(array $record, string $outcome): array
    {
        return [
            'promotion_id' => $record['action_id'],
            'target_type' => $record['target_type'],
            'target_record_id' => $record['record_id'],
            'record_version' => (int) $record['record_version'],
            'review_set_sha256' => $record['review_set_sha256'],
            'outcome' => $outcome,
        ];
    }

    /** @param array<string, mixed> $extraction @param array<string, array<string, mixed>> $reviews @param array<string, mixed> $provenance @return array<string, mixed> */
    private function buildRecord(string $recordId, array $extraction, array $reviews, DocumentContext $context, \DateTimeImmutable $now, array $provenance): array
    {
        if ($extraction['schema_name'] === 'lab-report') {
            $payload = $extraction['payload'];
            $analytes = [];
            foreach ($payload['analytes'] as $analyte) {
                $built = ['analyte_id' => $analyte['analyte_id']];
                foreach (['test_name', 'code', 'value', 'unit', 'reference_range', 'abnormal_flag'] as $name) {
                    if (isset($analyte[$name]) && isset($reviews[$analyte[$name]['field_id']])
                        && in_array($reviews[$analyte[$name]['field_id']]['decision'], ['approved', 'corrected'], true)) {
                        $built[$name] = $this->reviewedField($analyte[$name], $reviews[$analyte[$name]['field_id']]);
                    }
                }
                $analytes[] = $built;
            }
            return [
                'record_id' => $recordId,
                'record_version' => 1,
                'status' => 'active',
                'source' => $extraction['source'],
                'extraction_id' => $extraction['extraction_id'],
                'extraction_version' => (int) $extraction['extraction_version'],
                'schema_version' => $extraction['schema_version'],
                'collection_date' => $this->reviewedField($payload['collection_date'], $reviews[$payload['collection_date']['field_id']]),
                'analytes' => $analytes,
                'review_ids' => $this->sortedReviewIds($reviews),
                'reviewed_by' => $context->username,
                'reviewed_at' => $now->format('Y-m-d\TH:i:s\Z'),
                'provenance' => $provenance,
            ];
        }
        return $this->buildIntakeRecord($recordId, $extraction, $reviews, $context, $now, $provenance);
    }

    /** @param array<string, mixed> $proposed @param array<string, mixed> $review @return array<string, mixed> */
    private function reviewedField(array $proposed, array $review): array
    {
        return [
            'value' => $review['final_value'],
            'source_field_id' => $proposed['field_id'],
            'review_id' => $review['review_id'],
            'evidence_ids' => array_values($review['evidence_ids']),
        ];
    }

    /** @param array<string, mixed> $payload @return list<array<string, mixed>> */
    private function proposedFields(array $payload): array
    {
        $fields = [];
        $walk = function (mixed $value) use (&$walk, &$fields): void {
            if (!is_array($value)) {
                return;
            }
            if (isset($value['field_id']) && array_key_exists('value', $value)) {
                $fields[] = $value;
                return;
            }
            foreach ($value as $child) {
                $walk($child);
            }
        };
        $walk($payload);
        return $fields;
    }

    /** @param array<string, array<string, mixed>> $reviews @return list<string> */
    private function sortedReviewIds(array $reviews): array
    {
        $ids = array_column(array_values($reviews), 'review_id');
        sort($ids);
        return $ids;
    }

    /** @return array<string, mixed> */
    private function buildIntakeRecord(string $recordId, array $extraction, array $reviews, DocumentContext $context, \DateTimeImmutable $now, array $provenance): array
    {
        $payload = $extraction['payload'];
        $items = [];
        foreach ($payload['demographics'] as $name => $proposed) {
            if (is_array($proposed) && isset($reviews[$proposed['field_id']])) {
                $items[] = $this->questionnaireItem($proposed, $reviews[$proposed['field_id']], 'demographics-' . str_replace('_', '-', (string) $name));
            }
        }
        if (isset($payload['chief_concern']) && isset($reviews[$payload['chief_concern']['field_id']])) {
            $items[] = $this->questionnaireItem($payload['chief_concern'], $reviews[$payload['chief_concern']['field_id']], 'chief-concern');
        }
        foreach ([
            'medications' => 'medication',
            'allergies' => 'allergy',
            'family_history' => 'family-history',
        ] as $collection => $prefix) {
            foreach ($payload[$collection] as $entry) {
                foreach ($entry as $name => $proposed) {
                    if ($name === 'entry_id' || !is_array($proposed) || !isset($reviews[$proposed['field_id']])) {
                        continue;
                    }
                    $items[] = $this->questionnaireItem(
                        $proposed,
                        $reviews[$proposed['field_id']],
                        $prefix . '-' . str_replace('_', '-', (string) $name),
                        $entry['entry_id']
                    );
                }
            }
        }
        return [
            'record_id' => $recordId,
            'record_version' => 1,
            'resource_type' => 'QuestionnaireResponse',
            'questionnaire' => 'urn:agentforge:questionnaire:intake:v1',
            'status' => 'completed',
            'source' => $extraction['source'],
            'extraction_id' => $extraction['extraction_id'],
            'extraction_version' => (int) $extraction['extraction_version'],
            'schema_version' => $extraction['schema_version'],
            'subject' => 'Patient/' . $context->patientUuid,
            'authored' => $now->format('Y-m-d\TH:i:s\Z'),
            'reviewed_by' => $context->username,
            'review_ids' => $this->sortedReviewIds($reviews),
            'items' => $items,
            'provenance' => $provenance,
        ];
    }

    /** @param array<string, mixed> $proposed @param array<string, mixed> $review @return array<string, mixed> */
    private function questionnaireItem(array $proposed, array $review, string $linkId, ?string $repeatKey = null): array
    {
        $fieldId = $proposed['field_id'];
        $kind = match (true) {
            str_ends_with($fieldId, '.date_of_birth') => 'date',
            str_ends_with($fieldId, '.onset_age_years') => 'integer',
            str_ends_with($fieldId, '.administrative_sex'), str_ends_with($fieldId, '.status'), str_ends_with($fieldId, '.severity') => 'choice',
            default => 'string',
        };
        $item = [
            'item_id' => self::uuid(),
            'link_id' => $linkId,
            'source_field_id' => $fieldId,
            'review_id' => $review['review_id'],
            'evidence_ids' => array_values($review['evidence_ids']),
            'answer' => ['kind' => $kind, 'value' => $review['final_value']],
        ];
        if ($repeatKey !== null) {
            $item['repeat_key'] = $repeatKey;
        }
        return $item;
    }

    /** @param array<string, mixed> $record @return array<string, mixed> */
    private function recordEvent(string $eventType, string $eventId, string $recordId, array $record, DocumentContext $context, string $correlationId, \DateTimeImmutable $now): array
    {
        return [
            'event_id' => $eventId,
            'event_type' => $eventType,
            'aggregate_id' => $recordId,
            'site_id' => $context->siteId,
            'pid' => $context->pid,
            'user_id' => $context->userId,
            'correlation_id' => $correlationId,
            'payload' => [
                'record_id' => $recordId,
                'record_version' => $record['record_version'],
                'target_type' => $record['target_type'],
                'review_set_sha256' => $record['review_set_sha256'],
            ],
            'created_at' => $now->format('Y-m-d H:i:s'),
        ];
    }

    /** @param array<string, mixed> $command */
    private function validateReviewCommand(array $command): void
    {
        $allowed = ['idempotency_key', 'extraction_id', 'expected_extraction_version', 'field_id', 'action', 'corrected_value', 'reason'];
        if (array_diff(array_keys($command), $allowed) !== []
            || !$this->hasExactRequired($command, ['idempotency_key', 'extraction_id', 'expected_extraction_version', 'field_id', 'action'])
            || !self::isUuid($command['idempotency_key'])
            || !self::isUuid($command['extraction_id'])
            || !is_int($command['expected_extraction_version'])
            || $command['expected_extraction_version'] < 1
            || !is_string($command['field_id'])
            || preg_match('/^[a-z][a-z0-9_.-]{0,127}$/', $command['field_id']) !== 1
            || !in_array($command['action'], ['approve', 'correct', 'reject'], true)
        ) {
            throw $this->failure('invalid_contract', 'The review command is invalid.', 422);
        }
        $hasCorrection = array_key_exists('corrected_value', $command) && $command['corrected_value'] !== null;
        $hasReason = array_key_exists('reason', $command) && is_string($command['reason']) && strlen($command['reason']) >= 1 && strlen($command['reason']) <= 500;
        if (($command['action'] === 'correct') !== $hasCorrection
            || (($command['action'] !== 'approve') !== $hasReason)
            || ($command['action'] === 'approve' && (array_key_exists('reason', $command) || array_key_exists('corrected_value', $command)))
        ) {
            throw $this->failure('invalid_contract', 'The review decision fields are invalid.', 422);
        }
    }

    /** @param array<string, mixed> $command @param array<string, mixed> $fact */
    private function validateDecisionAgainstFact(array $command, array $fact): void
    {
        $value = $fact['typed_value'] ?? null;
        $evidence = $fact['evidence_ids'] ?? null;
        if (!is_array($evidence) || count($evidence) > 3 || count(array_unique($evidence)) !== count($evidence)) {
            throw $this->failure('source_mismatch', 'The field evidence is invalid.', 409);
        }
        if ($command['action'] !== 'reject' && !in_array($fact['state'] ?? null, ['schema_valid', 'review_required'], true)) {
            throw $this->failure('review_required', 'The proposed field is unavailable for acceptance.', 409);
        }
        if ($command['action'] === 'approve' && $value === null) {
            throw $this->failure('review_required', 'A missing value cannot be approved.', 409);
        }
        if ($command['action'] !== 'reject' && $evidence === []) {
            throw $this->failure('review_required', 'Evidence is required before acceptance.', 409);
        }
        if ($command['action'] === 'correct') {
            $this->validateCorrectedValue($command['field_id'], $command['corrected_value']);
        }
    }

    private function validateCorrectedValue(string $fieldId, mixed $corrected): void
    {
        if (!is_array($corrected) || count($corrected) !== 2
            || !array_key_exists('kind', $corrected) || !array_key_exists('value', $corrected)
            || !is_string($corrected['kind'])) {
            throw $this->failure('invalid_contract', 'The corrected value is invalid.', 422);
        }
        $kind = $corrected['kind'];
        $value = $corrected['value'];
        $valid = match ($kind) {
            'string' => is_string($value) && strlen($value) >= 1 && strlen($value) <= 2000,
            'date' => is_string($value) && self::isDate($value),
            'integer' => is_int($value) && $value >= 0 && $value <= 130,
            'choice' => is_string($value) && in_array($value, self::choicesFor($fieldId), true),
            'coded' => self::isCoded($value),
            'measurement' => self::isMeasurement($value),
            'reference_range' => self::isRange($value),
            default => false,
        };
        if (!$valid || !self::kindAllowedForField($fieldId, $kind)) {
            throw $this->failure('invalid_contract', 'The corrected value does not match the proposed field.', 422);
        }
    }

    /** @param array<string, mixed> $command @param array<string, mixed> $fact */
    private function finalValue(array $command, array $fact): mixed
    {
        if ($command['action'] === 'reject') {
            return null;
        }
        if ($command['action'] === 'correct') {
            return $command['corrected_value']['value'];
        }
        return $fact['typed_value'];
    }

    /** @param array<string, mixed> $existing @param array<string, mixed> $command */
    private function assertReviewReplayMatches(array $existing, array $command): void
    {
        $decision = $command['action'] === 'approve' ? 'approved' : ($command['action'] === 'correct' ? 'corrected' : 'rejected');
        $requestedFinal = $command['action'] === 'correct' ? $command['corrected_value']['value'] : ($command['action'] === 'reject' ? null : $existing['proposed_value']);
        if ($existing['extraction_id'] !== $command['extraction_id']
            || (int) $existing['extraction_version'] !== $command['expected_extraction_version']
            || $existing['field_id'] !== $command['field_id']
            || $existing['decision'] !== $decision
            || $existing['final_value'] !== $requestedFinal
            || ($existing['reason'] ?? null) !== ($command['reason'] ?? null)
        ) {
            throw $this->failure('conflict', 'The idempotency key was used for another review.', 409);
        }
    }

    /** @param array<string, mixed> $bound */
    private function assertContext(DocumentContext $context, array $bound): void
    {
        if ((string) ($bound['site_id'] ?? '') !== $context->siteId || (int) ($bound['pid'] ?? 0) !== $context->pid) {
            throw $this->failure('patient_context_changed', 'The active patient context has changed.', 409);
        }
    }

    /** @param array<string, mixed> $review @return array<string, mixed> */
    private function publicReview(array $review): array
    {
        unset($review['site_id'], $review['pid']);
        return $review;
    }

    /** @param array<string, mixed> $value */
    private static function isCoded(mixed $value): bool
    {
        if (!is_array($value) || array_diff(array_keys($value), ['system', 'code', 'display']) !== []
            || !is_string($value['system'] ?? null) || strlen($value['system']) < 1 || strlen($value['system']) > 500
            || !is_string($value['code'] ?? null) || strlen($value['code']) < 1 || strlen($value['code']) > 100
        ) {
            return false;
        }
        return !isset($value['display']) || (is_string($value['display']) && strlen($value['display']) >= 1 && strlen($value['display']) <= 200);
    }

    private static function isMeasurement(mixed $value): bool
    {
        return is_array($value) && count($value) === 2 && array_key_exists('kind', $value) && array_key_exists('value', $value)
            && (($value['kind'] === 'quantity' && (is_int($value['value']) || is_float($value['value']) || (is_string($value['value']) && preg_match('/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/', $value['value']) === 1)))
                || ($value['kind'] === 'text' && is_string($value['value']) && strlen($value['value']) >= 1 && strlen($value['value']) <= 500));
    }

    private static function isRange(mixed $value): bool
    {
        if (!is_array($value) || array_diff(array_keys($value), ['low', 'high', 'text', 'unit']) !== []) {
            return false;
        }
        return count(array_filter([$value['low'] ?? null, $value['high'] ?? null, $value['text'] ?? null], static fn(mixed $item): bool => $item !== null)) >= 1;
    }

    private static function kindAllowedForField(string $fieldId, string $kind): bool
    {
        if ($fieldId === 'collection_date' || str_ends_with($fieldId, '.date_of_birth')) {
            return $kind === 'date';
        }
        if (str_ends_with($fieldId, '.onset_age_years')) {
            return $kind === 'integer';
        }
        if (str_ends_with($fieldId, '.code')) {
            return $kind === 'coded';
        }
        if (str_ends_with($fieldId, '.value')) {
            return $kind === 'measurement';
        }
        if (str_ends_with($fieldId, '.reference_range')) {
            return $kind === 'reference_range';
        }
        if (str_ends_with($fieldId, '.administrative_sex') || str_ends_with($fieldId, '.status')
            || str_ends_with($fieldId, '.severity') || str_ends_with($fieldId, '.abnormal_flag')) {
            return $kind === 'choice';
        }
        return $kind === 'string';
    }

    /** @return list<string> */
    private static function choicesFor(string $fieldId): array
    {
        return match (true) {
            str_ends_with($fieldId, '.administrative_sex') => ['female', 'male', 'other', 'unknown'],
            str_ends_with($fieldId, '.severity') => ['mild', 'moderate', 'severe', 'unknown'],
            str_ends_with($fieldId, '.abnormal_flag') => ['low', 'high', 'abnormal', 'normal', 'unknown'],
            default => ['active', 'inactive', 'stopped', 'resolved', 'unknown'],
        };
    }

    private static function isDate(string $value): bool
    {
        $date = \DateTimeImmutable::createFromFormat('!Y-m-d', $value);
        return $date !== false && $date->format('Y-m-d') === $value;
    }

    /** @param array<string, mixed> $value @param list<string> $required */
    private function hasExactRequired(array $value, array $required): bool
    {
        foreach ($required as $key) {
            if (!array_key_exists($key, $value)) {
                return false;
            }
        }
        return true;
    }

    private static function isUuid(mixed $value): bool
    {
        return is_string($value) && preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $value) === 1;
    }

    private function failure(string $code, string $message, int $status): DocumentLifecycleException
    {
        return new DocumentLifecycleException($code, false, $message, $status);
    }

    private function atomic(callable $callback): mixed
    {
        try {
            return $this->repository->transaction($callback);
        } catch (DocumentLifecycleException $exception) {
            throw $exception;
        } catch (\Throwable $exception) {
            throw new DocumentLifecycleException(
                'unavailable',
                true,
                'The reviewed-document action could not be committed.',
                503
            );
        }
    }

    private static function uuid(): string
    {
        $bytes = random_bytes(16);
        $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
        $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
        $hex = bin2hex($bytes);
        return substr($hex, 0, 8) . '-' . substr($hex, 8, 4) . '-' . substr($hex, 12, 4) . '-'
            . substr($hex, 16, 4) . '-' . substr($hex, 20);
    }
}
