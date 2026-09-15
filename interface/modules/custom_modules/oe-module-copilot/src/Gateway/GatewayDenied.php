<?php

/**
 * A gateway check failed. The reason is specific in the audit log and generic
 * to the caller (ADR-0002 section 3).
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

final class GatewayDenied extends \RuntimeException
{
    public function __construct(
        public readonly string $reason,
        public readonly int $httpStatus = 403,
        public readonly bool $closesConversation = false,
    ) {
        parent::__construct('denied:' . $reason);
    }
}
