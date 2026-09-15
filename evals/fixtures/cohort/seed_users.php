<?php

/**
 * Create the demo clinician accounts the synthetic cohort and the access-control
 * evals expect: physician, audit-physician, audit-nurse, audit-frontdesk.
 * Idempotent (existing usernames are skipped). Demo data only.
 *
 * Usage (inside the OpenEMR container, as the apache user):
 *   DEMO_USER_PASSWORD_FILE=/run/secrets/demo_user_password \
 *   php evals/fixtures/cohort/seed_users.php --confirm-dev-data
 *
 * OPENEMR_ROOT and OPENEMR_SITE override the defaults. The password is read
 * from the file (trailing newline stripped), applied to every created user,
 * and never printed.
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

$options = getopt('', ['confirm-dev-data']);
if (!isset($options['confirm-dev-data'])) {
    fwrite(STDERR, "Refusing to run without --confirm-dev-data (creates demo users in the OpenEMR database).\n");
    exit(2);
}

$passwordFile = getenv('DEMO_USER_PASSWORD_FILE') ?: '';
if ($passwordFile === '' || !is_readable($passwordFile)) {
    fwrite(STDERR, "Set DEMO_USER_PASSWORD_FILE to a readable file containing the demo password.\n");
    exit(2);
}
$password = rtrim((string) file_get_contents($passwordFile), "\r\n");
if (strlen($password) < 12) {
    fwrite(STDERR, "Demo password must be at least 12 characters.\n");
    exit(2);
}

$_GET['site'] = getenv('OPENEMR_SITE') ?: 'default';
$ignoreAuth = true;
$openemrRoot = getenv('OPENEMR_ROOT') ?: dirname(__DIR__, 3);
if (!is_file($openemrRoot . '/interface/globals.php')) {
    fwrite(STDERR, "OpenEMR root not found at {$openemrRoot} (set OPENEMR_ROOT).\n");
    exit(2);
}
require_once $openemrRoot . '/interface/globals.php';

use OpenEMR\Common\Acl\AclExtended;
use OpenEMR\Common\Auth\AuthHash;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Uuid\UuidRegistry;

/** username => [fname, lname, ACL group title, authorized (provider), calendar] */
$specs = [
    'physician'       => ['Donna', 'Lee',        'Physicians',   1, 1],
    'audit-physician' => ['Audit', 'Physicians', 'Physicians',   1, 1],
    'audit-nurse'     => ['Audit', 'Clinicians', 'Clinicians',   0, 0],
    'audit-frontdesk' => ['Audit', 'FrontOffice', 'Front Office', 0, 0],
];

$facility = QueryUtils::fetchRecords('SELECT id, name FROM facility ORDER BY id LIMIT 1');
$facilityId = (int) ($facility[0]['id'] ?? 0);
$facilityName = (string) ($facility[0]['name'] ?? '');

$hasher = new AuthHash();
$result = ['created' => [], 'skipped' => []];

foreach ($specs as $username => [$fname, $lname, $group, $authorized, $calendar]) {
    $existing = QueryUtils::fetchRecords('SELECT id FROM users WHERE username = ?', [$username]);
    if (count($existing) > 0) {
        $result['skipped'][] = $username;
        continue;
    }

    $userData = [
        'username'    => $username,
        'password'    => 'NoLongerUsed',
        'fname'       => $fname,
        'lname'       => $lname,
        'authorized'  => $authorized,
        'active'      => 1,
        'calendar'    => $calendar,
        'see_auth'    => 1,
        'facility_id' => $facilityId,
        'facility'    => $facilityName,
        'uuid'        => UuidRegistry::getRegistryForTable('users')->createUuid(),
    ];
    $columns = array_map(static fn(string $c): string => '`' . $c . '`', array_keys($userData));
    $newUserId = QueryUtils::sqlInsert(
        'INSERT INTO `users` (' . implode(', ', $columns) . ') VALUES (' . implode(', ', array_fill(0, count($userData), '?')) . ')',
        array_values($userData)
    );

    $pwd = $password; // passwordHash takes a reference and may clear it
    $hash = $hasher->passwordHash($pwd);
    if (empty($hash)) {
        fwrite(STDERR, "Unable to hash the demo password.\n");
        exit(1);
    }
    QueryUtils::sqlInsert(
        'INSERT INTO `users_secure` (`id`, `username`, `password`, `last_update_password`) VALUES (?, ?, ?, NOW())',
        [$newUserId, $username, $hash]
    );

    // Without a groups row OpenEMR rejects the login ("user not found in a group").
    QueryUtils::sqlInsert('INSERT INTO `groups` SET name = ?, user = ?', ['Default', $username]);

    // Access-control group membership (phpGACL), the same call the Users admin page makes.
    AclExtended::setUserAro([$group], $username, $fname, '', $lname);

    $result['created'][] = ['username' => $username, 'acl_group' => $group, 'authorized' => $authorized];
}

echo json_encode($result) . "\n";
