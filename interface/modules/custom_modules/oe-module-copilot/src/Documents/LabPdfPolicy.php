<?php

/** @package OpenEMR */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Documents;

/**
 * Side-effect-free Slice 1 file policy. It intentionally validates only one
 * bounded PDF path; image and intake support is a later versioned contract.
 */
final class LabPdfPolicy
{
    public const MAX_BYTES = 20 * 1024 * 1024;
    public const MAX_PAGES = 20;

    /**
     * @return array{bytes: string, mime_type: 'application/pdf', byte_size: int, page_count: int, content_hash: string}
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
     * @return array{bytes: string, mime_type: 'application/pdf', byte_size: int, page_count: int, content_hash: string}
     * @throws SourceUploadException
     */
    public static function validateBytes(string $bytes, string|false $mime, ?int $declaredSize = null): array
    {
        $size = strlen($bytes);
        if ($declaredSize !== null && $declaredSize !== $size) {
            throw new SourceUploadException('malformed_source');
        }
        if ($size <= 0 || $size > self::MAX_BYTES || !str_starts_with($bytes, '%PDF-')) {
            throw new SourceUploadException('malformed_source');
        }
        if ($mime !== 'application/pdf') {
            throw new SourceUploadException('invalid_file');
        }
        // This is a deliberately conservative pre-storage bound, not an OCR parser.
        $pages = preg_match_all('/\/Type\s*\/Page(?!s)\b/', $bytes);
        if ($pages === false || $pages < 1 || $pages > self::MAX_PAGES) {
            throw new SourceUploadException('malformed_source');
        }
        return [
            'bytes' => $bytes,
            'mime_type' => 'application/pdf',
            'byte_size' => $size,
            'page_count' => $pages,
            'content_hash' => hash('sha3-512', $bytes),
        ];
    }
}
