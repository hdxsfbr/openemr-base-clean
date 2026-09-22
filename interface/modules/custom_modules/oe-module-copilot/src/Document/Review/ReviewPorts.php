<?php

/**
 * Persistence boundary for physician review and reviewed-record promotion.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Review;

interface ReviewRepositoryPort
{
    public function transaction(callable $callback): mixed;

    /** @return array<string, mixed>|null */
    public function findReviewByIdempotencyKey(string $key): ?array;

    /** @return array<string, mixed>|null */
    public function findExtraction(string $extractionId): ?array;

    /** @return array<string, mixed>|null */
    public function findProposedFact(string $extractionId, string $fieldId): ?array;

    /** @return array<string, mixed>|null */
    public function findCurrentReview(string $extractionId, string $fieldId): ?array;

    /** @param array<string, mixed> $review */
    public function insertReview(array $review): void;

    /** @param array<string, mixed> $event */
    public function appendOutbox(array $event): void;

    /** @return array<string, mixed>|null */
    public function findRecordByActionIdempotencyKey(string $key): ?array;

    /** @return array<string, mixed>|null */
    public function findRecordByDeterministicKey(string $key): ?array;

    /** @param list<string> $reviewIds @return list<array<string, mixed>> */
    public function findReviewsByIds(array $reviewIds): array;

    /** @return list<array<string, mixed>> */
    public function findCurrentReviewsForExtraction(string $extractionId): array;

    /** @param array<string, mixed> $record */
    public function insertRecord(array $record): void;

    /** @return array<string, mixed>|null */
    public function findLatestRecord(string $recordId): ?array;
}
