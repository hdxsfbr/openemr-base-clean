<?php

/** @package OpenEMR */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Documents;

/**
 * The deliberately small Slice 2A intake format is a tagged synthetic PDF.
 *
 * The tag is an intake-form format discriminator, not extracted content or a
 * clinical assertion. It lets the storage boundary reject a known lab fixture
 * misdeclared as an intake form before source storage. OCR/image support is a
 * later extraction concern and is intentionally not implied by this policy.
 */
final class IntakeFormPolicy
{
    public const MAX_BYTES = 10 * 1024 * 1024;
    public const MAX_PAGES = 10;
    public const FORMAT_MARKER = 'AgentForge Synthetic Intake Form';

    /**
     * @return array{bytes: string, document_type: 'intake_form', mime_type: 'application/pdf', byte_size: int, page_count: int, content_hash: string}
     * @throws SourceUploadException
     */
    public static function validate(array $file): array
    {
        if (($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK || !is_string($file['tmp_name'] ?? null) || !is_uploaded_file($file['tmp_name'])) {
            throw new SourceUploadException('invalid_file');
        }
        $size = (int) ($file['size'] ?? 0);
        if ($size <= 0 || $size > self::MAX_BYTES) {
            throw new SourceUploadException('invalid_file');
        }
        $mime = (new \finfo(FILEINFO_MIME_TYPE))->file($file['tmp_name']);
        $bytes = file_get_contents($file['tmp_name']);
        if (!is_string($bytes)) {
            throw new SourceUploadException('malformed_source');
        }
        return self::validateBytes($bytes, $mime, $size);
    }

    /**
     * @return array{bytes: string, document_type: 'intake_form', mime_type: 'application/pdf', byte_size: int, page_count: int, content_hash: string}
     * @throws SourceUploadException
     */
    public static function validateBytes(string $bytes, string|false $mime, ?int $declaredSize = null): array
    {
        $validated = LabPdfPolicy::validateBytes($bytes, $mime, $declaredSize);
        if ($validated['byte_size'] > self::MAX_BYTES || $validated['page_count'] > self::MAX_PAGES) {
            throw new SourceUploadException('malformed_source');
        }
        if (!str_contains($bytes, self::FORMAT_MARKER)) {
            throw new SourceUploadException('invalid_file');
        }
        return ['document_type' => 'intake_form'] + $validated;
    }
}
