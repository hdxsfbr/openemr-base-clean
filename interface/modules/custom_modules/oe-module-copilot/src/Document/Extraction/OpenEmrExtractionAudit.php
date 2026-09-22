<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

use OpenEMR\Modules\Copilot\Gateway\Audit;

final class OpenEmrExtractionAudit implements ExtractionAuditPort
{
    public function record(string $operation, string $outcome, array $identifiers): void
    {
        $pid = is_int($identifiers['pid'] ?? null) ? $identifiers['pid'] : null;
        unset($identifiers['pid']);
        Audit::event('copilot-extraction-' . $operation, 'copilot-extraction-worker', 'service', true, $pid, [
            'operation' => $operation,
            'outcome' => $outcome,
            'contract_version' => '1.0.0',
        ] + $identifiers);
    }
}

