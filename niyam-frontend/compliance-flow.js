// ============================================================
// Compliance Flow — single-page pipeline controller
// Upload → Extract → Compliance → ITC → Dashboard → Export
// ============================================================

(function () {
    const API = CONFIG.API_URL;
    // Use NiyamAuth for all authenticated requests (auto-refresh on 401)
    const jsonHeaders = () => ({ 'Content-Type': 'application/json' });

    // State
    let currentStep = 1;
    let uploadedDocId = null;
    let extractedData = null;
    let complianceData = null;
    let itcData = null;
    let dashboardData = null;

    // ---- Helpers ----
    const $ = id => document.getElementById(id);
    const show = el => { if (el) el.style.display = ''; };
    const hide = el => { if (el) el.style.display = 'none'; };
    const fmt = n => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n || 0);

    function setStep(step) {
        currentStep = step;
        document.querySelectorAll('.cf-step').forEach(el => {
            const s = parseInt(el.dataset.step);
            el.classList.toggle('active', s === step);
            el.classList.toggle('done', s < step);
        });
        for (let i = 1; i <= 6; i++) {
            const panel = $('cf-panel-' + i);
            if (panel) panel.style.display = i === step ? '' : 'none';
        }
        hideError();
        if (window.feather) feather.replace();
    }

    function showError(msg) {
        const el = $('cf-error');
        if (el) {
            el.textContent = msg;
            el.style.display = '';
        }
    }

    function hideError() {
        const el = $('cf-error');
        if (el) el.style.display = 'none';
    }

    // ============================================================
    // STEP 1: Upload
    // ============================================================
    function initUpload() {
        const input = $('cf-file-input');
        if (!input) return;
        input.addEventListener('change', async function () {
            if (!this.files || !this.files[0]) return;
            const file = this.files[0];

            show($('cf-upload-progress'));
            $('cf-upload-status').textContent = `Uploading "${file.name}"...`;
            $('cf-progress-fill').style.width = '30%';

            const form = new FormData();
            form.append('file', file);
            form.append('document_type', 'purchase_invoice');

            try {
                const res = NiyamAuth.niyamFetch(`${API}/upload`, { method: 'POST', body: form });
                $('cf-progress-fill').style.width = '70%';

                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `Upload failed (${res.status})`);
                }

                const data = await res.json();
                if (!data.success) throw new Error(data.detail || 'Upload failed');

                uploadedDocId = data.data.document_id;
                $('cf-progress-fill').style.width = '100%';
                $('cf-upload-status').textContent = 'Upload complete! Extracting data...';

                if (typeof showToast === 'function') showToast('File uploaded successfully.');

                // Auto-advance to extraction
                setTimeout(() => cfRunExtract(), 600);
            } catch (e) {
                showError(e.message);
                hide($('cf-upload-progress'));
                input.value = '';
            }
        });
    }

    // ============================================================
    // STEP 2: Extract
    // ============================================================
    async function cfRunExtract() {
        setStep(2);

        // Show loading inside step 2
        const panel = $('cf-panel-2');
        panel.innerHTML = '<div class="cf-loading"><div class="cf-spinner"></div><p>Extracting invoice data...</p></div>';
        show(panel);

        try {
            const res = NiyamAuth.niyamFetch(`${API}/extract`, {
                method: 'POST',
                headers: jsonHeaders(),
                body: JSON.stringify({ document_id: uploadedDocId })
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Extraction failed (${res.status})`);
            }

            const data = await res.json();
            if (!data.success) throw new Error(data.detail || data.error || 'Extraction failed');

            extractedData = data.data;
            renderExtraction(extractedData);
        } catch (e) {
            showError(e.message);
            panel.innerHTML = `
                <div class="card" style="text-align:center; padding:40px;">
                    <p style="color:var(--error); font-weight:600; margin-bottom:16px;">Extraction Failed</p>
                    <p style="color:var(--text-light); margin-bottom:20px;">${e.message}</p>
                    <button class="btn btn-outline" onclick="cfRestart()">Try Again</button>
                </div>`;
        }
    }

    function renderExtraction(data) {
        const norm = data.normalized || data;
        const conf = norm.confidence_score || norm.confidence || 0;
        const confBadge = $('cf-confidence-badge');
        if (confBadge) {
            confBadge.textContent = `${conf}% confidence`;
            confBadge.className = 'badge ' + (conf >= 80 ? 'badge-success' : conf >= 60 ? 'badge-upcoming' : 'badge-overdue');
        }

        const fields = [
            ['Invoice Number', norm.invoice_number],
            ['Invoice Date', norm.invoice_date],
            ['Vendor Name', norm.vendor_name],
            ['Vendor GSTIN', norm.vendor_gstin],
            ['Taxable Amount', fmt(norm.taxable_amount || norm.taxable_value)],
            ['CGST', fmt(norm.cgst)],
            ['SGST', fmt(norm.sgst)],
            ['IGST', fmt(norm.igst)],
            ['Total Amount', fmt(norm.total_amount)],
            ['Needs Review', norm.needs_review ? 'Yes' : 'No'],
        ];

        const panel = $('cf-panel-2');
        panel.innerHTML = `
            <div class="card">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
                    <h3>Extracted Invoice Data</h3>
                    <span id="cf-confidence-badge" class="badge ${conf >= 80 ? 'badge-success' : conf >= 60 ? 'badge-upcoming' : 'badge-overdue'}">${conf}% confidence</span>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
                    ${fields.map(([label, val]) => `
                        <div>
                            <p style="font-size:0.8rem; color:var(--text-light);">${label}</p>
                            <p style="font-weight:600;">${val || '—'}</p>
                        </div>
                    `).join('')}
                </div>
                ${norm.review_reasons && norm.review_reasons.length ? `
                    <div style="margin-top:16px; padding:12px; background:#fef3c7; border-radius:8px;">
                        <p style="font-weight:600; font-size:0.85rem; color:#92400e;">Review Notes: ${norm.review_reasons.join(', ')}</p>
                    </div>
                ` : ''}
                <div style="margin-top:24px; display:flex; gap:10px; justify-content:flex-end;">
                    <button class="btn btn-outline" onclick="cfRestart()">Start Over</button>
                    <button class="btn btn-primary" onclick="cfRunCompliance()">
                        Run Compliance Check
                    </button>
                </div>
            </div>`;
        if (window.feather) feather.replace();
    }

    // ============================================================
    // STEP 3: Compliance Check
    // ============================================================
    window.cfRunCompliance = async function () {
        setStep(3);
        show($('cf-compliance-loading'));
        hide($('cf-compliance-results'));

        try {
            const res = NiyamAuth.niyamFetch(`${API}/compliance-check`, {
                method: 'POST',
                headers: jsonHeaders(),
                body: JSON.stringify({ check_type: 'all' })
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Compliance check failed (${res.status})`);
            }

            const data = await res.json();
            if (!data.success) throw new Error(data.detail || 'Compliance check failed');

            complianceData = data.data;
            renderCompliance(complianceData);
        } catch (e) {
            showError(e.message);
            hide($('cf-compliance-loading'));
        }
    };

    function renderCompliance(data) {
        hide($('cf-compliance-loading'));
        show($('cf-compliance-results'));

        const score = data.compliance_score || 0;
        $('cf-comp-score').textContent = score + '%';
        $('cf-comp-score').style.color = score >= 80 ? 'var(--success)' : score >= 50 ? '#f59e0b' : 'var(--error)';

        const risk = data.risk_level || 'unknown';
        $('cf-risk-level').textContent = risk.charAt(0).toUpperCase() + risk.slice(1);
        $('cf-risk-level').style.color = risk === 'low' ? 'var(--success)' : risk === 'medium' ? '#f59e0b' : 'var(--error)';

        $('cf-penalties').textContent = fmt(data.estimated_penalties || 0);
        $('cf-penalties').style.color = (data.estimated_penalties || 0) > 0 ? 'var(--error)' : 'var(--success)';

        // Render flags
        const flags = data.flags || [];
        const flagsList = $('cf-flags-list');
        if (flags.length === 0) {
            flagsList.innerHTML = '<p style="color:var(--success); font-weight:600;">No compliance issues found.</p>';
        } else {
            flagsList.innerHTML = flags.slice(0, 10).map(f => {
                const sev = (f.severity || 'info').replace('Severity.', '');
                const colors = { critical: '#991b1b', error: '#dc2626', warning: '#d97706', info: '#2563eb' };
                const bgColors = { critical: '#fee2e2', error: '#fee2e2', warning: '#fef3c7', info: '#dbeafe' };
                return `
                    <div class="cf-flag" style="border-left:4px solid ${colors[sev] || '#94a3b8'}; background:${bgColors[sev] || '#f8fafc'};">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span class="badge" style="background:${colors[sev] || '#94a3b8'}; color:white;">${sev.toUpperCase()}</span>
                            <span style="font-size:0.75rem; color:var(--text-light);">${f.rule_id || ''}</span>
                        </div>
                        <p style="font-weight:600; margin-top:8px;">${f.message || ''}</p>
                        ${f.action_required ? `<p style="font-size:0.8rem; color:var(--text-light); margin-top:4px;">${f.action_required}</p>` : ''}
                    </div>`;
            }).join('');
            if (flags.length > 10) {
                flagsList.innerHTML += `<p style="color:var(--text-light); font-size:0.85rem; margin-top:12px;">...and ${flags.length - 10} more flags</p>`;
            }
        }

        if (window.feather) feather.replace();
    }

    // ============================================================
    // STEP 4: ITC Matching
    // ============================================================
    window.cfShowITCPanel = function () {
        setStep(4);
        hide($('cf-itc-loading'));
        hide($('cf-itc-results'));
    };

    window.cfRunITC = async function (gstr2bRaw) {
        show($('cf-itc-loading'));

        let gstr2b = {};
        if (gstr2bRaw && gstr2bRaw.trim()) {
            try {
                gstr2b = JSON.parse(gstr2bRaw);
            } catch (e) {
                showError('Invalid JSON in GSTR-2B input. Please check the format.');
                hide($('cf-itc-loading'));
                return;
            }
        }

        try {
            const res = NiyamAuth.niyamFetch(`${API}/itc-match`, {
                method: 'POST',
                headers: jsonHeaders(),
                body: JSON.stringify({
                    gstr2b_data: gstr2b,
                    period: new Date().toLocaleString('en-US', { month: 'short', year: 'numeric' }),
                    amount_tolerance: 1.0,
                    gst_tolerance: 1.0,
                    fuzzy_invoice_number: true
                })
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || err.detail || `ITC reconciliation failed (${res.status})`);
            }

            const data = await res.json();
            if (!data.success) throw new Error(data.error || data.detail || 'ITC reconciliation failed');

            itcData = data.data;
            renderITC(itcData);
        } catch (e) {
            showError(e.message);
            hide($('cf-itc-loading'));
        }
    };

    function renderITC(data) {
        hide($('cf-itc-loading'));
        show($('cf-itc-results'));

        const fin = data.financials || data.financial_summary || {};
        const elAvail = $('cf-itc-available');
        const elClaimed = $('cf-itc-claimed');
        const elRisk = $('cf-itc-risk');
        const elRecover = $('cf-itc-recoverable');
        if (elAvail) elAvail.textContent = fmt(fin.total_itc_available || fin.available || 0);
        if (elClaimed) elClaimed.textContent = fmt(fin.total_itc_claimed || fin.claimed || 0);
        if (elRisk) elRisk.textContent = fmt(fin.total_itc_at_risk || fin.at_risk || 0);
        if (elRecover) elRecover.textContent = fmt(fin.recoverable_itc || fin.recoverable || 0);

        // Priority actions from action_summary
        const actionSummary = data.action_summary || {};
        const actions = [
            ...(actionSummary.critical || []),
            ...(actionSummary.high || []),
            ...(actionSummary.medium || []),
            ...(actionSummary.low || []),
        ];
        const actionsEl = $('cf-itc-actions');
        if (actions.length === 0) {
            actionsEl.innerHTML = '<p style="color:var(--success); font-weight:600;">No ITC actions required.</p>';
        } else {
            actionsEl.innerHTML = actions.slice(0, 5).map((a, i) => `
                <div class="cf-action-item">
                    <span class="cf-action-num">${i + 1}</span>
                    <div>
                        <p style="font-weight:600;">${a.action_required || a.message || ''}</p>
                        <p style="font-size:0.8rem; color:var(--text-light);">
                            ${a.invoice_number || ''} ${a.itc_at_risk ? ' &middot; ' + fmt(a.itc_at_risk) + ' at risk' : ''}
                        </p>
                    </div>
                </div>
            `).join('');
        }

        if (window.feather) feather.replace();
    }

    // ============================================================
    // STEP 5: Dashboard Summary
    // ============================================================
    window.cfLoadDashboard = async function () {
        setStep(5);
        show($('cf-dash-loading'));
        hide($('cf-dash-results'));

        try {
            // Fetch dashboard + readiness in parallel
            const [dashRes, readyRes] = await Promise.all([
                fetch(`${API}/dashboard/summary?top_n=3`, { headers: headers() }),
                fetch(`${API}/export/readiness`, { headers: headers() }).catch(() => null)
            ]);

            if (!dashRes.ok) {
                const err = await dashRes.json().catch(() => ({}));
                throw new Error(err.detail || `Dashboard load failed (${dashRes.status})`);
            }

            const dashData = await dashRes.json();
            if (!dashData.success) throw new Error(dashData.detail || 'Dashboard load failed');
            dashboardData = dashData.data;

            let readiness = null;
            if (readyRes && readyRes.ok) {
                const readyData = await readyRes.json();
                if (readyData.success) readiness = readyData.data;
            }

            renderDashboard(dashboardData, readiness);
        } catch (e) {
            showError(e.message);
            hide($('cf-dash-loading'));
        }
    };

    function renderDashboard(data, readiness) {
        hide($('cf-dash-loading'));
        show($('cf-dash-results'));

        // Readiness banner
        const banner = $('cf-readiness-banner');
        if (readiness) {
            const ready = readiness.ready_to_file;
            banner.className = 'cf-readiness-banner ' + (ready ? 'cf-ready-yes' : 'cf-ready-no');
            banner.innerHTML = `
                <div style="display:flex; align-items:center; gap:12px;">
                    <span style="font-size:2rem;">${ready ? '\u2705' : '\u26A0\uFE0F'}</span>
                    <div>
                        <p style="font-weight:700; font-size:1.1rem;">${ready ? 'Ready to File' : 'Not Ready to File'}</p>
                        <p style="font-size:0.85rem; opacity:0.9;">
                            ${readiness.clean_invoice_count}/${readiness.total_invoice_count} clean invoices (${readiness.clean_rate}%)
                            ${readiness.blocking_issues && readiness.blocking_issues.length ? ' &middot; ' + readiness.blocking_issues.length + ' blocking issue(s)' : ''}
                        </p>
                    </div>
                </div>`;
            show(banner);
        } else {
            hide(banner);
        }

        // Top 3 Actions
        const topActions = data.top_actions || [];
        const actionsEl = $('cf-top-actions');
        if (topActions.length === 0) {
            actionsEl.innerHTML = '<p style="color:var(--success);">No urgent actions.</p>';
        } else {
            actionsEl.innerHTML = topActions.map((a, i) => {
                const urgencyColors = { critical: 'var(--error)', high: '#dc2626', medium: '#f59e0b', low: 'var(--success)' };
                const urgency = a.urgency || a.priority || 'medium';
                return `
                    <div class="cf-top-action">
                        <div class="cf-action-priority" style="background:${urgencyColors[urgency] || '#94a3b8'};">${i + 1}</div>
                        <div style="flex:1;">
                            <p style="font-weight:600;">${a.title || a.message || ''}</p>
                            <p style="font-size:0.8rem; color:var(--text-light);">${a.description || a.action_required || ''}</p>
                        </div>
                        ${a.amount ? `<span style="font-weight:700; color:var(--error);">${fmt(a.amount)}</span>` : ''}
                    </div>`;
            }).join('');
        }

        // Financial summary
        const fin = data.financials || data.financial_summary || {};
        const finEl = $('cf-financials');
        const finItems = [
            ['Tax Liability', fin.total_tax_liability || fin.tax_liability || 0, false],
            ['ITC Available', fin.total_itc_available || fin.itc_available || fin.total_itc || 0, false],
            ['ITC Claimed', fin.total_itc_claimed || fin.claimed || 0, false],
            ['Penalties at Risk', fin.total_penalty_risk || fin.penalties_at_risk || fin.estimated_penalties || 0, true],
        ];
        finEl.innerHTML = finItems.map(([label, val, isDanger]) => `
            <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f1f5f9;">
                <span style="color:var(--text-light);">${label}</span>
                <span style="font-weight:700; ${isDanger && val > 0 ? 'color:var(--error);' : ''}">${fmt(val)}</span>
            </div>
        `).join('');

        // Compliance overview
        const comp = data.compliance || {};
        const compEl = $('cf-compliance-overview');
        compEl.innerHTML = `
            <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f1f5f9;">
                <span style="color:var(--text-light);">Health Score</span>
                <span style="font-weight:700; color:${(comp.health_score || 0) >= 80 ? 'var(--success)' : 'var(--error)'};">${comp.health_score || 0}%</span>
            </div>
            <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f1f5f9;">
                <span style="color:var(--text-light);">Risk Level</span>
                <span style="font-weight:700;">${(comp.risk_level || 'N/A').charAt(0).toUpperCase() + (comp.risk_level || '').slice(1)}</span>
            </div>
            <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f1f5f9;">
                <span style="color:var(--text-light);">Upcoming Deadlines</span>
                <span style="font-weight:700;">${comp.upcoming_deadlines || data.upcoming_deadlines || 0}</span>
            </div>
            <div style="display:flex; justify-content:space-between; padding:10px 0;">
                <span style="color:var(--text-light);">Active Flags</span>
                <span style="font-weight:700;">${comp.active_flags || 0}</span>
            </div>`;

        if (window.feather) feather.replace();
    }

    // ============================================================
    // STEP 6: Export
    // ============================================================
    window.cfShowExport = async function () {
        setStep(6);
        hide($('cf-export-loading'));
        hide($('cf-export-result'));

        // Load readiness status
        try {
            const res = NiyamAuth.niyamFetch(`${API}/export/readiness`);
            if (res.ok) {
                const data = await res.json();
                if (data.success) renderExportReadiness(data.data);
            }
        } catch (e) { /* non-blocking */ }
    };

    function renderExportReadiness(readiness) {
        const el = $('cf-export-readiness');
        if (!el) return;
        const ready = readiness.ready_to_file;
        el.innerHTML = `
            <div style="padding:16px; border-radius:8px; background:${ready ? '#dcfce7' : '#fee2e2'};">
                <p style="font-weight:700; color:${ready ? '#166534' : '#991b1b'};">
                    ${ready ? '\u2705 Data is ready for filing' : '\u26A0\uFE0F Not ready for filing — ' + (readiness.blocking_issues || []).length + ' blocking issue(s)'}
                </p>
                <p style="font-size:0.85rem; margin-top:4px; color:${ready ? '#166534' : '#991b1b'};">
                    ${readiness.clean_invoice_count}/${readiness.total_invoice_count} clean (${readiness.clean_rate}%)
                </p>
            </div>`;
    }

    window.cfExport = async function (format) {
        // Highlight selected format
        ['json', 'excel', 'csv'].forEach(f => {
            const opt = $('cf-opt-' + f);
            if (opt) opt.classList.toggle('cf-export-selected', f === format);
        });

        show($('cf-export-loading'));
        hide($('cf-export-result'));

        const params = new URLSearchParams({ format });
        if ($('cf-filter-clean') && $('cf-filter-clean').checked) params.set('clean_only', 'true');
        if ($('cf-filter-risk') && $('cf-filter-risk').checked) params.set('exclude_high_risk', 'true');
        if ($('cf-filter-flagged') && !$('cf-filter-flagged').checked) params.set('include_flagged', 'false');

        try {
            const res = NiyamAuth.niyamFetch(`${API}/export?${params}`);

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Export failed (${res.status})`);
            }

            hide($('cf-export-loading'));

            if (format === 'json') {
                const data = await res.json();
                const exportData = data.data || data;
                const jsonStr = JSON.stringify(exportData, null, 2);
                const resultEl = $('cf-export-result');
                resultEl.innerHTML = `
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                            <h3>JSON Export</h3>
                            <button class="btn btn-primary" onclick="cfDownloadJSON()" style="padding:8px 16px; font-size:0.85rem;">Download JSON</button>
                        </div>
                        <pre style="background:#1e293b; color:#e2e8f0; padding:16px; border-radius:8px; overflow:auto; max-height:400px; font-size:0.75rem;">${escapeHtml(jsonStr.substring(0, 5000))}${jsonStr.length > 5000 ? '\n\n... truncated for preview ...' : ''}</pre>
                    </div>`;
                show(resultEl);
                // Store for download
                window._cfExportJSON = jsonStr;
            } else {
                // Binary (Excel or CSV zip)
                const blob = await res.blob();
                const ext = format === 'excel' ? 'xlsx' : 'zip';
                const filename = `niyam_export.${ext}`;
                downloadBlob(blob, filename);

                const resultEl = $('cf-export-result');
                resultEl.innerHTML = `
                    <div class="card" style="text-align:center; padding:30px;">
                        <p style="font-size:2rem; margin-bottom:12px;">\u2705</p>
                        <p style="font-weight:700; font-size:1.1rem;">Export Downloaded</p>
                        <p style="color:var(--text-light); margin-top:8px;">${filename} saved to your downloads.</p>
                    </div>`;
                show(resultEl);
            }

            if (typeof showToast === 'function') showToast(`${format.toUpperCase()} export ready!`);
        } catch (e) {
            showError(e.message);
            hide($('cf-export-loading'));
        }
    };

    window.cfDownloadJSON = function () {
        if (!window._cfExportJSON) return;
        const blob = new Blob([window._cfExportJSON], { type: 'application/json' });
        downloadBlob(blob, 'niyam_export.json');
    };

    function downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ============================================================
    // Restart
    // ============================================================
    window.cfRestart = function () {
        uploadedDocId = null;
        extractedData = null;
        complianceData = null;
        itcData = null;
        dashboardData = null;
        window._cfExportJSON = null;

        // Reset upload input
        const input = $('cf-file-input');
        if (input) input.value = '';
        hide($('cf-upload-progress'));

        // Reset ITC input
        const gstr = $('cf-gstr2b-input');
        if (gstr) gstr.value = '';

        setStep(1);
        if (typeof showToast === 'function') showToast('Flow reset. Ready for new upload.');
    };

    // ============================================================
    // Init
    // ============================================================
    document.addEventListener('DOMContentLoaded', () => {
        initUpload();
    });
})();
