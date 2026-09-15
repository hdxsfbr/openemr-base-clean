<?php

/**
 * Print the gateway's per-section decision matrix for one or more usernames,
 * exactly as ContextBuilder computes it for tool calls. Evidence for the
 * ADR-0002 parity claim; CLI only.
 *
 *   php interface/modules/custom_modules/oe-module-copilot/bin/acl_matrix.php audit-physician audit-nurse audit-frontdesk
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

$_GET['site'] = getenv('OPENEMR_SITE') ?: 'default';
$ignoreAuth = true;
$openemrRoot = getenv('OPENEMR_ROOT') ?: dirname(__DIR__, 5);
require_once $openemrRoot . '/interface/globals.php';
require_once dirname(__DIR__) . '/src/Gateway/ContextBuilder.php';

use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;

$users = array_slice($argv, 1);
if ($users === []) {
    fwrite(STDERR, "usage: acl_matrix.php <username> [...]\n");
    exit(2);
}
$out = [];
foreach ($users as $user) {
    if (!preg_match('/^[A-Za-z0-9_.\-]{1,255}$/', $user)) {
        continue;
    }
    $out[$user] = ['sections' => ContextBuilder::sectionMatrix($user), 'break_glass' => ContextBuilder::isBreakGlass($user)];
}
echo json_encode($out, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";
