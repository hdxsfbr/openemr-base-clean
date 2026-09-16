<?php

/**
 * Conversation bindings (ADR-0002, ADR-0005): identifiers only, in the
 * module's own table. Created in-session, read by the gateway per tool call.
 *
/**
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Conversation;

use OpenEMR\Common\Database\QueryUtils;

final class ConversationRepository
{
    public const RETENTION_HOURS_AFTER_CLOSE = 24;
    public const IDLE_MINUTES = 30;

    /** @return array{id: string, correlation_id: string} */
    public function start(string $siteId, int $userId, string $username, int $pid): array
    {
        $id = bin2hex(random_bytes(16));
        $correlationId = bin2hex(random_bytes(8));
        QueryUtils::sqlInsert(
            'INSERT INTO copilot_conversation (id, site_id, user_id, username, pid, correlation_id, created_at, last_turn_at, turn_count) '
            . 'VALUES (?, ?, ?, ?, ?, ?, NOW(), NOW(), 0)',
            [$id, $siteId, $userId, $username, $pid, $correlationId]
        );
        return ['id' => $id, 'correlation_id' => $correlationId];
    }

    /** @return array<string, mixed>|null */
    public function find(string $id): ?array
    {
        if (!preg_match('/^[a-f0-9]{32}$/', $id)) {
            return null;
        }
        $rows = QueryUtils::fetchRecords('SELECT * FROM copilot_conversation WHERE id = ?', [$id]);
        return $rows[0] ?? null;
    }

    /** Records a new turn and returns its sequence number. */
    public function nextTurn(string $id): int
    {
        QueryUtils::sqlStatementThrowException(
            'UPDATE copilot_conversation SET turn_count = turn_count + 1, last_turn_at = NOW() WHERE id = ? AND closed_at IS NULL',
            [$id]
        );
        $rows = QueryUtils::fetchRecords('SELECT turn_count FROM copilot_conversation WHERE id = ?', [$id]);
        return (int) ($rows[0]['turn_count'] ?? 0);
    }

    /** True when the conversation's last turn is older than the idle window. */
    public function isIdle(array $conversation, \DateTimeImmutable $now): bool
    {
        $last = $conversation['last_turn_at'] ?? $conversation['created_at'] ?? null;
        if (!is_string($last) || $last === '') {
            return true;
        }
        $lastTurn = \DateTimeImmutable::createFromFormat('Y-m-d H:i:s', $last);
        if ($lastTurn === false) {
            return true;
        }
        return $now->getTimestamp() - $lastTurn->getTimestamp() > self::IDLE_MINUTES * 60;
    }

    public function close(string $id, string $reason): void
    {
        QueryUtils::sqlStatementThrowException(
            'UPDATE copilot_conversation SET closed_at = NOW(), close_reason = ? WHERE id = ? AND closed_at IS NULL',
            [substr($reason, 0, 40), $id]
        );
    }

    /** Deletes bindings closed longer ago than the retention window. */
    public function sweep(): int
    {
        return QueryUtils::sqlStatementThrowException(
            'DELETE FROM copilot_conversation WHERE closed_at IS NOT NULL AND closed_at < DATE_SUB(NOW(), INTERVAL ? HOUR)',
            [self::RETENTION_HOURS_AFTER_CLOSE]
        ) ? 1 : 0;
    }
}
