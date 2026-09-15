<?php

/**
 * Audit measurement script (read-only). Run inside the openemr container as the web user:
 *   php docs/audit/scripts/audit_payload_sizes.php [args]
 * Prints timings, counts, and sizes only; never record contents.
 */
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
$_GET['site'] = 'default';
$ignoreAuth = true;
$sessionAllowWrite = true;
require_once __DIR__ . '/../../../interface/globals.php';

use OpenEMR\Common\Uuid\UuidRegistry;
use OpenEMR\Services\AllergyIntoleranceService;
use OpenEMR\Services\ClinicalNotesService;
use OpenEMR\Services\ConditionService;
use OpenEMR\Services\EncounterService;
use OpenEMR\Services\PatientIssuesService;
use OpenEMR\Services\PatientService;
use OpenEMR\Services\ProcedureService;
use OpenEMR\Services\Search\TokenSearchField;

/** @return list<mixed> */
function rowsOf(mixed $r): array {
    if (is_object($r) && method_exists($r, 'getData')) { return array_values($r->getData()); }
    return is_array($r) ? array_values($r) : [];
}
function uuidKeyCount(array $rows, string $key): int {
    $seen = [];
    foreach ($rows as $row) { if (is_array($row) && isset($row[$key])) { $seen[is_string($row[$key]) && strlen($row[$key]) === 16 ? bin2hex($row[$key]) : (string) $row[$key]] = true; } }
    return count($seen);
}
function bytesOf(array $rows): int {
    $clean = json_decode(json_encode($rows, JSON_INVALID_UTF8_SUBSTITUTE | JSON_PARTIAL_OUTPUT_ON_ERROR), true);
    return strlen((string) json_encode($clean, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
}

$targets = [900023 => 'AF-HEAVY', 900001 => 'AF-DQ-A2'];
printf("%-10s %-34s %7s %9s %9s %9s %8s %s\n", 'patient', 'tool', 'rows', 'distinct', 'bytes', '~tokens', 'ms', 'status');
foreach ($targets as $pid => $label) {
    $patient = (new PatientService())->findByPid($pid);
    $puuid = UuidRegistry::uuidToString($patient['uuid']);
    $calls = [
        'encounters (EncounterService)' => [fn() => (new EncounterService())->getEncountersForPatientByPid($pid), 'encounter'],
        'active issues (PatientIssuesService)' => [fn() => (new PatientIssuesService())->getActiveIssues($pid), 'id'],
        'conditions (ConditionService)' => [fn() => (new ConditionService())->getAll([], true, $puuid), 'condition_uuid'],
        'allergies (AllergyIntolerance)' => [fn() => (new AllergyIntoleranceService())->getAll([], true, $puuid), 'allergy_uuid'],
        'labs (ProcedureService::search)' => [fn() => (new ProcedureService())->search(['puuid' => new TokenSearchField('puuid', [$puuid], true)]), 'order_uuid'],
        'notes (ClinicalNotesService)' => [fn() => (new ClinicalNotesService())->getClinicalNotesForPatient($pid), 'id'],
    ];
    foreach ($calls as $name => [$call, $distinctKey]) {
        $start = hrtime(true);
        try {
            $rows = rowsOf($call());
            $status = 'ok';
        } catch (\Throwable $e) {
            $rows = [];
            $status = 'error:' . get_class($e);
        }
        $ms = (hrtime(true) - $start) / 1e6;
        $bytes = bytesOf($rows);
        $extra = '';
        if (str_starts_with($name, 'labs') && $rows !== []) {
            $results = 0; $keys = [];
            foreach ($rows as $o) { foreach (($o['reports'] ?? []) as $rep) { $results += count($rep['results'] ?? []); } }
            $extra = " lab_results_nested=$results first_row_keys=" . implode(',', array_slice(array_keys($rows[0]), 0, 6));
        }
        printf("%-10s %-34s %7d %9d %9d %9d %8.1f %s%s\n", $label, $name, count($rows), uuidKeyCount($rows, $distinctKey), $bytes, intdiv($bytes, 4), $ms, $status, $extra);
    }
}
