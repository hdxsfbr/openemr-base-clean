<?php

/**
 * Per-turn delegation token (ADR-0005). HMAC-SHA256 over a JSON payload that
 * carries only the conversation id, a turn id, and times; never a user or
 * patient identifier. The secret is a file shared with the agent container.
 *
/**
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway;

use OpenEMR\Modules\Copilot\Compat;

final class DelegationToken
{
    public const TTL_SECONDS = 90;
    public const VERSION = 1;

    /** @return array{cid: string, jti: string, iat: int, exp: int, v: int} */
    public static function mint(string $conversationId, string $turnId, int $ttl = self::TTL_SECONDS): array
    {
        $now = time();
        $payload = ['cid' => $conversationId, 'jti' => $turnId, 'iat' => $now, 'exp' => $now + $ttl, 'v' => self::VERSION];
        return $payload;
    }

    /** @param array{cid: string, jti: string, iat: int, exp: int, v: int} $payload */
    public static function encode(array $payload): string
    {
        $body = self::b64(json_encode($payload, JSON_THROW_ON_ERROR));
        return $body . '.' . self::b64(hash_hmac('sha256', $body, self::secret(), true));
    }

    /**
     * @return array{cid: string, jti: string, iat: int, exp: int, v: int}
     * @throws GatewayDenied
     */
    public static function verify(string $token): array
    {
        $parts = explode('.', $token);
        if (count($parts) !== 2 || $parts[0] === '' || $parts[1] === '') {
            throw new GatewayDenied('bad_token');
        }
        $expected = self::b64(hash_hmac('sha256', $parts[0], self::secret(), true));
        if (!hash_equals($expected, $parts[1])) {
            throw new GatewayDenied('bad_token');
        }
        $json = self::unb64($parts[0]);
        $payload = $json === null ? null : json_decode($json, true);
        if (
            !is_array($payload)
            || !isset($payload['cid'], $payload['jti'], $payload['iat'], $payload['exp'], $payload['v'])
            || !is_string($payload['cid']) || !is_string($payload['jti'])
            || !is_int($payload['iat']) || !is_int($payload['exp']) || $payload['v'] !== self::VERSION
            || !preg_match('/^[a-f0-9]{32}$/', $payload['cid']) || !preg_match('/^[a-f0-9]{16}$/', $payload['jti'])
        ) {
            throw new GatewayDenied('bad_token');
        }
        if ($payload['exp'] < time() || $payload['iat'] > time() + 30) {
            throw new GatewayDenied('token_expired');
        }
        return $payload;
    }

    private static function secret(): string
    {
        $path = getenv('COPILOT_DELEGATION_SECRET_FILE') ?: '/run/secrets/copilot_delegation_secret';
        if (!is_readable($path)) {
            // Development fallback: a per-site secret outside the web root, created once.
            $dir = Compat::siteDir() . '/documents/copilot';
            $path = $dir . '/delegation_secret';
            if (!is_file($path)) {
                if (!is_dir($dir)) {
                    mkdir($dir, 0700, true);
                }
                file_put_contents($path, bin2hex(random_bytes(32)));
                chmod($path, 0600);
            }
        }
        $secret = trim((string) file_get_contents($path));
        if (strlen($secret) < 32) {
            throw new \RuntimeException('Delegation secret missing or too short');
        }
        return $secret;
    }

    private static function b64(string $raw): string
    {
        return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
    }

    private static function unb64(string $encoded): ?string
    {
        $decoded = base64_decode(strtr($encoded, '-_', '+/'), true);
        return $decoded === false ? null : $decoded;
    }
}
