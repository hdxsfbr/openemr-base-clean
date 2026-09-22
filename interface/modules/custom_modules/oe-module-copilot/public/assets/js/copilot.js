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
 * The first turn can also start without a click: when session.php answers
 * `brief_on_open` (BriefPolicy decides, server-side), the panel asks the UC-01
 * brief question itself as the chart finishes loading, through the same
 * session, ticket, audit and verification path as a click. The physician reads
 * a finished brief instead of waiting about 9 s for one.
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
    var closeButton = document.getElementById('copilot-close');
    var uploadType = document.getElementById('copilot-upload-type');
    var uploadFile = document.getElementById('copilot-upload-file');
    var uploadSubmit = document.getElementById('copilot-upload-submit');
    var uploadStatus = document.getElementById('copilot-upload-status');
    var reviewPanel = document.getElementById('copilot-review');
    var reviewStatus = document.getElementById('copilot-review-status');
    var reviewWorkspace = document.getElementById('copilot-review-workspace');
    var menuItem = document.getElementById('copilot_menu');
    var menuTrigger = menuItem ? menuItem.querySelector('a') : null;
    var state = {
        csrf: null,
        conversationId: null,
        correlationId: null,
        renderedConversationId: undefined,
        syncPromise: null,
        busy: false,
        // Server-side decision from session.php; the panel never decides this itself.
        briefOnOpen: false,
        briefStarted: false,
        activeCitationId: null,
        sourceViewActive: false,
        reviewData: null,
        reviewBusy: false
    };
    var lastTrigger = null;

    // Source review is created in place so the existing OpenEMR panel hook
    // remains unchanged. Resizing changes presentation only; the answer DOM,
    // correction inputs, and active source stay mounted.
    var drawerBody = panel.querySelector('.copilot-drawer-body');
    var sourceTabs = el('div', 'copilot-view-tabs');
    var answerTab = el('button', 'btn btn-sm btn-outline-secondary is-active', 'Answer & review');
    var sourceTab = el('button', 'btn btn-sm btn-outline-secondary', 'Source');
    var sourceWorkspace = el('div', 'copilot-source-workspace');
    var answerPane = el('section', 'copilot-answer-pane');
    var sourcePane = el('section', 'copilot-source-pane');
    var sourceLive = el('div', 'sr-only');
    answerTab.type = 'button';
    sourceTab.type = 'button';
    answerTab.setAttribute('aria-controls', 'copilot-answer-pane');
    sourceTab.setAttribute('aria-controls', 'copilot-source-pane');
    answerPane.id = 'copilot-answer-pane';
    sourcePane.id = 'copilot-source-pane';
    sourcePane.setAttribute('aria-label', 'Citation source');
    sourcePane.setAttribute('aria-hidden', 'true');
    sourceLive.setAttribute('aria-live', 'polite');
    sourceLive.setAttribute('aria-atomic', 'true');
    sourceTabs.hidden = true;
    sourceTabs.appendChild(answerTab);
    sourceTabs.appendChild(sourceTab);
    if (drawerBody) {
        drawerBody.insertBefore(sourceTabs, drawerBody.firstChild);
        [document.getElementById('copilot-upload'), reviewPanel, transcript, composer].forEach(function (node) {
            if (node) { answerPane.appendChild(node); }
        });
        sourcePane.appendChild(sourceLive);
        sourceWorkspace.appendChild(answerPane);
        sourceWorkspace.appendChild(sourcePane);
        drawerBody.appendChild(sourceWorkspace);
    }

    // Versions before 0.4.1 kept one global conversation id in sessionStorage,
    // which could be reused after a patient switch. Remove it; recent history
    // is now resolved server-side from the authenticated open chart.
    try { sessionStorage.removeItem('copilot.conversation'); } catch (e) { /* storage unavailable */ }
    // A turn may take up to the agent's 45 s wall clock; the panel waits a little longer than that.
    var TURN_TIMEOUT_MS = 60000;
    // Starter questions (UC-01, UC-02, UC-03). After each turn the agent returns
    // follow-ups drawn from that turn's records; starters fill in when it has fewer than two.
    var STARTER_QUESTIONS = [
        'What changed since the last visit?',
        'Which recent abnormal labs still have no later result or documented follow-up?',
        'What does the chart say about why each current medication is on the list?'
    ];
    // The brief is the UC-01 starter, so it takes the same classification, the same
    // retrieval and the same gates as the click; nothing about it is a special path.
    var BRIEF_QUESTION = STARTER_QUESTIONS[0];
    // A reload while a brief is in flight would start a second one, because the
    // conversation has no turn to resume yet. This tab remembers for long enough
    // to cover the slowest turn (the agent's 45 s wall clock). The stored value is
    // a timestamp and nothing else: no conversation id, no patient, no chart data.
    var BRIEF_GUARD_KEY = 'copilot.brief.started';
    var BRIEF_GUARD_MS = 60000;
    var asked = [];

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) { node.className = className; }
        if (text !== undefined && text !== null) { node.textContent = String(text); }
        return node;
    }
    function setStatus(text, tone) {
        status.textContent = text;
        status.className = text ? 'small ' + (tone || 'text-muted') : 'd-none';
    }

    // ---- drawer ----
    function setExpanded(expanded) {
        if (menuTrigger) { menuTrigger.setAttribute('aria-expanded', expanded ? 'true' : 'false'); }
    }
    function openDrawer(event) {
        if (event && event.preventDefault) { event.preventDefault(); }
        lastTrigger = event && event.currentTarget ? event.currentTarget : menuTrigger;
        if (!panel.classList.contains('is-open')) {
            fetchJson(apiBase + '/health?panel=drawer_open', {}, 4000).catch(function () { /* a counter, never the user's problem */ });
        }
        panel.classList.add('is-open');
        panel.setAttribute('aria-hidden', 'false');
        setExpanded(true);
        if (!state.busy) {
            setBusy(true);
            setStatus('Loading this chart’s conversation…', 'text-muted');
            synchronizeChart().then(function () {
                setStatus('', 'text-muted');
            }).catch(function (error) {
                var code = error && error.message ? error.message : 'error';
                appendNote(ERROR_MESSAGES[code] || 'This chart’s conversation could not be loaded.', isSoftCode(code) ? 'text-warning' : 'text-danger');
                setStatus('', 'text-muted');
            }).finally(function () {
                setBusy(false);
                input.focus();
            });
        }
        return false;
    }
    function closeDrawer(event) {
        if (event && event.preventDefault) { event.preventDefault(); }
        panel.classList.remove('is-open');
        panel.setAttribute('aria-hidden', 'true');
        setExpanded(false);
        if (lastTrigger && typeof lastTrigger.focus === 'function') { lastTrigger.focus(); }
        return false;
    }
    function toggleDrawer(event) {
        return panel.classList.contains('is-open') ? closeDrawer(event) : openDrawer(event);
    }
    window.AgentForgeCopilot = { open: openDrawer, close: closeDrawer, toggle: toggleDrawer };

    if (menuTrigger) {
        menuTrigger.setAttribute('aria-controls', 'copilot-panel');
        menuTrigger.setAttribute('aria-expanded', 'false');
        if (!menuTrigger.querySelector('.copilot-new-badge')) {
            var newBadge = el('span', 'badge badge-info ml-1 copilot-new-badge', 'New');
            newBadge.setAttribute('aria-hidden', 'true');
            menuTrigger.appendChild(newBadge);
        }
    }
    if (closeButton) { closeButton.addEventListener('click', closeDrawer); }
    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape' || !panel.classList.contains('is-open')) { return; }
        if (state.sourceViewActive) { showAnswerView(); event.preventDefault(); return; }
        closeDrawer(event);
    });

    // ---- HTTP ----
    // Pin the shared session cookie back to THIS window's session id before any
    // same-origin call. OpenEMR lets one user hold several logins at once and
    // keeps them apart with top.restoreSession() (library/restoreSession.php);
    // most browsers share one cookie jar across windows, so without this a login,
    // logout, or patient switch in another window sends our request under that
    // window's session — the 400 (missing site_id) and patient_context_changed
    // the drawer was surfacing. Core and other modules pin before every server
    // call; this is the standard protocol the drawer was missing.
    function pinSession() {
        try {
            if (window.top && typeof window.top.restoreSession === 'function') {
                window.top.restoreSession();
            }
        } catch (e) { /* cross-frame or not yet defined; nothing to pin */ }
    }
    function fetchJson(url, options, timeoutMs) {
        pinSession();
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
    function postForm(url, form, timeoutMs) {
        return fetchJson(url, { method: 'POST', body: form }, timeoutMs);
    }

    // ---- reauthorized click-to-source review ----
    function setActiveCitation(citationId) {
        state.activeCitationId = citationId;
        Array.prototype.forEach.call(panel.querySelectorAll('.copilot-cite[data-citation-id]'), function (control) {
            control.setAttribute('aria-pressed', control.getAttribute('data-citation-id') === citationId ? 'true' : 'false');
        });
    }
    function narrowSourceLayout() {
        return typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 767.98px)').matches;
    }
    function synchronizeViewAccessibility() {
        if (!panel.classList.contains('has-source') || (narrowSourceLayout() && !state.sourceViewActive)) {
            sourcePane.setAttribute('aria-hidden', 'true');
        } else {
            sourcePane.removeAttribute('aria-hidden');
        }
        if (narrowSourceLayout() && state.sourceViewActive) {
            answerPane.setAttribute('aria-hidden', 'true');
        } else {
            answerPane.removeAttribute('aria-hidden');
        }
    }
    function showAnswerView() {
        state.sourceViewActive = false;
        panel.classList.remove('source-view-active');
        answerTab.classList.add('is-active');
        sourceTab.classList.remove('is-active');
        answerTab.setAttribute('aria-pressed', 'true');
        sourceTab.setAttribute('aria-pressed', 'false');
        synchronizeViewAccessibility();
        answerTab.focus();
    }
    function showSourceView() {
        state.sourceViewActive = true;
        panel.classList.add('has-source', 'source-view-active');
        sourceTabs.hidden = false;
        answerTab.classList.remove('is-active');
        sourceTab.classList.add('is-active');
        answerTab.setAttribute('aria-pressed', 'false');
        sourceTab.setAttribute('aria-pressed', 'true');
        synchronizeViewAccessibility();
    }
    answerTab.addEventListener('click', showAnswerView);
    sourceTab.addEventListener('click', function () {
        if (!state.activeCitationId) { return; }
        showSourceView();
        var heading = sourcePane.querySelector('.copilot-source-title');
        if (heading) { heading.focus(); }
    });
    window.addEventListener('resize', synchronizeViewAccessibility);

    function sourceRow(label, value) {
        var row = el('div', 'copilot-source-row');
        row.appendChild(el('dt', null, label));
        row.appendChild(el('dd', null, value));
        return row;
    }
    function displaySourceValue(value) {
        if (typeof value === 'string' || typeof value === 'number') { return String(value); }
        if (!value || typeof value !== 'object' || Array.isArray(value)) { return 'Structured reviewed value'; }
        if (typeof value.display === 'string') { return value.display; }
        if (typeof value.text === 'string') { return value.text; }
        if (value.value !== undefined && (typeof value.value === 'string' || typeof value.value === 'number')) {
            return String(value.value) + (typeof value.unit === 'string' ? ' ' + value.unit : '');
        }
        if (value.low !== undefined || value.high !== undefined) {
            return String(value.low !== undefined ? value.low : '—') + '–' + String(value.high !== undefined ? value.high : '—')
                + (typeof value.unit === 'string' ? ' ' + value.unit : '');
        }
        return 'Structured reviewed value';
    }
    function renderSourceLimitation(data) {
        sourcePane.textContent = '';
        sourcePane.appendChild(sourceLive);
        var card = el('div', 'copilot-source-limitation');
        var heading = el('h6', 'copilot-source-title', 'Source unavailable');
        heading.tabIndex = -1;
        card.appendChild(heading);
        card.appendChild(el('p', null, data && data.limitation
            ? data.limitation
            : 'This source cannot be opened right now. The verified answer remains available.'));
        if (data && data.retryable) {
            card.appendChild(el('p', 'small text-muted', 'Try the citation again after confirming the open chart.'));
        }
        sourcePane.appendChild(card);
        sourceLive.textContent = 'Source unavailable';
        heading.focus();
    }
    function renderSource(data) {
        if (!data || data.status !== 'available' || !data.source) { renderSourceLimitation(data); return; }
        sourcePane.textContent = '';
        sourcePane.appendChild(sourceLive);
        var source = data.source;
        var heading = el('h6', 'copilot-source-title', source.title || (source.source_type === 'guideline' ? 'Guideline evidence' : 'Source'));
        heading.tabIndex = -1;
        sourcePane.appendChild(heading);
        var badge = el('div', 'copilot-source-class', data.lane === 'guideline_evidence' ? 'Guideline evidence' : 'Patient record');
        sourcePane.appendChild(badge);

        if (source.source_type === 'reviewed_document' || source.source_type === 'document_proposal') {
            var metadata = el('dl', 'copilot-source-metadata');
            metadata.appendChild(sourceRow('Document type', source.document_type));
            metadata.appendChild(sourceRow(
                source.source_type === 'reviewed_document' ? 'Record version' : 'Extraction version',
                String(source.source_type === 'reviewed_document' ? source.record_version : source.extraction_version)
            ));
            metadata.appendChild(sourceRow('Location', 'Page ' + source.page_number + ' · ' + source.field_id));
            sourcePane.appendChild(metadata);

            var values = el('div', 'copilot-reviewed-values');
            if (source.review_decision === 'corrected') {
                values.appendChild(el('div', 'copilot-correction-marker', 'Physician corrected'));
            }
            var reviewed = el('div', 'copilot-reviewed-value');
            if (source.source_type === 'reviewed_document') {
                reviewed.appendChild(el('strong', null, source.reviewed.label + ': '));
                reviewed.appendChild(document.createTextNode(displaySourceValue(source.reviewed.value)));
            } else {
                reviewed.appendChild(el('strong', null, source.proposed.label + ': '));
                reviewed.appendChild(document.createTextNode(displaySourceValue(source.proposed.value)));
            }
            var printed = el('div', 'copilot-printed-value');
            printed.appendChild(el('strong', null, source.printed.label + ': '));
            printed.appendChild(document.createTextNode(displaySourceValue(source.printed.value)));
            values.appendChild(reviewed);
            values.appendChild(printed);
            sourcePane.appendChild(values);

            var page = el('figure', 'copilot-page');
            var pageCanvas = el('div', 'copilot-page-canvas');
            var image = el('img', 'copilot-page-image');
            image.alt = 'Authorized immutable source page ' + source.page_number;
            image.src = 'data:' + source.page.media_type + ';base64,' + source.page.data_base64;
            var focus = el('div', 'copilot-region-focus');
            focus.setAttribute('aria-label', source.focus_label);
            focus.style.left = (source.box.x * 100) + '%';
            focus.style.top = (source.box.y * 100) + '%';
            focus.style.width = (source.box.width * 100) + '%';
            focus.style.height = (source.box.height * 100) + '%';
            pageCanvas.appendChild(image);
            pageCanvas.appendChild(focus);
            page.appendChild(pageCanvas);
            page.appendChild(el('figcaption', 'small', 'Page ' + source.page_number + ' · ' + source.focus_label));
            sourcePane.appendChild(page);
        } else if (source.source_type === 'guideline') {
            var guidelineMeta = el('dl', 'copilot-source-metadata');
            guidelineMeta.appendChild(sourceRow('Publisher', source.publisher));
            guidelineMeta.appendChild(sourceRow('Section', source.section_path.join(' › ')));
            guidelineMeta.appendChild(sourceRow('Corpus version', source.corpus_version));
            sourcePane.appendChild(guidelineMeta);
            sourcePane.appendChild(el('blockquote', 'copilot-guideline-excerpt', source.exact_excerpt));
            sourcePane.appendChild(el('p', 'copilot-no-applicability', source.boundary));
            var publisherLink = el('a', 'btn btn-sm btn-outline-secondary', 'Open publisher page');
            publisherLink.href = source.canonical_url;
            publisherLink.target = '_blank';
            publisherLink.rel = 'noopener noreferrer';
            sourcePane.appendChild(publisherLink);
        } else if (source.source_type === 'openemr_record') {
            var recordMeta = el('dl', 'copilot-source-metadata');
            recordMeta.appendChild(sourceRow('Chart section', source.chart_section));
            recordMeta.appendChild(sourceRow('Record version', source.source_version));
            recordMeta.appendChild(sourceRow('Displayed value', source.displayed_value));
            sourcePane.appendChild(recordMeta);
            var chartLink = el('a', 'btn btn-sm btn-outline-primary', 'Open in this chart');
            chartLink.href = source.same_chart_href;
            chartLink.target = '_self';
            sourcePane.appendChild(chartLink);
        } else {
            renderSourceLimitation(null);
            return;
        }
        sourceLive.textContent = data.announcement || 'Citation source opened';
        heading.focus();
    }
    function openCitation(turnId, citationId, control) {
        setActiveCitation(citationId);
        showSourceView();
        sourcePane.textContent = '';
        sourcePane.appendChild(sourceLive);
        sourcePane.appendChild(el('div', 'copilot-source-loading', 'Reauthorizing and checking source integrity…'));
        sourceLive.textContent = 'Opening citation source';
        refreshSession().then(function () {
            if (!state.conversationId) { throw new Error('conversation_closed'); }
            return postJson(modulePath + '/public/api/sources.php', {
                csrf_token: state.csrf,
                conversation_id: state.conversationId,
                turn_id: turnId,
                citation_id: citationId
            }, { 'X-Correlation-Id': state.correlationId || panel.getAttribute('data-correlation-id') }, 15000);
        }).then(function (response) {
            if (!response.ok || !response.data || response.data.status !== 'available') {
                renderSourceLimitation(response.data);
                return;
            }
            renderSource(response.data);
        }).catch(function () {
            renderSourceLimitation(null);
        });
        if (control) { control.setAttribute('aria-pressed', 'true'); }
    }
    /**
     * POST a turn and read it as server-sent events. Resolves with the final
     * turn object (the `claims` event); rejects with an Error whose message is
     * an error code. Falls back to a plain JSON read when the agent answers
     * without a stream (for example an error envelope).
     */
    function postStream(url, payload, headers, timeoutMs, onEvent) {
        pinSession();
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
    function appendMessageTime(container, iso, alignment) {
        var formatted = clockTime(iso);
        if (!formatted) { return; }
        var timestamp = el('time', 'copilot-message-time copilot-message-time-' + alignment, formatted);
        timestamp.dateTime = iso;
        container.appendChild(timestamp);
    }
    function appendUser(question, sentAt) {
        clearPlaceholder();
        var msg = el('div', 'copilot-msg copilot-msg-user');
        msg.appendChild(el('div', 'copilot-message-text', question));
        appendMessageTime(msg, sentAt, 'user');
        transcript.appendChild(msg);
        scrollToEnd();
        return msg;
    }
    /**
     * The brief was not typed by anyone, so it is not shown as the physician's
     * question. The line says where it came from and, once answered, renderTurn
     * timestamps it -- a brief prepared minutes ago must not read as just-now.
     */
    function appendBriefHeader() {
        clearPlaceholder();
        var msg = el('div', 'copilot-brief-header small text-muted');
        msg.appendChild(el('span', null, 'Pre-visit brief · what changed since the last visit'));
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
    function appendNote(text, tone, createdAt) {
        clearPlaceholder();
        var msg = el('div', 'copilot-msg copilot-msg-assistant ' + (tone || 'text-muted'));
        msg.appendChild(el('div', 'copilot-message-text', text));
        appendMessageTime(msg, createdAt || new Date().toISOString(), 'assistant');
        transcript.appendChild(msg);
        scrollToEnd();
        return msg;
    }

    var CLAIM_LABELS = { change_event: 'Change', medication_status: 'Medication', problem_status: 'Problem', lab_result: 'Lab result', lab_comparison: 'Lab trend', documented_reference: 'Documented', absence: 'Absent', conflict: 'Conflict', undated: 'Undated', interpretation: 'Reading' };
    var STATUS_WORD = { complete: 'Verified', partial: 'Partially verified', fallback: 'Records only', denied: 'Denied', failed: 'Failed' };

    function claimDetail(claim) {
        var f = claim.facts || {};
        var bits = [];
        if (claim.type === 'lab_result') {
            if (f.value_text) { bits.push(f.value_text + (f.unit ? ' ' + f.unit : '')); }
            if (f.flag && f.flag !== 'unknown') { bits.push(f.flag); }
        } else if (claim.type === 'lab_comparison' && f.direction) {
            bits.push(f.analyte ? f.analyte + ' ' + f.direction : f.direction);
        } else if ((claim.type === 'medication_status' || claim.type === 'problem_status') && f.status) {
            bits.push(f.status);
        } else if (claim.type === 'absence' && f.state) {
            bits.push(f.state.replace(/_/g, ' '));
        } else if (claim.type === 'conflict' && f.kind) {
            bits.push(f.kind.replace(/_/g, ' '));
        }
        return bits.join(' · ');
    }
    function citationLinks(claim, sources, turn) {
        var citations = el('div', 'copilot-cites');
        if (Array.isArray(claim.citations) && claim.citations.length) {
            claim.citations.forEach(function (citation, i) {
                if (!citation || typeof citation.citation_id !== 'string' || !turn || typeof turn.turn_id !== 'string') { return; }
                var control = el('button', 'copilot-cite', '[' + (i + 1) + ']');
                control.type = 'button';
                control.setAttribute('aria-label', 'Open source ' + (i + 1) + ' for ' + (claim.text || 'verified claim'));
                control.setAttribute('aria-pressed', state.activeCitationId === citation.citation_id ? 'true' : 'false');
                control.setAttribute('data-citation-id', citation.citation_id);
                control.addEventListener('click', function () {
                    openCitation(turn.turn_id, citation.citation_id, control);
                });
                citations.appendChild(control);
                citations.appendChild(document.createTextNode(' '));
            });
            return citations;
        }
        (claim.source_ids || []).forEach(function (sid, i) {
            var source = sources[sid];
            var href = source ? chartUrl(source) : null;
            var link = el(href ? 'a' : 'span', 'copilot-cite', '[' + (i + 1) + ']');
            link.title = source ? source.label : sid;
            if (href) { link.href = href; link.target = '_blank'; link.rel = 'noopener'; }
            citations.appendChild(link);
            citations.appendChild(document.createTextNode(' '));
        });
        return citations;
    }
    function claimsList(claims, sources, turn) {
        var list = el('div', 'copilot-sources-list');
        claims.forEach(function (claim) {
            var item = el('div', 'copilot-source copilot-claim-' + claim.type);
            var heading = el('div', 'copilot-source-head');
            heading.appendChild(el('span', 'copilot-kind', CLAIM_LABELS[claim.type] || claim.type));
            var date = (claim.facts && claim.facts.date) || '';
            if (date) { heading.appendChild(el('span', 'copilot-date', date)); }
            item.appendChild(heading);
            item.appendChild(el('div', 'copilot-text', claim.text));
            var detail = claimDetail(claim);
            if (detail) { item.appendChild(el('div', 'small text-muted', detail)); }
            item.appendChild(citationLinks(claim, sources, turn));
            list.appendChild(item);
        });
        return list;
    }
    function limitationList(limitations) {
        var list = el('ul', 'copilot-limits small text-muted mb-0');
        limitations.forEach(function (limitation) {
            list.appendChild(el('li', limitation.kind === 'withheld' ? 'text-warning' : null, limitation.detail));
        });
        return list;
    }
    function disclosure(label, count, hint) {
        var details = el('details', 'copilot-disclosure');
        var summary = el('summary', 'copilot-disclosure-summary');
        summary.appendChild(el('span', 'copilot-disclosure-label', label + (count ? ' (' + count + ')' : '')));
        if (hint) { summary.appendChild(el('span', 'copilot-disclosure-hint', hint)); }
        details.appendChild(summary);
        return details;
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

        var claims = turn.claims || [];
        var patientClaims = claims.filter(function (claim) { return claim.claim_class !== 'guideline_evidence'; });
        var guidelineClaims = claims.filter(function (claim) { return claim.claim_class === 'guideline_evidence'; });
        if (turn.summary && !(patientClaims.length && guidelineClaims.length)) {
            container.appendChild(el('p', 'copilot-summary', turn.summary));
        }
        var limitations = turn.limitations || [];
        var guidelineLimitations = limitations.filter(function (limitation) { return limitation.section === 'guideline_evidence'; });
        var patientLimitations = limitations.filter(function (limitation) { return limitation.section !== 'guideline_evidence'; });
        if (claims.length === 0) {
            container.appendChild(el('p', 'mb-1 text-muted', 'No verified statements for this question.'));
        }

        var sourceCount = Object.keys(sources).length || claims.length;
        var detailCounts = [];
        if (sourceCount) { detailCounts.push(sourceCount + (sourceCount === 1 ? ' source' : ' sources')); }
        if (limitations.length) { detailCounts.push(limitations.length + (limitations.length === 1 ? ' limitation' : ' limitations')); }
        var answerDetails = disclosure('Sources & details', 0, detailCounts.join(' · ') || 'Turn details');
        var detailBody = el('div', 'copilot-disclosure-body');
        if (patientClaims.length || patientLimitations.length) {
            var patientLane = el('section', 'copilot-evidence-lane copilot-patient-lane');
            patientLane.appendChild(el('h6', 'copilot-lane-heading', 'Patient record'));
            if (patientClaims.length) { patientLane.appendChild(claimsList(patientClaims, sources, turn)); }
            if (patientLimitations.length) { patientLane.appendChild(limitationList(patientLimitations)); }
            detailBody.appendChild(patientLane);
        }
        if (guidelineClaims.length || guidelineLimitations.length) {
            var guidelineLane = el('section', 'copilot-evidence-lane copilot-guideline-lane');
            guidelineLane.appendChild(el('h6', 'copilot-lane-heading', 'Guideline evidence'));
            if (guidelineClaims.length) {
                guidelineLane.appendChild(claimsList(guidelineClaims, sources, turn));
                guidelineLane.appendChild(el('p', 'copilot-no-applicability', 'Guideline evidence for physician review; patient applicability was not determined.'));
            }
            if (guidelineLimitations.length) { guidelineLane.appendChild(limitationList(guidelineLimitations)); }
            detailBody.appendChild(guidelineLane);
        }
        var meta = evidenceLine(turn);
        if (meta) { detailBody.appendChild(el('div', 'copilot-meta small text-muted', meta)); }
        answerDetails.appendChild(detailBody);
        container.appendChild(answerDetails);
        appendMessageTime(container, turn.answered_at, 'assistant');
        scrollToEnd();
    }

    // ---- conversation flow ----
    function refreshSession(retrying) {
        return fetchJson(modulePath + '/public/api/session.php').then(function (r) {
            if (!r.ok || !r.data || !r.data.csrf_token) {
                // A sign-in change in another window may have briefly pointed the
                // shared cookie elsewhere. Re-pin this window's session and retry
                // once before surfacing anything to the user.
                if (!retrying) { pinSession(); return refreshSession(true); }
                throw new Error('session');
            }
            if (!r.data.chart_open) { throw new Error('no_chart'); }
            state.csrf = r.data.csrf_token;
            state.briefOnOpen = r.data.brief_on_open === true;
        });
    }

    // ---- physician document review (read-back before every explicit write) ----
    function setReviewStatus(message, tone) {
        if (!reviewStatus) { return; }
        reviewStatus.textContent = message || '';
        reviewStatus.className = 'small ' + (tone || 'text-muted');
    }
    function setReviewBusy(busy) {
        state.reviewBusy = busy;
        if (!reviewWorkspace) { return; }
        Array.prototype.forEach.call(reviewWorkspace.querySelectorAll('button, input, textarea'), function (control) {
            control.disabled = busy || control.getAttribute('data-server-disabled') === 'true';
        });
    }
    function reviewValue(value) {
        if (value === null || value === undefined) { return 'No value extracted'; }
        if (typeof value === 'string' || typeof value === 'number') { return String(value); }
        if (typeof value !== 'object' || Array.isArray(value)) { return 'Structured value'; }
        if (value.kind === 'quantity' || value.kind === 'text') { return String(value.value); }
        if (value.display) { return String(value.display); }
        if (value.text) { return String(value.text); }
        if (value.low !== undefined || value.high !== undefined) {
            return String(value.low !== undefined ? value.low : '—') + '–' + String(value.high !== undefined ? value.high : '—')
                + (value.unit ? ' ' + value.unit : '');
        }
        return JSON.stringify(value);
    }
    function correctionInputValue(fieldId, proposed) {
        if (/\.(code|reference_range)$/.test(fieldId) && proposed && typeof proposed === 'object') {
            return JSON.stringify(proposed);
        }
        return reviewValue(proposed);
    }
    function correctionFor(fieldId, proposed, raw) {
        var trimmed = raw.trim();
        if (!trimmed) { throw new Error('Enter the corrected value.'); }
        if (fieldId === 'collection_date' || /\.date_of_birth$/.test(fieldId)) {
            return { kind: 'date', value: trimmed };
        }
        if (/\.onset_age_years$/.test(fieldId)) {
            if (!/^\d+$/.test(trimmed)) { throw new Error('Enter a whole number of years.'); }
            return { kind: 'integer', value: Number(trimmed) };
        }
        if (/\.(administrative_sex|status|severity|abnormal_flag)$/.test(fieldId)) {
            return { kind: 'choice', value: trimmed };
        }
        if (/\.code$/.test(fieldId)) {
            return { kind: 'coded', value: JSON.parse(trimmed) };
        }
        if (/\.reference_range$/.test(fieldId)) {
            return { kind: 'reference_range', value: JSON.parse(trimmed) };
        }
        if (/\.value$/.test(fieldId) && proposed && typeof proposed === 'object'
            && (proposed.kind === 'quantity' || proposed.kind === 'text')) {
            return { kind: 'measurement', value: { kind: proposed.kind, value: trimmed } };
        }
        return { kind: 'string', value: trimmed };
    }
    function reviewError(error, fallback) {
        return error && error.data && error.data.limitation
            ? error.data.limitation
            : (error && error.message && error.message.indexOf('HTTP ') !== 0 ? error.message : fallback);
    }
    function reviewRequest(path, payload) {
        return refreshSession().then(function () {
            return postJson(modulePath + '/public/api/reviewed_documents.php' + path,
                Object.assign({ csrf_token: state.csrf }, payload || {}),
                { 'X-Correlation-Id': state.correlationId || panel.getAttribute('data-correlation-id') }, 20000);
        }).then(function (response) {
            if (!response.ok || !response.data) {
                var error = new Error(response.data && response.data.code ? response.data.code : ('HTTP ' + response.status));
                error.data = response.data;
                throw error;
            }
            return response.data;
        });
    }
    function submitReview(fact, action, correctedInput, reasonInput) {
        if (state.reviewBusy || !state.reviewData || !state.reviewData.extraction) { return; }
        var extraction = state.reviewData.extraction;
        var command = {
            idempotency_key: uploadUuid(),
            extraction_id: extraction.extraction_id,
            expected_extraction_version: extraction.extraction_version,
            field_id: fact.field_id,
            action: action
        };
        try {
            if (action === 'correct') {
                command.corrected_value = correctionFor(fact.field_id, fact.proposed_value, correctedInput.value);
                command.reason = reasonInput.value.trim();
                if (!command.reason) { throw new Error('Explain why the value was corrected.'); }
            } else if (action === 'reject') {
                command.reason = reasonInput.value.trim();
                if (!command.reason) { throw new Error('Explain why the proposed fact was rejected.'); }
            }
        } catch (error) {
            setReviewStatus(error.message || 'The review fields are invalid.', 'text-danger');
            return;
        }
        setReviewBusy(true);
        setReviewStatus('Saving the explicit physician decision…', 'text-muted');
        reviewRequest('/document-reviews', command).then(function () {
            return loadReviewWorkspace(false);
        }).catch(function (error) {
            setReviewStatus(reviewError(error, 'The review decision was not saved. The chart is unchanged.'), 'text-danger');
        }).finally(function () { setReviewBusy(false); });
    }
    function openReviewSource(fact, evidence, control) {
        if (!state.reviewData || !state.reviewData.extraction || state.reviewBusy) { return; }
        var extraction = state.reviewData.extraction;
        state.activeCitationId = 'review:' + evidence.evidence_id;
        showSourceView();
        sourcePane.textContent = '';
        sourcePane.appendChild(sourceLive);
        sourcePane.appendChild(el('div', 'copilot-source-loading', 'Reauthorizing and checking source integrity…'));
        sourceLive.textContent = 'Opening proposed fact source';
        reviewRequest('/review-source', {
            extraction_id: extraction.extraction_id,
            expected_extraction_version: extraction.extraction_version,
            source_document_id: extraction.source_document_id,
            source_content_sha256: extraction.source_content_sha256,
            field_id: fact.field_id,
            evidence_id: evidence.evidence_id,
            page_number: evidence.page_number,
            rendered_page_sha256: evidence.rendered_page_sha256
        }).then(renderSource).catch(function (error) {
            renderSourceLimitation(error.data || null);
        });
        if (control) { control.setAttribute('aria-pressed', 'true'); }
    }
    function reviewedRecordValues(record) {
        var values = [];
        if (!record || typeof record !== 'object') { return values; }
        if (record.collection_date && record.collection_date.source_field_id) {
            values.push([record.collection_date.source_field_id, record.collection_date.value]);
        }
        (record.analytes || []).forEach(function (analyte) {
            Object.keys(analyte).forEach(function (key) {
                var field = analyte[key];
                if (field && field.source_field_id) { values.push([field.source_field_id, field.value]); }
            });
        });
        (record.items || []).forEach(function (item) {
            if (item && item.source_field_id && item.answer) { values.push([item.source_field_id, item.answer.value]); }
        });
        return values;
    }
    function renderReviewedRecord(current) {
        var card = el('section', 'copilot-reviewed-record');
        card.appendChild(el('h6', null, 'Current reviewed record'));
        card.appendChild(el('p', 'small mb-1', 'Version ' + current.record_version + ' · ' + current.status.replace(/_/g, ' ')));
        var list = el('dl', 'copilot-review-readback');
        reviewedRecordValues(current.record).forEach(function (entry) {
            var row = el('div', 'copilot-review-readback-row');
            row.appendChild(el('dt', null, entry[0]));
            row.appendChild(el('dd', null, reviewValue(entry[1])));
            list.appendChild(row);
        });
        card.appendChild(list);
        return card;
    }
    function renderReviewFact(fact) {
        var card = el('section', 'copilot-review-fact');
        var heading = el('div', 'copilot-review-fact-head');
        heading.appendChild(el('h6', null, fact.field_id.replace(/[._-]/g, ' ')));
        var decision = fact.current_decision && fact.current_decision.decision ? fact.current_decision.decision : 'pending';
        heading.appendChild(el('span', 'badge copilot-review-state copilot-review-state-' + decision, decision.replace(/_/g, ' ')));
        card.appendChild(heading);
        card.appendChild(el('div', 'copilot-review-proposed', reviewValue(fact.proposed_value)));
        card.appendChild(el('div', 'small text-muted', 'Extraction: ' + String(fact.extraction_state || 'unavailable').replace(/_/g, ' ')));
        if (decision === 'corrected' && fact.current_decision.final_value !== undefined) {
            card.appendChild(el('div', 'copilot-review-current', 'Reviewed value: ' + reviewValue(fact.current_decision.final_value)));
        }

        var evidenceItems = Array.isArray(fact.evidence) ? fact.evidence : [];
        if (evidenceItems.length) {
            var sourceActions = el('div', 'copilot-review-source-actions');
            evidenceItems.forEach(function (evidence, index) {
                var sourceButton = el('button', 'btn btn-sm btn-outline-secondary copilot-review-source',
                    'View source ' + (index + 1) + ' · page ' + evidence.page_number);
                sourceButton.type = 'button';
                sourceButton.setAttribute('data-review-action', 'source');
                sourceButton.setAttribute('aria-pressed', 'false');
                sourceButton.addEventListener('click', function () { openReviewSource(fact, evidence, sourceButton); });
                sourceActions.appendChild(sourceButton);
            });
            card.appendChild(sourceActions);
        } else {
            card.appendChild(el('div', 'small text-warning', 'No source region is available for this proposed fact.'));
        }

        var correction = el('input', 'form-control form-control-sm');
        correction.type = 'text';
        correction.value = correctionInputValue(fact.field_id, fact.proposed_value);
        correction.maxLength = 2000;
        correction.setAttribute('aria-label', 'Corrected value for ' + fact.field_id);
        var reason = el('textarea', 'form-control form-control-sm');
        reason.rows = 2;
        reason.maxLength = 500;
        reason.placeholder = 'Reason required for correction or rejection';
        reason.setAttribute('aria-label', 'Reason for changing ' + fact.field_id);
        var fields = el('div', 'copilot-review-fields');
        fields.appendChild(correction);
        fields.appendChild(reason);
        card.appendChild(fields);

        var actions = el('div', 'copilot-review-actions');
        var approve = el('button', 'btn btn-sm btn-outline-success', 'Approve');
        var correct = el('button', 'btn btn-sm btn-outline-primary', 'Save correction');
        var reject = el('button', 'btn btn-sm btn-outline-danger', 'Reject');
        approve.type = correct.type = reject.type = 'button';
        approve.setAttribute('data-review-action', 'approve');
        correct.setAttribute('data-review-action', 'correct');
        reject.setAttribute('data-review-action', 'reject');
        var cannotAccept = fact.proposed_value === null || evidenceItems.length === 0
            || ['rejected', 'unavailable'].indexOf(fact.extraction_state) >= 0;
        if (cannotAccept) {
            approve.disabled = true;
            correct.disabled = true;
            approve.setAttribute('data-server-disabled', 'true');
            correct.setAttribute('data-server-disabled', 'true');
        }
        approve.addEventListener('click', function () { submitReview(fact, 'approve', correction, reason); });
        correct.addEventListener('click', function () { submitReview(fact, 'correct', correction, reason); });
        reject.addEventListener('click', function () { submitReview(fact, 'reject', correction, reason); });
        actions.appendChild(approve);
        actions.appendChild(correct);
        actions.appendChild(reject);
        card.appendChild(actions);
        return card;
    }
    function promoteReviewedDocument() {
        if (state.reviewBusy || !state.reviewData || !state.reviewData.extraction
            || !state.reviewData.promotion || state.reviewData.promotion.state !== 'ready') { return; }
        var extraction = state.reviewData.extraction;
        setReviewBusy(true);
        setReviewStatus('Creating one immutable reviewed record…', 'text-muted');
        reviewRequest('/document-promotions', {
            idempotency_key: uploadUuid(),
            extraction_id: extraction.extraction_id,
            expected_extraction_version: extraction.extraction_version,
            source_content_sha256: extraction.source_content_sha256,
            target_type: extraction.target_type,
            review_ids: state.reviewData.promotion.review_ids.slice()
        }).then(function () {
            return loadReviewWorkspace(false);
        }).catch(function (error) {
            setReviewStatus(reviewError(error, 'The reviewed record was not created. No chart record changed.'), 'text-danger');
        }).finally(function () { setReviewBusy(false); });
    }
    function renderReviewWorkspace(data) {
        if (!reviewWorkspace || !reviewPanel) { return; }
        state.reviewData = data;
        reviewWorkspace.textContent = '';
        if (!data || data.status === 'empty' || !data.extraction) {
            setReviewStatus('No extracted document is waiting for physician review.', 'text-muted');
            return;
        }
        reviewPanel.open = true;
        var summary = el('div', 'copilot-review-summary');
        summary.appendChild(el('strong', null, data.extraction.document_type === 'lab_report' ? 'Laboratory report' : 'Intake form'));
        summary.appendChild(el('span', 'small text-muted', ' Extraction v' + data.extraction.extraction_version
            + ' · ' + String(data.extraction.extraction_state).replace(/_/g, ' ')));
        reviewWorkspace.appendChild(summary);
        (data.facts || []).forEach(function (fact) { reviewWorkspace.appendChild(renderReviewFact(fact)); });

        if (data.promotion && data.promotion.current_record) {
            reviewWorkspace.appendChild(renderReviewedRecord(data.promotion.current_record));
        }
        var promotion = el('div', 'copilot-review-promotion');
        var promote = el('button', 'btn btn-sm btn-primary', 'Promote reviewed document');
        promote.type = 'button';
        promote.setAttribute('data-review-action', 'promote');
        var ready = data.promotion && data.promotion.state === 'ready';
        promote.disabled = !ready;
        if (!ready) { promote.setAttribute('data-server-disabled', 'true'); }
        promote.addEventListener('click', promoteReviewedDocument);
        promotion.appendChild(promote);
        if (data.promotion && data.promotion.state === 'promoted') {
            promotion.appendChild(el('div', 'small text-success', 'The current reviewed record is read back above. No further write occurs automatically.'));
        } else if (!ready) {
            var count = data.promotion ? data.promotion.blocker_count : 0;
            promotion.appendChild(el('div', 'small text-warning', count + ' proposed value(s) still block promotion.'));
        } else {
            promotion.appendChild(el('div', 'small text-muted', 'Promotion occurs only when you activate this button.'));
        }
        reviewWorkspace.appendChild(promotion);
        setReviewStatus(data.status === 'promoted' ? 'Reviewed record read back from OpenEMR.'
            : (ready ? 'All promotable values have current physician decisions.' : 'Physician review is required.'),
        data.status === 'promoted' || ready ? 'text-success' : 'text-warning');
    }
    function loadReviewWorkspace(refresh) {
        if (!reviewPanel || !reviewWorkspace) { return Promise.resolve(null); }
        setReviewStatus('Reading the latest extraction and current decisions…', 'text-muted');
        var ready = refresh === false ? Promise.resolve() : refreshSession();
        return ready.then(function () {
            return postJson(modulePath + '/public/api/reviewed_documents.php/review-workspace', {
                csrf_token: state.csrf
            }, { 'X-Correlation-Id': state.correlationId || panel.getAttribute('data-correlation-id') }, 15000);
        }).then(function (response) {
            if (!response.ok || !response.data) {
                var error = new Error(response.data && response.data.code ? response.data.code : 'unavailable');
                error.data = response.data;
                throw error;
            }
            renderReviewWorkspace(response.data);
            return response.data;
        }).catch(function (error) {
            state.reviewData = null;
            reviewWorkspace.textContent = '';
            setReviewStatus(reviewError(error, 'Document review is unavailable. No review or chart write occurred.'), 'text-danger');
            return null;
        });
    }

    // ---- patient-bound source upload ----
    function uploadUuid() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') { return window.crypto.randomUUID(); }
        var bytes = new Uint8Array(16);
        window.crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        var hex = Array.prototype.map.call(bytes, function (b) { return b.toString(16).padStart(2, '0'); }).join('');
        return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) + '-' + hex.slice(16, 20) + '-' + hex.slice(20);
    }
    function declaredPageCount(file) {
        if (file.type !== 'application/pdf') { return Promise.resolve(1); }
        return file.arrayBuffer().then(function (buffer) {
            var text = new TextDecoder('latin1').decode(buffer);
            var pages = text.match(/\/Type\s*\/Page\b/g);
            return pages ? pages.length : 0;
        });
    }
    function setUploadState(busy, message, tone) {
        uploadSubmit.disabled = busy;
        uploadType.disabled = busy;
        uploadFile.disabled = busy;
        uploadStatus.textContent = message || '';
        uploadStatus.className = 'small ' + (tone || 'text-muted');
    }
    function uploadSelectedSource() {
        var file = uploadFile.files && uploadFile.files[0];
        if (!file) { setUploadState(false, 'Choose a source file first.', 'text-warning'); return; }
        setUploadState(true, 'Checking the source…', 'text-muted');
        var category = uploadType.value;
        var intent = null;
        refreshSession().then(function () {
            return declaredPageCount(file);
        }).then(function (pageCount) {
            return postJson(modulePath + '/public/api/documents.php/upload-intents', {
                csrf_token: state.csrf,
                idempotency_key: uploadUuid(),
                category: category,
                original_filename: file.name,
                mime_type: file.type,
                byte_count: file.size,
                page_count: pageCount
            }, { 'X-Correlation-Id': state.correlationId || panel.getAttribute('data-correlation-id') }, 15000);
        }).then(function (response) {
            if (!response.ok || !response.data || !response.data.upload_intent_id) {
                var intentError = new Error(response.data && response.data.code ? response.data.code : 'unavailable');
                intentError.data = response.data;
                throw intentError;
            }
            intent = response.data;
            var form = new FormData();
            form.append('csrf_token', state.csrf);
            form.append('upload_token', intent.upload_token);
            form.append('content', file, file.name);
            setUploadState(true, 'Saving the immutable source…', 'text-muted');
            return postForm(modulePath + '/public/api/documents.php/upload-intents/' + encodeURIComponent(intent.upload_intent_id) + '/content', form, 30000);
        }).then(function (response) {
            if (!response.ok || !response.data || !response.data.source) {
                var contentError = new Error(response.data && response.data.code ? response.data.code : 'unavailable');
                contentError.data = response.data;
                throw contentError;
            }
            var duplicate = response.data.warnings && response.data.warnings[0];
            setUploadState(false, duplicate ? duplicate.message : 'Source saved to the open chart.', duplicate ? 'text-warning' : 'text-success');
            uploadFile.value = '';
            loadReviewWorkspace(false);
        }).catch(function (error) {
            var limitation = error && error.data && error.data.limitation;
            setUploadState(false, limitation || 'The source could not be uploaded. The chart is unchanged.', 'text-danger');
        });
    }
    if (uploadType && uploadFile && uploadSubmit && uploadStatus) {
        uploadType.addEventListener('change', function () {
            uploadFile.accept = uploadType.value === 'lab_report' ? 'application/pdf' : 'application/pdf,image/png,image/jpeg';
        });
        uploadSubmit.addEventListener('click', uploadSelectedSource);
    }
    function resumeConversation() {
        return postJson(modulePath + '/public/api/conversation.php', {
            action: 'resume',
            csrf_token: state.csrf
        }).then(function (r) {
            if (!r.ok || !r.data) { throw new Error(r.data && r.data.code ? r.data.code : 'resume'); }
            return r.data.conversation_id || null;
        });
    }
    function resetTranscript() {
        asked = [];
        transcript.textContent = '';
        renderSuggestions([]);
        transcript.appendChild(el('div', 'copilot-hint small text-muted', state.briefOnOpen
            ? 'Preparing this chart’s brief. Ask your own question any time.'
            : 'Nothing is retrieved until you ask. Pick a question or type your own.'));
    }
    function synchronizeChart() {
        if (state.syncPromise) { return state.syncPromise; }
        state.syncPromise = refreshSession().then(function () {
            return Promise.all([resumeConversation(), loadReviewWorkspace(false)]);
        }).then(function (results) {
            var conversationId = results[0];
            state.conversationId = conversationId;
            if (conversationId === state.renderedConversationId) { return false; }
            state.correlationId = null;
            resetTranscript();
            state.renderedConversationId = conversationId;
            return conversationId ? restoreHistory() : false;
        }).finally(function () {
            state.syncPromise = null;
        });
        return state.syncPromise;
    }
    /**
     * Keep an active drawer pinned to its current conversation. Re-resolving
     * the newest conversation before every turn can replace the transcript
     * when another browser tab starts a chat for the same patient. The ticket
     * endpoint still rechecks the live patient and authorization every turn.
     */
    function prepareTurn() {
        if (state.syncPromise) { return state.syncPromise; }
        return state.renderedConversationId === undefined ? synchronizeChart() : refreshSession();
    }
    function ensureConversation() {
        if (state.conversationId) { return Promise.resolve(); }
        return postJson(modulePath + '/public/api/conversation.php', { action: 'start', csrf_token: state.csrf }).then(function (r) {
            if (!r.ok || !r.data || !r.data.conversation_id) { throw new Error(r.data && r.data.code ? r.data.code : 'start'); }
            state.conversationId = r.data.conversation_id;
            state.renderedConversationId = state.conversationId;
            state.correlationId = r.data.correlation_id;
        });
    }
    function dropConversation(resynchronize) {
        state.conversationId = null;
        if (resynchronize) { state.renderedConversationId = undefined; }
    }
    function ticket() {
        return postJson(modulePath + '/public/api/ticket.php', { csrf_token: state.csrf, conversation_id: state.conversationId }).then(function (r) {
            if (r.status === 409 && r.data && (r.data.code === 'patient_context_changed' || r.data.code === 'conversation_closed')) {
                dropConversation(true);
                throw new Error(r.data.code);
            }
            if (!r.ok || !r.data || !r.data.token) {
                if (r.status === 404 || r.status === 403) { dropConversation(true); }
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
        session: 'Your session changed in another window. Reopen the patient chart to continue here.',
        patient_context_changed: 'The open chart changed. Ask again to start a conversation for this chart.',
        conversation_closed: 'The conversation ended. Ask again to start a new one.',
        rate_limited: 'Too many questions in a minute; wait a moment.',
        unauthorized: 'The co-pilot is not available for this chart or account.',
        AbortError: 'The co-pilot did not answer in time. The chart is unaffected.',
        stream_incomplete: 'The co-pilot stopped answering before it finished. The chart is unaffected.'
    };
    // Recoverable conditions the user can act on (reopen the chart, ask again):
    // shown as a calm warning rather than a red error, on every entry point.
    var SOFT_CODES = { patient_context_changed: 1, conversation_closed: 1, rate_limited: 1, session: 1, no_chart: 1 };
    function isSoftCode(code) { return Object.prototype.hasOwnProperty.call(SOFT_CODES, code); }
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
            chip.disabled = state.busy;
            chip.addEventListener('click', function () { ask(q); });
            suggestions.appendChild(chip);
        });
    }
    function ask(question, auto) {
        if (state.busy) { return; }
        setBusy(true);
        var pending = null;
        setStatus(auto ? 'Preparing the brief…' : 'Checking the open chart…', 'text-muted');
        prepareTurn().then(function () {
            asked.push(question);
            if (auto) { appendBriefHeader(); } else { appendUser(question, new Date().toISOString()); }
            pending = appendPending();
            setStatus(auto ? 'Preparing the brief…' : 'Working…', 'text-muted');
            return ensureConversation();
        }).then(ticket).then(function (t) {
            setProgress(pending, 'Retrieving chart records…');
            return postStream(apiBase + '/v1/conversations/' + state.conversationId + '/turns',
                { message: question, correlation_id: t.correlation_id, stream: true },
                { 'X-Copilot-Token': t.token, 'X-Correlation-Id': t.correlation_id }, TURN_TIMEOUT_MS,
                function (event, data) {
                    var text = progressFor(event, data);
                    if (text) { setProgress(pending, text); }
                });
        }).then(function (turn) {
            if (turn.status === 'denied') { dropConversation(true); }
            renderTurn(turn, pending);
            renderSuggestions(turn.suggestions);
            setStatus('', 'text-muted');
        }).catch(function (error) {
            var code = error && error.name === 'AbortError' ? 'AbortError' : (error && error.message ? error.message : 'error');
            if (error && error.status === 403 && error.data && error.data.status === 'denied') { dropConversation(true); }
            var soft = isSoftCode(code);
            var message = ERROR_MESSAGES[code] || ('Co-Pilot unavailable (' + code + '). The chart is unaffected.');
            if (pending) {
                pending.textContent = '';
                pending.className = 'copilot-msg copilot-msg-assistant ' + (soft ? 'text-warning' : 'text-danger');
                pending.appendChild(el('div', 'copilot-message-text', message));
                appendMessageTime(pending, new Date().toISOString(), 'assistant');
            } else {
                appendNote(message, soft ? 'text-warning' : 'text-danger');
            }
            setStatus('', 'text-muted');
        }).finally(function () { setBusy(false); scrollToEnd(); input.focus(); });
    }

    function briefStartedRecently() {
        try {
            var at = Number(sessionStorage.getItem(BRIEF_GUARD_KEY) || 0);
            return at > 0 && (Date.now() - at) < BRIEF_GUARD_MS;
        } catch (e) { return false; }
    }
    function markBriefStarted() {
        try { sessionStorage.setItem(BRIEF_GUARD_KEY, String(Date.now())); } catch (e) { /* storage unavailable */ }
    }
    /**
     * Start the brief for a chart that has just opened, if the server said to.
     * Skipped when this conversation already has turns (its answers are on
     * screen), when a question is already running, and when this tab started a
     * brief moments ago, so a reload mid-brief does not pay for a second one.
     */
    function maybeStartBrief(restored) {
        if (restored === true || !state.briefOnOpen || state.briefStarted || state.busy || asked.length) { return; }
        if (briefStartedRecently()) { return; }
        state.briefStarted = true;
        markBriefStarted();
        fetchJson(apiBase + '/health?panel=brief_started', {}, 4000).catch(function () { /* a counter, never the user's problem */ });
        ask(BRIEF_QUESTION, true);
    }

    /** Re-render the transcript selected server-side for the current open chart. */
    function restoreHistory() {
        if (!state.conversationId) { return Promise.resolve(false); }
        return ticket().then(function (t) {
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
                // The current API records when an answer completed, not when a
                // historical question was sent, so do not invent a timestamp.
                appendUser(past.question || '', null);
                var msg = el('div', 'copilot-msg copilot-msg-assistant');
                transcript.appendChild(msg);
                renderTurn(past, msg);
            });
            if (r.data.turns.length) { renderSuggestions(r.data.turns[r.data.turns.length - 1].suggestions); }
            return r.data.turns.length > 0;
        }).catch(function () {
            dropConversation();
            state.renderedConversationId = undefined;
            return false;
        });
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
    resetTranscript();

    var launchParams = new URLSearchParams(window.location.search);
    if (launchParams.get('copilot') === 'open') {
        openDrawer();
        launchParams.delete('copilot');
        var query = launchParams.toString();
        window.history.replaceState(null, '', window.location.pathname + (query ? '?' + query : '') + window.location.hash);
    }

    // Agent reachability through the edge; the chart does not depend on it.
    // `panel=` tells the agent why the check was made: the top of the usage funnel in its /metrics
    // (chart opened with the panel, brief prepared for it, drawer opened, kind of first question).
    // Briefs prepared against drawers opened is what the precompute costs against what it is worth.
    // No ids, no chart data.
    fetchJson(apiBase + '/health?panel=chart_open', {}, 4000).then(function (r) {
        if (r.ok && r.data) {
            setStatus('', 'text-muted');
            return synchronizeChart().then(maybeStartBrief);
        }
        setStatus('Unavailable: agent service not reachable. The chart is unaffected.', 'text-danger');
        return false;
    }).catch(function () {
        setStatus('Unavailable: agent service not reachable. The chart is unaffected.', 'text-danger');
    });
})();
