<?php

/**
 * AgentForge Clinical Co-Pilot module bootstrap class.
 *
 * Renders the co-pilot panel at the top of the patient dashboard through the
 * patient-scoped render event (ADR-0003). The panel is inert until the user
 * clicks a question: no retrieval, no model call, no audit row before that.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot;

use OpenEMR\Core\OEGlobalsBag;
use OpenEMR\Events\PatientDemographics\RenderEvent;
use Symfony\Component\EventDispatcher\EventDispatcherInterface;

final class Bootstrap
{
    public const MODULE_DIRECTORY = 'oe-module-copilot';
    public const MODULE_PATH = '/interface/modules/custom_modules/' . self::MODULE_DIRECTORY;
    public const VERSION = '0.1.0';

    /** Path prefix, relative to the site root, where the agent API is published by the edge. */
    public const API_BASE = '/copilot-api';

    public function __construct(private readonly EventDispatcherInterface $eventDispatcher)
    {
    }

    public function subscribeToEvents(): void
    {
        $this->eventDispatcher->addListener(RenderEvent::EVENT_SECTION_LIST_RENDER_TOP, $this->renderPanel(...));
    }

    public function renderPanel(RenderEvent $event): void
    {
        $pid = (int) $event->getPid();
        if ($pid <= 0) {
            return;
        }

        try {
            echo $this->panelHtml();
        } catch (\Throwable $e) {
            // ARCH-MEDIUM-007: a module failure must be visible, not silent.
            error_log('oe-module-copilot: panel render failed: ' . $e::class);
            echo '<div class="card mb-2" id="copilot-panel"><div class="card-body text-danger">'
                . xlt('Co-Pilot unavailable: the panel failed to render.') . '</div></div>';
        }
    }

    private function panelHtml(): string
    {
        $webRoot = OEGlobalsBag::getInstance()->getWebRoot();
        $assets = $webRoot . self::MODULE_PATH . '/public/assets';
        $version = self::VERSION;
        // Panel-load correlation id; conversation ids are minted server-side on start.
        $correlationId = bin2hex(random_bytes(8));

        return '<link rel="stylesheet" href="' . attr($assets . '/css/copilot.css?v=' . $version) . '">'
            . '<div id="copilot-panel" class="card mb-2" role="region" aria-label="' . attr(xl('Clinical Co-Pilot')) . '"'
            . ' data-api-base="' . attr($webRoot . self::API_BASE) . '"'
            . ' data-correlation-id="' . attr($correlationId) . '"'
            . ' data-version="' . attr($version) . '">'
            . '<div class="card-header py-2"><h6 class="mb-0">' . xlt('Clinical Co-Pilot') . '</h6></div>'
            . '<div class="card-body py-2">'
            . '<p id="copilot-status" class="mb-1 text-muted">' . xlt('Checking the co-pilot service...') . '</p>'
            . '<p class="small text-muted mb-0">'
            . xlt('Read-only. Every statement cites a chart record. Nothing is retrieved until you ask.')
            . '</p>'
            . '</div></div>'
            . '<script src="' . attr($assets . '/js/copilot.js?v=' . $version) . '" defer></script>';
    }
}
