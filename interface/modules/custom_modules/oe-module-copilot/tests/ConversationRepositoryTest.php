<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

use DateTimeImmutable;
use OpenEMR\Modules\Copilot\Conversation\ConversationRepository;
use PHPUnit\Framework\TestCase;

final class ConversationRepositoryTest extends TestCase
{
    public static function setUpBeforeClass(): void
    {
        require_once dirname(__DIR__) . '/src/Conversation/ConversationRepository.php';
    }

    public function testIdleWindowKeepsRecentConversationAndExpiresOldConversation(): void
    {
        $repository = new ConversationRepository();
        $now = new DateTimeImmutable('2026-09-18 17:00:00');

        self::assertFalse($repository->isIdle(['last_turn_at' => '2026-09-18 16:31:00'], $now));
        self::assertTrue($repository->isIdle(['last_turn_at' => '2026-09-18 16:29:00'], $now));
    }

    public function testIdleWindowFailsClosedWhenTimestampIsMissingOrInvalid(): void
    {
        $repository = new ConversationRepository();
        $now = new DateTimeImmutable('2026-09-18 17:00:00');

        self::assertTrue($repository->isIdle([], $now));
        self::assertTrue($repository->isIdle(['last_turn_at' => 'not-a-date'], $now));
    }
}
