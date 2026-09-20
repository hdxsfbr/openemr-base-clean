<?php

/**
 * Panel bootstrap under the user's session: returns the CSRF token for the
 * co-pilot subject, whether a chart is open, and whether the panel should
 * prepare the pre-visit brief for it (BriefPolicy). Never returns the pid.
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
use OpenEMR\Modules\Copilot\Bootstrap;
use OpenEMR\Modules\Copilot\BriefPolicy;
use OpenEMR\Modules\Copilot\Compat;
use OpenEMR\Modules\Copilot\Http\Json;

$correlationId = Json::correlationId();
$session = SessionWrapperFactory::getInstance()->getActiveSession();
$userId = (int) $session->get('authUserID', 0);
$username = (string) $session->get('authUser', '');
if ($userId <= 0 || $username === '') {
    Json::error(401, 'unauthorized', 'Not signed in.', $correlationId);
}
$pid = Compat::openPid();

Json::send(200, [
    'csrf_token' => CsrfUtils::collectCsrfToken($session, 'copilot'),
    'chart_open' => $pid > 0,
    'brief_on_open' => BriefPolicy::startsOnOpen($username, $pid),
    'module_version' => Bootstrap::VERSION,
    'correlation_id' => $correlationId,
], $correlationId);
