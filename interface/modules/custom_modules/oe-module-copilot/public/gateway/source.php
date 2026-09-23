<?php

/** Internal source-byte read for the bounded intake-extractor worker. @package OpenEMR */

$ignoreAuth = true;
require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Modules\Copilot\Conversation\ConversationRepository;
use OpenEMR\Modules\Copilot\Documents\SourceReader;
use OpenEMR\Modules\Copilot\Gateway\Audit;
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;
use OpenEMR\Modules\Copilot\Gateway\DelegationToken;
use OpenEMR\Modules\Copilot\Gateway\GatewayDenied;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
try {
    $bearer = Json::bearer();
    if ($bearer === null) {
        throw new GatewayDenied('missing_token', 401);
    }
    $token = DelegationToken::verify($bearer);
    $ctx = (new ContextBuilder(new ConversationRepository()))->build($token, $correlationId);
    $result = (new SourceReader())->read($ctx, (string) ($_GET['source_id'] ?? ''));
    Audit::toolRead($ctx, 'source_document', ['source_id' => $result['source']['source_id'], 'bytes' => (int) $result['source']['byte_size']]);
    // AI disclosure (same rule as tools.php): the bytes this call returns are
    // about to leave for the extraction worker's model provider (GitLab #55 --
    // #53/#54 wired the OpenRouter call but left this read undisclosed). The
    // agent declares {provider, model} on every read; no audit row means no bytes.
    $declaredProvider = $_GET['provider'] ?? null;
    $declaredModel = $_GET['model'] ?? null;
    if (is_string($declaredProvider) && is_string($declaredModel)) {
        try {
            Audit::modelDisclosure(
                $ctx,
                ['provider' => $declaredProvider, 'model' => $declaredModel],
                [['tool' => 'source_document', 'records' => 1]]
            );
        } catch (\Throwable $e) {
            error_log('oe-module-copilot gateway/source.php disclosure audit failed: ' . $e::class);
            throw new GatewayDenied('audit_unavailable', 503);
        }
    }
    header('Content-Type: ' . $result['source']['mime_type']);
    header('Cache-Control: no-store');
    header('X-Correlation-Id: ' . $correlationId);
    header('X-Copilot-Source-Id: ' . $result['source']['source_id']);
    header('X-Copilot-Document-Type: ' . $result['source']['document_type']);
    // Integrity metadata only: the worker recomputes this hash over the
    // returned bytes before a resolver may cite any proposed field.
    header('X-Copilot-Source-Hash: ' . $result['source']['content_hash']);
    echo $result['bytes'];
} catch (GatewayDenied $denied) {
    Audit::denied(null, null, null, $denied->reason, ['stage' => 'source_read', 'correlation_id' => $correlationId]);
    Json::error($denied->httpStatus, 'unauthorized', 'Request denied.', $correlationId);
} catch (\Throwable) {
    Audit::denied(null, null, null, 'source_unavailable', ['stage' => 'source_read', 'correlation_id' => $correlationId]);
    Json::error(503, 'dependency_unavailable', 'Source temporarily unavailable.', $correlationId);
}
