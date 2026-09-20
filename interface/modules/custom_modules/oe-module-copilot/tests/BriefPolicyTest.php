<?php

/**
 * The brief-on-open rule, over facts the caller has already read. The reads
 * themselves (ACL matrix, today's schedule) are exercised live by the eval
 * suite against a seeded cohort; what is worth pinning here is the rule.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

use OpenEMR\Modules\Copilot\BriefMode;
use OpenEMR\Modules\Copilot\BriefPolicy;
use PHPUnit\Framework\TestCase;

final class BriefPolicyTest extends TestCase
{
    public static function setUpBeforeClass(): void
    {
        require_once dirname(__DIR__) . '/src/BriefMode.php';
        require_once dirname(__DIR__) . '/src/BriefPolicy.php';
    }

    public function testOffPreparesNothingWhateverTheChartOrScheduleSays(): void
    {
        self::assertFalse(BriefPolicy::decide(BriefMode::Off, true, true));
        self::assertFalse(BriefPolicy::decide(BriefMode::Off, true, false));
    }

    public function testAlwaysPreparesForAnyChartTheUserMayRead(): void
    {
        self::assertTrue(BriefPolicy::decide(BriefMode::Always, true, false));
        self::assertTrue(BriefPolicy::decide(BriefMode::Always, true, true));
    }

    public function testVisitTodayPreparesOnlyForAPatientBeingSeenToday(): void
    {
        self::assertTrue(BriefPolicy::decide(BriefMode::VisitToday, true, true));
        self::assertFalse(BriefPolicy::decide(BriefMode::VisitToday, true, false));
    }

    /**
     * A role the chart hides clinical sections from (front desk) would get a
     * denied turn and an audit row on every chart it opened.
     */
    public function testNoModePreparesForAUserWhoMayNotReadTheChart(): void
    {
        foreach (BriefMode::cases() as $mode) {
            self::assertFalse(BriefPolicy::decide($mode, false, true), $mode->value);
        }
    }

    public function testModeIsReadFromTheEnvironmentAndFailsClosedOnAnUnknownValue(): void
    {
        $original = getenv(BriefPolicy::ENV_VAR);
        try {
            putenv(BriefPolicy::ENV_VAR . '=visit_today');
            self::assertSame(BriefMode::VisitToday, BriefPolicy::mode());
            putenv(BriefPolicy::ENV_VAR . '= VISIT_TODAY ');
            self::assertSame(BriefMode::VisitToday, BriefPolicy::mode(), 'case and padding from a compose file');
            putenv(BriefPolicy::ENV_VAR . '=sometimes');
            self::assertSame(BriefMode::Off, BriefPolicy::mode(), 'a typo must not spend on every chart open');
            putenv(BriefPolicy::ENV_VAR);
            self::assertSame(BriefMode::VisitToday, BriefPolicy::mode(), 'unset is the shipped default');
        } finally {
            if (is_string($original)) {
                putenv(BriefPolicy::ENV_VAR . '=' . $original);
            } else {
                putenv(BriefPolicy::ENV_VAR);
            }
        }
    }
}
