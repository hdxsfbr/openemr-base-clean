<?php

/**
 * AgentForge Clinical Co-Pilot module bootstrap class.
 *
 * Adds a patient-menu launcher and renders its drawer through supported
 * patient-scoped events (ADR-0003). What the drawer does on load is decided
 * server-side by BriefPolicy: under `off` it stays inert until the user clicks
 * a question, and otherwise it prepares the pre-visit brief for the chart being
 * opened, so the answer is waiting instead of being typed for (ADR-0003
 * amendment 2026-09-19).
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
use OpenEMR\Menu\PatientMenuEvent;
use Symfony\Component\EventDispatcher\EventDispatcherInterface;

final class Bootstrap
{
    public const MODULE_DIRECTORY = 'oe-module-copilot';
    public const MODULE_PATH = '/interface/modules/custom_modules/' . self::MODULE_DIRECTORY;
    public const VERSION = '0.6.0';

    /** Path prefix, relative to the site root, where the agent API is published by the edge. */
    public const API_BASE = '/copilot-api';

    public function __construct(private readonly EventDispatcherInterface $eventDispatcher)
    {
    }

    public function subscribeToEvents(): void
    {
        $this->eventDispatcher->addListener(PatientMenuEvent::MENU_UPDATE, $this->addPatientMenuItem(...));
        $this->eventDispatcher->addListener(RenderEvent::EVENT_SECTION_LIST_RENDER_TOP, $this->renderPanel(...));
    }

    /**
     * Add the launcher after External Data without changing OpenEMR core menu files.
     */
    public function addPatientMenuItem(PatientMenuEvent $event): PatientMenuEvent
    {
        $menu = $event->getMenu();
        foreach ($menu as $item) {
            if (($item->menu_id ?? '') === 'copilot_menu') {
                return $event;
            }
        }

        $webRoot = OEGlobalsBag::getInstance()->getWebRoot();
        $menuItem = new \stdClass();
        $menuItem->label = 'Clinical Copilot';
        $menuItem->url = $webRoot . '/interface/patient_file/summary/demographics.php?copilot=open';
        $menuItem->menu_id = 'copilot_menu';
        $menuItem->target = 'main';
        $menuItem->on_click = 'if (window.AgentForgeCopilot) {'
            . ' return window.AgentForgeCopilot.open(event);'
            . ' } top.restoreSession(); return true;';
        $menuItem->pid = 'false';
        $menuItem->children = [];
        $menuItem->requirement = 0;
        $menuItem->class = 'copilot-menu-item';

        $insertAt = count($menu);
        foreach ($menu as $index => $item) {
            if (($item->menu_id ?? '') === 'external_data') {
                $insertAt = $index + 1;
                break;
            }
        }
        array_splice($menu, $insertAt, 0, [$menuItem]);
        $event->setMenu($menu);

        return $event;
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
            echo '<div class="copilot-drawer is-open" id="copilot-panel"><div class="card-body text-danger">'
                . xlt('Co-Pilot unavailable: the drawer failed to render.') . '</div></div>';
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
            . '<aside id="copilot-panel" class="copilot-drawer" role="complementary"'
            . ' aria-label="' . attr(xl('Clinical Co-Pilot')) . '" aria-hidden="true"'
            . ' data-api-base="' . attr($webRoot . self::API_BASE) . '"'
            . ' data-module-path="' . attr($webRoot . self::MODULE_PATH) . '"'
            . ' data-web-root="' . attr($webRoot) . '"'
            . ' data-correlation-id="' . attr($correlationId) . '"'
            . ' data-version="' . attr($version) . '">'
            . '<div class="copilot-drawer-header">'
            . '<div><h6 class="mb-0">' . xlt('Clinical Co-Pilot') . '</h6>'
            . '<span id="copilot-status" class="small text-muted">'
            . xlt('Checking the co-pilot service...') . '</span></div>'
            . '<button type="button" id="copilot-close" class="close copilot-close"'
            . ' aria-label="' . attr(xl('Close Clinical Co-Pilot')) . '">'
            . '<span aria-hidden="true">&times;</span></button>'
            . '</div>'
            . '<div class="copilot-drawer-body">'
            . '<details class="copilot-upload" id="copilot-upload">'
            . '<summary>' . xlt('Add a document to this chart') . '</summary>'
            . '<div class="copilot-upload-controls">'
            . '<label for="copilot-upload-type" class="small">' . xlt('Document type') . '</label>'
            . '<select id="copilot-upload-type" class="form-control form-control-sm">'
            . '<option value="lab_report">' . xlt('Laboratory report (PDF)') . '</option>'
            . '<option value="intake_form">' . xlt('Intake form (PDF, PNG, or JPEG)') . '</option>'
            . '</select>'
            . '<label for="copilot-upload-file" class="small">' . xlt('Source file') . '</label>'
            . '<input id="copilot-upload-file" class="form-control-file" type="file" accept="application/pdf">'
            . '<button id="copilot-upload-submit" type="button" class="btn btn-sm btn-outline-primary">'
            . xlt('Upload source') . '</button>'
            . '<div id="copilot-upload-status" class="small text-muted" role="status" aria-live="polite"></div>'
            . '</div></details>'
            . '<div id="copilot-transcript" class="copilot-transcript" role="log" aria-live="polite"'
            . ' aria-label="' . attr(xl('Co-Pilot conversation')) . '"></div>'
            . '<div id="copilot-composer" class="copilot-composer"></div>'
            . '</div></aside>'
            . '<script src="' . attr($assets . '/js/copilot.js?v=' . $version) . '" defer></script>';
    }
}
