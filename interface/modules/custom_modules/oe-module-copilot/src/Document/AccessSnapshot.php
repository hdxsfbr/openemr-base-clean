<?php

/**
 * Current access state observed from OpenEMR.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

final readonly class AccessSnapshot
{
    public function __construct(
        public DocumentContext $context,
        public bool $active,
        public bool $docsAcl,
        public bool $squadAllowed,
        public bool $breakGlass,
        public string $principal,
        public bool $reviewAcl,
        public bool $targetWriteAcl,
    ) {
    }
}
