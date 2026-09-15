<?php

/**
 * Register and enable the co-pilot module without the Module Manager UI, and
 * apply its install SQL. Idempotent. CLI only: run inside the OpenEMR
 * container as the apache user, for example
 *   su -s /bin/sh apache -c "php interface/modules/custom_modules/oe-module-copilot/bin/register_module.php"
 * OPENEMR_ROOT and OPENEMR_SITE override the defaults.
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
if (!is_file($openemrRoot . '/interface/globals.php')) {
    fwrite(STDERR, "OpenEMR root not found at {$openemrRoot} (set OPENEMR_ROOT).\n");
    exit(2);
}
require_once $openemrRoot . '/interface/globals.php';

use OpenEMR\Common\Database\QueryUtils;

const MODULE_DIRECTORY = 'oe-module-copilot';
const MODULE_TYPE_CUSTOM = 0; // InstModuleTable::MODULE_TYPE_CUSTOM

$infoLines = file(dirname(__DIR__) . '/info.txt', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
$name = is_array($infoLines) && isset($infoLines[0]) ? trim($infoLines[0]) : MODULE_DIRECTORY;

$existing = QueryUtils::fetchRecords('SELECT mod_id, mod_active FROM modules WHERE mod_directory = ?', [MODULE_DIRECTORY]);

if (count($existing) === 0) {
    $max = QueryUtils::fetchRecords('SELECT COALESCE(MAX(section_id), 0) AS max_id FROM module_acl_sections');
    $sectionId = ((int) ($max[0]['max_id'] ?? 0)) + 1;
    $modId = QueryUtils::sqlInsert(
        'INSERT INTO modules SET mod_id = ?, mod_name = ?, mod_active = 1, mod_ui_active = 1, mod_ui_name = ?, '
        . 'mod_relative_link = ?, mod_directory = ?, type = ?, sql_run = 1, date = NOW()',
        [$sectionId, $name, 'Clinical Co-Pilot', MODULE_DIRECTORY . '/index.php', MODULE_DIRECTORY, MODULE_TYPE_CUSTOM]
    );
    QueryUtils::sqlStatementThrowException(
        'INSERT INTO module_acl_sections (module_id, section_name, parent_section, section_identifier, section_id) VALUES (?, ?, 0, ?, ?)',
        [$modId, $name, MODULE_DIRECTORY, $modId]
    );
    $action = 'registered and enabled';
} elseif ((int) $existing[0]['mod_active'] !== 1) {
    QueryUtils::sqlStatementThrowException('UPDATE modules SET mod_active = 1, mod_ui_active = 1 WHERE mod_directory = ?', [MODULE_DIRECTORY]);
    $action = 'enabled';
} else {
    $action = 'already enabled';
}

$sql = file_get_contents(dirname(__DIR__) . '/sql/install.sql');
if ($sql === false) {
    fwrite(STDERR, "install.sql not readable\n");
    exit(2);
}
$statements = array_filter(array_map('trim', explode(";\n", preg_replace('/^--.*$/m', '', $sql) ?? '')));
foreach ($statements as $statement) {
    QueryUtils::sqlStatementThrowException($statement);
}

echo json_encode(['module' => MODULE_DIRECTORY, 'action' => $action, 'tables' => ['copilot_conversation']]) . "\n";
