<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\SourceReview;

final readonly class SourceReviewContext
{
    public function __construct(
        public string $siteId,
        public int $userId,
        public int $pid,
        public string $conversationId,
        public string $turnId,
        public string $correlationId = '',
    ) {
    }
}
