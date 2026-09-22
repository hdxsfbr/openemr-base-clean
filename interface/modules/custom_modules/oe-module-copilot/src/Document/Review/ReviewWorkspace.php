<?php

/**
 * Authorized read model and exact source-region resolver for physician review.
 *
 * Reads never create a review or a promoted record. The returned promotion
 * selectors are server-owned values from one current extraction and must be
 * submitted unchanged to the separate write workflow after an explicit click.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Review;

use OpenEMR\Modules\Copilot\Document\AuditPort;
use OpenEMR\Modules\Copilot\Document\AuthorizationPort;
use OpenEMR\Modules\Copilot\Document\DocumentContext;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleException;

final class ReviewWorkspace
{
    public function __construct(
        private readonly AuthorizationPort $authorization,
        private readonly ReviewWorkspaceRepositoryPort $repository,
        private readonly ReviewSourcePort $source,
        private readonly AuditPort $audit,
    ) {
    }

    /** @return array<string, mixed> */
    public function read(string $correlationId): array
    {
        $context = $this->authorization->authorize('review', $correlationId);
        $extraction = $this->repository->findLatestExtractionForPatient($context->siteId, $context->pid);
        if ($extraction === null) {
            $this->audit($context, 'review_read', 'empty', $correlationId, []);
            return [
                'status' => 'empty',
                'extraction' => null,
                'facts' => [],
                'promotion' => [
                    'state' => 'blocked',
                    'review_ids' => [],
                    'blocker_count' => 0,
                    'current_record' => null,
                ],
            ];
        }
        $this->assertContext($context, $extraction);

        $extractionId = (string) $extraction['extraction_id'];
        $facts = $this->repository->findProposedFactsForExtraction($extractionId);
        $reviews = $this->repository->findCurrentReviewsForExtraction($extractionId);
        $record = $this->repository->findLatestRecordForExtraction($extractionId);
        $byField = [];
        $reviewIds = [];
        foreach ($reviews as $review) {
            $this->assertContext($context, $review);
            if (($review['extraction_id'] ?? null) !== $extractionId
                || (int) ($review['extraction_version'] ?? 0) !== (int) $extraction['extraction_version']
                || !is_string($review['field_id'] ?? null)
                || !is_string($review['review_id'] ?? null)) {
                throw $this->failure('source_mismatch', 'The current review set does not match the extraction.', 409);
            }
            $byField[$review['field_id']] = $review;
            $reviewIds[] = $review['review_id'];
        }
        sort($reviewIds);

        $blockers = 0;
        $publicFacts = [];
        foreach ($facts as $fact) {
            if (($fact['extraction_id'] ?? null) !== $extractionId || !is_string($fact['field_id'] ?? null)) {
                throw $this->failure('source_mismatch', 'A proposed fact does not match the extraction.', 409);
            }
            $review = $byField[$fact['field_id']] ?? null;
            $promotable = ($fact['typed_value'] ?? null) !== null;
            if ($promotable && ($review === null
                || !in_array($review['decision'] ?? null, ['approved', 'corrected'], true)
                || ($review['final_value'] ?? null) === null)) {
                $blockers++;
            }
            $publicFacts[] = [
                'field_id' => $fact['field_id'],
                'proposed_value' => $fact['typed_value'] ?? null,
                'extraction_state' => $fact['state'] ?? 'unavailable',
                'evidence' => array_values(is_array($fact['evidence'] ?? null) ? $fact['evidence'] : []),
                'current_decision' => $review === null ? ['decision' => 'pending'] : $this->publicReview($review),
            ];
        }

        if ($record !== null) {
            $this->assertContext($context, $record);
            if (($record['extraction_id'] ?? null) !== $extractionId
                || (int) ($record['extraction_version'] ?? 0) !== (int) $extraction['extraction_version']
                || ($record['source_content_sha256'] ?? null) !== $extraction['source_content_sha256']) {
                throw $this->failure('source_mismatch', 'The reviewed record does not match the extraction.', 409);
            }
        }

        $status = $record !== null ? 'promoted' : ($blockers === 0 && $reviewIds !== [] ? 'ready_to_promote' : 'review_required');
        $promotionState = $record !== null ? 'promoted' : ($status === 'ready_to_promote' ? 'ready' : 'blocked');
        $this->audit($context, 'review_read', $status, $correlationId, [
            'extraction_id' => $extractionId,
            'extraction_version' => (int) $extraction['extraction_version'],
            'fact_count' => count($publicFacts),
            'blocker_count' => $blockers,
        ]);

        return [
            'status' => $status,
            'extraction' => [
                'extraction_id' => $extractionId,
                'extraction_version' => (int) $extraction['extraction_version'],
                'extraction_state' => (string) $extraction['state'],
                'schema_name' => (string) $extraction['schema_name'],
                'schema_version' => (string) $extraction['schema_version'],
                'target_type' => $extraction['schema_name'] === 'lab-report' ? 'lab_report' : 'intake_response',
                'source_document_id' => (string) $extraction['source_document_id'],
                'source_content_sha256' => (string) $extraction['source_content_sha256'],
                'document_type' => (string) ($extraction['source']['document_type'] ?? ''),
                'page_count' => (int) ($extraction['source']['page_count'] ?? 0),
            ],
            'facts' => $publicFacts,
            'promotion' => [
                'state' => $promotionState,
                'review_ids' => $reviewIds,
                'blocker_count' => $blockers,
                'current_record' => $record === null ? null : $this->publicRecord($record),
            ],
        ];
    }

    /** @param array<string, mixed> $request @return array<string, mixed> */
    public function source(array $request, string $correlationId): array
    {
        $this->validateSourceRequest($request);
        $context = $this->authorization->authorize('review', $correlationId);
        $extraction = $this->repository->findLatestExtractionForPatient($context->siteId, $context->pid);
        if ($extraction === null) {
            throw $this->failure('not_found', 'The extraction was not found.', 404);
        }
        $this->assertContext($context, $extraction);
        if (($extraction['extraction_id'] ?? null) !== $request['extraction_id']
            || (int) ($extraction['extraction_version'] ?? 0) !== $request['expected_extraction_version']) {
            throw $this->failure('stale_extraction', 'The extraction version has changed.', 409);
        }
        if (($extraction['source_document_id'] ?? null) !== $request['source_document_id']
            || !hash_equals((string) ($extraction['source_content_sha256'] ?? ''), $request['source_content_sha256'])) {
            throw $this->failure('source_mismatch', 'The source content has changed.', 409);
        }

        $fact = null;
        foreach ($this->repository->findProposedFactsForExtraction($request['extraction_id']) as $candidate) {
            if (($candidate['field_id'] ?? null) === $request['field_id']) {
                $fact = $candidate;
                break;
            }
        }
        if ($fact === null) {
            throw $this->failure('not_found', 'The proposed field was not found.', 404);
        }
        $evidence = null;
        foreach (is_array($fact['evidence'] ?? null) ? $fact['evidence'] : [] as $candidate) {
            if (($candidate['evidence_id'] ?? null) === $request['evidence_id']) {
                $evidence = $candidate;
                break;
            }
        }
        if ($evidence === null
            || (int) ($evidence['page_number'] ?? 0) !== $request['page_number']
            || ($evidence['rendered_page_sha256'] ?? null) !== $request['rendered_page_sha256']
            || !$this->validBox($evidence['box'] ?? null)) {
            throw $this->failure('source_mismatch', 'The source evidence has changed.', 409);
        }

        $page = $this->source->renderPage($request['source_document_id'], $request['page_number'], $correlationId);
        if (($page['source_document_id'] ?? null) !== $request['source_document_id']
            || !hash_equals($request['source_content_sha256'], (string) ($page['content_sha256'] ?? ''))
            || (int) ($page['page_number'] ?? 0) !== $request['page_number']
            || ($page['media_type'] ?? null) !== 'image/png'
            || !is_string($page['bytes'] ?? null)
            || $page['bytes'] === '') {
            throw $this->failure('source_mismatch', 'The immutable source page could not be verified.', 409);
        }

        $review = null;
        foreach ($this->repository->findCurrentReviewsForExtraction($request['extraction_id']) as $candidate) {
            if (($candidate['field_id'] ?? null) === $request['field_id']) {
                $this->assertContext($context, $candidate);
                if (($candidate['extraction_id'] ?? null) !== $request['extraction_id']
                    || (int) ($candidate['extraction_version'] ?? 0) !== $request['expected_extraction_version']) {
                    throw $this->failure('source_mismatch', 'The current review does not match the extraction.', 409);
                }
                $review = $candidate;
                break;
            }
        }
        $this->audit($context, 'review_source', 'opened', $correlationId, [
            'extraction_id' => $request['extraction_id'],
            'extraction_version' => $request['expected_extraction_version'],
            'field_id' => $request['field_id'],
            'evidence_id' => $request['evidence_id'],
            'page_number' => $request['page_number'],
        ]);

        $documentType = (string) ($extraction['source']['document_type'] ?? 'document');
        return [
            'status' => 'available',
            'lane' => 'patient_record',
            'announcement' => 'Source page ' . $request['page_number'] . ', field ' . $request['field_id'],
            'source' => [
                'source_type' => 'document_proposal',
                'title' => $documentType === 'lab_report' ? 'Laboratory report proposal' : 'Intake form proposal',
                'document_type' => $documentType,
                'extraction_version' => $request['expected_extraction_version'],
                'field_id' => $request['field_id'],
                'extraction_state' => (string) ($fact['state'] ?? 'unavailable'),
                'review_decision' => (string) ($review['decision'] ?? 'pending'),
                'proposed' => ['label' => 'Proposed', 'value' => $fact['typed_value'] ?? null],
                'printed' => ['label' => 'Printed', 'value' => (string) ($evidence['printed_quote'] ?? '')],
                'page_number' => $request['page_number'],
                'box' => $evidence['box'],
                'focus_label' => 'Proposed fact evidence region',
                'page' => [
                    'media_type' => 'image/png',
                    'data_base64' => base64_encode($page['bytes']),
                ],
            ],
        ];
    }

    /** @param array<string, mixed> $request */
    private function validateSourceRequest(array $request): void
    {
        $keys = [
            'extraction_id', 'expected_extraction_version', 'source_document_id', 'source_content_sha256',
            'field_id', 'evidence_id', 'page_number', 'rendered_page_sha256',
        ];
        $actual = array_keys($request);
        sort($keys);
        sort($actual);
        if ($actual !== $keys
            || !self::isUuid($request['extraction_id'] ?? null)
            || !is_int($request['expected_extraction_version'] ?? null) || $request['expected_extraction_version'] < 1
            || !self::isUuid($request['source_document_id'] ?? null)
            || !self::isSha256($request['source_content_sha256'] ?? null)
            || !is_string($request['field_id'] ?? null)
            || preg_match('/^[a-z][a-z0-9_.-]{0,127}$/', $request['field_id']) !== 1
            || !self::isUuid($request['evidence_id'] ?? null)
            || !is_int($request['page_number'] ?? null) || $request['page_number'] < 1
            || !self::isSha256($request['rendered_page_sha256'] ?? null)) {
            throw $this->failure('invalid_contract', 'The source request is invalid.', 422);
        }
    }

    /** @param array<string, mixed> $review @return array<string, mixed> */
    private function publicReview(array $review): array
    {
        return array_intersect_key($review, array_flip([
            'review_id', 'decision', 'final_value', 'reason', 'reviewed_by', 'reviewed_at', 'supersedes_review_id',
        ]));
    }

    /** @param array<string, mixed> $record @return array<string, mixed> */
    private function publicRecord(array $record): array
    {
        return [
            'record_id' => (string) $record['record_id'],
            'record_version' => (int) $record['record_version'],
            'target_type' => (string) $record['target_type'],
            'status' => (string) $record['status'],
            'review_set_sha256' => (string) $record['review_set_sha256'],
            'record' => $record['record_json'],
        ];
    }

    /** @param array<string, mixed> $bound */
    private function assertContext(DocumentContext $context, array $bound): void
    {
        if (($bound['site_id'] ?? null) !== $context->siteId || (int) ($bound['pid'] ?? 0) !== $context->pid) {
            throw $this->failure('patient_context_changed', 'The active patient context has changed.', 409);
        }
    }

    private function audit(DocumentContext $context, string $operation, string $reason, string $correlationId, array $identifiers): void
    {
        try {
            $this->audit->record($context, $operation, true, $reason, ['correlation_id' => $correlationId] + $identifiers);
        } catch (\Throwable $exception) {
            throw $this->failure('unavailable', 'The review read could not be audited.', 503, true);
        }
    }

    private function validBox(mixed $box): bool
    {
        if (!is_array($box) || array_keys($box) !== ['x', 'y', 'width', 'height']) {
            return false;
        }
        foreach ($box as $number) {
            if ((!is_float($number) && !is_int($number)) || $number < 0 || $number > 1) {
                return false;
            }
        }
        return $box['width'] > 0 && $box['height'] > 0
            && $box['x'] + $box['width'] <= 1 && $box['y'] + $box['height'] <= 1;
    }

    private static function isUuid(mixed $value): bool
    {
        return is_string($value) && preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $value) === 1;
    }

    private static function isSha256(mixed $value): bool
    {
        return is_string($value) && preg_match('/^[0-9a-f]{64}$/', $value) === 1;
    }

    private function failure(string $code, string $message, int $status, bool $retryable = false): DocumentLifecycleException
    {
        return new DocumentLifecycleException($code, $retryable, $message, $status);
    }
}
