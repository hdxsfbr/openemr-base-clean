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
    'description' => 'Source-cited pre-visit assistant with physician-controlled immutable document sources in the patient dashboard.',
    'version' => '0.6.0',
    'author' => 'Andre Batista',
    'license' => 'GPL-3.0',
    'acl_category' => 'patients',
    'acl_section' => 'demo',
    'require' => [
        'openemr' => '>=8.1.0',
    ],
    'tables' => [
        'copilot_conversation',
        'copilot_document_upload',
        'copilot_document_extraction',
        'copilot_proposed_fact',
        'copilot_fact_review',
        'copilot_promoted_record',
        'copilot_action_outbox',
    ],
    'install' => [
        'sql' => 'sql/install.sql',
    ],
    'uninstall' => [
        'sql' => 'sql/uninstall.sql',
    ],
    'upgrade' => [
        '0.6.0' => [
            'sql' => 'sql/upgrade_0.6.0.sql',
        ],
    ],
];
