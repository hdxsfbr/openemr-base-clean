<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Uuid\UuidRegistry;
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;

/**
 * Rebuilds a worker's authority from live OpenEMR records immediately before
 * a leased source document is decrypted. The queued job contributes only the
 * scoped subject and acting user identifier; it is not an authorization grant.
 */
final class WorkerAccessSnapshot implements AccessSnapshotPort
{
    /** @param array<string, mixed> $job */
    public function __construct(private readonly array $job)
    {
    }

    public function current(): AccessSnapshot
    {
        $userId = (int) ($this->job['created_by'] ?? 0);
        $siteId = (string) ($this->job['site_id'] ?? '');
        $pid = (int) ($this->job['pid'] ?? 0);
        $users = $userId > 0
            ? QueryUtils::fetchRecords('SELECT id, username, active FROM users WHERE id = ?', [$userId])
            : [];
        $username = count($users) === 1 ? (string) $users[0]['username'] : '';
        $active = count($users) === 1 && (int) $users[0]['active'] === 1;
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
            new DocumentContext($siteId, $userId, $username, 'Default', $pid, $patientUuid),
            $active && $patientExists && $siteId !== '',
            (bool) $docsAcl,
            (bool) $squadAllowed,
            $breakGlass,
            'worker',
            false,
            false
        );
    }
}
