<?php

/**
 * Minimal JSON request/response helpers for the module endpoints. Error
 * bodies are generic (code, message, correlation id); details go to the log.
 *
/**
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Http;

final class Json
{
    public static function correlationId(): string
    {
        $header = $_SERVER['HTTP_X_CORRELATION_ID'] ?? '';
        return is_string($header) && preg_match('/^[A-Za-z0-9\-._]{8,64}$/', $header) ? $header : bin2hex(random_bytes(8));
    }

    /** @return array<string, mixed> */
    public static function body(): array
    {
        $raw = file_get_contents('php://input');
        if ($raw === false || trim($raw) === '') {
            return [];
        }
        $decoded = json_decode($raw, true);
        return is_array($decoded) ? $decoded : [];
    }

    /**
     * The delegation token from `X-Copilot-Token`, or from `Authorization: Bearer`.
     * mod_php does not expose Authorization in $_SERVER unless Apache is
     * configured to pass it, so the raw request headers are consulted too.
     */
    public static function bearer(): ?string
    {
        $candidates = [$_SERVER['HTTP_X_COPILOT_TOKEN'] ?? null, $_SERVER['HTTP_AUTHORIZATION'] ?? null, $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? null];
        if (function_exists('apache_request_headers')) {
            $headers = array_change_key_case((array) apache_request_headers(), CASE_LOWER);
            $candidates[] = $headers['x-copilot-token'] ?? null;
            $candidates[] = $headers['authorization'] ?? null;
        }
        foreach ($candidates as $value) {
            if (!is_string($value) || $value === '') {
                continue;
            }
            if (preg_match('/^(?:Bearer\s+)?([A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)$/', trim($value), $m)) {
                return $m[1];
            }
        }
        return null;
    }

    /** @param array<string, mixed> $payload */
    public static function send(int $status, array $payload, string $correlationId): never
    {
        http_response_code($status);
        header('Content-Type: application/json');
        header('Cache-Control: no-store');
        header('X-Correlation-Id: ' . $correlationId);
        echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
        exit;
    }

    public static function error(int $status, string $code, string $message, string $correlationId): never
    {
        self::send($status, ['code' => $code, 'message' => $message, 'correlation_id' => $correlationId], $correlationId);
    }
}
