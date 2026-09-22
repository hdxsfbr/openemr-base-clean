<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

require_once dirname(__DIR__) . '/src/Document/DocumentPorts.php';
require_once dirname(__DIR__) . '/src/Document/DocumentLifecycleException.php';
require_once dirname(__DIR__) . '/src/Document/DocumentAuthorization.php';

use OpenEMR\Modules\Copilot\Document\AccessSnapshot;
use OpenEMR\Modules\Copilot\Document\AccessSnapshotPort;
use OpenEMR\Modules\Copilot\Document\AuditPort;
use OpenEMR\Modules\Copilot\Document\DocumentAuthorization;
use OpenEMR\Modules\Copilot\Document\DocumentContext;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleException;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class DocumentAuthorizationTest extends TestCase
{
    /** @return iterable<string, array{string}> */
    public static function browserOperations(): iterable
    {
        foreach (['upload', 'source_read', 'review', 'promotion', 'amendment', 'withdrawal'] as $operation) {
            yield $operation => [$operation];
        }
    }

    #[DataProvider('browserOperations')]
    public function testEachDocumentOperationHasAnExplicitLiveBrowserPolicy(string $operation): void
    {
        $authorization = new DocumentAuthorization(new FixedAccessSnapshot(), new PolicyAudit());

        $context = $authorization->authorize($operation, 'corr-policy-0001');

        self::assertSame(42, $context->pid);
    }

    /** @return iterable<string, array{AccessSnapshot, string}> */
    public static function deniedSnapshots(): iterable
    {
        yield 'inactive user' => [FixedAccessSnapshot::snapshot(active: false), 'forbidden'];
        yield 'missing document ACL' => [FixedAccessSnapshot::snapshot(docsAcl: false), 'forbidden'];
        yield 'squad denied' => [FixedAccessSnapshot::snapshot(squadAllowed: false), 'forbidden'];
        yield 'break glass' => [FixedAccessSnapshot::snapshot(breakGlass: true), 'forbidden'];
        yield 'model write attempt' => [FixedAccessSnapshot::snapshot(principal: 'agent'), 'forbidden'];
    }

    #[DataProvider('deniedSnapshots')]
    public function testDeniedRolesSquadsBreakGlassAndModelWritesAreAudited(AccessSnapshot $snapshot, string $code): void
    {
        $audit = new PolicyAudit();
        $authorization = new DocumentAuthorization(new FixedAccessSnapshot($snapshot), $audit);

        try {
            $authorization->authorize('promotion', 'corr-policy-deny');
            self::fail('The live policy must deny this snapshot.');
        } catch (DocumentLifecycleException $exception) {
            self::assertSame($code, $exception->errorCode);
        }

        self::assertCount(1, $audit->events);
        self::assertFalse($audit->events[0]['success']);
    }

    public function testUnknownOperationFailsClosedAndIsAudited(): void
    {
        $audit = new PolicyAudit();
        $authorization = new DocumentAuthorization(new FixedAccessSnapshot(), $audit);

        $this->expectException(DocumentLifecycleException::class);
        try {
            $authorization->authorize('model_write', 'corr-wrong-op');
        } finally {
            self::assertCount(1, $audit->events);
        }
    }
}

final class FixedAccessSnapshot implements AccessSnapshotPort
{
    public function __construct(private readonly ?AccessSnapshot $fixed = null)
    {
    }

    public function current(): AccessSnapshot
    {
        return $this->fixed ?? self::snapshot();
    }

    public static function snapshot(
        bool $active = true,
        bool $docsAcl = true,
        bool $squadAllowed = true,
        bool $breakGlass = false,
        string $principal = 'browser',
    ): AccessSnapshot {
        return new AccessSnapshot(
            new DocumentContext('default', 7, 'synthetic-physician', 'Physicians', 42, 'patient-uuid-42'),
            $active,
            $docsAcl,
            $squadAllowed,
            $breakGlass,
            $principal
        );
    }
}

final class PolicyAudit implements AuditPort
{
    /** @var list<array<string, mixed>> */
    public array $events = [];

    public function record(DocumentContext $context, string $operation, bool $success, string $reason, array $identifiers): void
    {
        $this->events[] = compact('operation', 'success', 'reason', 'identifiers');
    }
}
