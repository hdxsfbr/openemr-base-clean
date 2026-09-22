<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\SourceReview;

use OpenEMR\Modules\Copilot\Conversation\ConversationRepository;
use OpenEMR\Modules\Copilot\Document\DocumentAuthorization;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleException;
use OpenEMR\Modules\Copilot\Document\LiveAccessSnapshot;
use OpenEMR\Modules\Copilot\Document\OpenEmrDocumentAudit;

final class LiveSourceReviewAuthorization implements SourceReviewAuthorizationPort
{
    public function authorize(string $conversationId, string $turnId, string $correlationId): SourceReviewContext
    {
        if (preg_match('/^[a-f0-9]{32}$/', $conversationId) !== 1
            || preg_match('/^[a-f0-9]{16}$/', $turnId) !== 1) {
            throw new SourceReviewException('invalid_contract', false, 'The source request is invalid.', 422);
        }

        try {
            $documentContext = (new DocumentAuthorization(
                new LiveAccessSnapshot('browser'),
                new OpenEmrDocumentAudit()
            ))->authorize('source_read', $correlationId);
        } catch (DocumentLifecycleException $exception) {
            throw new SourceReviewException('forbidden', false, 'Source access is not authorized.', 403);
        }

        $repository = new ConversationRepository();
        $conversation = $repository->find($conversationId);
        if ($conversation === null
            || $conversation['closed_at'] !== null
            || $repository->isIdle($conversation, new \DateTimeImmutable())
            || (string) $conversation['site_id'] !== $documentContext->siteId
            || (int) $conversation['user_id'] !== $documentContext->userId
            || (string) $conversation['username'] !== $documentContext->username
            || (int) $conversation['pid'] !== $documentContext->pid) {
            throw new SourceReviewException('patient_context_changed', false, 'The source request no longer matches the open chart.', 409);
        }

        return new SourceReviewContext(
            $documentContext->siteId,
            $documentContext->userId,
            $documentContext->pid,
            $conversationId,
            $turnId,
            $correlationId,
        );
    }
}
