<?php

/**
 * Runs one tool call end to end: validate params, check section ACL, audit,
 * run (ADR-0003 step 4). Used once for the legacy single-tool request and
 * once per item for a batched request (public/gateway/tools.php), so the two
 * paths share every check instead of duplicating them.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway;

use OpenEMR\Modules\Copilot\Gateway\Tools\AbstractTool;
use OpenEMR\Modules\Copilot\Gateway\Tools\ToolRegistry;

final class BatchRunner
{
    /** @param array<string, mixed> $rawParams */
    public static function runOne(AbstractTool $tool, AuthorizedPatientContext $ctx, array $rawParams): array
    {
        try {
            $params = ToolRegistry::params($tool, $rawParams);
        } catch (\InvalidArgumentException) {
            Audit::denied($ctx->username, $ctx->groupName, $ctx->pid, 'invalid_params', [
                'tool' => $tool->name(),
                'conversation_id' => $ctx->conversationId,
                'turn_id' => $ctx->turnId,
                'correlation_id' => $ctx->correlationId,
            ]);
            return self::rawUnavailable($tool->name(), $ctx, 'invalid_params');
        }

        // Section ACL per tool, the same checks the chart pages make (ADR-0002 section 1).
        $missing = array_values(array_filter($tool->sections(), static fn(string $s): bool => !$ctx->allows($s)));
        if ($missing !== []) {
            Audit::denied($ctx->username, $ctx->groupName, $ctx->pid, 'forbidden', [
                'tool' => $tool->name(),
                'sections' => implode(',', $missing),
                'conversation_id' => $ctx->conversationId,
                'turn_id' => $ctx->turnId,
                'correlation_id' => $ctx->correlationId,
            ]);
            // The tool answers "unavailable/forbidden" so the turn continues for other sections (ADR-0002 section 3).
            return $tool->unavailable($ctx, $params, 'forbidden');
        }

        // Audit before data leaves (COMP-HIGH-004). If this insert fails the tool is unavailable.
        try {
            Audit::toolRead($ctx, $tool->name(), [
                'since' => $params['since'],
                'until' => $params['until'],
                'term' => $params['term'] !== null ? 'yes' : null,
                'analyte' => $params['analyte'] !== null ? 'yes' : null,
            ]);
        } catch (\Throwable) {
            return $tool->unavailable($ctx, $params, 'audit_unavailable');
        }

        return $tool->run($ctx, $params);
    }

    /**
     * A tool ran into a problem before an AbstractTool instance could build its
     * own envelope (unknown name, invalid params, or an unexpected exception
     * elsewhere in a batch item) — degrades only that one item, never the
     * whole request.
     */
    public static function rawUnavailable(string $toolName, AuthorizedPatientContext $ctx, string $reason): array
    {
        return [
            'tool' => $toolName,
            'tool_version' => 'n/a',
            'contract_version' => AbstractTool::CONTRACT_VERSION,
            'status' => 'unavailable',
            'reason' => $reason,
            'records' => [],
            'window' => ['since' => null, 'until' => null],
            'truncated' => false,
            'omitted_count' => 0,
            'counts' => (object) [],
            'absence_state' => null,
            'latency_ms' => 0.0,
            'correlation_id' => $ctx->correlationId,
        ];
    }
}
