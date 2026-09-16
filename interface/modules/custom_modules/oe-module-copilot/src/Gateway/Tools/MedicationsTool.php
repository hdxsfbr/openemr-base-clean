<?php

/**
 * Medications from both sources, never merged without a code match
 * (DQ-HIGH-003): the medication list (`lists` + `lists_medication`) and
 * `prescriptions`. Status carries its basis and a conflict flag (DQ-HIGH-002);
 * dose fields use resolved labels (DQ-MEDIUM-010).
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
use OpenEMR\Common\Uuid\UuidRegistry;
use OpenEMR\Modules\Copilot\Gateway\AuthorizedPatientContext;
use OpenEMR\Modules\Copilot\Gateway\Dates;
use OpenEMR\Services\PrescriptionService;
use OpenEMR\Services\Search\TokenSearchField;

final class MedicationsTool extends AbstractTool
{
    public function name(): string
    {
        return 'medications';
    }

    public function version(): string
    {
        return '1.0.0';
    }

    public function sections(): array
    {
        return ['medications', 'prescriptions'];
    }

    protected function fetch(AuthorizedPatientContext $ctx, array $params): array
    {
        $records = [];
        $today = date('Y-m-d');

        // Source 1: the medication list. Same rows the chart's Medications card shows.
        $listRows = QueryUtils::fetchRecords(
            'SELECT l.id, l.uuid, l.title, l.begdate, l.enddate, l.activity, l.diagnosis, l.user, '
            . 'lm.drug_dosage_instructions FROM lists l LEFT JOIN lists_medication lm ON lm.list_id = l.id '
            . "WHERE l.pid = ? AND l.type = 'medication' ORDER BY l.begdate DESC, l.id DESC",
            [$ctx->pid]
        );
        foreach ($listRows as $row) {
            $start = Dates::clinical($row['begdate'] ?? null, 'clinical');
            $end = Dates::clinical($row['enddate'] ?? null, 'clinical');
            $endDay = Dates::day($end);
            // The chart summary greys a list entry by end date only: no end date means it is shown as
            // current. The API path uses `activity`. When the two disagree (DQ-HIGH-002, fixture AF-DQ-B:
            // activity=0 with no end date) the record carries a status conflict instead of a status.
            $byEnd = $endDay === null ? 'active' : ($endDay > $today ? 'active' : 'inactive');
            $byActivity = isset($row['activity']) ? ((int) $row['activity'] === 1 ? 'active' : 'inactive') : null;
            [$status, $basis, $conflict] = self::reconcile($byEnd, $byActivity);
            $records[] = [
                'source' => self::source('lists', (int) $row['id'], self::uuid($row['uuid'] ?? null)),
                'provenance' => 'lists',
                'name' => (string) $row['title'],
                'codes' => ProblemsTool::codes($row['diagnosis'] ?? null),
                'dose_text' => ($row['drug_dosage_instructions'] ?? '') !== '' ? mb_substr((string) $row['drug_dosage_instructions'], 0, 255) : null,
                'start' => $start,
                'end' => $end,
                'status' => $status,
                'status_basis' => $basis,
                'status_conflict' => $conflict,
                'prescriber' => self::person($row['user'] ?? null),
                'documented_indication' => null, // the list carries codes, not an indication text
                'undated' => !Dates::isKnown($start),
            ];
        }

        // Source 2: prescriptions. Resolved labels from the service, dates and indication from the row.
        $resolved = [];
        foreach (self::rows((new PrescriptionService())->getAll(['puuid' => new TokenSearchField('puuid', [$ctx->patientUuid], true)])) as $row) {
            if (is_array($row) && ($row['source_table'] ?? '') === 'prescriptions' && isset($row['uuid'])) {
                $resolved[(string) $row['uuid']] = $row;
            }
        }
        $rxRows = QueryUtils::fetchRecords(
            'SELECT p.id, p.uuid, p.drug, p.rxnorm_drugcode, p.dosage, p.unit, p.route, p.`interval`, p.start_date, p.end_date, p.active, '
            . 'p.indication, p.date_added, u.username AS provider_username FROM prescriptions p LEFT JOIN users u ON u.id = p.provider_id '
            . 'WHERE p.patient_id = ? ORDER BY p.start_date DESC, p.id DESC',
            [$ctx->pid]
        );
        foreach ($rxRows as $row) {
            $uuid = self::uuid($row['uuid'] ?? null);
            $svc = $uuid !== null ? ($resolved[$uuid] ?? []) : [];
            $start = Dates::clinical($row['start_date'] ?? null, 'clinical');
            if (!Dates::isKnown($start)) {
                $start = Dates::clinical($row['date_added'] ?? null, 'entered');
            }
            $end = Dates::clinical($row['end_date'] ?? null, 'clinical');
            $endDay = Dates::day($end);
            $byEnd = $endDay === null ? null : ($endDay > $today ? 'active' : 'inactive');
            $byActivity = isset($row['active']) ? ((int) $row['active'] === 1 ? 'active' : 'inactive') : null;
            [$status, $basis, $conflict] = self::reconcile($byEnd, $byActivity);
            $dose = trim(implode(' ', array_filter([
                (string) ($svc['dosage'] ?? $row['dosage'] ?? ''),
                (string) ($svc['unit_title'] ?? ''),
                (string) ($svc['route_title'] ?? ''),
                (string) ($svc['interval_title'] ?? ''),
            ], static fn(string $s): bool => $s !== '')));
            $codes = [];
            if (($row['rxnorm_drugcode'] ?? '') !== '') {
                $codes[] = ['system' => 'RXNORM', 'code' => (string) $row['rxnorm_drugcode'], 'as_written' => 'RXNORM:' . $row['rxnorm_drugcode']];
            }
            $records[] = [
                'source' => self::source('prescriptions', (int) $row['id'], $uuid),
                'provenance' => 'prescriptions',
                'name' => (string) $row['drug'],
                'codes' => $codes,
                'dose_text' => $dose !== '' ? mb_substr($dose, 0, 255) : null,
                'start' => $start,
                'end' => $end,
                'status' => $status,
                'status_basis' => $basis,
                'status_conflict' => $conflict,
                'prescriber' => self::person($row['provider_username'] ?? null),
                'documented_indication' => ($row['indication'] ?? '') !== '' ? mb_substr((string) $row['indication'], 0, 255) : null,
                'undated' => !Dates::isKnown($start) || $start['basis'] !== 'clinical',
            ];
        }

        $records = array_values(array_filter($records, static fn(array $r): bool => Dates::inWindow($r['start'], $params['since'], $params['until']) || Dates::inWindow($r['end'], $params['since'], $params['until'])));
        self::sortByDateDesc($records, 'start');
        return ['records' => $records, 'counts' => ['lists' => count($listRows), 'prescriptions' => count($rxRows)]];
    }

    /** @return array{0: string, 1: string, 2: bool} status, basis, conflict */
    private static function reconcile(?string $byEnd, ?string $byActivity): array
    {
        if ($byEnd !== null && $byActivity !== null) {
            return $byEnd === $byActivity ? [$byEnd, 'both', false] : [$byActivity, 'activity', true];
        }
        if ($byActivity !== null) {
            return [$byActivity, 'activity', false];
        }
        if ($byEnd !== null) {
            return [$byEnd, 'enddate', false];
        }
        return ['unknown', 'none', false];
    }

    private static function uuid(mixed $raw): ?string
    {
        if (!is_string($raw) || $raw === '') {
            return null;
        }
        return strlen($raw) === 16 ? UuidRegistry::uuidToString($raw) : $raw;
    }
}
