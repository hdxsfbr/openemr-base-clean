<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\SourceReview;

final class SourceReviewHttp
{
    public function __construct(private readonly SourceReview $review)
    {
    }

    /** @param array<string, mixed> $request @return array{http_status: int, body: array<string, mixed>} */
    public function handle(array $request, string $correlationId): array
    {
        try {
            return [
                'http_status' => 200,
                'body' => $this->review->open($request, $correlationId) + ['correlation_id' => $correlationId],
            ];
        } catch (SourceReviewException $exception) {
            return [
                'http_status' => $exception->httpStatus,
                'body' => [
                    'status' => 'unavailable',
                    'code' => $exception->errorCode,
                    'retryable' => $exception->retryable,
                    'limitation' => self::limitation($exception->errorCode),
                    'correlation_id' => $correlationId,
                ],
            ];
        } catch (\Throwable $exception) {
            return [
                'http_status' => 503,
                'body' => [
                    'status' => 'unavailable',
                    'code' => 'source_unavailable',
                    'retryable' => true,
                    'limitation' => self::limitation('source_unavailable'),
                    'correlation_id' => $correlationId,
                ],
            ];
        }
    }

    private static function limitation(string $code): string
    {
        return match ($code) {
            'invalid_contract' => 'The source request was not accepted. The verified answer remains available.',
            'forbidden', 'unauthorized', 'patient_context_changed', 'conversation_closed' =>
                'Source access is no longer authorized. Reopen the chart and try again.',
            'guideline_stale' =>
                'The guideline evidence is no longer current and cannot be opened. Patient-record claims remain available.',
            'source_integrity_failed' =>
                'The source failed its integrity checks and cannot be shown. The verified answer remains available.',
            default => 'This source cannot be opened right now. The verified answer remains available.',
        };
    }
}
