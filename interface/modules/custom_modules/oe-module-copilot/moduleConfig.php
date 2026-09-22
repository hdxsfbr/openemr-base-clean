<?php

/**
 * AgentForge Clinical Co-Pilot module information.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

return [
    'name' => 'AgentForge Clinical Co-Pilot',
    'description' => 'Read-only, source-cited pre-visit assistant embedded in the patient dashboard. See ARCHITECTURE.md and USERS.md in the repository root.',
    'version' => '0.5.0',
    'author' => 'Andre Batista',
    'license' => 'GPL-3.0',
    'acl_category' => 'patients',
    'acl_section' => 'demo',
    'require' => [
        'openemr' => '>=8.1.0',
    ],
    'tables' => [
        'copilot_conversation',
        'copilot_source_upload_intent',
        'copilot_source_document',
    ],
    'install' => [
        'sql' => 'sql/install.sql',
    ],
    'uninstall' => [
        'sql' => 'sql/uninstall.sql',
    ],
];
