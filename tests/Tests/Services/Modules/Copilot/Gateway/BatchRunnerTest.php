<?php

/**
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Services\Modules\Copilot\Gateway;

use OpenEMR\Modules\Copilot\Gateway\AuthorizedPatientContext;
use OpenEMR\Modules\Copilot\Gateway\BatchRunner;
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;
use OpenEMR\Modules\Copilot\Gateway\Tools\EncountersTool;
use OpenEMR\Modules\Copilot\Gateway\Tools\PatientContextTool;
use PHPUnit\Framework\Attributes\Test;
use PHPUnit\Framework\TestCase;

/**
 * Covers BatchRunner::runOne(), used by public/gateway/tools.php once for the
 * legacy single-tool request and once per item for a batched request — so
 * every path here is exercised on both, without duplicating the check.
 */
class BatchRunnerTest extends TestCase
{
    /** Demo patient seeded by the dev-easy install; not created or torn down here. */
    private const DEMO_PID = 1;

    /** @param array<string, bool> $allowedSections */
    private function context(array $allowedSections): AuthorizedPatientContext
    {
        // A context built directly (not through ContextBuilder, which needs a real
        // conversation) — BatchRunner only ever receives an already-built one.
        return new AuthorizedPatientContext(
            userId: 1,
            username: 'phpunit-batchrunner-test',
            groupName: 'Default',
            pid: self::DEMO_PID,
            patientUuid: '',
            // PHP's array + keeps the left operand's value on a key collision, so the
            // overrides must come first for them to actually win over the all-false default.
            allowedSections: $allowedSections + array_fill_keys(ContextBuilder::SECTIONS, false),
            conversationId: str_repeat('a', 32),
            turnId: str_repeat('b', 16),
            correlationId: 'batchrunner-test',
        );
    }

    #[Test]
    public function normalRunReturnsTheToolsOwnEnvelope(): void
    {
        $ctx = $this->context(['demo' => true]);
        $result = BatchRunner::runOne(new PatientContextTool(), $ctx, []);

        $this->assertSame('patient_context', $result['tool']);
        // A real demo patient: retrieval succeeds and returns its one demographics
        // record, "ok" — proves run() was actually reached with a validated $ctx/$params,
        // not stopped at the params/ACL/audit checks before it.
        $this->assertSame('ok', $result['status']);
        $this->assertSame('batchrunner-test', $result['correlation_id']);
    }

    #[Test]
    public function missingSectionAclDeniesWithoutRunningTheTool(): void
    {
        // encounters needs the 'encounters' section; grant nothing.
        $ctx = $this->context([]);
        $result = BatchRunner::runOne(new EncountersTool(), $ctx, []);

        $this->assertSame('unavailable', $result['status']);
        $this->assertSame('forbidden', $result['reason']);
    }

    #[Test]
    public function invalidParamsDenyWithoutRunningTheTool(): void
    {
        $ctx = $this->context(['encounters' => true]);
        $result = BatchRunner::runOne(new EncountersTool(), $ctx, ['unexpected_key' => 'x']);

        $this->assertSame('unavailable', $result['status']);
        $this->assertSame('invalid_params', $result['reason']);
    }

    #[Test]
    public function rawUnavailableBuildsAnEnvelopeWithNoToolInstance(): void
    {
        // Exercises the shape BatchRunner::runOne() and tools.php's batch loop return for a
        // batch item that never reached an AbstractTool at all (unknown tool name, or an
        // unexpected exception the loop's own try/catch degrades to service_error).
        $ctx = $this->context([]);
        $result = BatchRunner::rawUnavailable('bogus_tool', $ctx, 'unknown_tool');

        $this->assertSame('bogus_tool', $result['tool']);
        $this->assertSame('unavailable', $result['status']);
        $this->assertSame('unknown_tool', $result['reason']);
        $this->assertSame([], $result['records']);
        $this->assertSame('batchrunner-test', $result['correlation_id']);
    }
}
