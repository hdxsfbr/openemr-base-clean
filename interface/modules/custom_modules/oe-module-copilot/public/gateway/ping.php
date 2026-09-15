<?php

/**
 * Gateway readiness probe for the agent service (internal network only; the
 * edge returns 404 for this path). Confirms OpenEMR bootstraps and the
 * database answers. Returns no data.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

$ignoreAuth = true;
require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Database\QueryUtils;

header('Content-Type: application/json');
header('Cache-Control: no-store');

try {
    $row = QueryUtils::fetchRecords('SELECT 1 AS ok');
    $ok = isset($row[0]['ok']) && (int) $row[0]['ok'] === 1;
} catch (\Throwable) {
    $ok = false;
}

http_response_code($ok ? 200 : 503);
echo json_encode(['status' => $ok ? 'ok' : 'database_unavailable', 'module' => 'oe-module-copilot', 'version' => '0.1.0']);
