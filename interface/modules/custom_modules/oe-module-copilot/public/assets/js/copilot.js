/**
 * AgentForge Clinical Co-Pilot panel (skeleton).
 *
 * Reports whether the agent service is reachable through the edge. Renders
 * text only via textContent; never inserts HTML from any response.
 *
 * @package   OpenEMR
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */
(function () {
    'use strict';

    var panel = document.getElementById('copilot-panel');
    if (!panel) {
        return;
    }
    var status = document.getElementById('copilot-status');
    var apiBase = panel.getAttribute('data-api-base');
    var correlationId = panel.getAttribute('data-correlation-id');

    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 4000);

    fetch(apiBase + '/health', {
        method: 'GET',
        headers: { 'Accept': 'application/json', 'X-Correlation-Id': correlationId },
        credentials: 'same-origin',
        signal: controller.signal
    }).then(function (response) {
        if (!response.ok) {
            throw new Error('HTTP ' + response.status);
        }
        return response.json();
    }).then(function (body) {
        status.textContent = 'Co-pilot service reachable (agent ' + String(body.version || 'unknown')
            + '). Conversation features arrive with the next release.';
        status.className = 'mb-1 text-success';
    }).catch(function (error) {
        status.textContent = 'Co-Pilot unavailable: the agent service is not reachable ('
            + (error && error.name === 'AbortError' ? 'timeout' : String(error && error.message || error))
            + '). The chart is unaffected.';
        status.className = 'mb-1 text-danger';
    }).finally(function () {
        clearTimeout(timer);
    });
})();
