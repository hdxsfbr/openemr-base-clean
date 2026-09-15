<?php

/**
 * Laboratory results via ProcedureService::search() (never getAll(),
 * PERF-MED-001), flattened order -> report -> result. Values stay as stored;
 * numeric_value is set only for strictly numeric text; abnormality comes from
 * the recorded flag or a parseable same-unit range, never elsewhere
 * (DQ-MEDIUM-009).
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
use OpenEMR\Services\ProcedureService;
use OpenEMR\Services\Search\TokenSearchField;

final class LabResultsTool extends AbstractTool
{
    private const ABNORMAL_FLAGS = ['yes', 'high', 'low', 'hi', 'lo', 'h', 'l', 'hh', 'll', 'abnormal', 'critical', 'a', 'aa'];
    private const NORMAL_FLAGS = ['no', 'normal', 'n'];

    public function name(): string
    {
        return 'lab_results';
    }

    public function version(): string
    {
        return '1.0.0';
    }

    public function sections(): array
    {
        return ['labs'];
    }

    protected function fetch(AuthorizedPatientContext $ctx, array $params): array
    {
        $analyte = $params['analyte'] !== null ? mb_strtolower($params['analyte']) : null;
        $records = [];
        $partial = false;
        $orders = self::rows((new ProcedureService())->search(['puuid' => new TokenSearchField('puuid', [$ctx->patientUuid], true)]));
        foreach ($orders as $order) {
            if (!is_array($order) || (int) ($order['patient_id'] ?? 0) !== $ctx->pid) {
                continue;
            }
            foreach ((array) ($order['reports'] ?? []) as $report) {
                if (!is_array($report)) {
                    continue;
                }
                $reportDate = Dates::clinical($report['date'] ?? $order['date_collected'] ?? $order['date_ordered'] ?? null, 'clinical');
                foreach ((array) ($report['results'] ?? []) as $result) {
                    if (!is_array($result) || !isset($result['id'])) {
                        $partial = true;
                        continue;
                    }
                    if (!Dates::inWindow($reportDate, $params['since'], $params['until'])) {
                        continue;
                    }
                    $name = (string) ($result['text'] ?? '');
                    $code = ($result['code'] ?? '') !== '' ? (string) $result['code'] : null;
                    if ($analyte !== null && !str_contains(mb_strtolower($name), $analyte) && mb_strtolower((string) $code) !== $analyte) {
                        continue;
                    }
                    $valueText = trim((string) ($result['result'] ?? ''));
                    $numeric = preg_match('/^-?\d+(\.\d+)?$/', $valueText) ? (float) $valueText : null;
                    $unit = ($result['units'] ?? '') !== '' ? (string) $result['units'] : null;
                    $range = ($result['range'] ?? '') !== '' ? (string) $result['range'] : null;
                    $recorded = strtolower(trim((string) ($result['abnormal'] ?? '')));
                    $flag = self::flag($recorded, $numeric, $range);
                    $status = ($result['status'] ?? '') !== '' ? (string) $result['status'] : null;
                    $records[] = [
                        'source' => self::source('procedure_result', (int) $result['id'], $result['uuid'] ?? null),
                        'order_id' => (int) ($order['procedure_order_id'] ?? 0),
                        'report_id' => (int) ($report['id'] ?? 0),
                        'analyte' => $name,
                        'analyte_code' => $code,
                        'value_text' => mb_substr($valueText, 0, 255),
                        'numeric_value' => $numeric,
                        'unit' => $unit,
                        'range_text' => $range,
                        'flag' => $flag,
                        'flag_as_recorded' => $recorded !== '' ? $recorded : null,
                        'date' => $reportDate,
                        'result_status' => $status,
                        'corrected' => in_array(strtolower((string) $status), ['correct', 'corrected', 'c'], true),
                        'comparable' => $numeric !== null && $unit !== null,
                    ];
                }
            }
        }
        self::sortByDateDesc($records, 'date');
        return ['records' => $records, 'partial' => $partial, 'reason' => $partial ? 'orphan_rows_omitted' : null, 'counts' => ['orders' => count($orders)]];
    }

    private static function flag(string $recorded, ?float $numeric, ?string $range): string
    {
        if (in_array($recorded, self::ABNORMAL_FLAGS, true)) {
            return 'abnormal';
        }
        if (in_array($recorded, self::NORMAL_FLAGS, true)) {
            return 'normal';
        }
        if ($numeric !== null && $range !== null && preg_match('/^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$/', $range, $m)) {
            $low = (float) $m[1];
            $high = (float) $m[2];
            return ($numeric < $low || $numeric > $high) ? 'abnormal' : 'normal';
        }
        return 'unknown';
    }
}
