<?php

/**
 * Authenticated patient-bound document upload routes.
 *
 * POST /documents.php/upload-intents
 * POST /documents.php/upload-intents/{uuid}/content
 *
 * The active patient is read only from the OpenEMR session. Neither route
 * accepts a patient, site, user, filesystem path, or OpenEMR document id.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleException;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleFactory;
use OpenEMR\Modules\Copilot\Document\HttpUploadFile;
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
$auditRouteDenial = static function (string $reason) use ($session, $correlationId): void {
    Audit::denied(
        (string) $session->get('authUser', ''),
        (string) $session->get('authProvider', 'Default'),
        (int) $session->get('pid', 0) ?: null,
        $reason,
        ['stage' => 'document_route', 'correlation_id' => $correlationId]
    );
};
$path = '/' . trim((string) ($_SERVER['PATH_INFO'] ?? ''), '/');

try {
    $lifecycle = DocumentLifecycleFactory::browser();

    if ($path === '/upload-intents') {
        $body = Json::body();
        $csrf = $body['csrf_token'] ?? null;
        if (!is_string($csrf) || !CsrfUtils::verifyCsrfToken($csrf, $session, 'copilot')) {
            $auditRouteDenial('csrf');
            throw new DocumentLifecycleException('forbidden', false, 'The request is not authorized.', 403);
        }
        unset($body['csrf_token']);
        Json::send(200, $lifecycle->createUploadIntent($body, $correlationId), $correlationId);
    }

    if (preg_match('#^/upload-intents/([0-9a-f-]{36})/content$#', $path, $match) === 1) {
        $postKeys = array_keys($_POST);
        sort($postKeys);
        if ($postKeys !== ['csrf_token', 'upload_token'] || array_keys($_FILES) !== ['content']) {
            $auditRouteDenial('invalid_contract');
            throw new DocumentLifecycleException('invalid_contract', false, 'The upload request is invalid.', 422);
        }
        if (!CsrfUtils::verifyCsrfToken((string) $_POST['csrf_token'], $session, 'copilot')) {
            $auditRouteDenial('csrf');
            throw new DocumentLifecycleException('forbidden', false, 'The request is not authorized.', 403);
        }
        try {
            $upload = HttpUploadFile::fromPhpUpload((array) $_FILES['content']);
        } catch (DocumentLifecycleException $exception) {
            $auditRouteDenial($exception->errorCode);
            throw $exception;
        }
        Json::send(200, $lifecycle->uploadContent(
            $match[1],
            (string) $_POST['upload_token'],
            $upload,
            $correlationId
        ), $correlationId);
    }

    throw new DocumentLifecycleException('not_found', false, 'The document route was not found.', 404);
} catch (DocumentLifecycleException $exception) {
    $error($exception);
} catch (Throwable $exception) {
    // Never log exception messages here: upstream storage failures can contain
    // paths. The class is sufficient for server-side diagnosis correlation.
    error_log('oe-module-copilot: document route failed [' . $correlationId . '] ' . $exception::class);
    $error(new DocumentLifecycleException('unavailable', true, 'The document service is unavailable.', 503));
}
