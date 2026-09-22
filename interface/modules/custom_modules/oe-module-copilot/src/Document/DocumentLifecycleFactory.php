<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

use OpenEMR\Modules\Copilot\Compat;

final class DocumentLifecycleFactory
{
    public static function browser(): DocumentLifecycle
    {
        $audit = new OpenEmrDocumentAudit();
        return new DocumentLifecycle(
            new DocumentAuthorization(new LiveAccessSnapshot('browser'), $audit),
            new OpenEmrUploadRepository(),
            new OpenEmrDocumentStore(),
            new OpenEmrMalwareScanner(),
            $audit,
            new SystemClock(),
            self::secret()
        );
    }

    private static function secret(): string
    {
        $path = getenv('COPILOT_UPLOAD_SECRET_FILE') ?: Compat::siteDir() . '/documents/copilot/upload_secret';
        if (!is_file($path)) {
            $directory = dirname($path);
            if (!is_dir($directory) && !mkdir($directory, 0700, true) && !is_dir($directory)) {
                throw new \RuntimeException('Upload secret directory unavailable');
            }
            $secret = bin2hex(random_bytes(32));
            if (file_put_contents($path, $secret, LOCK_EX) === false) {
                throw new \RuntimeException('Upload secret unavailable');
            }
            chmod($path, 0600);
        }
        $secret = trim((string) file_get_contents($path));
        if (strlen($secret) < 32) {
            throw new \RuntimeException('Upload secret missing or too short');
        }
        return $secret;
    }
}
