<?php

/**
 * Internal adapter for the server-owned source registry. The browser never
 * sends source metadata to this adapter. The agent-side resolver must re-open
 * the current source and return both its resolver-authored citation and its
 * freshly checked view projection.
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\SourceReview;

use OpenEMR\Modules\Copilot\Gateway\DelegationToken;

final class AgentSourceReviewAuthority implements CitationAuthorityPort, SourceViewAuthorityPort
{
    /** @var array<string, array{citation: array<string, mixed>, source: array<string, mixed>}> */
    private array $resolved = [];

    public function __construct(private readonly string $baseUrl)
    {
    }

    public function find(SourceReviewContext $context, string $citationId): ?array
    {
        $key = $this->key($context, $citationId);
        if (!isset($this->resolved[$key])) {
            $response = $this->request($context, $citationId);
            if ($response === null) {
                return null;
            }
            $this->resolved[$key] = $response;
        }
        return $this->resolved[$key]['citation'];
    }

    public function resolve(SourceReviewContext $context, array $citation): ?array
    {
        $citationId = $citation['citation_id'] ?? null;
        if (!is_string($citationId)) {
            return null;
        }
        $key = $this->key($context, $citationId);
        return $this->resolved[$key]['source'] ?? null;
    }

    /** @return array{citation: array<string, mixed>, source: array<string, mixed>}|null */
    private function request(SourceReviewContext $context, string $citationId): ?array
    {
        $token = DelegationToken::encode(DelegationToken::mint($context->conversationId, $context->turnId));
        $url = rtrim($this->baseUrl, '/') . '/v1/conversations/' . rawurlencode($context->conversationId)
            . '/turns/' . rawurlencode($context->turnId) . '/sources/' . rawurlencode($citationId);
        $handle = curl_init($url);
        if ($handle === false) {
            return null;
        }
        curl_setopt_array($handle, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT_MS => 1_000,
            CURLOPT_TIMEOUT_MS => 5_000,
            CURLOPT_HTTPHEADER => [
                'Accept: application/json',
                'X-Copilot-Token: ' . $token,
                'X-Correlation-Id: ' . $context->correlationId,
            ],
        ]);
        $body = curl_exec($handle);
        $status = (int) curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
        curl_close($handle);
        if (!is_string($body) || $status !== 200 || strlen($body) > 12_000_000) {
            return null;
        }
        try {
            $decoded = json_decode($body, true, 64, JSON_THROW_ON_ERROR);
        } catch (\JsonException $exception) {
            return null;
        }
        if (!is_array($decoded)
            || !is_array($decoded['citation'] ?? null)
            || !is_array($decoded['source'] ?? null)
            || ($decoded['citation']['citation_id'] ?? null) !== $citationId) {
            return null;
        }
        return ['citation' => $decoded['citation'], 'source' => $decoded['source']];
    }

    private function key(SourceReviewContext $context, string $citationId): string
    {
        return $context->conversationId . ':' . $context->turnId . ':' . $citationId;
    }
}
