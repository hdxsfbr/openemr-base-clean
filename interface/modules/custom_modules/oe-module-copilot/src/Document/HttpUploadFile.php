<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

final class HttpUploadFile implements UploadFilePort
{
    private function __construct(private readonly string $name, private readonly string $temporaryPath)
    {
    }

    /** @param array<string, mixed> $file */
    public static function fromPhpUpload(array $file): self
    {
        if (($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK
            || !is_string($file['name'] ?? null)
            || !is_string($file['tmp_name'] ?? null)
            || !is_uploaded_file($file['tmp_name'])) {
            throw new DocumentLifecycleException('invalid_contract', false, 'The upload did not complete.', 422);
        }
        return new self($file['name'], $file['tmp_name']);
    }

    public function clientFilename(): string
    {
        return $this->name;
    }

    public function read(int $maximumBytes): string
    {
        $size = filesize($this->temporaryPath);
        if ($size === false || $size <= 0 || $size > $maximumBytes) {
            throw new DocumentLifecycleException('invalid_contract', false, 'The uploaded file exceeds the size limit.', 422);
        }
        $handle = fopen($this->temporaryPath, 'rb');
        if ($handle === false) {
            throw new DocumentLifecycleException('unavailable', true, 'The uploaded file is unavailable.', 503);
        }
        try {
            $bytes = stream_get_contents($handle, $maximumBytes + 1);
        } finally {
            fclose($handle);
        }
        if (!is_string($bytes) || strlen($bytes) > $maximumBytes) {
            throw new DocumentLifecycleException('invalid_contract', false, 'The uploaded file exceeds the size limit.', 422);
        }
        return $bytes;
    }

    public function scannerPath(): ?string
    {
        return $this->temporaryPath;
    }
}
