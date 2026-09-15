<?php

/**
 * Encounters: the timeline UC-01 anchors on. `is_clinical_visit` marks
 * reference-encounter candidates; non-visit categories never anchor a window.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway\Tools;

use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Modules\Copilot\Gateway\AuthorizedPatientContext;
use OpenEMR\Modules\Copilot\Gateway\Dates;
use OpenEMR\Services\EncounterService;

final class EncountersTool extends AbstractTool
{
    private const NON_VISIT_CATEGORIES = ['phone call', 'telephone call', 'telephone', 'reminder', 'message', 'note'];

    public function name(): string
    {
        return 'encounters';
    }

    public function version(): string
    {
        return '1.0.0';
    }

    public function sections(): array
    {
        return ['encounters'];
    }

    protected function fetch(AuthorizedPatientContext $ctx, array $params): array
    {
        $records = [];
        $usernames = [];
        foreach (self::rows((new EncounterService())->getEncountersForPatientByPid($ctx->pid)) as $row) {
            if (!is_array($row) || (int) ($row['pid'] ?? 0) !== $ctx->pid) {
                continue; // never cross-attach
            }
            $date = Dates::clinical($row['date'] ?? null, 'clinical');
            if (!Dates::inWindow($date, $params['since'], $params['until'])) {
                continue;
            }
            $category = ($row['pc_catname'] ?? '') !== '' ? (string) $row['pc_catname'] : null;
            [$reason] = self::cap($row['reason'] ?? null, 200);
            $records[] = [
                'source' => self::source('form_encounter', (int) $row['eid'], $row['euuid'] ?? null),
                'encounter_id' => (int) $row['eid'],
                'date' => $date,
                'category' => $category,
                'class_code' => ($row['class_code'] ?? '') !== '' ? (string) $row['class_code'] : null,
                'reason' => $reason !== '' ? $reason : null,
                'provider' => self::person(self::providerUsername($row, $usernames)),
                'is_clinical_visit' => Dates::isKnown($date) && !in_array(strtolower((string) $category), self::NON_VISIT_CATEGORIES, true),
                'sensitivity' => ($row['sensitivity'] ?? '') !== '' ? (string) $row['sensitivity'] : null,
            ];
        }
        self::sortByDateDesc($records, 'date');
        return ['records' => $records];
    }

    /**
     * EncounterService leaves provider_username null; resolve provider_id once per user.
     * @param array<string, mixed> $row
     * @param array<int, ?string> $cache
     */
    private static function providerUsername(array $row, array &$cache): ?string
    {
        if (($row['provider_username'] ?? '') !== '') {
            return (string) $row['provider_username'];
        }
        $providerId = (int) ($row['provider_id'] ?? 0);
        if ($providerId <= 0) {
            return null;
        }
        if (!array_key_exists($providerId, $cache)) {
            $user = QueryUtils::fetchRecords('SELECT username FROM users WHERE id = ?', [$providerId]);
            $cache[$providerId] = isset($user[0]['username']) ? (string) $user[0]['username'] : null;
        }
        return $cache[$providerId];
    }
}
