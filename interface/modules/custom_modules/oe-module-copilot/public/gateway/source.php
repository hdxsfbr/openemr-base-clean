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
    header('Content-Type: application/pdf');
    header('Cache-Control: no-store');
    header('X-Correlation-Id: ' . $correlationId);
    header('X-Copilot-Source-Id: ' . $result['source']['source_id']);
    echo $result['bytes'];
} catch (GatewayDenied $denied) {
    Audit::denied(null, null, null, $denied->reason, ['stage' => 'source_read', 'correlation_id' => $correlationId]);
    Json::error($denied->httpStatus, 'unauthorized', 'Request denied.', $correlationId);
}
