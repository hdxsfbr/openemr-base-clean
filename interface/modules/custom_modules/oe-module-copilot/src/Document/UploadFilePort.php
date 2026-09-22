<?php

/**
 * Uploaded-file boundary that defers byte access until authorization succeeds.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

interface UploadFilePort
{
    public function clientFilename(): string;

    public function read(int $maximumBytes): string;

    public function scannerPath(): ?string;
}
