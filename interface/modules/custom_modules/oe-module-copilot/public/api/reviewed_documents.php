<?php

/**
 * Browser-only physician review, promotion, amendment, and withdrawal routes.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleException;
use OpenEMR\Modules\Copilot\Document\Review\ReviewWorkflowFactory;
use OpenEMR\Modules\Copilot\Gateway\Audit;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
$error = static function (DocumentLifecycleException $exception) use ($correlationId): never {
    Json::send($exception->httpStatus, [
        'code' => $exception->errorCode,
        'correlation_id' => $correlationId,
        'retryable' => $exception->retryable,
        'limitation' => $exception->getMessage(),
    ], $correlationId);
};

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    $error(new DocumentLifecycleException('invalid_contract', false, 'POST is required.', 405));
}

$session = SessionWrapperFactory::getInstance()->getActiveSession();
$auditDenial = static function (string $reason) use ($session, $correlationId): void {
    Audit::denied(
        (string) $session->get('authUser', ''),
        (string) $session->get('authProvider', 'Default'),
        (int) $session->get('pid', 0) ?: null,
        $reason,
        ['stage' => 'reviewed_document_route', 'correlation_id' => $correlationId]
    );
};

try {
    $body = Json::body();
    $csrf = $body['csrf_token'] ?? null;
    if (!is_string($csrf) || !CsrfUtils::verifyCsrfToken($csrf, $session, 'copilot')) {
        $auditDenial('csrf');
        throw new DocumentLifecycleException('forbidden', false, 'The request is not authorized.', 403);
    }
    unset($body['csrf_token']);
    $path = '/' . trim((string) ($_SERVER['PATH_INFO'] ?? ''), '/');
    $workflow = ReviewWorkflowFactory::browser();

    if ($path === '/document-reviews') {
        Json::send(200, $workflow->review($body, $correlationId), $correlationId);
    }
    if ($path === '/document-promotions') {
        Json::send(200, $workflow->promote($body, $correlationId), $correlationId);
    }
    if (preg_match('#^/reviewed-records/([0-9a-f-]{36})/revisions$#', $path, $match) === 1) {
        if (array_key_exists('record_id', $body)) {
            $auditDenial('invalid_contract');
            throw new DocumentLifecycleException('invalid_contract', false, 'The record identity must come from the route.', 422);
        }
        $body['record_id'] = $match[1];
        Json::send(200, $workflow->revise($body, $correlationId), $correlationId);
    }
    throw new DocumentLifecycleException('not_found', false, 'The reviewed-document route was not found.', 404);
} catch (DocumentLifecycleException $exception) {
    $error($exception);
} catch (Throwable $exception) {
    error_log('oe-module-copilot: reviewed-document route failed [' . $correlationId . '] ' . $exception::class);
    $error(new DocumentLifecycleException('unavailable', true, 'The reviewed-document service is unavailable.', 503));
}
