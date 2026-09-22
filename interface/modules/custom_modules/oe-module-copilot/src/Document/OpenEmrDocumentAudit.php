<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

use OpenEMR\Modules\Copilot\Gateway\Audit;

final class OpenEmrDocumentAudit implements AuditPort
{
    public function record(
        DocumentContext $context,
        string $operation,
        bool $success,
        string $reason,
        array $identifiers,
    ): void {
        Audit::event('copilot-document-' . str_replace('_', '-', $operation), $context->username, $context->groupName, $success, $context->pid, [
            'operation' => $operation,
            'reason' => $reason,
            'policy' => 'document-parity-1',
        ] + $identifiers);
    }
}
