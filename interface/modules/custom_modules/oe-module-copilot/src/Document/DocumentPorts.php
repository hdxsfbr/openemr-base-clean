<?php

/**
 * System-boundary ports for the patient-bound document lifecycle.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

require_once __DIR__ . '/DocumentContext.php';
require_once __DIR__ . '/AuthorizationPort.php';
require_once __DIR__ . '/AccessSnapshot.php';
require_once __DIR__ . '/AccessSnapshotPort.php';
require_once __DIR__ . '/UploadRepositoryPort.php';
require_once __DIR__ . '/DocumentStorePort.php';
require_once __DIR__ . '/UploadFilePort.php';
require_once __DIR__ . '/MalwareScannerPort.php';
require_once __DIR__ . '/AuditPort.php';
require_once __DIR__ . '/ClockPort.php';
