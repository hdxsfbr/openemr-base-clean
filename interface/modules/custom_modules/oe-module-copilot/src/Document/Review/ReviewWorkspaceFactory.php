<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Review;

use OpenEMR\Modules\Copilot\Document\DocumentAuthorization;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleFactory;
use OpenEMR\Modules\Copilot\Document\LiveAccessSnapshot;
use OpenEMR\Modules\Copilot\Document\OpenEmrDocumentAudit;

final class ReviewWorkspaceFactory
{
    public static function browser(): ReviewWorkspace
    {
        $audit = new OpenEmrDocumentAudit();
        return new ReviewWorkspace(
            new DocumentAuthorization(new LiveAccessSnapshot('browser'), $audit),
            new OpenEmrReviewRepository(dirname(__DIR__, 7) . '/contracts/schema'),
            new OpenEmrReviewSource(DocumentLifecycleFactory::browser()),
            $audit,
        );
    }
}
