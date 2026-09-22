<?php

/**
 * Reauthorized click-to-source endpoint.
 *
 * POST accepts only CSRF plus opaque conversation, turn, and citation
 * selectors. Source identity, hrefs, values, hashes, pages, and boxes are
 * resolved again from server-owned authorities.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

require_once __DIR__ . '/../../../../../globals.php';

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\Copilot\Http\Json;
use OpenEMR\Modules\Copilot\SourceReview\SourceReviewFactory;
use OpenEMR\Modules\Copilot\SourceReview\SourceReviewHttp;

$correlationId = Json::correlationId();
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    Json::error(405, 'invalid_contract', 'POST is required.', $correlationId);
}
$session = SessionWrapperFactory::getInstance()->getActiveSession();
$body = Json::body();
$csrf = $body['csrf_token'] ?? null;
if (!is_string($csrf) || !CsrfUtils::verifyCsrfToken($csrf, $session, 'copilot')) {
    Json::error(403, 'forbidden', 'The source request is not authorized.', $correlationId);
}
unset($body['csrf_token']);

$response = (new SourceReviewHttp(SourceReviewFactory::browser()))->handle($body, $correlationId);
Json::send($response['http_status'], $response['body'], $correlationId);
