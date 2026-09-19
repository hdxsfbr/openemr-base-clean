<?php

/**
 * Conversation binding under the user's session (ADR-0002 section 1).
 * POST {action: "resume"|"start"|"end", csrf_token, conversation_id?}
 * resume: finds the recent conversation bound to the current server-side
 * chart and user without accepting or returning a patient identifier.
 * start: binds a new conversation to (site, user, open patient); the client
 * never supplies a pid. end: closes it.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\Copilot\Compat;
use OpenEMR\Modules\Copilot\Conversation\ConversationRepository;
use OpenEMR\Modules\Copilot\Gateway\Audit;
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    Json::error(405, 'invalid_request', 'POST only.', $correlationId);
}
$session = SessionWrapperFactory::getInstance()->getActiveSession();
$userId = (int) $session->get('authUserID', 0);
$username = (string) $session->get('authUser', '');
$groupName = (string) $session->get('authProvider', 'Default');
$siteId = (string) $session->get('site_id', 'default');
if ($userId <= 0 || $username === '') {
    Json::error(401, 'unauthorized', 'Not signed in.', $correlationId);
}
$body = Json::body();
if (!CsrfUtils::verifyCsrfToken((string) ($body['csrf_token'] ?? ''), $session, 'copilot')) {
    Json::error(403, 'unauthorized', 'CSRF token invalid.', $correlationId);
}

$conversations = new ConversationRepository();
$action = $body['action'] ?? '';

if ($action === 'resume') {
    $pid = Compat::openPid();
    if ($pid <= 0) {
        Json::error(409, 'invalid_request', 'No chart is open.', $correlationId);
    }
    $conversation = $conversations->findResumable(
        $siteId,
        $userId,
        $username,
        $pid,
        new DateTimeImmutable()
    );
    Json::send(200, [
        'conversation_id' => $conversation['id'] ?? null,
        'idle_timeout_minutes' => ConversationRepository::IDLE_MINUTES,
        'correlation_id' => $correlationId,
    ], $correlationId);
}

if ($action === 'start') {
    $pid = Compat::openPid();
    if ($pid <= 0) {
        Json::error(409, 'invalid_request', 'No chart is open.', $correlationId);
    }
    if (ContextBuilder::isBreakGlass($username)) {
        Audit::denied($username, $groupName, $pid, 'breakglass', [
            'stage' => 'start',
            'correlation_id' => $correlationId,
        ]);
        Json::error(403, 'unauthorized', 'The co-pilot is not available under emergency access.', $correlationId);
    }
    $patient = QueryUtils::fetchRecords('SELECT squad FROM patient_data WHERE pid = ?', [$pid]);
    $squad = (string) ($patient[0]['squad'] ?? '');
    if (count($patient) !== 1 || ($squad !== '' && !AclMain::aclCheckCore('squads', $squad))) {
        Audit::denied($username, $groupName, $pid, 'squad', [
            'stage' => 'start',
            'correlation_id' => $correlationId,
        ]);
        Json::error(403, 'unauthorized', 'Request denied.', $correlationId);
    }
    $created = $conversations->start($siteId, $userId, $username, $pid);
    Audit::event('copilot-session-start', $username, $groupName, true, $pid, [
        'conversation_id' => $created['id'],
        'correlation_id' => $created['correlation_id'],
        'module_version' => '0.1.0',
        'policy' => 'parity-1',
    ]);
    Json::send(200, [
        'conversation_id' => $created['id'],
        'correlation_id' => $created['correlation_id'],
    ], $created['correlation_id']);
}

if ($action === 'end') {
    $conversation = $conversations->find((string) ($body['conversation_id'] ?? ''));
    if ($conversation === null || (int) $conversation['user_id'] !== $userId) {
        Json::error(404, 'invalid_request', 'Unknown conversation.', $correlationId);
    }
    if ($conversation['closed_at'] === null) {
        $conversations->close($conversation['id'], 'panel_close');
        Audit::event('copilot-session-end', $username, $groupName, true, (int) $conversation['pid'], [
            'conversation_id' => $conversation['id'],
            'turns' => (int) $conversation['turn_count'],
            'reason' => 'panel_close',
            'correlation_id' => (string) $conversation['correlation_id'],
        ]);
    }
    Json::send(200, ['conversation_id' => $conversation['id'], 'closed' => true], $correlationId);
}

Json::error(400, 'invalid_request', 'Unknown action.', $correlationId);
