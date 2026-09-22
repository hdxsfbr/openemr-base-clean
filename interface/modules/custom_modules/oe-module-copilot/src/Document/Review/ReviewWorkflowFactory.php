<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Review;

use OpenEMR\Modules\Copilot\Document\DocumentAuthorization;
use OpenEMR\Modules\Copilot\Document\LiveAccessSnapshot;
use OpenEMR\Modules\Copilot\Document\OpenEmrDocumentAudit;
use OpenEMR\Modules\Copilot\Document\SystemClock;

final class ReviewWorkflowFactory
{
    public static function browser(): ReviewPromotionWorkflow
    {
        $audit = new OpenEmrDocumentAudit();
        return new ReviewPromotionWorkflow(
            new DocumentAuthorization(new LiveAccessSnapshot('browser'), $audit),
            new OpenEmrReviewRepository(dirname(__DIR__, 7) . '/contracts/schema'),
            $audit,
            new SystemClock()
        );
    }
}
