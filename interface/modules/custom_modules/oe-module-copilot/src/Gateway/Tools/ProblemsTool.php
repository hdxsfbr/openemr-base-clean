<?php

/**
 * Problems: one record per condition (ConditionService returns one row per
 * linked encounter, DQ-MEDIUM-014), codes exactly as written (DQ-HIGH-005),
 * undated rows flagged rather than placed (DQ-HIGH-004).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway\Tools;

use OpenEMR\Modules\Copilot\Gateway\AuthorizedPatientContext;
use OpenEMR\Modules\Copilot\Gateway\Dates;
use OpenEMR\Services\ConditionService;

final class ProblemsTool extends AbstractTool
{
    public function name(): string
    {
        return 'problems';
    }

    public function version(): string
    {
        return '1.0.0';
    }

    public function sections(): array
    {
        return ['problems'];
    }

    protected function fetch(AuthorizedPatientContext $ctx, array $params): array
    {
        $byUuid = [];
        $links = [];
        foreach (self::rows((new ConditionService())->getAll([], true, $ctx->patientUuid)) as $row) {
            if (!is_array($row) || (int) ($row['pid'] ?? 0) !== $ctx->pid) {
                continue;
            }
            $key = (string) ($row['condition_uuid'] ?? $row['uuid'] ?? $row['id']);
            $links[$key] = ($links[$key] ?? 0) + (!empty($row['encounter_uuid']) ? 1 : 0);
            if (isset($byUuid[$key])) {
                continue;
            }
            $begin = Dates::clinical($row['begdate'] ?? null, 'clinical');
            $end = Dates::clinical($row['enddate'] ?? null, 'clinical');
            $active = isset($row['activity']) ? (int) $row['activity'] : null;
            $byUuid[$key] = [
                'source' => self::source('lists', (int) $row['id'], $row['uuid'] ?? null),
                'title' => (string) ($row['title'] ?? ''),
                'codes' => self::codes($row['diagnosis'] ?? null),
                'status' => $active === null ? 'unknown' : ($active === 1 ? 'active' : 'inactive'),
                'begin' => $begin,
                'end' => $end,
                'undated' => !Dates::isKnown($begin),
                'verification' => ($row['verification'] ?? '') !== '' ? (string) $row['verification'] : null,
                'author' => self::person($row['provider_username'] ?? $row['user'] ?? null),
                'linked_encounter_count' => 0,
            ];
        }
        $records = [];
        foreach ($byUuid as $key => $record) {
            $record['linked_encounter_count'] = $links[$key] ?? 0;
            if (Dates::inWindow($record['begin'], $params['since'], $params['until']) || Dates::inWindow($record['end'], $params['since'], $params['until'])) {
                $records[] = $record;
            }
        }
        self::sortByDateDesc($records, 'begin');
        return ['records' => $records];
    }

    /** @return list<array{system: ?string, code: ?string, as_written: string}> */
    public static function codes(mixed $diagnosis): array
    {
        $out = [];
        if (is_string($diagnosis) && $diagnosis !== '') {
            foreach (explode(';', $diagnosis) as $part) {
                $part = trim($part);
                if ($part === '') {
                    continue;
                }
                $pair = explode(':', $part, 2);
                $out[] = ['system' => count($pair) === 2 ? $pair[0] : null, 'code' => count($pair) === 2 ? $pair[1] : null, 'as_written' => mb_substr($part, 0, 128)];
            }
        } elseif (is_array($diagnosis)) {
            foreach ($diagnosis as $entryKey => $entry) {
                if (is_array($entry)) {
                    $code = (string) ($entry['code'] ?? $entryKey);
                    $system = (string) ($entry['system'] ?? $entry['code_type'] ?? '');
                    $out[] = ['system' => $system !== '' ? $system : null, 'code' => $code !== '' ? $code : null, 'as_written' => mb_substr(trim($system . ':' . $code, ':'), 0, 128)];
                } elseif (is_string($entry) && $entry !== '') {
                    $out = array_merge($out, self::codes($entry));
                }
            }
        }
        return $out;
    }
}
