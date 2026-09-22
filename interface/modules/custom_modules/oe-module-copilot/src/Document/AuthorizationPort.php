<?php

/**
 * Authorization boundary for document operations.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

interface AuthorizationPort
{
    /** @throws DocumentLifecycleException */
    public function authorize(string $operation, string $correlationId): DocumentContext;
}
