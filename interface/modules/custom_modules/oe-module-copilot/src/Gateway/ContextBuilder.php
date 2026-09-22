<?php

/**
 * Builds the AuthorizedPatientContext by running every ADR-0002 check, in
 * order, against the conversation binding and the bound user. Runs without a
 * browser session: the agent calls with a delegation token only.
 *
/**
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway;

use OpenEMR\Common\Acl\AclExtended;
use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Uuid\UuidRegistry;
use OpenEMR\Modules\Copilot\Conversation\ConversationRepository;

final class ContextBuilder
{
    public const IDLE_TIMEOUT_MINUTES = 30;
    public const BREAK_GLASS_GROUP = 'Emergency Login';

    /** Section keys the tools use, mapped to the same checks the chart pages make. */
    public const SECTIONS = ['demo', 'encounters', 'notes', 'problems', 'medications', 'prescriptions', 'allergies', 'labs'];

    public function __construct(private readonly ConversationRepository $conversations)
    {
    }

    /**
     * @param array{cid: string, jti: string, iat: int, exp: int, v: int} $token
     * @throws GatewayDenied
     */
    public function build(array $token, string $correlationId): AuthorizedPatientContext
    {
        $conversation = $this->conversations->find($token['cid']);
        if ($conversation === null || $conversation['closed_at'] !== null) {
            throw new GatewayDenied('conversation_closed');
        }
        $lastTurn = $conversation['last_turn_at'] ?? $conversation['created_at'];
        if (strtotime((string) $lastTurn) < time() - self::IDLE_TIMEOUT_MINUTES * 60) {
            $this->conversations->close($conversation['id'], 'idle_timeout');
            throw new GatewayDenied('conversation_closed', 403, true);
        }

        $user = QueryUtils::fetchRecords('SELECT id, username, active FROM users WHERE id = ?', [(int) $conversation['user_id']]);
        if (count($user) !== 1 || (int) $user[0]['active'] !== 1 || $user[0]['username'] !== $conversation['username']) {
            $this->conversations->close($conversation['id'], 'user_inactive');
            throw new GatewayDenied('user_inactive', 403, true);
        }
        $username = (string) $user[0]['username'];

        if (self::isBreakGlass($username)) {
            $this->conversations->close($conversation['id'], 'breakglass');
            throw new GatewayDenied('breakglass', 403, true);
        }

        $patient = QueryUtils::fetchRecords('SELECT pid, uuid, squad FROM patient_data WHERE pid = ?', [(int) $conversation['pid']]);
        if (count($patient) !== 1) {
            throw new GatewayDenied('patient_not_found', 404);
        }
        $squad = (string) ($patient[0]['squad'] ?? '');
        if ($squad !== '' && !AclMain::aclCheckCore('squads', $squad, $username)) {
            $this->conversations->close($conversation['id'], 'squad');
            throw new GatewayDenied('squad', 403, true);
        }

        $group = QueryUtils::fetchRecords('SELECT name FROM `groups` WHERE user = ? LIMIT 1', [$username]);

        return new AuthorizedPatientContext(
            userId: (int) $user[0]['id'],
            username: $username,
            groupName: (string) ($group[0]['name'] ?? 'Default'),
            pid: (int) $patient[0]['pid'],
            patientUuid: UuidRegistry::uuidToString($patient[0]['uuid']),
            allowedSections: self::sectionMatrix($username),
            conversationId: (string) $conversation['id'],
            turnId: $token['jti'],
            correlationId: $correlationId,
            siteId: (string) $conversation['site_id'],
        );
    }

    /**
     * The chart's own checks (demographics.php, encounters.php), by username.
     *
     * Issue sections are NOT checked through AclMain::aclCheckIssue(): that
     * helper returns true whenever the $ISSUE_TYPES table is not loaded at
     * global scope, which is the case in this session-less gateway request
     * (observed 2026-09-15: Front Office was granted problems and allergies).
     * The gateway reads the same `issue_types.aco_spec` the chart uses and
     * fails closed when a spec is missing.
     *
     * @return array<string, bool>
     */
    public static function sectionMatrix(string $username): array
    {
        $specs = self::issueAcoSpecs();
        $issue = static function (string $type) use ($specs, $username): bool {
            $spec = $specs[$type] ?? '';
            if ($spec === '' || !str_contains($spec, '|')) {
                error_log('oe-module-copilot: no aco_spec for issue type ' . $type . '; denying (fail closed)');
                return false;
            }
            return (bool) AclMain::aclCheckAcoSpec($spec, $username);
        };
        return [
            'demo' => (bool) AclMain::aclCheckCore('patients', 'demo', $username),
            'encounters' => (bool) AclMain::aclCheckCore('encounters', 'notes', $username),
            'notes' => (bool) AclMain::aclCheckCore('encounters', 'notes', $username),
            'problems' => $issue('medical_problem'),
            'medications' => $issue('medication'),
            'prescriptions' => (bool) AclMain::aclCheckCore('patients', 'rx', $username),
            'allergies' => $issue('allergy'),
            'labs' => (bool) AclMain::aclCheckCore('patients', 'lab', $username),
        ];
    }

    /** @return array<string, string> issue type => aco_spec, from the table the chart's $ISSUE_TYPES is built from */
    private static function issueAcoSpecs(): array
    {
        $out = [];
        foreach (QueryUtils::fetchRecords("SELECT type, aco_spec FROM issue_types WHERE type IN ('medical_problem', 'medication', 'allergy')") as $row) {
            $out[(string) $row['type']] = (string) ($row['aco_spec'] ?? '');
        }
        return $out;
    }

    public static function isBreakGlass(string $username): bool
    {
        $titles = AclExtended::aclGetGroupTitles($username);
        return is_array($titles) && in_array(self::BREAK_GLASS_GROUP, $titles, true);
    }
}
