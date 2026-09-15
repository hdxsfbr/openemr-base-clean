<?php

/**
 * Per-turn delegation ticket (ADR-0005 decision 2). Under the user's session
 * with CSRF, re-checks: session alive, user active, the open chart equals the
 * bound patient, not break-glass. A mismatch closes the conversation. Returns a
 * 90-second token that carries no user or patient identifier.
 *
 * POST {csrf_token, conversation_id}
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\Copilot\Compat;
use OpenEMR\Modules\Copilot\Conversation\ConversationRepository;
use OpenEMR\Modules\Copilot\Gateway\Audit;
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;
use OpenEMR\Modules\Copilot\Gateway\DelegationToken;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    Json::error(405, 'invalid_request', 'POST only.', $correlationId);
}
$session = SessionWrapperFactory::getInstance()->getActiveSession();
$userId = (int) $session->get('authUserID', 0);
$username = (string) $session->get('authUser', '');
$groupName = (string) $session->get('authProvider', 'Default');
if ($userId <= 0 || $username === '') {
    Json::error(401, 'unauthorized', 'Not signed in.', $correlationId);
}
$body = Json::body();
if (!CsrfUtils::verifyCsrfToken((string) ($body['csrf_token'] ?? ''), $session, 'copilot')) {
    Json::error(403, 'unauthorized', 'CSRF token invalid.', $correlationId);
}

$conversations = new ConversationRepository();
$conversation = $conversations->find((string) ($body['conversation_id'] ?? ''));
if ($conversation === null || (int) $conversation['user_id'] !== $userId || $conversation['username'] !== $username) {
    Json::error(404, 'invalid_request', 'Unknown conversation.', $correlationId);
}
$pid = (int) $conversation['pid'];
$baseCorrelation = (string) $conversation['correlation_id'];

if ($conversation['closed_at'] !== null) {
    Json::error(409, 'conversation_closed', 'This conversation is closed.', $baseCorrelation);
}

$user = QueryUtils::fetchRecords('SELECT active FROM users WHERE id = ?', [$userId]);
if ((int) ($user[0]['active'] ?? 0) !== 1) {
    $conversations->close($conversation['id'], 'user_inactive');
    Audit::denied($username, $groupName, $pid, 'user_inactive', ['stage' => 'ticket', 'conversation_id' => $conversation['id'], 'correlation_id' => $baseCorrelation]);
    Json::error(403, 'conversation_closed', 'Request denied.', $baseCorrelation);
}
if (ContextBuilder::isBreakGlass($username)) {
    $conversations->close($conversation['id'], 'breakglass');
    Audit::denied($username, $groupName, $pid, 'breakglass', ['stage' => 'ticket', 'conversation_id' => $conversation['id'], 'correlation_id' => $baseCorrelation]);
    Json::error(403, 'conversation_closed', 'Request denied.', $baseCorrelation);
}
if (Compat::openPid() !== $pid) {
    // SEC-HIGH-002 / ARCH-HIGH-001: the session pid is a request, not a grant.
    $conversations->close($conversation['id'], 'patient_context_changed');
    Audit::denied($username, $groupName, $pid, 'patient_context_changed', ['stage' => 'ticket', 'conversation_id' => $conversation['id'], 'correlation_id' => $baseCorrelation]);
    Json::error(409, 'patient_context_changed', 'The open chart changed; start a new conversation for it.', $baseCorrelation);
}

$turn = $conversations->nextTurn($conversation['id']);
$turnId = bin2hex(random_bytes(8));
$payload = DelegationToken::mint($conversation['id'], $turnId);
Json::send(200, [
    'token' => DelegationToken::encode($payload),
    'expires_in' => DelegationToken::TTL_SECONDS,
    'turn' => $turn,
    'correlation_id' => $baseCorrelation . '.' . $turn,
], $baseCorrelation . '.' . $turn);
