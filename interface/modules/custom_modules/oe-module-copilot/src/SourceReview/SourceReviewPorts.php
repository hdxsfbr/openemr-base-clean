<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\SourceReview;

interface SourceReviewAuthorizationPort
{
    public function authorize(string $conversationId, string $turnId, string $correlationId): SourceReviewContext;
}

interface CitationAuthorityPort
{
    /** @return array<string, mixed>|null */
    public function find(SourceReviewContext $context, string $citationId): ?array;
}

interface SourceViewAuthorityPort
{
    /** @param array<string, mixed> $citation @return array<string, mixed>|null */
    public function resolve(SourceReviewContext $context, array $citation): ?array;
}
