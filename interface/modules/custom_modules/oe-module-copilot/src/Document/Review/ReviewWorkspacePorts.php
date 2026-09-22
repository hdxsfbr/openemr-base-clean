<?php

/**
 * Read-only boundaries used by the physician document-review workspace.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Review;

interface ReviewWorkspaceRepositoryPort
{
    /** @return array<string, mixed>|null */
    public function findLatestExtractionForPatient(string $siteId, int $pid): ?array;

    /** @return list<array<string, mixed>> */
    public function findProposedFactsForExtraction(string $extractionId): array;

    /** @return list<array<string, mixed>> */
    public function findCurrentReviewsForExtraction(string $extractionId): array;

    /** @return array<string, mixed>|null */
    public function findLatestRecordForExtraction(string $extractionId): ?array;
}

interface ReviewSourcePort
{
    /** @return array{source_document_id: string, content_sha256: string, page_number: int, media_type: string, bytes: string} */
    public function renderPage(string $sourceDocumentId, int $pageNumber, string $correlationId): array;
}
