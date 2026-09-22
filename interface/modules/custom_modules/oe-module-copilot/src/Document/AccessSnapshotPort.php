<?php

/**
 * OpenEMR access-state boundary.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

interface AccessSnapshotPort
{
    public function current(): AccessSnapshot;
}
