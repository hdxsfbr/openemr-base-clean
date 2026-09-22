<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Common\Uuid\UuidRegistry;
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;

final class LiveAccessSnapshot implements AccessSnapshotPort
{
    public function __construct(private readonly string $principal = 'browser')
    {
    }

    public function current(): AccessSnapshot
    {
        $session = SessionWrapperFactory::getInstance()->getActiveSession();
        $userId = (int) $session->get('authUserID', 0);
        $username = (string) $session->get('authUser', '');
        $groupName = (string) $session->get('authProvider', 'Default');
        $siteId = (string) $session->get('site_id', 'default');
        $pid = (int) $session->get('pid', 0);

        $users = $userId > 0
            ? QueryUtils::fetchRecords('SELECT id, username, active FROM users WHERE id = ?', [$userId])
            : [];
        $active = count($users) === 1
            && (int) $users[0]['active'] === 1
            && hash_equals((string) $users[0]['username'], $username);
        $patients = $pid > 0
            ? QueryUtils::fetchRecords('SELECT pid, uuid, squad FROM patient_data WHERE pid = ?', [$pid])
            : [];
        $patientExists = count($patients) === 1;
        $patientUuid = $patientExists ? UuidRegistry::uuidToString($patients[0]['uuid']) : 'unavailable';
        $squad = $patientExists ? (string) ($patients[0]['squad'] ?? '') : '';
        $squadAllowed = $patientExists && ($squad === '' || AclMain::aclCheckCore('squads', $squad, $username));
        $docsAcl = $active && $patientExists && AclMain::aclCheckCore('patients', 'docs', $username);
        $breakGlass = $username !== '' && ContextBuilder::isBreakGlass($username);

        return new AccessSnapshot(
            new DocumentContext($siteId, $userId, $username, $groupName, $pid, $patientUuid),
            $active && $patientExists,
            (bool) $docsAcl,
            (bool) $squadAllowed,
            $breakGlass,
            $this->principal
        );
    }
}
