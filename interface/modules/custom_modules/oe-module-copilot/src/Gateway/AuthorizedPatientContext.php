<?php

/**
 * The immutable result of the gateway's checks (ADR-0002 section 1). Tools
 * receive this and never read the session, the ACL, or a raw pid themselves.
 *
/**
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway;

final readonly class AuthorizedPatientContext
{
    public const POLICY_VERSION = 'parity-1';

    /** @param array<string, bool> $allowedSections section key => allowed */
    public function __construct(
        public int $userId,
        public string $username,
        public string $groupName,
        public int $pid,
        public string $patientUuid,
        public array $allowedSections,
        public string $conversationId,
        public string $turnId,
        public string $correlationId,
    ) {
    }

    public function allows(string $section): bool
    {
        return $this->allowedSections[$section] ?? false;
    }
}
