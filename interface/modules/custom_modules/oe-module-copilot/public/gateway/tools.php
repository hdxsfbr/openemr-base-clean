<?php

/**
 * Tool gateway (ADR-0003 step 4). Called by the agent service on the internal
 * network with a per-turn delegation token; unrouted at the edge. Every call
 * rebuilds the AuthorizedPatientContext (ADR-0002), checks the tool's section
 * ACLs for the bound user, writes an audit event before returning data, and
 * returns the typed envelope. Denials are generic to the caller, specific in
 * the audit log.
 *
 * GET/POST ?tool=<name>   body: JSON params (since, until, limit, term, analyte)
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
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;
use OpenEMR\Modules\Copilot\Gateway\DelegationToken;
use OpenEMR\Modules\Copilot\Gateway\GatewayDenied;
use OpenEMR\Modules\Copilot\Gateway\Tools\ToolRegistry;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
$toolName = $_GET['tool'] ?? '';
$tool = is_string($toolName) ? ToolRegistry::get($toolName) : null;
if ($tool === null) {
    Json::error(404, 'invalid_request', 'Unknown tool.', $correlationId);
}

$bearer = Json::bearer();
if ($bearer === null) {
    Audit::denied(null, null, null, 'missing_token', ['tool' => $tool->name(), 'correlation_id' => $correlationId]);
    Json::error(401, 'unauthorized', 'A delegation token is required.', $correlationId);
}

$conversations = new ConversationRepository();
try {
    $payload = DelegationToken::verify($bearer);
    $ctx = (new ContextBuilder($conversations))->build($payload, $correlationId);
} catch (GatewayDenied $denied) {
    Audit::denied(null, null, null, $denied->reason, ['tool' => $tool->name(), 'correlation_id' => $correlationId]);
    $code = in_array($denied->reason, ['conversation_closed', 'user_inactive', 'breakglass', 'squad'], true) ? 'conversation_closed' : 'unauthorized';
    Json::error($denied->httpStatus, $code, 'Request denied.', $correlationId);
}

try {
    $params = ToolRegistry::params($tool, $_SERVER['REQUEST_METHOD'] === 'POST' ? Json::body() : array_diff_key($_GET, ['tool' => true]));
} catch (\InvalidArgumentException $e) {
    Audit::denied($ctx->username, $ctx->groupName, $ctx->pid, 'invalid_params', ['tool' => $tool->name(), 'correlation_id' => $correlationId, 'detail' => $e->getMessage()]);
    Json::error(400, 'invalid_request', 'Invalid tool parameters.', $correlationId);
}

// Section ACL per tool, the same checks the chart pages make (ADR-0002 section 1).
$missing = array_values(array_filter($tool->sections(), static fn(string $s): bool => !$ctx->allows($s)));
if ($missing !== []) {
    Audit::denied($ctx->username, $ctx->groupName, $ctx->pid, 'forbidden', ['tool' => $tool->name(), 'sections' => implode(',', $missing), 'conversation_id' => $ctx->conversationId, 'turn_id' => $ctx->turnId, 'correlation_id' => $correlationId]);
    // The tool answers "unavailable/forbidden" so the turn continues for other sections (ADR-0002 section 3).
    Json::send(200, $tool->unavailable($ctx, $params, 'forbidden'), $correlationId);
}

// Audit before data leaves (COMP-HIGH-004). If this insert fails the tool is unavailable.
try {
    Audit::toolRead($ctx, $tool->name(), ['since' => $params['since'], 'until' => $params['until'], 'term' => $params['term'] !== null ? 'yes' : null, 'analyte' => $params['analyte'] !== null ? 'yes' : null]);
} catch (\Throwable) {
    Json::send(200, $tool->unavailable($ctx, $params, 'audit_unavailable'), $correlationId);
}

Json::send(200, $tool->run($ctx, $params), $correlationId);
