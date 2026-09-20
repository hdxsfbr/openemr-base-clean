<?php

/**
 * Decides whether the panel starts the pre-visit brief when a chart opens
 * instead of waiting for the physician to click a question (ADR-0003
 * amendment 2026-09-19).
 *
 * The decision is made here, server-side, under the physician's own session,
 * and the panel only obeys it: there is no client flag to forge, exactly as
 * the agent's known-plan table matches on its own constants rather than on
 * anything the client asserts.
 *
 * Authorization is unchanged. The only chart read is the one already open
 * under ADR-0002, and the schedule question is "does this open chart have a
 * visit today", never "which patients are on my schedule" -- no patient
 * lookup, and no read of a chart that is not open.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot;

use DateTimeImmutable;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Modules\Copilot\Gateway\ContextBuilder;

final class BriefPolicy
{
    public const ENV_VAR = 'COPILOT_BRIEF_ON_OPEN';

    /**
     * Sections a brief can make a statement from. `demo` is excluded on
     * purpose: a role holding only demographics (front desk) would get a
     * denied turn and an audit row on every chart it opens, so it gets no
     * brief at all.
     */
    private const CLINICAL_SECTIONS = ['encounters', 'notes', 'problems', 'medications', 'prescriptions', 'allergies', 'labs'];

    public static function mode(): BriefMode
    {
        $raw = getenv(self::ENV_VAR);
        if (!is_string($raw) || trim($raw) === '') {
            // The same default the runtime compose file sets, so there is one
            // answer to "what does it do here", and it is the cheap one: a brief
            // for a patient being seen today. A site with no schedule for today
            // prepares nothing until it sets `always`.
            return BriefMode::VisitToday;
        }
        $mode = BriefMode::tryFrom(strtolower(trim($raw)));
        if ($mode === null) {
            // Fail closed on a typo: spending on every chart open is the costly direction.
            error_log('oe-module-copilot: unknown ' . self::ENV_VAR . ' value; no brief is prepared on chart open');
            return BriefMode::Off;
        }
        return $mode;
    }

    /** Whether the open chart's panel should prepare the brief for this user now. */
    public static function startsOnOpen(string $username, int $pid, ?DateTimeImmutable $now = null): bool
    {
        $mode = self::mode();
        if ($mode === BriefMode::Off || $pid <= 0 || $username === '') {
            return false;
        }
        return self::decide(
            $mode,
            !ContextBuilder::isBreakGlass($username) && self::hasClinicalAccess($username),
            // Only the mode that reads the schedule asks the schedule.
            $mode === BriefMode::VisitToday && self::hasVisitToday($pid, $now ?? new DateTimeImmutable()),
        );
    }

    /** The rule itself, over facts the caller has already read. */
    public static function decide(BriefMode $mode, bool $mayReadTheChart, bool $hasVisitToday): bool
    {
        return match ($mode) {
            BriefMode::Off => false,
            BriefMode::Always => $mayReadTheChart,
            BriefMode::VisitToday => $mayReadTheChart && $hasVisitToday,
        };
    }

    /**
     * A visit on today's schedule for this patient, with any provider: the
     * physician opening the chart may be covering for the one it is booked
     * under. Cancelled appointments (`x`) do not count. The query is bounded
     * by the `pc_eventDate` index and today's schedule, so it reads a handful
     * of rows (AUDIT.md 2.2 flagged unindexed whole-schedule prefetch; this
     * is neither).
     *
     * "Today" is PHP's, passed in, not the database's `CURDATE()`. The two are
     * the same clock only because OpenEMR re-points the MySQL session at PHP's
     * offset per request, which depends on a `gbl_time_zone` row existing to
     * run that branch (interface/globals.php). A brief is not worth that
     * chain: the appointment the physician sees on their calendar is the one
     * this must agree with, and that is PHP's day.
     */
    private static function hasVisitToday(int $pid, DateTimeImmutable $today): bool
    {
        $rows = QueryUtils::fetchRecords(
            "SELECT 1 FROM openemr_postcalendar_events WHERE pc_eventDate = ? AND pc_pid = ? AND pc_apptstatus != 'x' LIMIT 1",
            [$today->format('Y-m-d'), (string) $pid]
        );
        return $rows !== [];
    }

    private static function hasClinicalAccess(string $username): bool
    {
        $matrix = ContextBuilder::sectionMatrix($username);
        foreach (self::CLINICAL_SECTIONS as $section) {
            if ($matrix[$section] ?? false) {
                return true;
            }
        }
        return false;
    }
}
