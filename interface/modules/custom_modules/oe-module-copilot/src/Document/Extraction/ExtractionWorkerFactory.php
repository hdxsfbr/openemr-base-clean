<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

use OpenEMR\Modules\Copilot\Compat;

final class ExtractionWorkerFactory
{
    public static function http(): ExtractionWorkerHttp
    {
        $repository = new OpenEmrExtractionRepository();
        $clock = new SystemExtractionClock();
        $gateway = new ExtractionJobGateway(
            $repository,
            new OpenEmrExtractionSource(),
            new OpenEmrExtractionAudit(),
            $clock,
            new StrictExtractionEnvelopeValidator(dirname(__DIR__, 7) . '/contracts/schema')
        );
        return new ExtractionWorkerHttp(
            new ExtractionWorkerAuthenticator(self::delegationSecret(), $repository, fn(): \DateTimeImmutable => $clock->now()),
            $gateway
        );
    }

    private static function delegationSecret(): string
    {
        $path = getenv('COPILOT_DELEGATION_SECRET_FILE') ?: Compat::siteDir() . '/documents/copilot/delegation_secret';
        if (!is_readable($path)) {
            throw new \RuntimeException('Delegation secret unavailable');
        }
        $secret = trim((string) file_get_contents($path));
        if (strlen($secret) < 32) {
            throw new \RuntimeException('Delegation secret missing or too short');
        }
        return $secret;
    }
}

