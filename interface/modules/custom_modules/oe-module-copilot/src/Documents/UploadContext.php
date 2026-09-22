<?php

/**
 * Trusted context for a browser-originated source-document operation.
 *
 * The browser never constructs this object: the module derives it from the
 * live OpenEMR session and repeats the chart, ACL, squad, and break-glass
 * checks before storage and before any later source read.
 *
 * @package   OpenEMR
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Documents;

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\Copilot\Compat;
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;
use OpenEMR\Modules\Copilot\Gateway\GatewayDenied;

final readonly class UploadContext
{
    public function __construct(
        public string $siteId,
        public int $userId,
        public string $username,
        public string $groupName,
        public int $pid,
        public string $correlationId,
    ) {
    }

    /** @throws GatewayDenied */
    public static function fromSession(string $correlationId): self
    {
        $session = SessionWrapperFactory::getInstance()->getActiveSession();
        $userId = (int) $session->get('authUserID', 0);
        $username = (string) $session->get('authUser', '');
        if ($userId <= 0 || $username === '') {
            throw new GatewayDenied('unauthorized', 401);
        }
        if (ContextBuilder::isBreakGlass($username)) {
            throw new GatewayDenied('breakglass', 403);
        }
        $pid = Compat::openPid();
        if ($pid <= 0) {
            throw new GatewayDenied('patient_context_changed', 409);
        }
        $user = QueryUtils::fetchRecords('SELECT active FROM users WHERE id = ?', [$userId]);
        if (count($user) !== 1 || (int) $user[0]['active'] !== 1) {
            throw new GatewayDenied('user_inactive', 403);
        }
        $patient = QueryUtils::fetchRecords('SELECT squad FROM patient_data WHERE pid = ?', [$pid]);
        $squad = (string) ($patient[0]['squad'] ?? '');
        if (count($patient) !== 1 || ($squad !== '' && !AclMain::aclCheckCore('squads', $squad, $username))) {
            throw new GatewayDenied('squad', 403);
        }
        // This mirrors the standard document endpoint's write-or-add-only boundary.
        if (!AclMain::aclCheckCore('patients', 'docs', $username, ['write', 'addonly'])) {
            throw new GatewayDenied('document_acl', 403);
        }
        return new self(
            siteId: (string) $session->get('site_id', 'default'),
            userId: $userId,
            username: $username,
            groupName: (string) $session->get('authProvider', 'Default'),
            pid: $pid,
            correlationId: $correlationId,
        );
    }
}
