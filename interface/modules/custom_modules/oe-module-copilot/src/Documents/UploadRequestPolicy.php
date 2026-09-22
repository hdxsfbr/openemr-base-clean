<?php

/** @package OpenEMR */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Documents;

/** Pure request-shape guard: patient and type authority are always server-bound. */
final class UploadRequestPolicy
{
    /** @param array<string, mixed> $body */
    public static function acceptsIntent(array $body): bool
    {
        return ($body['document_type'] ?? null) === SourceDocumentRepository::DOCUMENT_TYPE
            && !array_key_exists('pid', $body)
            && !array_key_exists('patient_id', $body);
    }

    /** @param array<string, mixed> $body */
    public static function acceptsUpload(array $body): bool
    {
        return !array_key_exists('pid', $body)
            && !array_key_exists('patient_id', $body)
            && !array_key_exists('document_type', $body);
    }
}
