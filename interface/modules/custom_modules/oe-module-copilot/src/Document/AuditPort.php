<?php

/**
 * Audit boundary for document access and lifecycle events.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

interface AuditPort
{
    /** @param array<string, scalar|null> $identifiers */
    public function record(
        DocumentContext $context,
        string $operation,
        bool $success,
        string $reason,
        array $identifiers,
    ): void;
}
