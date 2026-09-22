<?php

/** Create a server-bound Slice 1 lab-upload intent. @package OpenEMR */

require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\Copilot\Documents\SourceDocumentRepository;
use OpenEMR\Modules\Copilot\Documents\UploadContext;
use OpenEMR\Modules\Copilot\Documents\UploadRequestPolicy;
use OpenEMR\Modules\Copilot\Gateway\Audit;
use OpenEMR\Modules\Copilot\Gateway\GatewayDenied;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    Json::error(405, 'invalid_request', 'POST only.', $correlationId);
}
$body = Json::body();
$session = SessionWrapperFactory::getInstance()->getActiveSession();
if (!CsrfUtils::verifyCsrfToken((string) ($body['csrf_token'] ?? ''), $session, 'copilot')) {
    Json::error(403, 'unauthorized', 'CSRF token invalid.', $correlationId);
}
if (!UploadRequestPolicy::acceptsIntent($body)) {
    Json::error(400, 'invalid_request', 'Unsupported document request.', $correlationId);
}
try {
    $ctx = UploadContext::fromSession($correlationId);
    $intent = (new SourceDocumentRepository())->createIntent($ctx);
    Audit::event('copilot-document-intent', $ctx->username, $ctx->groupName, true, $ctx->pid, [
        'intent_id' => $intent['intent_id'], 'document_type' => 'lab_pdf', 'correlation_id' => $correlationId,
    ]);
    Json::send(201, $intent + ['correlation_id' => $correlationId], $correlationId);
} catch (GatewayDenied $denied) {
    Audit::denied(null, null, null, $denied->reason, ['stage' => 'document_intent', 'correlation_id' => $correlationId]);
    Json::error($denied->httpStatus, 'unauthorized', 'Request denied.', $correlationId);
}
