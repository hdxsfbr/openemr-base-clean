/**
 * @jest-environment jsdom
 */

const fs = require('fs');
const path = require('path');

const moduleRoot = path.resolve(__dirname, '..');
const script = fs.readFileSync(path.join(moduleRoot, 'public/assets/js/copilot.js'), 'utf8');
const css = fs.readFileSync(path.join(moduleRoot, 'public/assets/css/copilot.css'), 'utf8');

function response(status, data) {
    return Promise.resolve({
        ok: status >= 200 && status < 300,
        status,
        headers: { get: () => 'application/json' },
        text: () => Promise.resolve(JSON.stringify(data))
    });
}

function workspace(decision = null) {
    return {
        status: decision ? 'ready_to_promote' : 'review_required',
        extraction: {
            extraction_id: '11111111-1111-4111-8111-111111111111',
            extraction_version: 3,
            extraction_state: 'review_required',
            schema_name: 'lab-report',
            target_type: 'lab_report',
            source_document_id: '22222222-2222-4222-8222-222222222222',
            source_content_sha256: 'a'.repeat(64),
            document_type: 'lab_report',
            page_count: 2
        },
        facts: [{
            field_id: 'analyte.potassium.value',
            proposed_value: { kind: 'quantity', value: '4.2' },
            extraction_state: 'review_required',
            evidence: [{
                evidence_id: '55555555-5555-4555-8555-555555555555',
                page_number: 2,
                box: { x: 0.1, y: 0.2, width: 0.3, height: 0.08 },
                printed_quote: 'Potassium 4.2',
                rendered_page_sha256: 'c'.repeat(64)
            }],
            current_decision: decision || { decision: 'pending' }
        }],
        promotion: {
            state: decision ? 'ready' : 'blocked',
            review_ids: decision ? [decision.review_id] : [],
            blocker_count: decision ? 0 : 1,
            current_record: null
        }
    };
}

function mount(fetchImpl) {
    document.body.innerHTML = `
        <a id="copilot_menu"><span></span></a>
        <aside id="copilot-panel" class="copilot-drawer" aria-hidden="true"
            data-api-base="/copilot-api" data-module-path="/module" data-web-root=""
            data-correlation-id="corr-browser-1">
            <div class="copilot-drawer-body">
                <details id="copilot-review" class="copilot-review">
                    <summary>Review extracted document</summary>
                    <div id="copilot-review-status" role="status"></div>
                    <div id="copilot-review-workspace"></div>
                </details>
                <details id="copilot-upload"><select id="copilot-upload-type"><option value="lab_report"></option></select>
                    <input id="copilot-upload-file" type="file"><button id="copilot-upload-submit"></button>
                    <div id="copilot-upload-status"></div></details>
                <div id="copilot-transcript"></div><div id="copilot-composer"></div>
            </div>
            <span id="copilot-status"></span><button id="copilot-close"></button>
        </aside>`;
    window.matchMedia = jest.fn().mockReturnValue({ matches: true });
    window.top.restoreSession = jest.fn();
    global.fetch = jest.fn(fetchImpl);
    window.eval(script);
}

async function settle() {
    await Promise.resolve();
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('physician review browser seam', () => {
    test('renders pending read-back and posts an exact CSRF-bound approval before enabling promotion', async () => {
        let current = workspace();
        const calls = [];
        mount((url, options = {}) => {
            calls.push({ url, options });
            if (url.includes('/health')) return response(200, { ok: true });
            if (url.endsWith('/session.php')) return response(200, { csrf_token: 'csrf-demo', chart_open: true, brief_on_open: false });
            if (url.endsWith('/conversation.php')) return response(200, { conversation_id: null });
            if (url.endsWith('/review-workspace')) return response(200, current);
            if (url.endsWith('/document-reviews')) {
                current = workspace({
                    review_id: '66666666-6666-4666-8666-666666666666',
                    decision: 'approved',
                    final_value: { kind: 'quantity', value: '4.2' },
                    reviewed_by: 'physician-demo',
                    reviewed_at: '2026-09-21T12:00:00Z'
                });
                return response(200, current.facts[0].current_decision);
            }
            if (url.endsWith('/document-promotions')) {
                current.status = 'promoted';
                current.promotion.state = 'promoted';
                current.promotion.current_record = {
                    record_id: '88888888-8888-4888-8888-888888888888',
                    record_version: 1,
                    target_type: 'lab_report',
                    status: 'final',
                    review_set_sha256: 'b'.repeat(64),
                    record: {
                        collection_date: null,
                        analytes: [{ value: { source_field_id: 'analyte.potassium.value', value: { kind: 'quantity', value: '4.2' } } }]
                    }
                };
                return response(200, {
                    promotion_id: '77777777-7777-4777-8777-777777777777',
                    target_type: 'lab_report',
                    target_record_id: '88888888-8888-4888-8888-888888888888',
                    record_version: 1,
                    review_set_sha256: 'b'.repeat(64),
                    outcome: 'created'
                });
            }
            throw new Error(`Unexpected request ${url}`);
        });
        await settle();

        expect(calls.some((call) => /\/(document-reviews|document-promotions)$/.test(call.url))).toBe(false);
        expect(document.querySelector('[data-review-action="correct"]').tagName).toBe('BUTTON');
        expect(document.querySelector('[data-review-action="reject"]').tagName).toBe('BUTTON');
        expect(document.querySelector('[data-review-action="promote"]').disabled).toBe(true);
        document.querySelector('[data-review-action="approve"]').click();
        await settle();

        const approval = calls.find((call) => call.url.endsWith('/document-reviews'));
        const approvalBody = JSON.parse(approval.options.body);
        expect(Object.keys(approvalBody).sort()).toEqual([
            'action', 'csrf_token', 'expected_extraction_version', 'extraction_id', 'field_id', 'idempotency_key'
        ]);
        expect(approvalBody).toEqual(expect.objectContaining({
            csrf_token: 'csrf-demo',
            extraction_id: '11111111-1111-4111-8111-111111111111',
            expected_extraction_version: 3,
            field_id: 'analyte.potassium.value',
            action: 'approve'
        }));
        expect(document.querySelector('[data-review-action="promote"]').disabled).toBe(false);
        document.querySelector('[data-review-action="promote"]').click();
        await settle();

        const promotion = calls.find((call) => call.url.endsWith('/document-promotions'));
        const promotionBody = JSON.parse(promotion.options.body);
        expect(Object.keys(promotionBody).sort()).toEqual([
            'csrf_token', 'expected_extraction_version', 'extraction_id', 'idempotency_key', 'review_ids',
            'source_content_sha256', 'target_type'
        ]);
        expect(promotionBody).toEqual(expect.objectContaining({
            csrf_token: 'csrf-demo',
            extraction_id: '11111111-1111-4111-8111-111111111111',
            expected_extraction_version: 3,
            source_content_sha256: 'a'.repeat(64),
            target_type: 'lab_report',
            review_ids: ['66666666-6666-4666-8666-666666666666']
        }));
        expect(document.querySelector('.copilot-reviewed-record').textContent).toContain('Version 1 · final');
        expect(document.querySelector('.copilot-reviewed-record').textContent).toContain('4.2');
    });

    test('preserves structured coded values in an explicit correction command', async () => {
        const current = workspace();
        current.facts[0].field_id = 'analyte.potassium.code';
        current.facts[0].proposed_value = { system: 'http://loinc.org', code: '2823-3', display: 'Potassium' };
        const calls = [];
        mount((url, options = {}) => {
            calls.push({ url, options });
            if (url.includes('/health')) return response(200, { ok: true });
            if (url.endsWith('/session.php')) return response(200, { csrf_token: 'csrf-demo', chart_open: true, brief_on_open: false });
            if (url.endsWith('/conversation.php')) return response(200, { conversation_id: null });
            if (url.endsWith('/review-workspace')) return response(200, current);
            if (url.endsWith('/document-reviews')) return response(200, { decision: 'corrected' });
            throw new Error(`Unexpected request ${url}`);
        });
        await settle();

        const correction = document.querySelector('[aria-label="Corrected value for analyte.potassium.code"]');
        expect(JSON.parse(correction.value)).toEqual(current.facts[0].proposed_value);
        document.querySelector('[aria-label="Reason for changing analyte.potassium.code"]').value = 'Confirmed in source';
        document.querySelector('[data-review-action="correct"]').click();
        await settle();

        const command = JSON.parse(calls.find((call) => call.url.endsWith('/document-reviews')).options.body);
        expect(command).toEqual(expect.objectContaining({
            action: 'correct',
            field_id: 'analyte.potassium.code',
            corrected_value: { kind: 'coded', value: current.facts[0].proposed_value },
            reason: 'Confirmed in source'
        }));
    });

    test('requires a reason and sends rejection only after an explicit click', async () => {
        const calls = [];
        mount((url, options = {}) => {
            calls.push({ url, options });
            if (url.includes('/health')) return response(200, { ok: true });
            if (url.endsWith('/session.php')) return response(200, { csrf_token: 'csrf-demo', chart_open: true, brief_on_open: false });
            if (url.endsWith('/conversation.php')) return response(200, { conversation_id: null });
            if (url.endsWith('/review-workspace')) return response(200, workspace());
            if (url.endsWith('/document-reviews')) return response(200, { decision: 'rejected' });
            throw new Error(`Unexpected request ${url}`);
        });
        await settle();

        document.querySelector('[data-review-action="reject"]').click();
        await settle();
        expect(calls.some((call) => call.url.endsWith('/document-reviews'))).toBe(false);

        document.querySelector('[aria-label="Reason for changing analyte.potassium.value"]').value = 'Not present in source';
        document.querySelector('[data-review-action="reject"]').click();
        await settle();
        const command = JSON.parse(calls.find((call) => call.url.endsWith('/document-reviews')).options.body);
        expect(Object.keys(command).sort()).toEqual([
            'action', 'csrf_token', 'expected_extraction_version', 'extraction_id', 'field_id', 'idempotency_key', 'reason'
        ]);
        expect(command).toEqual(expect.objectContaining({ action: 'reject', reason: 'Not present in source' }));
    });

    test('source click sends exact evidence hashes and Escape restores review at a narrow viewport', async () => {
        const calls = [];
        mount((url, options = {}) => {
            calls.push({ url, options });
            if (url.includes('/health')) return response(200, { ok: true });
            if (url.endsWith('/session.php')) return response(200, { csrf_token: 'csrf-demo', chart_open: true, brief_on_open: false });
            if (url.endsWith('/conversation.php')) return response(200, { conversation_id: null });
            if (url.endsWith('/review-workspace')) return response(200, workspace());
            if (url.endsWith('/review-source')) return response(200, {
                status: 'available', lane: 'patient_record', announcement: 'Source region opened',
                source: {
                    source_type: 'document_proposal', title: 'Laboratory report proposal', document_type: 'lab_report',
                    extraction_version: 3, field_id: 'analyte.potassium.value', extraction_state: 'review_required',
                    proposed: { label: 'Proposed', value: { kind: 'quantity', value: '4.2' } },
                    printed: { label: 'Printed', value: 'Potassium 4.2' }, page_number: 2,
                    box: { x: 0.1, y: 0.2, width: 0.3, height: 0.08 }, focus_label: 'Proposed fact evidence region',
                    page: { media_type: 'image/png', data_base64: btoa('synthetic page') }
                }
            });
            throw new Error(`Unexpected request ${url}`);
        });
        await settle();

        window.AgentForgeCopilot.open();
        await settle();
        document.querySelector('[data-review-action="source"]').click();
        await settle();
        const sourceCall = calls.find((call) => call.url.endsWith('/review-source'));
        expect(JSON.parse(sourceCall.options.body)).toEqual({
            csrf_token: 'csrf-demo',
            extraction_id: '11111111-1111-4111-8111-111111111111',
            expected_extraction_version: 3,
            source_document_id: '22222222-2222-4222-8222-222222222222',
            source_content_sha256: 'a'.repeat(64),
            field_id: 'analyte.potassium.value',
            evidence_id: '55555555-5555-4555-8555-555555555555',
            page_number: 2,
            rendered_page_sha256: 'c'.repeat(64)
        });
        expect(document.getElementById('copilot-panel').classList.contains('source-view-active')).toBe(true);

        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        expect(document.getElementById('copilot-panel').classList.contains('source-view-active')).toBe(false);
        expect(document.activeElement.textContent).toBe('Answer & review');
        expect(css).toContain('@media (max-width: 320px)');
        expect(css).toContain('.copilot-review-actions');
    });
});
