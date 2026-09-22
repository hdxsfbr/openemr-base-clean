<?php

/**
 * UI-safe failure from the document boundary. No source bytes or document
 * text may be placed in the message.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

final class DocumentLifecycleException extends \RuntimeException
{
    public function __construct(
        public readonly string $errorCode,
        public readonly bool $retryable,
        string $limitation,
        public readonly int $httpStatus = 400,
    ) {
        parent::__construct($limitation);
    }
}
