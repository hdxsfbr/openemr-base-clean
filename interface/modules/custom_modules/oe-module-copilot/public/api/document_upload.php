<?php

/** Store exactly one lab PDF for a previously server-bound upload intent. @package OpenEMR */

require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\Copilot\Documents\LabPdfPolicy;
use OpenEMR\Modules\Copilot\Documents\SourceDocumentRepository;
use OpenEMR\Modules\Copilot\Documents\SourceUploadException;
use OpenEMR\Modules\Copilot\Documents\UploadContext;
use OpenEMR\Modules\Copilot\Gateway\Audit;
use OpenEMR\Modules\Copilot\Gateway\GatewayDenied;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    Json::error(405, 'invalid_request', 'POST only.', $correlationId);
}
$session = SessionWrapperFactory::getInstance()->getActiveSession();
if (!CsrfUtils::verifyCsrfToken((string) ($_POST['csrf_token'] ?? ''), $session, 'copilot')) {
    Json::error(403, 'unauthorized', 'CSRF token invalid.', $correlationId);
}
if (isset($_POST['pid'], $_POST['patient_id'], $_POST['document_type'])) {
    Json::error(400, 'invalid_request', 'Unsupported document request.', $correlationId);
}
try {
    $ctx = UploadContext::fromSession($correlationId);
    $intentId = (string) ($_POST['intent_id'] ?? '');
    if (!preg_match('/^[a-f0-9]{32}$/', $intentId)) {
        Json::error(400, 'invalid_request', 'Unsupported document request.', $correlationId);
    }
    $repository = new SourceDocumentRepository();
    $existing = $repository->sourceForIntent($intentId);
    if ($existing !== null) {
        $repository->assertIntentUsable($ctx, $intentId);
        Json::send(200, ['contract_version' => '2.0.0', 'intent_id' => $intentId, 'status' => 'stored', 'source' => SourceDocumentRepository::publicSource($existing)], $correlationId);
    }
    $file = LabPdfPolicy::validate($_FILES['document'] ?? []);
    $source = $repository->store($ctx, $intentId, $file, $file['bytes']);
    Audit::event('copilot-document-stored', $ctx->username, $ctx->groupName, true, $ctx->pid, [
        'source_id' => $source['source_id'], 'intent_id' => $intentId, 'document_type' => 'lab_pdf',
        'bytes' => $file['byte_size'], 'pages' => $file['page_count'], 'content_hash' => $file['content_hash'], 'correlation_id' => $correlationId,
    ]);
    Json::send(201, ['contract_version' => '2.0.0', 'intent_id' => $intentId, 'status' => 'stored', 'source' => SourceDocumentRepository::publicSource($source)], $correlationId);
} catch (GatewayDenied $denied) {
    Audit::denied(null, null, null, $denied->reason, ['stage' => 'document_upload', 'correlation_id' => $correlationId]);
    Json::error($denied->httpStatus, 'unauthorized', 'Request denied.', $correlationId);
} catch (SourceUploadException $error) {
    // Deliberately no document filename, bytes, content, patient, or session details.
    Json::send(409, ['contract_version' => '2.0.0', 'intent_id' => $intentId, 'status' => 'rejected', 'limitation' => ['code' => $error->reason, 'detail' => 'The document could not be stored.']], $correlationId);
}
