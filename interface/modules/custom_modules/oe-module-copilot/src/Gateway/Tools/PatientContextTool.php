<?php

/**
 * Patient context: age band and sex only (minimum necessary); no name, DOB,
 * address, phone, or insurance ever leaves the gateway.
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
use OpenEMR\Services\PatientService;

final class PatientContextTool extends AbstractTool
{
    public function name(): string
    {
        return 'patient_context';
    }

    public function version(): string
    {
        return '1.0.0';
    }

    public function sections(): array
    {
        return ['demo'];
    }

    protected function fetch(AuthorizedPatientContext $ctx, array $params): array
    {
        $patient = (new PatientService())->findByPid($ctx->pid);
        if (!is_array($patient) || (int) ($patient['pid'] ?? 0) !== $ctx->pid) {
            throw new \RuntimeException('patient row missing');
        }
        $dob = (string) ($patient['DOB'] ?? '');
        $ageBand = 'unknown';
        if (preg_match('/^\d{4}-\d{2}-\d{2}$/', $dob) && !str_starts_with($dob, '0000')) {
            $age = (new \DateTimeImmutable($dob))->diff(new \DateTimeImmutable('today'))->y;
            $ageBand = $age >= 90 ? '90+' : sprintf('%d-%d', intdiv($age, 10) * 10, intdiv($age, 10) * 10 + 9);
        }
        $counts = [];
        foreach (['encounters' => 'SELECT COUNT(*) c FROM form_encounter WHERE pid = ?', 'problems' => "SELECT COUNT(*) c FROM lists WHERE pid = ? AND type = 'medical_problem'", 'medications' => "SELECT COUNT(*) c FROM lists WHERE pid = ? AND type = 'medication'", 'allergies' => "SELECT COUNT(*) c FROM lists WHERE pid = ? AND type = 'allergy'"] as $key => $sql) {
            $counts[$key] = (int) (QueryUtils::fetchRecords($sql, [$ctx->pid])[0]['c'] ?? 0);
        }
        return ['records' => [[
            'source' => self::source('patient_data', $ctx->pid, $ctx->patientUuid),
            'age_band' => $ageBand,
            'sex' => ($patient['sex'] ?? '') !== '' ? (string) $patient['sex'] : null,
            'counts' => $counts,
        ]]];
    }
}
