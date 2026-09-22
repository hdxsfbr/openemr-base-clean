<?php

/**
 * OpenEMR Document storage boundary.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

interface DocumentStorePort
{
    public function store(DocumentContext $context, string $category, string $filename, string $mimeType, string $bytes): string;

    public function read(DocumentContext $context, string $openEmrDocumentId): string;

    public function remove(DocumentContext $context, string $openEmrDocumentId): void;
}
