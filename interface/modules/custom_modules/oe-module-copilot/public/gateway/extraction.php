<?php

/**
 * Internal-only extraction worker endpoint. The edge proxy must not route it.
 * Every raw request is HMAC authenticated before JSON parsing.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3
 */

$ignoreAuth = true;
require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Modules\Copilot\Document\Extraction\ExtractionWorkerFactory;
use OpenEMR\Modules\Copilot\Http\Json;

$raw = file_get_contents('php://input');
$raw = is_string($raw) ? $raw : '';
$headers = [];
foreach ([
    'HTTP_X_COPILOT_WORKER_TIMESTAMP' => 'x-copilot-worker-timestamp',
    'HTTP_X_COPILOT_WORKER_NONCE' => 'x-copilot-worker-nonce',
    'HTTP_X_COPILOT_WORKER_SIGNATURE' => 'x-copilot-worker-signature',
] as $serverKey => $header) {
    if (is_string($_SERVER[$serverKey] ?? null)) {
        $headers[$header] = trim($_SERVER[$serverKey]);
    }
}
$correlationId = Json::correlationId();
try {
    $response = ExtractionWorkerFactory::http()->handle(
        (string) ($_SERVER['REQUEST_METHOD'] ?? ''),
        '/gateway/extraction.php',
        (string) ($_SERVER['REMOTE_ADDR'] ?? ''),
        $headers,
        $raw,
        $correlationId
    );
} catch (\Throwable $exception) {
    error_log('oe-module-copilot extraction gateway bootstrap failed: ' . $exception::class);
    $response = ['status' => 503, 'body' => [
        'code' => 'unavailable',
        'correlation_id' => $correlationId,
        'retryable' => true,
        'limitation' => 'The extraction gateway is unavailable.',
    ]];
}
Json::send($response['status'], $response['body'], $correlationId);
