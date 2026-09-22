<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\SourceReview;

final class SourceReviewFactory
{
    public static function browser(): SourceReview
    {
        $baseUrl = getenv('COPILOT_AGENT_INTERNAL_URL') ?: 'http://agent:8080';
        $authority = new AgentSourceReviewAuthority($baseUrl);
        return new SourceReview(new LiveSourceReviewAuthorization(), $authority, $authority);
    }
}
