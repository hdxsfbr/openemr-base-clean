<?php

/**
 * Authorized OpenEMR context for one document operation.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

final readonly class DocumentContext
{
    public function __construct(
        public string $siteId,
        public int $userId,
        public string $username,
        public string $groupName,
        public int $pid,
        public string $patientUuid,
    ) {
    }
}
