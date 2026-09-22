<?php

/**
 * Persistence boundary for upload intents and immutable source mappings.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

interface UploadRepositoryPort
{
    public function transaction(callable $action): mixed;

    /** @return array<string, mixed>|null */
    public function findIntentByKey(string $siteId, int $pid, string $category, string $idempotencyKey): ?array;

    /** @param array<string, mixed> $intent */
    public function insertIntent(array $intent): void;

    /** @return array<string, mixed>|null */
    public function findIntent(string $intentId): ?array;

    /** @param array<string, mixed> $source */
    public function completeIntent(string $intentId, array $source): bool;

    /** @return array<string, mixed>|null */
    public function findSource(string $sourceDocumentId): ?array;

    /** @return list<string> */
    public function findDuplicateSourceIds(string $siteId, int $pid, string $sha256, string $exceptIntentId): array;

    /** @param array<string, mixed> $event */
    public function appendOutbox(array $event): void;
}
