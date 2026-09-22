<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

final class ExtractionGatewayException extends \RuntimeException
{
    public function __construct(
        public readonly string $errorCode,
        public readonly bool $retryable,
        string $limitation,
        public readonly int $httpStatus,
    ) {
        parent::__construct($limitation);
    }
}

