<?php

/**
 * Compatibility seams for the two OpenEMR versions the module runs on: the
 * repository (8.2.0-dev, local dev stack) and the pinned release image (8.1.1,
 * deployment). Only APIs present in both are used here, so upstream drift
 * fails in one place.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot;

use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Core\OEGlobalsBag;

final class Compat
{
    /** The open chart's pid from the login session (0 when no chart is open). */
    public static function openPid(): int
    {
        $session = SessionWrapperFactory::getInstance()->getActiveSession();
        return (int) ($session->get('pid') ?? 0);
    }

    public static function siteDir(): string
    {
        return (string) OEGlobalsBag::getInstance()->get('OE_SITE_DIR');
    }
}
