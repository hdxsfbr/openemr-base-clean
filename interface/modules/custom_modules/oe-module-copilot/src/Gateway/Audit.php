<?php

/**
 * Co-pilot audit events in OpenEMR's own audit log (COMP-HIGH-004,
 * docs/audit/compliance.md section 5). Identifiers and counts only; never a
 * clinical value, prompt, or response.
 *
/**
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway;

use OpenEMR\Common\Logging\EventAuditLogger;

final class Audit
{
    /** @param array<string, scalar|null> $fields */
    public static function event(string $event, string $username, string $groupName, bool $success, ?int $pid, array $fields): void
    {
        $comment = json_encode($fields, JSON_UNESCAPED_SLASHES);
        EventAuditLogger::getInstance()->newEvent($event, $username, $groupName, $success ? 1 : 0, (string) $comment, $pid);
    }

    /** @param array<string, scalar|null> $fields */
    public static function toolRead(AuthorizedPatientContext $ctx, string $tool, array $fields): void
    {
        self::event('copilot-tool-read', $ctx->username, $ctx->groupName, true, $ctx->pid, [
            'tool' => $tool,
            'conversation_id' => $ctx->conversationId,
            'turn_id' => $ctx->turnId,
            'correlation_id' => $ctx->correlationId,
        ] + $fields);
    }

    /** @param array<string, scalar|null> $fields */
    public static function denied(?string $username, ?string $groupName, ?int $pid, string $reason, array $fields): void
    {
        self::event('copilot-denied', $username ?? '', $groupName ?? '', false, $pid, ['reason' => $reason] + $fields);
    }
}
