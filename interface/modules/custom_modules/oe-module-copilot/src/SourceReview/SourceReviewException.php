<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\SourceReview;

final class SourceReviewException extends \RuntimeException
{
    public function __construct(
        public readonly string $errorCode,
        public readonly bool $retryable,
        string $message,
        public readonly int $httpStatus = 409,
    ) {
        parent::__construct($message);
    }
}
