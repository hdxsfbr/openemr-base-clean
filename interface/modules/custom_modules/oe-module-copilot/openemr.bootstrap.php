<?php

/**
 * AgentForge Clinical Co-Pilot module bootstrap.
 *
 * Included by OpenEMR on every request while the module is active
 * (ModulesApplication::bootstrapCustomModules). It only registers listeners;
 * nothing clinical happens until the physician opens a chart the co-pilot
 * prepares a brief for (BriefPolicy), or asks a question.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

use OpenEMR\Core\ModulesClassLoader;
use OpenEMR\Core\OEGlobalsBag;
use OpenEMR\Modules\Copilot\Bootstrap;

$classLoader = new ModulesClassLoader(OEGlobalsBag::getInstance()->getProjectDir());
$classLoader->registerNamespaceIfNotExists('OpenEMR\\Modules\\Copilot\\', __DIR__ . DIRECTORY_SEPARATOR . 'src');

$bootstrap = new Bootstrap(OEGlobalsBag::getInstance()->getKernel()->getEventDispatcher());
$bootstrap->subscribeToEvents();
