<?php

/**
 * Panel bootstrap under the user's session: returns the CSRF token for the
 * co-pilot subject and whether a chart is open. Never returns the pid.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\Copilot\Compat;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
$session = SessionWrapperFactory::getInstance()->getActiveSession();
$userId = (int) $session->get('authUserID', 0);
if ($userId <= 0) {
    Json::error(401, 'unauthorized', 'Not signed in.', $correlationId);
}

Json::send(200, [
    'csrf_token' => CsrfUtils::collectCsrfToken($session, 'copilot'),
    'chart_open' => Compat::openPid() > 0,
    'module_version' => '0.1.0',
    'correlation_id' => $correlationId,
], $correlationId);
