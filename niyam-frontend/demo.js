// ============================================================
// Demo Mode — instant full-pipeline demo, no auth required
// ============================================================

(function () {
    const API = CONFIG.API_URL;
    const $ = id => document.getElementById(id);
    const fmt = n => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n || 0);

    let demoLoaded = false;

    // Auto-trigger demo if arriving via #demo hash (from landing page)
    document.addEventListener('DOMContentLoaded', () => {
        if (window.location.hash === '#demo') {
            // Skip auth check for demo mode
            window._demoMode = true;
            setTimeout(() => {
                const sidebarItem = $('sidebar-demo');
                if (typeof switchView === 'function') switchView('demo', sidebarItem);
                runDemo();
            }, 200);
        }
    });

    window.runDemo = async function () {
        if (demoLoaded) return; // don't re-fetch if already loaded

        const loading = $('demo-loading');
        const results = $('demo-results');
        if (loading) loading.style.display = '';
        if (results) results.style.display = 'none';

        try {
            const res = await fetch(`${API}/demo/run?top_n=3`);
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Demo failed (${res.status})`);
            }

            const json = await res.json();
            if (!json.success) throw new Error('Demo run failed');

            renderDemo(json.data);
            demoLoaded = true;
        } catch (e) {
            if (loading) {
                loading.innerHTML = `
                    <div style="text-align:center; padding:40px;">
                        <p style="color:var(--error); font-weight:600; margin-bottom:12px;">Demo Error</p>
                        <p style="color:var(--text-light); margin-bottom:20px;">${e.message}</p>
                        <button class="btn btn-primary" onclick="demoLoaded=false; runDemo();">Retry</button>
                    </div>`;
            }
        }
    };

    function renderDemo(data) {
        const loading = $('demo-loading');
        const results = $('demo-results');
        if (loading) loading.style.display = 'none';
        if (results) results.style.display = '';

        // ---- Readiness Banner ----
        const r = data.filing_readiness || {};
        const banner = $('demo-readiness');
        if (banner) {
            const ready = r.ready_to_file;
            banner.className = 'cf-readiness-banner ' + (ready ? 'cf-ready-yes' : 'cf-ready-no');
            banner.innerHTML = `
                <div style="display:flex; align-items:center; gap:12px;">
                    <span style="font-size:2rem;">${ready ? '\u2705' : '\u26A0\uFE0F'}</span>
                    <div>
                        <p style="font-weight:700; font-size:1.1rem;">${ready ? 'Ready to File' : 'Not Ready to File'}</p>
                        <p style="font-size:0.85rem; opacity:0.9;">
                            ${r.clean_invoice_count || 0}/${r.total_invoice_count || 0} clean invoices (${r.clean_rate || 0}%)
                            ${r.blocking_issues && r.blocking_issues.length ? ' \u00b7 ' + r.blocking_issues.length + ' blocking issues' : ''}
                        </p>
                    </div>
                </div>`;
        }

        // ---- Data Summary Cards ----
        const ds = data.data_summary || {};
        const summaryCards = $('demo-summary-cards');
        if (summaryCards) {
            const items = [
                ['Total Invoices', ds.total_invoices, '#2563eb'],
                ['Clean', ds.clean_invoices, '#10b981'],
                ['Flags', ds.compliance_flags, '#f59e0b'],
                ['ITC Matches', ds.itc_matches, '#8b5cf6'],
                ['Blocking', ds.blocking_issues, '#ef4444'],
            ];
            summaryCards.innerHTML = items.map(([label, val, color]) => `
                <div class="card cf-stat-card" style="border-top:3px solid ${color};">
                    <p class="cf-stat-label">${label}</p>
                    <p class="cf-stat-value" style="color:${color};">${val}</p>
                </div>
            `).join('');
        }

        // ---- Top Actions (with trust) ----
        const topActions = (data.dashboard || {}).top_actions || [];
        const actionsEl = $('demo-top-actions');
        if (actionsEl) {
            actionsEl.innerHTML = topActions.map((a, i) => {
                const urgencyColors = { critical: '#ef4444', high: '#dc2626', medium: '#f59e0b', low: '#10b981' };
                const urgency = a.urgency || a.priority || 'medium';
                const trust = a.trust || {};
                return `
                    <div class="demo-action-card">
                        <div style="display:flex; align-items:center; gap:14px; margin-bottom:12px;">
                            <div class="cf-action-priority" style="background:${urgencyColors[urgency] || '#94a3b8'};">${i + 1}</div>
                            <div style="flex:1;">
                                <p style="font-weight:700;">${a.title || a.message || ''}</p>
                                <p style="font-size:0.85rem; color:var(--text-light);">${a.description || a.action_required || ''}</p>
                            </div>
                            ${a.amount ? `<span style="font-weight:700; color:var(--error); white-space:nowrap;">${fmt(a.amount)}</span>` : ''}
                        </div>
                        ${trust.explanation ? `
                        <div class="demo-trust-box">
                            <div class="demo-trust-row"><span class="demo-trust-label">Why:</span> ${trust.explanation}</div>
                            ${trust.calculation ? `<div class="demo-trust-row"><span class="demo-trust-label">Calc:</span> ${trust.calculation}</div>` : ''}
                            ${trust.source ? `<div class="demo-trust-row"><span class="demo-trust-label">Source:</span> ${trust.source}</div>` : ''}
                        </div>` : ''}
                    </div>`;
            }).join('');
        }

        // ---- Financial Summary ----
        const fin = (data.dashboard || {}).financials || {};
        const finEl = $('demo-financials');
        if (finEl) {
            const items = [
                ['Tax Liability', fin.total_tax_liability || fin.tax_liability, false],
                ['ITC Available', fin.itc_available || fin.total_itc, false],
                ['Net Payable', fin.net_payable, false],
                ['Penalties at Risk', fin.penalties_at_risk || fin.estimated_penalties, true],
            ];
            finEl.innerHTML = items.map(([label, val, danger]) => `
                <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f1f5f9;">
                    <span style="color:var(--text-light);">${label}</span>
                    <span style="font-weight:700; ${danger && val > 0 ? 'color:var(--error);' : ''}">${fmt(val)}</span>
                </div>
            `).join('');
        }

        // ---- Compliance Overview ----
        const comp = data.compliance || {};
        const compEl = $('demo-compliance-overview');
        if (compEl) {
            compEl.innerHTML = `
                <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f1f5f9;">
                    <span style="color:var(--text-light);">Compliance Score</span>
                    <span style="font-weight:700; color:${comp.score >= 80 ? 'var(--success)' : 'var(--error)'};">${comp.score || 0}%</span>
                </div>
                <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f1f5f9;">
                    <span style="color:var(--text-light);">Risk Level</span>
                    <span style="font-weight:700;">${((comp.risk_level || 'N/A') + '').charAt(0).toUpperCase() + (comp.risk_level || '').slice(1)}</span>
                </div>
                <div style="display:flex; justify-content:space-between; padding:10px 0;">
                    <span style="color:var(--text-light);">Est. Penalties</span>
                    <span style="font-weight:700; color:var(--error);">${fmt(comp.estimated_penalties)}</span>
                </div>`;
        }

        // ---- ITC Financials ----
        const itcFin = (data.itc_results || {}).financial_summary || {};
        const itcFinEl = $('demo-itc-financials');
        if (itcFinEl) {
            itcFinEl.innerHTML = [
                ['Available', itcFin.total_itc_available || itcFin.available, '#10b981'],
                ['At Risk', itcFin.total_itc_at_risk || itcFin.at_risk, '#ef4444'],
                ['Recoverable', itcFin.recoverable_itc || itcFin.recoverable, '#2563eb'],
            ].map(([l, v, c]) => `<span style="font-size:0.8rem;"><span style="color:var(--text-light);">${l}:</span> <strong style="color:${c};">${fmt(v)}</strong></span>`).join('');
        }

        // ---- ITC Matches (with trust) ----
        const matches = (data.itc_results || {}).matches || [];
        const matchesEl = $('demo-itc-matches');
        if (matchesEl) {
            const matchColors = {
                exact_match: '#10b981', partial_match: '#f59e0b',
                missing_in_2b: '#ef4444', missing_in_invoices: '#8b5cf6',
                duplicate_claim: '#dc2626',
            };
            const matchLabels = {
                exact_match: 'Exact Match', partial_match: 'Partial Mismatch',
                missing_in_2b: 'Missing in 2B', missing_in_invoices: 'Missing in Books',
                duplicate_claim: 'Duplicate Claim',
            };
            matchesEl.innerHTML = matches.map(m => {
                const mt = m.match_type || '';
                const trust = m.trust || {};
                return `
                    <div class="demo-itc-card" style="border-left:4px solid ${matchColors[mt] || '#94a3b8'};">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <div>
                                <span class="badge" style="background:${matchColors[mt] || '#94a3b8'}; color:white;">${matchLabels[mt] || mt}</span>
                                <span style="font-weight:700; margin-left:8px;">${m.invoice_number || 'N/A'}</span>
                            </div>
                            <span style="font-size:0.8rem; color:var(--text-light);">${m.vendor_gstin || ''}</span>
                        </div>
                        <div style="display:flex; gap:20px; font-size:0.85rem; margin-bottom:8px;">
                            <span>Eligible: <strong>${fmt(m.eligible_itc)}</strong></span>
                            <span>At Risk: <strong style="color:var(--error);">${fmt(m.itc_at_risk)}</strong></span>
                        </div>
                        ${trust.explanation ? `
                        <div class="demo-trust-box">
                            <div class="demo-trust-row"><span class="demo-trust-label">Why:</span> ${trust.explanation}</div>
                            ${trust.calculation ? `<div class="demo-trust-row"><span class="demo-trust-label">Calc:</span> ${trust.calculation}</div>` : ''}
                            ${trust.source ? `<div class="demo-trust-row"><span class="demo-trust-label">Source:</span> ${trust.source}</div>` : ''}
                        </div>` : ''}
                    </div>`;
            }).join('');
        }

        // ---- Compliance Flags (with trust) ----
        const flags = (data.compliance || {}).flags || [];
        const flagsEl = $('demo-flags');
        if (flagsEl) {
            const sevColors = { critical: '#991b1b', error: '#dc2626', warning: '#d97706', info: '#2563eb' };
            const sevBgs = { critical: '#fee2e2', error: '#fee2e2', warning: '#fef3c7', info: '#dbeafe' };
            flagsEl.innerHTML = flags.slice(0, 8).map(f => {
                const sev = (f.severity || 'info');
                const trust = f.trust || {};
                return `
                    <div class="cf-flag" style="border-left:4px solid ${sevColors[sev] || '#94a3b8'}; background:${sevBgs[sev] || '#f8fafc'};">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span class="badge" style="background:${sevColors[sev] || '#94a3b8'}; color:white;">${sev.toUpperCase()}</span>
                            <span style="font-size:0.75rem; color:var(--text-light);">${f.rule_id || ''}</span>
                        </div>
                        <p style="font-weight:600; margin-top:8px;">${f.message || ''}</p>
                        ${f.action_required ? `<p style="font-size:0.8rem; color:var(--text-light); margin-top:4px;">${f.action_required}</p>` : ''}
                        ${trust.explanation ? `
                        <div class="demo-trust-box" style="margin-top:8px;">
                            <div class="demo-trust-row"><span class="demo-trust-label">Why:</span> ${trust.explanation}</div>
                            ${trust.calculation ? `<div class="demo-trust-row"><span class="demo-trust-label">Calc:</span> ${trust.calculation}</div>` : ''}
                            ${trust.source ? `<div class="demo-trust-row"><span class="demo-trust-label">Source:</span> ${trust.source}</div>` : ''}
                        </div>` : ''}
                    </div>`;
            }).join('');
            if (flags.length > 8) {
                flagsEl.innerHTML += `<p style="color:var(--text-light); font-size:0.85rem; margin-top:12px;">...and ${flags.length - 8} more flags</p>`;
            }
        }

        // ---- Elapsed time ----
        const elapsed = $('demo-elapsed');
        if (elapsed) {
            elapsed.textContent = `Pipeline completed in ${data.elapsed_ms || 0}ms on ${data.invoices?.count || 5} invoices`;
        }

        if (window.feather) feather.replace();
    }
})();
