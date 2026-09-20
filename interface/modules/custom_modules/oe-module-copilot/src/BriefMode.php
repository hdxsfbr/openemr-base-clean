<?php

/**
 * When the co-pilot prepares the pre-visit brief for an opening chart.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot;

/** Read from the `COPILOT_BRIEF_ON_OPEN` environment variable, so it is a backed enum. */
enum BriefMode: string
{
    /** Retrieve nothing until the physician asks: the behaviour before 0.5.0. */
    case Off = 'off';

    /** Prepare the brief on every chart the physician opens. */
    case Always = 'always';

    /** Prepare it only for a patient the schedule shows a visit for today. */
    case VisitToday = 'visit_today';
}
