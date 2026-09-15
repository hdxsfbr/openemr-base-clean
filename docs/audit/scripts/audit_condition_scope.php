<?php

/**
 * Audit measurement script (read-only). Run inside the openemr container as the web user:
 *   php docs/audit/scripts/audit_condition_scope.php [args]
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
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Uuid\UuidRegistry;
use OpenEMR\Services\ConditionService;
use OpenEMR\Services\PatientService;
foreach ([900022 => 'AF-DQ-R (empty chart)', 900023 => 'AF-HEAVY', 1 => 'demo pid 1'] as $pid => $label) {
    $p = (new PatientService())->findByPid($pid);
    $puuid = UuidRegistry::uuidToString($p['uuid']);
    $rows = (new ConditionService())->getAll([], true, $puuid)->getData();
    $pids = [];
    foreach ($rows as $r) { $pids[(string)($r['puuid'] ?? $r['pid'] ?? '?')] = true; }
    $own = (int) QueryUtils::fetchSingleValue("SELECT COUNT(*) c FROM lists WHERE pid = ? AND type='medical_problem'", 'c', [$pid]);
    printf("%-24s returned=%d distinct_patient_refs=%d own_medical_problem_rows=%d\n", $label, count($rows), count($pids), $own);
}
printf("all medical_problem rows in DB=%d\n", (int) QueryUtils::fetchSingleValue("SELECT COUNT(*) c FROM lists WHERE type='medical_problem'", 'c'));
