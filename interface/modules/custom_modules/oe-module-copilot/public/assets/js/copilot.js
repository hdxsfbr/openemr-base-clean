/**
 * AgentForge Clinical Co-Pilot panel.
 *
 * A chat transcript over one chart-bound conversation. Flow per question
 * (ARCHITECTURE.md): session (CSRF) -> start conversation (bound server-side
 * to the open chart) -> per-turn ticket (re-checks the session and open
 * chart) -> agent turn streamed as server-sent events -> render the summary,
 * verified claims with chart links, and limitations. Progress events carry
 * node names only; no claim text leaves the agent before the verifier.
 * Everything is rendered through textContent and DOM APIs; no HTML from any
 * response is inserted.
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
    var transcript = document.getElementById('copilot-transcript');
    var composer = document.getElementById('copilot-composer');
    var state = { csrf: null, conversationId: null, correlationId: null, busy: false };

    // The conversation id survives a page reload within the tab; the ticket
    // endpoint re-checks the open chart before any history is shown.
    var STORAGE_KEY = 'copilot.conversation';
    // A turn may take up to the agent's 45 s wall clock; the panel waits a little longer than that.
    var TURN_TIMEOUT_MS = 60000;
    // Starter questions (UC-01, UC-02, UC-03). After each turn the agent returns
    // follow-ups drawn from that turn's records; starters fill in when it has fewer than two.
    var STARTER_QUESTIONS = [
        'What changed since the last visit?',
        'Which recent abnormal labs still have no later result or documented follow-up?',
        'What does the chart say about why each current medication is on the list?'
    ];
    var asked = [];

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) { node.className = className; }
        if (text !== undefined && text !== null) { node.textContent = String(text); }
        return node;
    }
    function setStatus(text, tone) {
        status.textContent = text;
        status.className = 'small ' + (tone || 'text-muted');
    }
    function remember(id) {
        try { if (id) { sessionStorage.setItem(STORAGE_KEY, id); } else { sessionStorage.removeItem(STORAGE_KEY); } } catch (e) { /* storage unavailable */ }
    }
    function recall() {
        try { return sessionStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
    }

    // ---- HTTP ----
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
    function postJson(url, payload, headers, timeoutMs) {
        return fetchJson(url, { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}), body: JSON.stringify(payload) }, timeoutMs);
    }
    /**
     * POST a turn and read it as server-sent events. Resolves with the final
     * turn object (the `claims` event); rejects with an Error whose message is
     * an error code. Falls back to a plain JSON read when the agent answers
     * without a stream (for example an error envelope).
     */
    function postStream(url, payload, headers, timeoutMs, onEvent) {
        var controller = new AbortController();
        var timer = setTimeout(function () { controller.abort(); }, timeoutMs);
        var options = {
            method: 'POST', signal: controller.signal, credentials: 'same-origin',
            headers: Object.assign({ 'Content-Type': 'application/json', 'Accept': 'text/event-stream' }, headers || {}),
            body: JSON.stringify(payload)
        };
        return fetch(url, options).then(function (response) {
            var type = response.headers.get('Content-Type') || '';
            if (type.indexOf('text/event-stream') < 0 || !response.body) {
                return response.text().then(function (text) {
                    var data = null;
                    try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
                    if (data && data.turn_id) { return data; }
                    var err = new Error(data && data.code ? data.code : ('HTTP ' + response.status));
                    err.data = data; err.status = response.status;
                    throw err;
                });
            }
            var reader = response.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            var finalTurn = null;
            var failure = null;
            function handleFrame(frame) {
                var event = 'message';
                var dataLines = [];
                frame.split('\n').forEach(function (line) {
                    if (line.indexOf('event:') === 0) { event = line.slice(6).trim(); }
                    else if (line.indexOf('data:') === 0) { dataLines.push(line.slice(5).trim()); }
                });
                var data = null;
                try { data = JSON.parse(dataLines.join('\n')); } catch (e) { data = null; }
                if (event === 'claims' && data) { finalTurn = data; }
                else if (event === 'error') { failure = new Error(data && data.code ? data.code : 'internal_error'); failure.data = data; }
                else if (onEvent) { onEvent(event, data); }
            }
            function pump() {
                return reader.read().then(function (chunk) {
                    if (chunk.done) {
                        if (buffer.trim()) { handleFrame(buffer); }
                        if (failure) { throw failure; }
                        if (!finalTurn) { throw new Error('stream_incomplete'); }
                        return finalTurn;
                    }
                    buffer += decoder.decode(chunk.value, { stream: true });
                    var index;
                    while ((index = buffer.indexOf('\n\n')) >= 0) {
                        handleFrame(buffer.slice(0, index));
                        buffer = buffer.slice(index + 2);
                    }
                    return pump();
                });
            }
            return pump();
        }).finally(function () { clearTimeout(timer); });
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

    // ---- transcript ----
    function scrollToEnd() {
        transcript.scrollTop = transcript.scrollHeight;
    }
    function clearPlaceholder() {
        var hint = transcript.querySelector('.copilot-hint');
        if (hint) { hint.remove(); }
    }
    function appendUser(question) {
        clearPlaceholder();
        var msg = el('div', 'copilot-msg copilot-msg-user', question);
        transcript.appendChild(msg);
        scrollToEnd();
        return msg;
    }
    function appendPending() {
        var msg = el('div', 'copilot-msg copilot-msg-assistant');
        var line = el('div', 'copilot-progress');
        var dots = el('span', 'copilot-dots');
        dots.setAttribute('aria-hidden', 'true');
        for (var i = 0; i < 3; i++) { dots.appendChild(el('span')); }
        line.appendChild(dots);
        line.appendChild(el('span', 'copilot-progress-text', 'Checking the chart…'));
        msg.appendChild(line);
        transcript.appendChild(msg);
        scrollToEnd();
        return msg;
    }
    function setProgress(msg, text) {
        var line = msg.querySelector('.copilot-progress-text');
        if (!line) { return; }
        // Restart the fade so each step visibly arrives.
        var fresh = el('span', 'copilot-progress-text', text);
        line.parentNode.replaceChild(fresh, line);
    }
    function appendNote(text, tone) {
        clearPlaceholder();
        var msg = el('div', 'copilot-msg copilot-msg-assistant ' + (tone || 'text-muted'), text);
        transcript.appendChild(msg);
        scrollToEnd();
        return msg;
    }

    var CLAIM_LABELS = { change_event: 'Change', medication_status: 'Medication', lab_result: 'Lab result', lab_comparison: 'Lab trend', documented_reference: 'Documented', absence: 'Absent', conflict: 'Conflict', undated: 'Undated', interpretation: 'Reading' };
    var STATUS_WORD = { complete: 'Verified', partial: 'Partially verified', fallback: 'Records only', denied: 'Denied', failed: 'Failed' };

    function claimDetail(claim) {
        var f = claim.facts || {};
        var bits = [];
        if (claim.type === 'lab_result') {
            if (f.value_text) { bits.push(f.value_text + (f.unit ? ' ' + f.unit : '')); }
            if (f.flag && f.flag !== 'unknown') { bits.push(f.flag); }
        } else if (claim.type === 'lab_comparison' && f.direction) {
            bits.push(f.analyte ? f.analyte + ' ' + f.direction : f.direction);
        } else if (claim.type === 'medication_status' && f.status) {
            bits.push(f.status);
        } else if (claim.type === 'absence' && f.state) {
            bits.push(f.state.replace(/_/g, ' '));
        } else if (claim.type === 'conflict' && f.kind) {
            bits.push(f.kind.replace(/_/g, ' '));
        }
        return bits.join(' · ');
    }
    function citationCell(claim, sources) {
        var cell = el('td', 'copilot-cites text-nowrap');
        (claim.source_ids || []).forEach(function (sid, i) {
            var source = sources[sid];
            var href = source ? chartUrl(source) : null;
            var link = el(href ? 'a' : 'span', 'copilot-cite', '[' + (i + 1) + ']');
            link.title = source ? source.label : sid;
            if (href) { link.href = href; link.target = '_blank'; link.rel = 'noopener'; }
            cell.appendChild(link);
            cell.appendChild(document.createTextNode(' '));
        });
        return cell;
    }
    function claimsTable(claims, sources) {
        var wrap = el('div', 'table-responsive');
        var table = el('table', 'table table-sm table-borderless copilot-claims mb-1');
        var head = el('thead');
        var hr = el('tr');
        ['Kind', 'Statement', 'Date', 'Chart'].forEach(function (h) { hr.appendChild(el('th', null, h)); });
        head.appendChild(hr);
        table.appendChild(head);
        var tbody = el('tbody');
        claims.forEach(function (claim) {
            var row = el('tr', 'copilot-claim-' + claim.type);
            row.appendChild(el('td', 'copilot-kind', CLAIM_LABELS[claim.type] || claim.type));
            var text = el('td', 'copilot-text');
            text.appendChild(document.createTextNode(claim.text));
            var detail = claimDetail(claim);
            if (detail) { text.appendChild(el('div', 'small text-muted', detail)); }
            row.appendChild(text);
            row.appendChild(el('td', 'copilot-date text-nowrap', (claim.facts && claim.facts.date) || ''));
            row.appendChild(citationCell(claim, sources));
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        return wrap;
    }
    function clockTime(iso) {
        if (!iso) { return null; }
        var d = new Date(iso);
        if (isNaN(d.getTime())) { return null; }
        var sameDay = d.toDateString() === new Date().toDateString();
        var time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        return sameDay ? time : d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + time;
    }
    function evidenceLine(turn) {
        var parts = [];
        var when = clockTime(turn.answered_at);
        if (when) { parts.push('Answered ' + when); }
        if (turn.window_since) { parts.push('Window since ' + turn.window_since); }
        (turn.evidence || []).forEach(function (e) {
            parts.push(e.tool.replace(/_/g, ' ') + ': ' + (e.status === 'ok' || e.status === 'empty' ? e.record_count : e.status));
        });
        if (turn.correlation_id) { parts.push('ref ' + turn.correlation_id); }
        return parts.join(' · ');
    }
    /** Build the assistant message for one turn (live or restored from history). */
    function renderTurn(turn, container) {
        container.textContent = '';
        var sources = {};
        (turn.sources || []).forEach(function (s) { sources[s.source_id] = s; });

        var header = el('div', 'copilot-turn-head');
        var tone = turn.status === 'complete' ? 'success' : turn.status === 'denied' || turn.status === 'failed' ? 'danger' : 'warning';
        header.appendChild(el('span', 'badge badge-' + tone + ' mr-2', STATUS_WORD[turn.status] || turn.status));
        if (turn.summary_basis === 'deterministic') {
            header.appendChild(el('span', 'small text-muted', 'Summary built from verified records only.'));
        }
        container.appendChild(header);

        if (turn.summary) {
            container.appendChild(el('p', 'copilot-summary', turn.summary));
        }
        var claims = turn.claims || [];
        if (claims.length === 0) {
            container.appendChild(el('p', 'mb-1 text-muted', 'No verified statements for this question.'));
        } else {
            container.appendChild(claimsTable(claims, sources));
        }
        if (turn.limitations && turn.limitations.length) {
            var lim = el('ul', 'copilot-limits small text-muted mb-1');
            turn.limitations.forEach(function (l) {
                var item = el('li', l.kind === 'withheld' ? 'text-warning' : null, l.detail);
                lim.appendChild(item);
            });
            container.appendChild(lim);
        }
        var meta = evidenceLine(turn);
        if (meta) { container.appendChild(el('div', 'copilot-meta small text-muted', meta)); }
        scrollToEnd();
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
            remember(state.conversationId);
        });
    }
    function dropConversation() {
        state.conversationId = null;
        remember(null);
    }
    function ticket() {
        return postJson(modulePath + '/public/api/ticket.php', { csrf_token: state.csrf, conversation_id: state.conversationId }).then(function (r) {
            if (r.status === 409 && r.data && (r.data.code === 'patient_context_changed' || r.data.code === 'conversation_closed')) {
                dropConversation();
                throw new Error(r.data.code);
            }
            if (!r.ok || !r.data || !r.data.token) {
                if (r.status === 404 || r.status === 403) { dropConversation(); }
                throw new Error(r.data && r.data.code ? r.data.code : 'ticket');
            }
            return r.data;
        });
    }
    var PROGRESS = {
        plan: 'Deciding which chart records to read…',
        narrate: 'Verifying every statement against the chart…',
        repair: 'Verifying the repaired answer…'
    };
    function progressFor(event, data) {
        if (event === 'evidence' && data) {
            var total = (data.evidence || []).reduce(function (n, e) { return n + (e.record_count || 0); }, 0);
            return 'Retrieved ' + total + ' chart record(s). Writing the answer…';
        }
        if (event === 'progress' && data) {
            if (data.node === 'verify') { return data.next === 'repair' ? 'Some statements did not verify; asking for a repair…' : 'Preparing the answer…'; }
            return PROGRESS[data.node] || null;
        }
        return null;
    }
    var ERROR_MESSAGES = {
        no_chart: 'Open a patient chart to use the co-pilot.',
        patient_context_changed: 'The open chart changed. Ask again to start a conversation for this chart.',
        conversation_closed: 'The conversation ended. Ask again to start a new one.',
        rate_limited: 'Too many questions in a minute; wait a moment.',
        unauthorized: 'The co-pilot is not available for this chart or account.',
        AbortError: 'The co-pilot did not answer in time. The chart is unaffected.',
        stream_incomplete: 'The co-pilot stopped answering before it finished. The chart is unaffected.'
    };
    function setBusy(busy) {
        state.busy = busy;
        input.disabled = busy;
        send.disabled = busy;
        Array.prototype.forEach.call(suggestions.querySelectorAll('button'), function (b) { b.disabled = busy; });
    }
    /** Offer follow-up questions as chips: the turn's own, topped up with starters not yet asked. */
    function renderSuggestions(list) {
        var items = (list || []).slice(0, 3);
        STARTER_QUESTIONS.forEach(function (q) {
            if (items.length < 3 && items.indexOf(q) < 0 && asked.indexOf(q) < 0) { items.push(q); }
        });
        suggestions.textContent = '';
        items.forEach(function (q) {
            var chip = el('button', 'btn btn-sm btn-outline-primary copilot-chip', q);
            chip.type = 'button';
            chip.addEventListener('click', function () { ask(q); });
            suggestions.appendChild(chip);
        });
    }
    function ask(question) {
        if (state.busy) { return; }
        setBusy(true);
        asked.push(question);
        appendUser(question);
        var pending = appendPending();
        setStatus('Working…', 'text-muted');
        ensureSession().then(ensureConversation).then(ticket).then(function (t) {
            setProgress(pending, 'Retrieving chart records…');
            return postStream(apiBase + '/v1/conversations/' + state.conversationId + '/turns',
                { message: question, correlation_id: t.correlation_id, stream: true },
                { 'X-Copilot-Token': t.token, 'X-Correlation-Id': t.correlation_id }, TURN_TIMEOUT_MS,
                function (event, data) {
                    var text = progressFor(event, data);
                    if (text) { setProgress(pending, text); }
                });
        }).then(function (turn) {
            if (turn.status === 'denied') { dropConversation(); }
            renderTurn(turn, pending);
            renderSuggestions(turn.suggestions);
            setStatus(turn.status === 'complete' ? 'Verified against the chart.' : turn.status === 'fallback' ? 'Records only; narrative unavailable.' : 'Partially verified; see limitations.', turn.status === 'complete' ? 'text-success' : 'text-warning');
        }).catch(function (error) {
            var code = error && error.name === 'AbortError' ? 'AbortError' : (error && error.message ? error.message : 'error');
            if (error && error.status === 403 && error.data && error.data.status === 'denied') { dropConversation(); }
            var soft = code === 'patient_context_changed' || code === 'conversation_closed' || code === 'rate_limited';
            pending.textContent = '';
            pending.className = 'copilot-msg copilot-msg-assistant ' + (soft ? 'text-warning' : 'text-danger');
            pending.textContent = ERROR_MESSAGES[code] || ('Co-Pilot unavailable (' + code + '). The chart is unaffected.');
            setStatus(soft ? 'Ask again.' : 'Co-Pilot unavailable.', soft ? 'text-warning' : 'text-danger');
        }).finally(function () { setBusy(false); scrollToEnd(); input.focus(); });
    }

    /** Re-render the transcript of a conversation remembered in this tab, if the open chart still matches. */
    function restoreHistory() {
        var remembered = recall();
        if (!remembered) { return Promise.resolve(false); }
        state.conversationId = remembered;
        return ensureSession().then(ticket).then(function (t) {
            return fetchJson(apiBase + '/v1/conversations/' + state.conversationId, { headers: { 'X-Copilot-Token': t.token, 'X-Correlation-Id': t.correlation_id } }, 8000);
        }).then(function (r) {
            if (!r.ok || !r.data || !Array.isArray(r.data.turns)) { dropConversation(); return false; }
            if (r.data.closed) { dropConversation(); return false; }
            if (r.data.turns.length) {
                clearPlaceholder();
                transcript.appendChild(el('div', 'copilot-divider small text-muted', 'Earlier in this session. Each answer reflects the chart at the time shown; ask again for the current state.'));
            }
            r.data.turns.forEach(function (past) {
                asked.push(past.question || '');
                appendUser(past.question || '');
                var msg = el('div', 'copilot-msg copilot-msg-assistant');
                transcript.appendChild(msg);
                renderTurn(past, msg);
            });
            if (r.data.turns.length) { renderSuggestions(r.data.turns[r.data.turns.length - 1].suggestions); }
            return r.data.turns.length > 0;
        }).catch(function () { dropConversation(); return false; });
    }

    // ---- composer (fixed below the transcript) ----
    var suggestions = el('div', 'copilot-suggestions');
    var form = el('form', 'copilot-form');
    var input = el('input', 'form-control form-control-sm');
    input.type = 'text';
    input.maxLength = 1000;
    input.placeholder = 'Ask about this chart…';
    input.setAttribute('aria-label', 'Ask the co-pilot about this chart');
    var send = el('button', 'btn btn-sm btn-primary', 'Ask');
    send.type = 'submit';
    form.appendChild(input);
    form.appendChild(send);
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var q = input.value.trim();
        if (q) { ask(q); input.value = ''; }
    });
    composer.appendChild(suggestions);
    composer.appendChild(form);
    renderSuggestions([]);
    transcript.appendChild(el('div', 'copilot-hint small text-muted', 'Nothing is retrieved until you ask. Pick a question or type your own.'));

    // Agent reachability through the edge; the chart does not depend on it.
    fetchJson(apiBase + '/health', {}, 4000).then(function (r) {
        if (r.ok && r.data) {
            setStatus('Ready', 'text-muted');
            return restoreHistory();
        }
        setStatus('Unavailable: agent service not reachable. The chart is unaffected.', 'text-danger');
        return false;
    }).catch(function () {
        setStatus('Unavailable: agent service not reachable. The chart is unaffected.', 'text-danger');
    });
})();
