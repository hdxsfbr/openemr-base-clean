/**
 * AgentForge Clinical Co-Pilot panel.
 *
 * Flow per question (ARCHITECTURE.md): session (CSRF) -> start conversation
 * (bound server-side to the open chart) -> per-turn ticket (re-checks the
 * session and open chart) -> agent turn -> render verified claims with
 * chart links, limitations, and withheld count. Everything is rendered
 * through textContent and DOM APIs; no HTML from any response is inserted.
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
    var apiBase = panel.getAttribute('data-api-base');
    var modulePath = panel.getAttribute('data-module-path');
    var webRoot = panel.getAttribute('data-web-root') || '';
    var status = document.getElementById('copilot-status');
    var body = document.getElementById('copilot-body');
    var state = { csrf: null, conversationId: null, correlationId: null, busy: false };

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) { node.className = className; }
        if (text !== undefined && text !== null) { node.textContent = String(text); }
        return node;
    }
    function setStatus(text, tone) {
        status.textContent = text;
        status.className = 'mb-1 ' + (tone || 'text-muted');
    }
    function fetchJson(url, options, timeoutMs) {
        var controller = new AbortController();
        var timer = setTimeout(function () { controller.abort(); }, timeoutMs || 15000);
        options = options || {};
        options.signal = controller.signal;
        options.credentials = 'same-origin';
        options.headers = Object.assign({ 'Accept': 'application/json' }, options.headers || {});
        return fetch(url, options).then(function (response) {
            return response.text().then(function (text) {
                var data = null;
                try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
                return { ok: response.ok, status: response.status, data: data };
            });
        }).finally(function () { clearTimeout(timer); });
    }
    function postJson(url, payload, headers) {
        return fetchJson(url, { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}), body: JSON.stringify(payload) });
    }

    // ---- chart links for cited sources (CAP-05) ----
    function chartUrl(source) {
        var id = parseInt(source.id, 10);
        if (!isFinite(id) || id <= 0) { return null; }
        switch (source.table) {
            case 'form_encounter':
                return webRoot + '/interface/patient_file/encounter/encounter_top.php?set_encounter=' + id;
            case 'form_clinical_notes':
                return source.encounter_id ? webRoot + '/interface/patient_file/encounter/encounter_top.php?set_encounter=' + parseInt(source.encounter_id, 10) : null;
            case 'lists':
                return webRoot + '/interface/patient_file/summary/add_edit_issue.php?issue=' + id;
            case 'prescriptions':
                return webRoot + '/controller.php?prescription&edit&id=' + id;
            case 'procedure_result':
                return source.order_id ? webRoot + '/interface/orders/single_order_results.php?orderid=' + parseInt(source.order_id, 10) : null;
            default:
                return null;
        }
    }

    // ---- rendering ----
    function renderTurn(turn) {
        body.textContent = '';
        var sources = {};
        (turn.sources || []).forEach(function (s) { sources[s.source_id] = s; });

        var header = el('div', 'small text-muted mb-2');
        var statusWord = { complete: 'Verified', partial: 'Partially verified', fallback: 'Records only (narrative unavailable)', denied: 'Denied', failed: 'Failed' }[turn.status] || turn.status;
        header.appendChild(el('span', 'badge badge-' + (turn.status === 'complete' ? 'success' : turn.status === 'denied' ? 'danger' : 'warning') + ' mr-2', statusWord));
        header.appendChild(document.createTextNode((turn.window_since ? 'Window since ' + turn.window_since + '. ' : 'No prior visit window. ')
            + (turn.evidence || []).map(function (e) { return e.tool.replace('_', ' ') + ': ' + (e.status === 'ok' || e.status === 'empty' ? e.record_count : e.status); }).join(' · ')
            + ' · ref ' + (turn.correlation_id || '')));
        body.appendChild(header);

        if (!turn.claims || turn.claims.length === 0) {
            body.appendChild(el('p', 'mb-2', 'No verified statements for this question.'));
        } else {
            var list = el('ul', 'list-unstyled mb-2');
            turn.claims.forEach(function (claim) {
                var item = el('li', 'mb-1');
                var typeTag = el('span', 'badge badge-light mr-1', claim.type === 'interpretation' ? 'reading' : claim.type.replace('_', ' '));
                item.appendChild(typeTag);
                item.appendChild(document.createTextNode(claim.text + ' '));
                (claim.source_ids || []).forEach(function (sid, i) {
                    var source = sources[sid];
                    var href = source ? chartUrl(source) : null;
                    var link = el(href ? 'a' : 'span', 'copilot-cite small', '[' + (i + 1) + ']');
                    link.title = source ? source.label : sid;
                    if (href) { link.href = href; link.target = '_blank'; link.rel = 'noopener'; }
                    item.appendChild(link);
                    item.appendChild(document.createTextNode(' '));
                });
                list.appendChild(item);
            });
            body.appendChild(list);
        }
        if (turn.limitations && turn.limitations.length) {
            var lim = el('ul', 'small text-muted mb-1');
            turn.limitations.forEach(function (l) { lim.appendChild(el('li', null, l.detail)); });
            body.appendChild(lim);
        }
        if (turn.withheld_count) {
            body.appendChild(el('p', 'small text-warning mb-0', turn.withheld_count + ' statement(s) withheld: not verifiable against the chart.'));
        }
    }
    function renderError(message, tone) {
        body.textContent = '';
        body.appendChild(el('p', 'mb-0 ' + (tone || 'text-danger'), message));
    }

    // ---- conversation flow ----
    function ensureSession() {
        if (state.csrf) { return Promise.resolve(); }
        return fetchJson(modulePath + '/public/api/session.php').then(function (r) {
            if (!r.ok || !r.data || !r.data.csrf_token) { throw new Error('session'); }
            if (!r.data.chart_open) { throw new Error('no_chart'); }
            state.csrf = r.data.csrf_token;
        });
    }
    function ensureConversation() {
        if (state.conversationId) { return Promise.resolve(); }
        return postJson(modulePath + '/public/api/conversation.php', { action: 'start', csrf_token: state.csrf }).then(function (r) {
            if (!r.ok || !r.data || !r.data.conversation_id) { throw new Error(r.data && r.data.code ? r.data.code : 'start'); }
            state.conversationId = r.data.conversation_id;
            state.correlationId = r.data.correlation_id;
        });
    }
    function ticket() {
        return postJson(modulePath + '/public/api/ticket.php', { csrf_token: state.csrf, conversation_id: state.conversationId }).then(function (r) {
            if (r.status === 409 && r.data && (r.data.code === 'patient_context_changed' || r.data.code === 'conversation_closed')) {
                state.conversationId = null;
                throw new Error(r.data.code);
            }
            if (!r.ok || !r.data || !r.data.token) { throw new Error(r.data && r.data.code ? r.data.code : 'ticket'); }
            return r.data;
        });
    }
    function ask(question) {
        if (state.busy) { return; }
        state.busy = true;
        setStatus('Retrieving chart records…', 'text-muted');
        body.textContent = '';
        ensureSession().then(ensureConversation).then(ticket).then(function (t) {
            setStatus('Verifying…', 'text-muted');
            return postJson(apiBase + '/v1/conversations/' + state.conversationId + '/turns',
                { message: question, correlation_id: t.correlation_id, stream: false },
                { 'X-Copilot-Token': t.token, 'X-Correlation-Id': t.correlation_id });
        }).then(function (r) {
            if (r.status === 403 && r.data && r.data.status === 'denied') { state.conversationId = null; }
            if (!r.data || (!r.ok && !r.data.turn_id)) {
                var code = r.data && r.data.code ? r.data.code : ('HTTP ' + r.status);
                throw new Error(code);
            }
            renderTurn(r.data);
            setStatus(r.data.status === 'complete' ? 'Answer verified against the chart.' : r.data.status === 'fallback' ? 'Showing verified records; the narrative service was unavailable.' : 'Answer partially verified; see limitations.', r.data.status === 'complete' ? 'text-success' : 'text-warning');
        }).catch(function (error) {
            var code = error && error.message ? error.message : 'error';
            var messages = {
                no_chart: 'Open a patient chart to use the co-pilot.',
                patient_context_changed: 'The open chart changed. Ask again to start a conversation for this chart.',
                conversation_closed: 'The conversation ended. Ask again to start a new one.',
                rate_limited: 'Too many questions in a minute; wait a moment.',
                unauthorized: 'The co-pilot is not available for this chart or account.',
                AbortError: 'The co-pilot did not answer in time. The chart is unaffected.'
            };
            renderError(messages[code] || ('Co-Pilot unavailable (' + code + '). The chart is unaffected.'), code === 'patient_context_changed' || code === 'conversation_closed' ? 'text-warning' : 'text-danger');
            setStatus('Co-Pilot unavailable.', 'text-danger');
        }).finally(function () { state.busy = false; });
    }

    // ---- controls ----
    var controls = document.getElementById('copilot-controls');
    var chip = el('button', 'btn btn-sm btn-primary mr-2 mb-1', 'What changed since the last visit?');
    chip.type = 'button';
    chip.addEventListener('click', function () { ask('What changed since the last visit?'); });
    var form = el('form', 'form-inline mb-1');
    var input = el('input', 'form-control form-control-sm mr-2');
    input.type = 'text';
    input.maxLength = 1000;
    input.placeholder = 'Follow-up about this chart…';
    input.style.minWidth = '18rem';
    var send = el('button', 'btn btn-sm btn-secondary', 'Ask');
    send.type = 'submit';
    form.appendChild(input);
    form.appendChild(send);
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var q = input.value.trim();
        if (q) { ask(q); input.value = ''; }
    });
    controls.appendChild(chip);
    controls.appendChild(form);

    // Agent reachability through the edge; the chart does not depend on it.
    fetchJson(apiBase + '/health', {}, 4000).then(function (r) {
        if (r.ok && r.data) { setStatus('Ready. Nothing is retrieved until you ask.', 'text-muted'); }
        else { setStatus('Co-Pilot unavailable: the agent service is not reachable. The chart is unaffected.', 'text-danger'); }
    }).catch(function () {
        setStatus('Co-Pilot unavailable: the agent service is not reachable. The chart is unaffected.', 'text-danger');
    });
})();
