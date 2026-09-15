<?php

/**
 * Audit measurement script (read-only). Run inside the openemr container as the web user:
 *   php docs/audit/scripts/audit_service_timing.php [args]
 * Prints timings, counts, and sizes only; never record contents.
 */

/**
 * Audit-only: time the in-process clinical services the co-pilot tools would
 * call for UC-01. Demo data only. Prints timings and result counts, never
 * record contents. Not application code; lives in tmp/ and is not committed.
 *
 * Usage (inside container):
 *   php docs/audit/scripts/audit_service_timing.php <pid> <iterations>
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
use OpenEMR\Services\ConditionService;
use OpenEMR\Services\EncounterService;
use OpenEMR\Services\PatientIssuesService;
use OpenEMR\Services\PatientService;
use OpenEMR\Services\PrescriptionService;
use OpenEMR\Services\ProcedureService;

$pid = (int) ($argv[1] ?? 1);
$iterations = max(1, (int) ($argv[2] ?? 10));

$patient = (new PatientService())->findByPid($pid);
if (!is_array($patient) || empty($patient['uuid'])) {
    fwrite(STDERR, "patient not found\n");
    exit(1);
}
$puuid = strlen((string) $patient['uuid']) === 16
    ? UuidRegistry::uuidToString($patient['uuid'])
    : (string) $patient['uuid'];

/** @return int count of records in a ProcessingResult, array, or other */
$countOf = static function (mixed $result): int {
    if (is_object($result) && method_exists($result, 'getData')) {
        return count($result->getData());
    }
    return is_array($result) ? count($result) : -1;
};

$calls = [
    'patient.findByPid' => static fn() => (new PatientService())->findByPid($pid),
    'encounter.getEncountersForPatientByPid' => static fn() => (new EncounterService())->getEncountersForPatientByPid($pid),
    'issues.getActiveIssues' => static fn() => (new PatientIssuesService())->getActiveIssues($pid),
    'condition.getAll(puuid)' => static fn() => (new ConditionService())->getAll([], true, $puuid),
    'allergy.getAll(puuid)' => static fn() => (new AllergyIntoleranceService())->getAll([], true, $puuid),
    'prescription.getAll(puuid)' => static fn() => (new PrescriptionService())->getAll(['puuid' => $puuid]),
    'procedure.getAll(puuid)' => static fn() => (new ProcedureService())->getAll([], true, $puuid),
];

printf("%-42s %4s %9s %9s %9s %7s %s\n", 'call', 'n', 'p50_ms', 'p95_ms', 'max_ms', 'records', 'status');
$serialP50Sum = 0.0;
foreach ($calls as $name => $call) {
    $times = [];
    $records = -1;
    $status = 'ok';
    for ($i = 0; $i < $iterations; $i++) {
        $start = hrtime(true);
        try {
            $records = $countOf($call());
        } catch (\Throwable $e) {
            $status = 'error:' . get_class($e);
            break;
        }
        $times[] = (hrtime(true) - $start) / 1e6;
    }
    if ($times === []) {
        printf("%-42s %4d %9s %9s %9s %7s %s\n", $name, 0, '-', '-', '-', '-', $status);
        continue;
    }
    sort($times);
    $n = count($times);
    $p50 = $times[(int) floor(($n - 1) * 0.50)];
    $p95 = $times[(int) floor(($n - 1) * 0.95)];
    $serialP50Sum += $p50;
    printf("%-42s %4d %9.2f %9.2f %9.2f %7d %s\n", $name, $n, $p50, $p95, $times[$n - 1], $records, $status);
}
printf("serial sum of p50: %.2f ms\n", $serialP50Sum);
