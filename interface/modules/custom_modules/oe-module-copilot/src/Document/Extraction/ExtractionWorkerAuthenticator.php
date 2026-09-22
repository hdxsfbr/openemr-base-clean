<?php

/**
 * Purpose-separated request authentication for the internal extraction worker.
 * The signature covers method, route, raw body, timestamp, and a durable nonce.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

final class ExtractionWorkerAuthenticator
{
    private const PURPOSE = 'copilot-extraction-worker-v1';
    private const CANONICAL_VERSION = 'copilot-extraction-v1';
    private const MAX_SKEW_SECONDS = 60;

    /** @param callable(): \DateTimeImmutable $now */
    public function __construct(
        private readonly string $delegationSecret,
        private readonly ExtractionNoncePort $nonces,
        private readonly mixed $now,
    ) {
        if (strlen($delegationSecret) < 32) {
            throw new \InvalidArgumentException('Delegation secret must be at least 32 bytes.');
        }
    }

    /** @param array<string, string> $headers */
    public function authenticate(array $headers, string $method, string $path, string $rawBody): void
    {
        $timestamp = $headers['x-copilot-worker-timestamp'] ?? '';
        $nonce = $headers['x-copilot-worker-nonce'] ?? '';
        $signature = $headers['x-copilot-worker-signature'] ?? '';
        $now = ($this->now)();
        if (preg_match('/^[0-9]{10}$/', $timestamp) !== 1
            || preg_match('/^[a-f0-9]{32}$/', $nonce) !== 1
            || preg_match('/^[a-f0-9]{64}$/', $signature) !== 1
            || abs($now->getTimestamp() - (int) $timestamp) > self::MAX_SKEW_SECONDS
            || $method !== 'POST'
            || $path !== '/gateway/extraction.php') {
            throw $this->unauthorized();
        }
        $canonical = self::CANONICAL_VERSION . "\n{$timestamp}\n{$nonce}\n{$method}\n{$path}\n" . hash('sha256', $rawBody);
        $key = hash_hmac('sha256', self::PURPOSE, $this->delegationSecret, true);
        $expected = hash_hmac('sha256', $canonical, $key);
        if (!hash_equals($expected, $signature)
            || !$this->nonces->consume($nonce, $now->modify('+' . self::MAX_SKEW_SECONDS . ' seconds'))) {
            throw $this->unauthorized();
        }
    }

    private function unauthorized(): ExtractionGatewayException
    {
        return new ExtractionGatewayException('unauthorized', false, 'Worker request denied.', 401);
    }
}

