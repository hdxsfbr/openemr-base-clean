<?php

/**
 * Tool gateway (ADR-0003 step 4). Called by the agent service on the internal
 * network with a per-turn delegation token; unrouted at the edge. Every
 * request rebuilds the AuthorizedPatientContext once (ADR-0002); each tool it
 * serves gets its own section-ACL check, audit event before data returns, and
 * typed envelope, so one tool's denial or failure never affects another's.
 * Denials are generic to the caller, specific in the audit log.
 *
 * GET/POST ?tool=<name>   body: JSON params (since, until, limit, term, analyte)
 * POST (no ?tool)         body: {"calls": [{"tool": <name>, "params": {...}}, ...]}
 *                         -> {"results": [<envelope>, ...]}, one per call, in
 *                         request order. Added to serve a turn's whole tool
 *                         fan-out in one request instead of one bootstrap
 *                         (globals.php: translations, ACL, layout lookups,
 *                         PERF-MED-002) per tool call.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

$ignoreAuth = true;
require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Modules\Copilot\Conversation\ConversationRepository;
use OpenEMR\Modules\Copilot\Gateway\Audit;
use OpenEMR\Modules\Copilot\Gateway\BatchRunner;
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;
use OpenEMR\Modules\Copilot\Gateway\DelegationToken;
use OpenEMR\Modules\Copilot\Gateway\GatewayDenied;
use OpenEMR\Modules\Copilot\Gateway\Tools\ToolRegistry;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();

$bearer = Json::bearer();
if ($bearer === null) {
    Audit::denied(null, null, null, 'missing_token', ['correlation_id' => $correlationId]);
    Json::error(401, 'unauthorized', 'A delegation token is required.', $correlationId);
}

$conversations = new ConversationRepository();
try {
    $payload = DelegationToken::verify($bearer);
    $ctx = (new ContextBuilder($conversations))->build($payload, $correlationId);
} catch (GatewayDenied $denied) {
    Audit::denied(null, null, null, $denied->reason, ['correlation_id' => $correlationId]);
    $code = in_array($denied->reason, ['conversation_closed', 'user_inactive', 'breakglass', 'squad'], true) ? 'conversation_closed' : 'unauthorized';
    Json::error($denied->httpStatus, $code, 'Request denied.', $correlationId);
}

$toolName = $_GET['tool'] ?? '';
if (is_string($toolName) && $toolName !== '') {
    // Legacy single-tool request; kept working unchanged as the rollback path.
    $tool = ToolRegistry::get($toolName);
    if ($tool === null) {
        Audit::denied($ctx->username, $ctx->groupName, $ctx->pid, 'unknown_tool', ['tool' => $toolName, 'correlation_id' => $correlationId]);
        Json::error(404, 'invalid_request', 'Unknown tool.', $correlationId);
    }
    $raw = $_SERVER['REQUEST_METHOD'] === 'POST' ? Json::body() : array_diff_key($_GET, ['tool' => true]);
    Json::send(200, BatchRunner::runOne($tool, $ctx, $raw), $correlationId);
}

// Batch request: one context build serves every tool the turn needs.
$body = Json::body();
$calls = $body['calls'] ?? null;
if (!is_array($calls) || $calls === []) {
    Json::error(400, 'invalid_request', 'A non-empty "calls" list is required.', $correlationId);
}

$results = [];
foreach ($calls as $call) {
    $requestedName = is_array($call) && is_string($call['tool'] ?? null) ? $call['tool'] : null;
    if ($requestedName === null) {
        Json::error(400, 'invalid_request', 'Each call needs a "tool" name.', $correlationId);
    }
    try {
        $tool = ToolRegistry::get($requestedName);
        if ($tool === null) {
            Audit::denied($ctx->username, $ctx->groupName, $ctx->pid, 'unknown_tool', ['tool' => $requestedName, 'correlation_id' => $correlationId]);
            $results[] = BatchRunner::rawUnavailable($requestedName, $ctx, 'unknown_tool');
            continue;
        }
        $rawParams = is_array($call['params'] ?? null) ? $call['params'] : [];
        $results[] = BatchRunner::runOne($tool, $ctx, $rawParams);
    } catch (\Throwable $e) {
        // One item's unexpected failure must never orphan the rest of the batch's response.
        error_log('oe-module-copilot tools.php batch item failed: ' . $requestedName . ': ' . $e::class);
        $results[] = BatchRunner::rawUnavailable($requestedName, $ctx, 'service_error');
    }
}

Json::send(200, ['results' => $results], $correlationId);
