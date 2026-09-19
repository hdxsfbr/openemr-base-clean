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

    /**
     * Chart records are about to leave for an AI model provider (the agent declared it on the
     * batch that retrieved them). Who, which patient, which provider and model, which tools and
     * how many records; never a record. Written before the records are returned, like toolRead.
     *
     * @param array<array-key, mixed> $declared the agent's {provider, model}; anything not id-shaped is recorded as "unspecified"
     * @param list<array<string, mixed>> $released the tool envelopes of this batch that carry records
     */
    public static function modelDisclosure(AuthorizedPatientContext $ctx, array $declared, array $released): void
    {
        $idShaped = static fn(mixed $value): string => is_string($value) && preg_match('/^[A-Za-z0-9._:-]{1,64}$/', $value) === 1 ? $value : 'unspecified';
        $tools = [];
        $records = 0;
        foreach ($released as $envelope) {
            $tools[] = is_string($envelope['tool'] ?? null) ? $envelope['tool'] : 'unknown';
            $records += is_array($envelope['records'] ?? null) ? count($envelope['records']) : 0;
        }
        self::event('copilot-model-disclosure', $ctx->username, $ctx->groupName, true, $ctx->pid, [
            'provider' => $idShaped($declared['provider'] ?? null),
            'model' => $idShaped($declared['model'] ?? null),
            'tools' => implode(',', $tools),
            'records' => $records,
            'conversation_id' => $ctx->conversationId,
            'turn_id' => $ctx->turnId,
            'correlation_id' => $ctx->correlationId,
        ]);
    }

    /** @param array<string, scalar|null> $fields */
    public static function denied(?string $username, ?string $groupName, ?int $pid, string $reason, array $fields): void
    {
        self::event('copilot-denied', $username ?? '', $groupName ?? '', false, $pid, ['reason' => $reason] + $fields);
    }
}
