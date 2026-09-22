<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Review;

use OpenEMR\Modules\Copilot\Document\DocumentLifecycle;
use OpenEMR\Modules\Copilot\Document\DocumentLifecycleException;

final class OpenEmrReviewSource implements ReviewSourcePort
{
    public function __construct(private readonly DocumentLifecycle $documents)
    {
    }

    public function renderPage(string $sourceDocumentId, int $pageNumber, string $correlationId): array
    {
        $read = $this->documents->readSource($sourceDocumentId, $correlationId);
        $source = $read['source'];
        if ($pageNumber < 1 || $pageNumber > (int) ($source['page_count'] ?? 0) || !class_exists(\Imagick::class)) {
            throw new DocumentLifecycleException('unavailable', true, 'The source page cannot be rendered.', 503);
        }

        try {
            $image = new \Imagick();
            $image->setResolution(144, 144);
            $image->readImageBlob($read['bytes'], 'source.' . ($source['mime_type'] === 'application/pdf' ? 'pdf' : 'image'));
            if ($source['mime_type'] === 'application/pdf') {
                $image->setIteratorIndex($pageNumber - 1);
            }
            $page = $image->getImage();
            $page->setImageBackgroundColor('white');
            if ($page->getImageAlphaChannel()) {
                $page = $page->mergeImageLayers(\Imagick::LAYERMETHOD_FLATTEN);
            }
            if ($page->getImageWidth() > 2400 || $page->getImageHeight() > 3200) {
                $page->thumbnailImage(2400, 3200, true, true);
            }
            $page->setImageFormat('png');
            $page->stripImage();
            $bytes = $page->getImageBlob();
            $page->clear();
            $image->clear();
        } catch (\Throwable $exception) {
            throw new DocumentLifecycleException('unavailable', true, 'The source page cannot be rendered.', 503);
        }
        if ($bytes === '' || strlen($bytes) > 12_000_000) {
            throw new DocumentLifecycleException('unavailable', true, 'The source page cannot be rendered.', 503);
        }

        return [
            'source_document_id' => $sourceDocumentId,
            'content_sha256' => (string) $source['content_sha256'],
            'page_number' => $pageNumber,
            'media_type' => 'image/png',
            'bytes' => $bytes,
        ];
    }
}
