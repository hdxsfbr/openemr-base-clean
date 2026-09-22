<?php

/**
 * Time boundary for deterministic lifecycle tests.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

use DateTimeImmutable;

interface ClockPort
{
    public function now(): DateTimeImmutable;
}
