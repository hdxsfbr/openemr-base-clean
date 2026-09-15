<?php

/**
 * Allergies with an explicit absence state: documented, reviewed_none
 * (`lists_touch` marker, no rows), or not_documented (DQ-MEDIUM-007).
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
use OpenEMR\Services\AllergyIntoleranceService;

final class AllergiesTool extends AbstractTool
{
    public function name(): string
    {
        return 'allergies';
    }

    public function version(): string
    {
        return '1.0.0';
    }

    public function sections(): array
    {
        return ['allergies'];
    }

    protected function fetch(AuthorizedPatientContext $ctx, array $params): array
    {
        $records = [];
        foreach (self::rows((new AllergyIntoleranceService())->getAll([], true, $ctx->patientUuid)) as $row) {
            if (!is_array($row) || (int) ($row['pid'] ?? 0) !== $ctx->pid) {
                continue;
            }
            $begin = Dates::clinical($row['begdate'] ?? null, 'clinical');
            $active = isset($row['activity']) ? (int) $row['activity'] : null;
            $records[] = [
                'source' => self::source('lists', (int) $row['id'], $row['uuid'] ?? null),
                'substance' => (string) ($row['title'] ?? ''),
                'reaction' => ($row['reaction_title'] ?? '') !== '' ? (string) $row['reaction_title'] : null,
                'severity' => ($row['severity_al'] ?? '') !== '' ? (string) $row['severity_al'] : null,
                'status' => $active === null ? 'unknown' : ($active === 1 ? 'active' : 'inactive'),
                'begin' => $begin,
                'undated' => !Dates::isKnown($begin),
            ];
        }
        $reviewed = QueryUtils::fetchRecords("SELECT date FROM lists_touch WHERE pid = ? AND type = 'allergy'", [$ctx->pid]);
        $absence = count($records) > 0 ? 'documented' : (count($reviewed) > 0 ? 'reviewed_none' : 'not_documented');
        $records = array_values(array_filter($records, static fn(array $r): bool => Dates::inWindow($r['begin'], $params['since'], $params['until'])));
        self::sortByDateDesc($records, 'begin');
        return ['records' => $records, 'absence_state' => $absence, 'counts' => ['reviewed_marker' => count($reviewed)]];
    }
}
