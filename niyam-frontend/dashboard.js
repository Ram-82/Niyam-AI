// ============================================================
// Niyam AI Dashboard - Main JavaScript
// ============================================================

// Initialize icons
feather.replace();

// Handle User Name from localStorage
const businessName = localStorage.getItem("niyam_user_business") || "MSME Owner";
const welcomeEl = document.getElementById("welcome-text");
if (welcomeEl) welcomeEl.innerText = `Good morning, ${businessName}`;

// Use CONFIG.API_URL from config.js
const API_URL = CONFIG.API_URL;

// ============================================================
// View Switching Logic
// ============================================================
function switchView(viewId, element) {
    const targetView = document.getElementById(`view-${viewId}`);
    if (!targetView) {
        console.warn(`View not found: view-${viewId}, falling back to dashboard`);
        if (viewId !== 'dashboard') return switchView('dashboard', element);
        return;
    }

    document.querySelectorAll(".sidebar-item").forEach(item => item.classList.remove("active"));
    if (element) element.classList.add("active");

    document.querySelectorAll(".content-view").forEach(view => view.classList.remove("active"));
    targetView.classList.add("active");

    window.scrollTo(0, 0);

    if (viewId === 'calendar') {
        setTimeout(() => { calendar.render(); }, 100);
    }
    if (viewId === 'reports') {
        setTimeout(() => { initCharts(); }, 100);
    }

    feather.replace();
}

// URL hash deep-linking: dashboard.html#gst opens GST view directly
window.addEventListener('DOMContentLoaded', () => {
    const hash = window.location.hash.replace('#', '');
    if (hash) switchView(hash);
});

// ============================================================
// Calendar Initialization
// ============================================================
let calendar;
document.addEventListener('DOMContentLoaded', function () {
    var calendarEl = document.getElementById('calendar');
    calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,listMonth'
        },
        events: (function() {
            // Generate statutory deadlines dynamically based on current month
            const now = new Date();
            const y = now.getFullYear();
            const m = now.getMonth(); // 0-indexed
            const pad = n => String(n).padStart(2, '0');
            const dt = (mo, d) => `${y}-${pad(mo)}-${pad(d)}`;

            // Current month deadlines
            const cm = m + 1; // 1-indexed
            const nm = m + 2 > 12 ? 1 : m + 2; // next month
            const ny = nm === 1 ? y + 1 : y;

            return [
                { title: 'TDS Payment', start: dt(cm, 7), color: '#10b981', extendedProps: { description: 'Monthly TDS deposit (Section 194)' } },
                { title: 'GSTR-1 Filing', start: dt(cm, 11), color: '#2563eb', extendedProps: { description: 'Monthly GSTR-1 return for sales' } },
                { title: 'GSTR-3B Filing', start: dt(cm, 20), color: '#2563eb', extendedProps: { description: 'Summary return + GST payment' } },
                // Next month
                { title: 'TDS Payment', start: `${ny}-${pad(nm)}-07`, color: '#10b981', extendedProps: { description: 'Monthly TDS deposit (Section 194)' } },
                { title: 'GSTR-1 Filing', start: `${ny}-${pad(nm)}-11`, color: '#2563eb', extendedProps: { description: 'Monthly GSTR-1 return for sales' } },
                { title: 'GSTR-3B Filing', start: `${ny}-${pad(nm)}-20`, color: '#2563eb', extendedProps: { description: 'Summary return + GST payment' } },
            ];
        })(),
        eventClick: function (info) {
            showEventDetails(info.event.title, info.event.startStr, info.event.extendedProps.description);
        }
    });
});

function showEventDetails(title, date, description) {
    description = description || 'Compliance filing requirement.';
    const modal = document.getElementById('modal');
    document.getElementById('modal-title').innerText = title;
    document.getElementById('modal-body').innerText = `${description}\n\nDue Date: ${date}`;
    modal.style.display = 'flex';
}

function openAddDeadlineModal() {
    showToast('Add Deadline form coming soon in full version!');
}

// ============================================================
// File Upload — Single-call /api/process-invoice pipeline
// ============================================================
async function handleFileUpload(input) {
    if (!input.files || !input.files[0]) return;

    const file = input.files[0];
    const progress = document.getElementById("upload-progress");
    const bar = document.getElementById("progress-bar-inner");
    const percent = document.getElementById("progress-percent");
    const results = document.getElementById("ocr-results");

    // Show progress
    progress.style.display = "block";
    results.style.display = "none";
    bar.style.width = "10%";
    percent.textContent = "10% — Uploading...";

    // Timeout for Render free tier cold starts
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);

    try {
        bar.style.width = "30%";
        percent.textContent = "30% — Processing with AI...";

        // Single call: upload + OCR + parse + validate
        const formData = new FormData();
        formData.append('file', file);

        const response = await NiyamAuth.niyamFetch(`${API_URL}/process-invoice`, {
            method: 'POST',
            body: formData,
            signal: controller.signal,
        });

        clearTimeout(timeoutId);
        bar.style.width = "80%";
        percent.textContent = "80% — Reading response...";

        // Safe JSON parsing (backend may return non-JSON on 502/503)
        const responseText = await response.text();
        let data;
        try {
            data = JSON.parse(responseText);
        } catch (parseErr) {
            console.error('Invalid JSON response:', responseText.substring(0, 200));
            throw new Error(
                response.status === 502 ? 'Server is starting up — please retry in 30 seconds' :
                response.status === 503 ? 'Server temporarily unavailable — please retry' :
                `Server returned invalid response (HTTP ${response.status})`
            );
        }

        if (!response.ok) {
            throw new Error(data.error || data.detail || data.reason || `Processing failed (HTTP ${response.status})`);
        }

        bar.style.width = "100%";
        percent.textContent = "100%";

        setTimeout(() => {
            progress.style.display = "none";
            if (data.status === "success") {
                window._lastInvoiceResult = data;
                displayInvoiceResults(data);
                results.style.display = "block";
                if (data.saved) {
                    showToast("Invoice processed and saved!");
                } else {
                    showToast("Invoice processed successfully!");
                }
            } else if (data.status === "failed") {
                showToast(data.reason === "OCR_FAILED"
                    ? "Could not read the document. Try a clearer image or digital PDF."
                    : `Processing failed: ${data.reason || 'Unknown error'}`);
            } else {
                displayInvoiceResults(data);
                results.style.display = "block";
            }
        }, 400);

    } catch (error) {
        clearTimeout(timeoutId);
        console.error('Invoice processing error:', error);
        progress.style.display = "none";
        if (error.name === 'AbortError') {
            showToast('Request timed out — server may be cold-starting. Please retry in 30 seconds.');
        } else {
            showToast(`Error: ${error.message}`);
        }
    }
}

// Format currency for display
function _fmtINR(val) {
    const num = Number(val);
    if (isNaN(num) || num === 0) return '₹0.00';
    return '₹' + num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function displayInvoiceResults(data) {
    const resultsContainer = document.getElementById("ocr-results");
    if (!resultsContainer) return;

    const vendor = escapeHtml(data.vendor_name || 'Not detected');
    const gstin = escapeHtml(data.vendor_gstin || 'Not detected');
    const invoiceNum = escapeHtml(data.invoice_number || 'Not detected');
    const invoiceDate = escapeHtml(data.invoice_date || 'Not detected');
    const total = data.total_amount ? _fmtINR(data.total_amount) : 'Not detected';
    const taxable = data.taxable_value ? _fmtINR(data.taxable_value) : 'Not detected';
    const gst = data.gst_breakdown || {};
    const rawConf = data.confidence_score || 0;
    const confidence = Math.round(rawConf * 100);
    const confColor = confidence >= 70 ? 'var(--success)' : confidence >= 40 ? '#f59e0b' : 'var(--error)';
    const ocrMeta = data.ocr_metadata || {};
    const compliance = data.compliance || {};
    const compIssues = compliance.issues || [];
    const itc = compliance.itc_eligibility || {};

    // Compliance badge
    let compBadge = '';
    if (compliance.is_valid === true) {
        compBadge = '<span style="background:#dcfce7;color:#166534;padding:3px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;">GST COMPLIANT</span>';
    } else if (compliance.is_valid === false) {
        compBadge = '<span style="background:#fee2e2;color:#991b1b;padding:3px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;">' + compIssues.length + ' ISSUE(S)</span>';
    }

    // Issues HTML
    let issuesHtml = '';
    if (compIssues.length > 0) {
        issuesHtml = '<div style="margin-top:15px;border-top:1px solid #e2e8f0;padding-top:15px;">' +
            '<p style="font-size:0.85rem;font-weight:600;margin-bottom:8px;">Compliance Issues</p>' +
            compIssues.map(issue => {
                const sevColor = issue.severity === 'high' ? '#ef4444' : issue.severity === 'medium' ? '#f59e0b' : '#6b7280';
                return '<div style="padding:8px 10px;margin-bottom:6px;background:#f8fafc;border-radius:6px;border-left:3px solid ' + sevColor + ';">' +
                    '<p style="font-size:0.8rem;font-weight:600;color:' + sevColor + ';">' + escapeHtml((issue.type || '').replace(/_/g, ' ')) + '</p>' +
                    '<p style="font-size:0.78rem;color:var(--text-light);">' + escapeHtml(issue.message || '') + '</p>' +
                    (issue.impact ? '<p style="font-size:0.75rem;color:#64748b;margin-top:4px;">' + escapeHtml(issue.impact) + '</p>' : '') +
                    '</div>';
            }).join('') +
            '</div>';
    }

    // Line items
    let lineItemsHtml = '';
    const items = data.line_items || [];
    if (items.length > 0) {
        lineItemsHtml = '<div style="margin-top:15px;border-top:1px solid #e2e8f0;padding-top:15px;">' +
            '<p style="font-size:0.85rem;font-weight:600;margin-bottom:8px;">Line Items (' + items.length + ')</p>' +
            '<table style="width:100%;font-size:0.8rem;border-collapse:collapse;">' +
            '<thead><tr style="text-align:left;color:var(--text-light);border-bottom:1px solid #e2e8f0;">' +
            '<th style="padding:6px;">Description</th><th style="padding:6px;">Qty</th><th style="padding:6px;">Rate</th><th style="padding:6px;">Amount</th></tr></thead><tbody>' +
            items.slice(0, 20).map(item =>
                '<tr style="border-bottom:1px solid #f1f5f9;">' +
                '<td style="padding:6px;">' + escapeHtml(item.description || '-') + '</td>' +
                '<td style="padding:6px;">' + escapeHtml(item.quantity || '-') + '</td>' +
                '<td style="padding:6px;">' + (item.rate ? _fmtINR(item.rate) : '-') + '</td>' +
                '<td style="padding:6px;">' + (item.amount ? _fmtINR(item.amount) : '-') + '</td></tr>'
            ).join('') +
            '</tbody></table></div>';
    }

    // ITC eligibility
    let itcHtml = '';
    if (itc.eligible !== undefined) {
        const itcColor = itc.eligible ? '#166534' : '#991b1b';
        const itcBg = itc.eligible ? '#dcfce7' : '#fee2e2';
        itcHtml = '<div style="margin-top:15px;padding:10px;background:' + itcBg + ';border-radius:8px;">' +
            '<p style="font-size:0.85rem;font-weight:600;color:' + itcColor + ';">ITC ' + (itc.eligible ? 'Eligible' : 'At Risk') + ': ' + _fmtINR(itc.eligible ? itc.itc_amount : (itc.itc_at_risk || 0)) + '</p>' +
            (itc.reasons || []).map(r => '<p style="font-size:0.75rem;color:#64748b;">- ' + escapeHtml(r) + '</p>').join('') +
            '</div>';
    }

    resultsContainer.innerHTML = `
        <h3 style="margin-bottom: 15px;">Extracted Invoice Data</h3>
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <div>
                    <span style="font-size: 0.85rem; color: var(--text-light);">Confidence</span>
                    <span style="font-weight: 700; color: ${confColor}; margin-left: 8px;">${confidence}%</span>
                </div>
                <div style="display:flex;gap:8px;align-items:center;">
                    ${compBadge}
                    <span style="font-size:0.7rem;color:var(--text-light);">${ocrMeta.method || 'auto'}</span>
                    <button class="btn btn-outline" style="padding:4px 12px;font-size:0.75rem;" onclick="toggleInvoiceEdit()" id="edit-toggle-btn">Edit Fields</button>
                </div>
            </div>
            <div id="invoice-fields-display" style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                <div><p style="font-size:0.78rem;color:var(--text-light);">Invoice Number</p><p style="font-weight:600;">${invoiceNum}</p></div>
                <div><p style="font-size:0.78rem;color:var(--text-light);">Invoice Date</p><p style="font-weight:600;">${invoiceDate}</p></div>
                <div><p style="font-size:0.78rem;color:var(--text-light);">Vendor</p><p style="font-weight:600;">${vendor}</p></div>
                <div><p style="font-size:0.78rem;color:var(--text-light);">GSTIN</p><p style="font-weight:600;">${gstin}</p></div>
                <div><p style="font-size:0.78rem;color:var(--text-light);">Taxable Value</p><p style="font-weight:600;">${taxable}</p></div>
                <div><p style="font-size:0.78rem;color:var(--text-light);">Total Amount</p><p style="font-weight:600;font-size:1.1rem;">${total}</p></div>
                <div><p style="font-size:0.78rem;color:var(--text-light);">CGST / SGST</p><p style="font-weight:600;">${_fmtINR(gst.cgst||0)} / ${_fmtINR(gst.sgst||0)}</p></div>
                <div><p style="font-size:0.78rem;color:var(--text-light);">IGST</p><p style="font-weight:600;">${_fmtINR(gst.igst||0)}</p></div>
            </div>
            <div id="invoice-fields-edit" style="display:none;">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:0.75rem;color:var(--text-light);">Invoice Number</label>
                        <input type="text" id="edit-invoice-number" value="${escapeHtml(data.invoice_number || '')}" style="font-size:0.85rem;padding:6px 10px;">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:0.75rem;color:var(--text-light);">Invoice Date</label>
                        <input type="text" id="edit-invoice-date" value="${escapeHtml(data.invoice_date || '')}" placeholder="YYYY-MM-DD" style="font-size:0.85rem;padding:6px 10px;">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:0.75rem;color:var(--text-light);">Vendor Name</label>
                        <input type="text" id="edit-vendor-name" value="${escapeHtml(data.vendor_name || '')}" style="font-size:0.85rem;padding:6px 10px;">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:0.75rem;color:var(--text-light);">Vendor GSTIN</label>
                        <input type="text" id="edit-vendor-gstin" value="${escapeHtml(data.vendor_gstin || '')}" maxlength="15" style="font-size:0.85rem;padding:6px 10px;text-transform:uppercase;">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:0.75rem;color:var(--text-light);">Taxable Value (₹)</label>
                        <input type="number" id="edit-taxable-value" value="${data.taxable_value || 0}" step="0.01" style="font-size:0.85rem;padding:6px 10px;">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:0.75rem;color:var(--text-light);">Total Amount (₹)</label>
                        <input type="number" id="edit-total-amount" value="${data.total_amount || 0}" step="0.01" style="font-size:0.85rem;padding:6px 10px;">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:0.75rem;color:var(--text-light);">CGST (₹)</label>
                        <input type="number" id="edit-cgst" value="${gst.cgst || 0}" step="0.01" style="font-size:0.85rem;padding:6px 10px;">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:0.75rem;color:var(--text-light);">SGST (₹)</label>
                        <input type="number" id="edit-sgst" value="${gst.sgst || 0}" step="0.01" style="font-size:0.85rem;padding:6px 10px;">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="font-size:0.75rem;color:var(--text-light);">IGST (₹)</label>
                        <input type="number" id="edit-igst" value="${gst.igst || 0}" step="0.01" style="font-size:0.85rem;padding:6px 10px;">
                    </div>
                </div>
                <p style="font-size:0.7rem;color:var(--text-light);margin-top:8px;">Edit the fields above and click "Save Corrections" to update the invoice.</p>
            </div>
            ${itcHtml}
            ${lineItemsHtml}
            ${issuesHtml}
            <div style="margin-top: 20px; text-align: right; display:flex; gap:8px; justify-content:flex-end;">
                <button class="btn btn-outline" style="padding: 8px 16px; font-size: 0.8rem;"
                    onclick="document.getElementById('file-upload-input').click()">Upload Another</button>
                <button class="btn btn-primary" style="padding: 8px 16px; font-size: 0.8rem;"
                    id="invoice-save-btn" onclick="confirmInvoiceSave()">Confirm & Save</button>
            </div>
        </div>
    `;
}

function toggleInvoiceEdit() {
    const display = document.getElementById('invoice-fields-display');
    const edit = document.getElementById('invoice-fields-edit');
    const toggleBtn = document.getElementById('edit-toggle-btn');
    const saveBtn = document.getElementById('invoice-save-btn');
    if (!display || !edit) return;

    const isEditing = edit.style.display !== 'none';
    if (isEditing) {
        // Switch back to view mode
        edit.style.display = 'none';
        display.style.display = 'grid';
        if (toggleBtn) toggleBtn.textContent = 'Edit Fields';
        if (saveBtn) saveBtn.textContent = 'Confirm & Save';
    } else {
        // Switch to edit mode
        display.style.display = 'none';
        edit.style.display = 'block';
        if (toggleBtn) toggleBtn.textContent = 'Cancel Edit';
        if (saveBtn) saveBtn.textContent = 'Save Corrections';
    }
}

async function confirmInvoiceSave() {
    const lastResult = window._lastInvoiceResult;
    if (!lastResult) {
        showToast('No invoice to save. Process an invoice first.');
        return;
    }
    if (!NiyamAuth.isAuthenticated()) {
        showToast('Please login to save invoices to your compliance register.');
        return;
    }

    const editPanel = document.getElementById('invoice-fields-edit');
    const isEditing = editPanel && editPanel.style.display !== 'none';

    // If editing and invoice was already saved, PATCH the corrections
    if (isEditing && lastResult.saved && lastResult.invoice_id) {
        const corrections = {
            invoice_number: document.getElementById('edit-invoice-number').value.trim(),
            invoice_date: document.getElementById('edit-invoice-date').value.trim(),
            vendor_name: document.getElementById('edit-vendor-name').value.trim(),
            vendor_gstin: document.getElementById('edit-vendor-gstin').value.toUpperCase().trim(),
            taxable_value: parseFloat(document.getElementById('edit-taxable-value').value) || 0,
            total_amount: parseFloat(document.getElementById('edit-total-amount').value) || 0,
            cgst: parseFloat(document.getElementById('edit-cgst').value) || 0,
            sgst: parseFloat(document.getElementById('edit-sgst').value) || 0,
            igst: parseFloat(document.getElementById('edit-igst').value) || 0,
            needs_review: false,
        };

        const saveBtn = document.getElementById('invoice-save-btn');
        if (saveBtn) { saveBtn.textContent = 'Saving...'; saveBtn.disabled = true; }

        try {
            const response = await NiyamAuth.niyamFetch(`${API_URL}/invoices/${lastResult.invoice_id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(corrections),
            });
            const result = await response.json();
            if (result.success) {
                showToast('Invoice corrections saved successfully!');
                // Update local cache
                Object.assign(lastResult, corrections);
                lastResult.gst_breakdown = { cgst: corrections.cgst, sgst: corrections.sgst, igst: corrections.igst };
                // Switch back to view mode and re-render
                displayInvoiceResults(lastResult);
                fetchDashboardData();
            } else {
                showToast(result.detail || 'Failed to save corrections');
            }
        } catch (error) {
            showToast('Error saving: ' + error.message);
        } finally {
            if (saveBtn) { saveBtn.textContent = 'Save Corrections'; saveBtn.disabled = false; }
        }
        return;
    }

    // Not editing — just confirm the auto-saved invoice
    if (lastResult.saved) {
        showToast('Invoice saved (ID: ' + (lastResult.invoice_id || 'unknown').slice(0, 8) + ')');
        fetchDashboardData();
        return;
    }

    showToast('Invoice was processed but could not be saved. Try uploading again while logged in.');
}

// ============================================================
// Chat Widget Logic
// ============================================================
const chatToggle = document.getElementById("chat-toggle");
const chatBox = document.getElementById("chat-box");
const chatClose = document.getElementById("chat-close");
if (chatToggle) chatToggle.onclick = () => chatBox.style.display = chatBox.style.display === "none" ? "flex" : "none";
if (chatClose) chatClose.onclick = () => chatBox.style.display = "none";

const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatMessages = document.getElementById("chat-messages");

if (chatForm) {
    chatForm.onsubmit = (e) => {
        e.preventDefault();
        const text = chatInput.value.trim().toLowerCase();
        if (!text) return;

        addChatMessage(chatInput.value, "user");
        chatInput.value = "";

        setTimeout(() => {
            let response = "I'm Niyam AI assistant. I can help with GST, TDS, ROC, or general compliance questions. What area are you inquiring about?";

            const intentMap = {
                "gst": "To see your GST data, upload invoices on the Dashboard tab. I can help with GSTR-1 (due 11th monthly), GSTR-3B (due 20th monthly), and ITC reconciliation via the GST/ITC tab.",
                "tds": "TDS payments are due by the 7th of each month. Quarterly returns (24Q/26Q) are due 31st of Jul, Oct, Jan, May. Use the TDS section for deadline tracking.",
                "roc": "ROC filings include AOC-4 (due Oct 30), MGT-7 (due Nov 29), and DIR-3-KYC (due Sep 30). Check the Calendar for your deadlines.",
                "bank": "Bank statement import is coming soon. For now, you can upload invoices to track your compliance.",
                "deadline": "Check the Calendar tab for all upcoming deadlines. Key monthly dates: TDS (7th), GSTR-1 (11th), GSTR-3B (20th).",
                "support": "For professional help, consult a Chartered Accountant. Niyam AI helps organize your data for faster CA reviews.",
                "help": "I can help with: uploading invoices, GST compliance checks, ITC reconciliation (GST/ITC tab), and deadline tracking (Calendar tab)."
            };

            for (const [key, value] of Object.entries(intentMap)) {
                if (text.includes(key)) {
                    response = value;
                    break;
                }
            }
            addChatMessage(response, "bot");
        }, 600);
    };
}

function addChatMessage(text, sender) {
    const msg = document.createElement("div");
    msg.className = `message message-${sender}`;
    msg.textContent = text;
    chatMessages.appendChild(msg);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ============================================================
// Table Filtering & Metrics
// ============================================================
function filterTable(status) {
    const rows = document.querySelectorAll("#deadlines-table tbody tr");
    rows.forEach(row => {
        row.style.display = (status === "all" || row.dataset.status === status) ? "" : "none";
    });
    showToast(`Filtering for ${status} items...`);
}

function showHealthBreakdown() { showToast("Upload invoices to see your compliance health breakdown."); }

// ============================================================
// Toast Notifications
// ============================================================
function showToast(message) {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        document.body.appendChild(container);
    }
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(-20px)";
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ============================================================
// Modal Logic
// ============================================================
document.body.addEventListener("click", (e) => {
    if (e.target.classList.contains("btn-action")) {
        const modal = document.getElementById("modal");
        if (modal) modal.style.display = "flex";
    }
});
const modalClose = document.getElementById("modal-close");
if (modalClose) modalClose.onclick = () => document.getElementById("modal").style.display = "none";

window.onclick = (e) => {
    const modal = document.getElementById("modal");
    if (e.target == modal) modal.style.display = "none";
};

// ============================================================
// TDS Interest Calculator
// ============================================================
function calculateTDSInterest() {
    const amount = parseFloat(document.getElementById('calc-amount').value);
    const months = parseFloat(document.getElementById('calc-months').value);
    const resultDiv = document.getElementById('calc-result');
    const valueEl = document.getElementById('calc-interest-value');

    if (isNaN(amount) || isNaN(months) || amount <= 0 || months <= 0) {
        showToast("Please enter valid positive numbers.");
        return;
    }

    const interest = amount * 0.015 * months;
    valueEl.innerText = `₹${interest.toLocaleString('en-IN')}`;
    resultDiv.style.display = 'block';
    showToast("Interest calculated successfully!");
}

// ============================================================
// Penalty Calculator
// ============================================================
function calculatePenalty() {
    const days = parseInt(document.getElementById('penalty-days').value);
    const rate = parseInt(document.getElementById('penalty-type').value);
    const resultDiv = document.getElementById('penalty-result');
    const valueEl = document.getElementById('penalty-value');

    if (isNaN(days) || days < 0) {
        showToast("Please enter a valid number of days.");
        return;
    }

    const penalty = days * rate;
    valueEl.innerText = `₹${penalty.toLocaleString('en-IN')}`;
    resultDiv.style.display = 'block';
    showToast("Penalty estimate updated.");
}

// ============================================================
// Settings Tabs
// ============================================================
function switchSettingsTab(tabId, element) {
    document.querySelectorAll('.settings-tab-btn').forEach(btn => btn.classList.remove('active'));
    element.classList.add('active');

    document.querySelectorAll('.settings-section').forEach(sec => sec.classList.remove('active'));
    document.getElementById(`settings-${tabId}`).classList.add('active');

    if (tabId === 'billing') {
        renderInvoices();
    }

    feather.replace();
}

// ============================================================
// Subscription Module
// ============================================================
function switchPlanTab(tabId, element) {
    document.querySelectorAll('.plan-tab-btn').forEach(btn => btn.classList.remove('active'));
    element.classList.add('active');

    document.getElementById('tab-msme').style.display = tabId === 'msme' ? 'block' : 'none';
    document.getElementById('tab-ca').style.display = tabId === 'ca' ? 'block' : 'none';
}

function selectPlan(planName) {
    const effectiveDate = new Date();
    effectiveDate.setDate(effectiveDate.getDate() + 1);
    showToast(`Switching to: ${planName}. Effective: ${effectiveDate.toLocaleDateString()}`);
}

function toggleAddon(name, price) {
    showToast(`${name} add-on updated! Monthly bill adjusted by ₹${price}.`);
}

const invoices = [
    { date: "2025-09-15", desc: "Monthly Subscription", amount: "₹2,999", status: "Paid", id: "INV-2025-09-001" },
    { date: "2025-08-15", desc: "Monthly Subscription", amount: "₹2,999", status: "Paid", id: "INV-2025-08-001" },
    { date: "2025-07-15", desc: "Monthly Subscription + CA Add-on", amount: "₹3,998", status: "Paid", id: "INV-2025-07-001" },
    { date: "2025-06-15", desc: "Monthly Subscription", amount: "₹2,999", status: "Paid", id: "INV-2025-06-001" },
    { date: "2025-05-15", desc: "Monthly Subscription", amount: "₹2,999", status: "Paid", id: "INV-2025-05-001" }
];

function renderInvoices() {
    const container = document.getElementById('invoice-history-body');
    if (!container) return;

    container.innerHTML = invoices.map(inv => `
        <tr>
            <td>${escapeHtml(inv.date)}</td>
            <td>${escapeHtml(inv.desc)}</td>
            <td>${escapeHtml(inv.amount)}</td>
            <td><span class="badge" style="background: var(--success); color: white;">${escapeHtml(inv.status)}</span></td>
            <td><button class="btn btn-outline" style="font-size: 0.7rem; padding: 4px 8px;" onclick="showToast('Downloading ${escapeHtml(inv.id)}...')">PDF</button></td>
        </tr>
    `).join('');
}

function searchSupport(query) {
    query = query.toLowerCase();
    const items = document.querySelectorAll('.faq-item');
    items.forEach(item => {
        const text = item.innerText.toLowerCase();
        item.style.display = text.includes(query) ? 'block' : 'none';
    });
}

// ============================================================
// Reports & Analytics Charts
// ============================================================
// NOTE: Chart data below is SAMPLE/PLACEHOLDER data for UI demonstration.
// Real data will populate from processed invoices once the reporting API is wired.
// TODO: Replace with fetch from /api/analytics/trends once backend endpoint exists.
let currentChartData = {
    '6M': {
        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
        taxLiability: [0, 0, 0, 0, 0, 0],
        cashFlow: [0, 0, 0, 0, 0, 0],
        itcAvailable: [0, 0, 0, 0, 0, 0],
        _isSampleData: true
    },
    '1Y': {
        labels: ['Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
        taxLiability: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        cashFlow: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        itcAvailable: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        _isSampleData: true
    },
    'QTD': {
        labels: ['Apr', 'May', 'Jun'],
        taxLiability: [0, 0, 0],
        cashFlow: [0, 0, 0],
        itcAvailable: [0, 0, 0],
        _isSampleData: true
    }
};

function initCharts() {
    const lCtx = document.getElementById('liabilityChart');
    const cCtx = document.getElementById('cashflowChart');
    if (!lCtx || !cCtx) return;

    if (window.lChart) window.lChart.destroy();

    const data = currentChartData['6M'];
    window.lChart = new Chart(lCtx.getContext('2d'), {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: 'Tax Liability',
                    data: data.taxLiability,
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37, 99, 235, 0.1)',
                    fill: true, tension: 0.4, borderWidth: 3,
                    pointRadius: 2, pointHoverRadius: 6, yAxisID: 'y'
                },
                {
                    label: 'Cash Flow',
                    data: data.cashFlow,
                    borderColor: '#10b981',
                    borderWidth: 2, fill: false, tension: 0.4,
                    pointRadius: 2, pointHoverRadius: 6, yAxisID: 'y1'
                },
                {
                    label: 'ITC Available',
                    data: data.itcAvailable,
                    borderColor: '#8b5cf6',
                    borderDash: [5, 5], borderWidth: 2, fill: false, tension: 0.4,
                    pointRadius: 2, pointHoverRadius: 6, yAxisID: 'y'
                }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, position: 'bottom', labels: { usePointStyle: true, boxWidth: 6, font: { size: 11 } } },
                tooltip: {
                    backgroundColor: '#1e293b', titleFont: { size: 14, weight: 'bold' }, bodyFont: { size: 12 }, padding: 12,
                    callbacks: {
                        label: function (context) {
                            let label = context.dataset.label || '';
                            if (label) label += ': ';
                            if (context.parsed.y !== null) {
                                label += new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(context.parsed.y);
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                y: { type: 'linear', display: true, position: 'left', suggestedMax: 100000, ticks: { font: { size: 10 }, callback: value => '₹' + (value / 1000) + 'k' }, grid: { color: '#e2e8f0', drawBorder: false } },
                y1: { type: 'linear', display: false, position: 'right', grid: { drawOnChartArea: false } },
                x: { ticks: { font: { size: 10 } }, grid: { display: false } }
            }
        }
    });

    updateDataTable('6M');

    // Compliance Impact Chart
    if (window.cChart) window.cChart.destroy();
    if (!cCtx) return;

    const ctx = cCtx.getContext('2d');
    if (!ctx) return;

    const cashFlowGradient = ctx.createLinearGradient(0, 0, 0, 400);
    cashFlowGradient.addColorStop(0, 'rgba(16, 185, 129, 0.3)');
    cashFlowGradient.addColorStop(1, 'rgba(16, 185, 129, 0.05)');

    // Compliance chart — zeroed out until real analytics API is wired
    // TODO: Replace with fetch from /api/analytics/compliance-trends
    window.complianceChartData = {
        '6M': {
            labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
            cashFlow: [0, 0, 0, 0, 0, 0],
            complianceCosts: [0, 0, 0, 0, 0, 0],
            impactScore: [0, 0, 0, 0, 0, 0]
        },
        '1Y': {
            labels: ['Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
            cashFlow: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            complianceCosts: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            impactScore: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        },
        'YTD': {
            labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
            cashFlow: [0, 0, 0, 0, 0, 0],
            complianceCosts: [0, 0, 0, 0, 0, 0],
            impactScore: [0, 0, 0, 0, 0, 0]
        }
    };

    const initialData = window.complianceChartData['6M'];

    window.cChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: initialData.labels,
            datasets: [
                {
                    label: 'Cash Flow', data: initialData.cashFlow,
                    borderColor: '#10b981', backgroundColor: cashFlowGradient,
                    fill: true, tension: 0.4, borderWidth: 3,
                    pointRadius: 4, pointHoverRadius: 7,
                    pointBackgroundColor: '#10b981', pointBorderColor: '#fff', pointBorderWidth: 2, yAxisID: 'y'
                },
                {
                    label: 'Compliance Costs', data: initialData.complianceCosts,
                    borderColor: '#ef4444', backgroundColor: 'transparent',
                    fill: false, tension: 0.4, borderWidth: 2,
                    pointRadius: 4, pointHoverRadius: 7,
                    pointBackgroundColor: '#ef4444', pointBorderColor: '#fff', pointBorderWidth: 2, yAxisID: 'y'
                },
                {
                    label: 'Impact Score', data: initialData.impactScore,
                    borderColor: '#8b5cf6', backgroundColor: 'transparent',
                    fill: false, tension: 0.4, borderWidth: 2, borderDash: [5, 5],
                    pointRadius: 4, pointHoverRadius: 7,
                    pointBackgroundColor: '#8b5cf6', pointBorderColor: '#fff', pointBorderWidth: 2, yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true, position: 'top', align: 'end',
                    labels: { usePointStyle: true, boxWidth: 8, font: { size: 11, weight: '600', family: 'Inter, system-ui, sans-serif' }, color: '#64748b', padding: 15 },
                    onClick: function (e, legendItem, legend) {
                        const index = legendItem.datasetIndex;
                        const ci = legend.chart;
                        const meta = ci.getDatasetMeta(index);
                        meta.hidden = meta.hidden === null ? !ci.data.datasets[index].hidden : null;
                        ci.update();
                    }
                },
                tooltip: {
                    backgroundColor: '#1e293b',
                    titleFont: { size: 13, weight: 'bold', family: 'Inter, system-ui, sans-serif' },
                    bodyFont: { size: 12, family: 'Inter, system-ui, sans-serif' },
                    padding: 14, cornerRadius: 8, displayColors: true, boxWidth: 8, boxHeight: 8, usePointStyle: true,
                    callbacks: {
                        title: function (tooltipItems) { return tooltipItems[0].label; },
                        label: function (context) {
                            let label = context.dataset.label || '';
                            if (label) label += ': ';
                            if (context.datasetIndex === 2) {
                                label += context.parsed.y + '/100';
                            } else {
                                label += new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(context.parsed.y);
                            }
                            return label;
                        },
                        afterBody: function (tooltipItems) {
                            const dataIndex = tooltipItems[0].dataIndex;
                            const cashFlow = window.cChart.data.datasets[0].data[dataIndex];
                            const complianceCost = window.cChart.data.datasets[1].data[dataIndex];
                            const percentage = ((complianceCost / cashFlow) * 100).toFixed(1);
                            return '\nCompliance: ' + percentage + '% of cash flow';
                        }
                    }
                }
            },
            scales: {
                y: {
                    type: 'linear', display: true, position: 'left', beginAtZero: false,
                    grid: { color: '#f1f5f9', drawBorder: false },
                    ticks: { font: { size: 10, family: 'Inter, system-ui, sans-serif' }, color: '#94a3b8', callback: value => '₹' + (value / 1000) + 'k' },
                    title: { display: true, text: 'Amount (₹)', font: { size: 11, weight: '600', family: 'Inter, system-ui, sans-serif' }, color: '#64748b' }
                },
                y1: {
                    type: 'linear', display: true, position: 'right', min: 0, max: 100,
                    grid: { drawOnChartArea: false, drawBorder: false },
                    ticks: { font: { size: 10, family: 'Inter, system-ui, sans-serif' }, color: '#8b5cf6', callback: value => value },
                    title: { display: true, text: 'Impact Score', font: { size: 11, weight: '600', family: 'Inter, system-ui, sans-serif' }, color: '#8b5cf6' }
                },
                x: {
                    grid: { display: false, drawBorder: false },
                    ticks: { font: { size: 11, weight: '500', family: 'Inter, system-ui, sans-serif' }, color: '#64748b' }
                }
            },
            animation: { duration: 750, easing: 'easeInOutQuart' }
        }
    });

    updateComplianceMetrics('6M');
}

function updateChartPeriod(period, btn) {
    document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const data = currentChartData[period];
    if (!data || !window.lChart) return;

    window.lChart.data.labels = data.labels;
    window.lChart.data.datasets[0].data = data.taxLiability;
    window.lChart.data.datasets[1].data = data.cashFlow;
    window.lChart.data.datasets[2].data = data.itcAvailable;
    window.lChart.update();
    updateDataTable(period);
    showToast(`Showing ${period} trend.`);
}

function exportChart(chartId) {
    const canvas = document.getElementById(chartId);
    if (!canvas) return;
    const link = document.createElement('a');
    link.download = `NiyamAI-Report-${new Date().toISOString().split('T')[0]}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
    showToast("Report exported as PNG.");
}

function toggleDataTable() {
    const container = document.getElementById('data-table-container');
    const link = event.target;
    if (container.style.display === 'none') {
        container.style.display = 'block';
        link.innerText = 'Hide Data Table';
    } else {
        container.style.display = 'none';
        link.innerText = 'Show Data Table';
    }
}

function updateDataTable(period) {
    const body = document.getElementById('chart-data-body');
    const data = currentChartData[period];
    if (!body || !data) return;

    body.innerHTML = data.labels.map((label, i) => `
        <tr>
            <td style="padding: 6px; border: 1px solid #e2e8f0;">${label}</td>
            <td style="padding: 6px; border: 1px solid #e2e8f0;">₹${data.taxLiability[i].toLocaleString()}</td>
            <td style="padding: 6px; border: 1px solid #e2e8f0;">₹${data.cashFlow[i].toLocaleString()}</td>
            <td style="padding: 6px; border: 1px solid #e2e8f0;">₹${data.itcAvailable[i].toLocaleString()}</td>
        </tr>
    `).join('');
}

function updateComplianceChartPeriod(period, btn) {
    document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const data = window.complianceChartData[period];
    if (!data || !window.cChart) return;

    window.cChart.data.labels = data.labels;
    window.cChart.data.datasets[0].data = data.cashFlow;
    window.cChart.data.datasets[1].data = data.complianceCosts;
    window.cChart.data.datasets[2].data = data.impactScore;
    window.cChart.update();
    updateComplianceMetrics(period);
    showToast(`Showing ${period} compliance data.`);
}

function updateComplianceMetrics(period) {
    const data = window.complianceChartData[period];
    if (!data) return;

    let totalPercentage = 0;
    const len = data.cashFlow ? data.cashFlow.length : 0;
    for (let i = 0; i < len; i++) {
        const cf = data.cashFlow[i] || 0;
        const cc = data.complianceCosts[i] || 0;
        totalPercentage += cf > 0 ? (cc / cf) * 100 : 0;
    }
    const avgPercentage = len > 0 ? (totalPercentage / len).toFixed(1) : '0.0';

    let highestImpactIndex = 0;
    let lowestScore = data.impactScore[0];
    for (let i = 1; i < data.impactScore.length; i++) {
        if (data.impactScore[i] < lowestScore) {
            lowestScore = data.impactScore[i];
            highestImpactIndex = i;
        }
    }
    const highestImpactMonth = data.labels[highestImpactIndex];
    const currentScore = data.impactScore[data.impactScore.length - 1];

    const avgPctEl = document.getElementById('avg-compliance-pct');
    const highestImpactEl = document.getElementById('highest-impact-month');
    const currentScoreEl = document.getElementById('current-impact-score');

    if (avgPctEl) avgPctEl.innerText = avgPercentage + '%';
    if (highestImpactEl) highestImpactEl.innerText = highestImpactMonth;
    if (currentScoreEl) currentScoreEl.innerText = currentScore + '/100';
}

// ============================================================
// ITC Matching — GSTR-2B Upload & Reconciliation
// ============================================================

function loadSample2B() {
    const sampleData = {
        "b2b": [
            {"gstin": "29ABCDE1234F1Z5", "invoice_number": "INV-2026-001", "invoice_date": "2026-03-01", "taxable_value": 50000, "cgst": 4500, "sgst": 4500, "igst": 0},
            {"gstin": "07BBBBB1111B2Z6", "invoice_number": "INV-2026-002", "invoice_date": "2026-03-05", "taxable_value": 25000, "cgst": 2250, "sgst": 2250, "igst": 0},
            {"gstin": "27CCCCC2222C3Z7", "invoice_number": "INV-2026-003", "invoice_date": "2026-03-10", "taxable_value": 75000, "cgst": 0, "sgst": 0, "igst": 13500}
        ]
    };
    const textarea = document.getElementById('gstr2b-input');
    if (textarea) textarea.value = JSON.stringify(sampleData, null, 2);
    showToast('Sample GSTR-2B data loaded');
}

async function runITCMatch() {
    if (!NiyamAuth.isAuthenticated()) {
        showToast('Please login first');
        return;
    }

    const textarea = document.getElementById('gstr2b-input');
    const rawInput = textarea ? textarea.value.trim() : '';

    if (!rawInput) {
        showToast('Please paste GSTR-2B JSON data first');
        return;
    }

    let gstr2bData;
    try {
        gstr2bData = JSON.parse(rawInput);
    } catch (e) {
        showToast('Invalid JSON format. Please check your GSTR-2B data.');
        return;
    }

    showToast('Running ITC reconciliation...');

    try {
        const response = await NiyamAuth.niyamFetch(`${API_URL}/itc-match`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                gstr2b_data: gstr2bData,
                amount_tolerance: 1.0,
                gst_tolerance: 1.0,
                fuzzy_invoice_number: true,
            }),
        });

        const result = await response.json();

        if (result.success && result.data) {
            displayITCResults(result.data);
            showToast('ITC reconciliation complete!');
        } else {
            showToast(result.error || result.message || 'ITC matching failed');
        }
    } catch (error) {
        console.error('ITC match error:', error);
        showToast(`Error: ${error.message}`);
    }
}

function displayITCResults(data) {
    const financials = data.financials || {};
    const matchResults = data.match_results || [];

    // Update metric cards
    const fmtINR = (val) => {
        const num = Number(val);
        if (isNaN(num) || num === 0) return '₹0';
        return '₹' + num.toLocaleString('en-IN', {minimumFractionDigits: 0, maximumFractionDigits: 0});
    };

    const itcAvailEl = document.getElementById('gst-itc-available');
    const itcRiskEl = document.getElementById('gst-itc-risk');
    const recoverEl = document.getElementById('gst-recoverable');

    if (itcAvailEl) itcAvailEl.textContent = fmtINR(financials.total_itc_claimed || 0);
    if (itcRiskEl) itcRiskEl.textContent = fmtINR(financials.total_itc_at_risk || 0);
    if (recoverEl) recoverEl.textContent = fmtINR(financials.recoverable_itc || 0);

    const subtextAvail = document.getElementById('gst-itc-subtext');
    if (subtextAvail) subtextAvail.textContent = `Utilization: ${financials.utilization_rate || 0}%`;

    // Update results table
    const tbody = document.getElementById('itc-results-body');
    if (!tbody) return;

    if (matchResults.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-light); padding:30px;">No matches found</td></tr>';
        return;
    }

    tbody.innerHTML = matchResults.map(r => {
        const matchType = (r.match_type || '').replace(/_/g, ' ');
        const severity = r.severity || 'none';
        let badgeStyle = 'background: var(--success); color: white;';
        if (severity === 'critical') badgeStyle = 'background: var(--error); color: white;';
        else if (severity === 'high') badgeStyle = 'background: #ef4444; color: white;';
        else if (severity === 'medium') badgeStyle = 'background: #f59e0b; color: white;';
        else if (severity === 'low') badgeStyle = 'background: #3b82f6; color: white;';

        const eligible = Number(r.eligible_itc || 0);
        const atRisk = Number(r.itc_at_risk || 0);
        const action = r.action_required || '-';
        const truncAction = action.length > 60 ? action.substring(0, 57) + '...' : action;

        return `<tr>
            <td style="font-weight:600;">${escapeHtml(r.invoice_number || '-')}</td>
            <td style="font-size:0.8rem;">${escapeHtml(r.vendor_gstin || '-')}</td>
            <td>${fmtINR(eligible)}</td>
            <td style="color: ${atRisk > 0 ? 'var(--error)' : 'inherit'};">${fmtINR(atRisk)}</td>
            <td><span class="badge" style="${badgeStyle}">${escapeHtml(matchType)}</span></td>
            <td style="font-size:0.8rem;" title="${escapeHtml(action)}">${escapeHtml(truncAction)}</td>
        </tr>`;
    }).join('');
}

// ============================================================
// Authentication Check & Dashboard Data Fetch
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    // Allow demo mode to bypass auth
    if (!NiyamAuth.isAuthenticated() && !window._demoMode && window.location.hash !== '#demo') {
        window.location.href = 'login.html';
        return;
    }

    const userName = localStorage.getItem('niyam_user_name') || 'User';
    const businessNameStored = localStorage.getItem('niyam_business_name') || localStorage.getItem('niyam_user_business') || 'Your Business';
    const welcomeMsg = document.getElementById('welcome-text');
    if (welcomeMsg) {
        welcomeMsg.innerText = `Good Morning, ${userName.split(' ')[0]}`;
    }

    // Account dropdown info
    const initials = document.getElementById('account-initials');
    if (initials) initials.textContent = userName.charAt(0).toUpperCase();
    const ddName = document.getElementById('dropdown-name');
    if (ddName) ddName.textContent = userName;
    const ddBiz = document.getElementById('dropdown-business');
    if (ddBiz) ddBiz.textContent = businessNameStored;

    fetchDashboardData();
});

async function fetchDashboardData() {
    setSectionLoading('view-dashboard', true);
    try {
        const response = await NiyamAuth.niyamFetch(`${API_URL}/dashboard/summary`);
        const data = await response.json();
        if (data.success && data.data) {
            updateDashboardUI(data.data);
            renderHealthChart(data.data);
        } else {
            renderHealthChart({});
        }
    } catch (error) {
        console.error('Error fetching dashboard data:', error);
        renderHealthChart({});
    } finally {
        setSectionLoading('view-dashboard', false);
    }

    // Fetch analytics trends for Reports charts
    fetchAnalyticsTrends();

    // Fetch TDS and ROC deadlines
    fetchTDSDeadlines();
    fetchROCDeadlines();

    // Fetch recent activity
    fetchActivityFeed();
}

async function fetchActivityFeed() {
    if (!NiyamAuth.isAuthenticated()) return;
    try {
        const response = await NiyamAuth.niyamFetch(`${API_URL}/audit-log?page_size=15`);
        const result = await response.json();
        if (result.success && result.data) {
            renderActivityFeed(result.data);
        }
    } catch (error) {
        console.error('Error fetching activity feed:', error);
    }
}

function renderActivityFeed(data) {
    const feed = document.getElementById('activity-feed');
    const countEl = document.getElementById('activity-count');
    if (!feed) return;

    const entries = data.entries || [];
    if (countEl) countEl.textContent = `${data.total || 0} total events`;

    if (entries.length === 0) {
        feed.innerHTML = '<p style="font-size:0.85rem; color:var(--text-light); padding:20px 0; text-align:center;">No activity yet. Upload an invoice to get started.</p>';
        return;
    }

    const iconMap = {
        'invoice_uploaded': 'upload',
        'invoice_corrected': 'edit-2',
        'tds_deadline_filed': 'check-circle',
        'roc_deadline_filed': 'check-circle',
        'user_signup': 'user-plus',
        'user_login': 'log-in',
    };
    const colorMap = {
        'invoice_uploaded': '#2563eb',
        'invoice_corrected': '#f59e0b',
        'tds_deadline_filed': '#10b981',
        'roc_deadline_filed': '#10b981',
        'user_signup': '#8b5cf6',
        'user_login': '#6b7280',
    };

    feed.innerHTML = entries.map(entry => {
        const action = entry.action || '';
        const label = escapeHtml(entry.action_label || action.replace(/_/g, ' '));
        const icon = iconMap[action] || 'activity';
        const color = colorMap[action] || '#6b7280';
        const details = entry.details || {};
        const ts = entry.timestamp || '';
        const timeStr = ts ? new Date(ts).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '';

        let subtitle = '';
        if (action === 'invoice_uploaded' && details.filename) {
            subtitle = escapeHtml(details.filename);
            if (details.total_amount) subtitle += ' — ' + _fmtINR(details.total_amount);
        } else if (action === 'invoice_corrected' && details.corrected_fields) {
            subtitle = 'Fields: ' + escapeHtml(details.corrected_fields.join(', '));
        } else if (action === 'tds_deadline_filed' && details.challan_number) {
            subtitle = 'Challan: ' + escapeHtml(details.challan_number);
        }

        return `<div style="display:flex; gap:12px; align-items:flex-start; padding:8px 0; border-bottom:1px solid #f8fafc;">
            <i data-feather="${icon}" style="width:16px; height:16px; color:${color}; flex-shrink:0; margin-top:2px;"></i>
            <div style="flex:1; min-width:0;">
                <p style="font-size:0.85rem; font-weight:500;">${label}</p>
                ${subtitle ? '<p style="font-size:0.75rem; color:var(--text-light); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + subtitle + '</p>' : ''}
            </div>
            <span style="font-size:0.7rem; color:var(--text-light); white-space:nowrap;">${escapeHtml(timeStr)}</span>
        </div>`;
    }).join('');

    if (window.feather) feather.replace();
}

async function fetchAnalyticsTrends() {
    try {
        const response = await NiyamAuth.niyamFetch(`${API_URL}/analytics/trends`);
        const result = await response.json();
        if (result.success && result.data) {
            const trends = result.data;
            // Update chart data from real backend data
            if (trends['6M']) currentChartData['6M'] = trends['6M'];
            if (trends['1Y']) currentChartData['1Y'] = trends['1Y'];
            if (trends['QTD']) currentChartData['QTD'] = trends['QTD'];

            // Refresh chart if already initialized
            if (window.lChart) {
                const data = currentChartData['6M'];
                window.lChart.data.labels = data.labels;
                window.lChart.data.datasets[0].data = data.taxLiability;
                window.lChart.data.datasets[1].data = data.cashFlow;
                window.lChart.data.datasets[2].data = data.itcAvailable;
                window.lChart.update();
                updateDataTable('6M');
            }
        }
    } catch (error) {
        console.error('Error fetching analytics trends:', error);
    }
}

function updateDashboardUI(data) {
    // data comes from /api/dashboard/summary → data.data
    // Structure: { top_actions, financial_summary, compliance_summary, risk_timeline }
    const compliance = data.compliance_summary || {};
    const financial = data.financial_summary || {};
    const topActions = data.top_actions || [];
    const timeline = data.risk_timeline || [];

    // --- Metric Card 1: Upcoming Deadlines ---
    const deadlineCount = document.querySelector('#view-dashboard .metric-card:nth-child(1) .metric-value span');
    const deadlineText = document.querySelector('#view-dashboard .metric-card:nth-child(1) p:last-child');
    const upcomingCount = compliance.upcoming_deadlines != null ? compliance.upcoming_deadlines : (compliance.critical_issues || 0);
    if (deadlineCount) deadlineCount.innerText = upcomingCount || '0';

    // Find next deadline from timeline
    const nextDeadline = timeline.find(t => t.type === 'deadline' && t.due_date);
    if (deadlineText) {
        if (nextDeadline && nextDeadline.due_date) {
            deadlineText.innerText = `Next due: ${nextDeadline.due_date}`;
        } else if (upcomingCount > 0) {
            deadlineText.innerText = `${upcomingCount} upcoming deadline(s)`;
        } else {
            deadlineText.innerText = 'No upcoming deadlines';
        }
    }

    // --- Metric Card 2: Compliance Health ---
    const healthPct = document.querySelector('#view-dashboard .metric-card:nth-child(2) .metric-value span');
    const healthBarParent = document.querySelector('#view-dashboard .metric-card:nth-child(2) .metric-value');
    const healthBar = healthBarParent ? healthBarParent.nextElementSibling?.firstElementChild : null;
    const rawScore = compliance.compliance_score;
    const health = rawScore != null && !isNaN(rawScore) ? Math.round(rawScore) : 0;
    if (healthPct) healthPct.innerText = health + '%';
    if (healthBar) healthBar.style.width = Math.max(health, 5) + '%';

    // --- Metric Card 3: Penalty Risk ---
    const riskVal = document.querySelector('#risk-card .metric-value span');
    const riskText = document.querySelector('#risk-card p:last-child');
    if (riskVal) {
        const risk = compliance.penalty_risk || 'low';
        const riskDisplay = risk.charAt(0).toUpperCase() + risk.slice(1);
        riskVal.innerText = riskDisplay + ' Risk';
        if (risk === 'low') {
            riskVal.style.color = 'var(--success)';
        } else if (risk === 'medium') {
            riskVal.style.color = '#f59e0b';
        } else {
            riskVal.style.color = 'var(--error)';
        }
    }
    if (riskText) {
        const penaltyRisk = financial.total_penalty_risk || 0;
        const itcRisk = financial.total_itc_at_risk || 0;
        const totalRisk = penaltyRisk + itcRisk;
        if (totalRisk > 0) {
            riskText.innerText = `Total exposure: ₹${totalRisk.toLocaleString('en-IN')}`;
        } else {
            riskText.innerText = 'No immediate threats detected';
        }
    }

    // --- Invoice Stats (if available) ---
    const invoiceStats = data.invoice_stats || {};
    const totalInvoices = invoiceStats.total_invoices || 0;
    const needsReviewCount = invoiceStats.needs_review || 0;

    // Update the financial summary cards if present in GST section
    const taxLiabilityEl = document.getElementById('total-tax-liability');
    const itcAvailableEl = document.getElementById('total-itc-available');
    if (taxLiabilityEl && financial.total_tax_liability != null) {
        taxLiabilityEl.textContent = '₹' + financial.total_tax_liability.toLocaleString('en-IN');
    }
    if (itcAvailableEl && financial.total_itc_available != null) {
        itcAvailableEl.textContent = '₹' + financial.total_itc_available.toLocaleString('en-IN');
    }

    // --- Update Deadlines Table from top_actions + timeline ---
    updateDeadlinesTable(topActions, timeline);
}

function updateDeadlinesTable(topActions, timeline) {
    const tbody = document.querySelector('#deadlines-table tbody');
    if (!tbody) return;

    // Build rows from timeline (deadline-type items)
    const deadlineItems = timeline.filter(t => t.type === 'deadline' || t.type === 'compliance');

    if (deadlineItems.length === 0) return; // Keep static HTML if no data

    tbody.innerHTML = deadlineItems.slice(0, 10).map(item => {
        const severity = (item.severity || 'info').toLowerCase();
        let statusClass = 'badge-upcoming';
        let statusText = 'Upcoming';
        let rowClass = '';

        if (severity === 'critical' || severity === 'error') {
            statusClass = 'badge-overdue';
            statusText = 'Overdue';
            rowClass = 'class="status-border-error"';
        } else if (severity === 'warning') {
            statusClass = 'badge-upcoming';
            statusText = 'Upcoming';
        } else {
            statusClass = '';
            statusText = 'On Track';
        }

        const category = (item.category || 'GST').toUpperCase();
        const dueDate = item.due_date || 'TBD';
        const impact = item.impact ? ` (₹${item.impact.toLocaleString('en-IN')})` : '';

        return `
            <tr ${rowClass} data-status="${statusText}">
                <td style="font-weight: 600;">${category}${impact}</td>
                <td>${dueDate}</td>
                <td><span class="badge ${statusClass}">${statusText}</span></td>
                <td><button class="btn-action" onclick="showToast('${(item.action_required || item.title || '').replace(/'/g, "\\'")}')">View</button></td>
            </tr>
        `;
    }).join('');
}

function renderHealthChart(data) {
    const canvas = document.getElementById('healthTrendChart');
    if (!canvas) return;
    const container = canvas.parentElement;

    // Show placeholder if no chart data
    if (!data.labels || !data.health_history || data.health_history.length === 0) {
        container.innerHTML = '<div style="display:flex; align-items:center; justify-content:center; height:100%; color:var(--text-light); text-align:center; flex-direction:column; gap:8px;"><i data-feather="bar-chart-2" style="width:32px; height:32px; opacity:0.4;"></i><p style="font-size:0.9rem;">Compliance trend will appear after data is processed</p></div>';
        if (window.feather) feather.replace();
        return;
    }

    const ctx = canvas.getContext('2d');
    if (window.myChart) window.myChart.destroy();
    window.myChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Compliance Score',
                data: data.health_history,
                borderColor: '#6366f1',
                backgroundColor: 'rgba(99, 102, 241, 0.1)',
                borderWidth: 3, tension: 0.4, fill: true,
                pointBackgroundColor: '#6366f1', pointRadius: 4
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: false, min: 60, max: 100, grid: { color: '#f1f5f9' }, ticks: { callback: value => value + '%' } },
                x: { grid: { display: false } }
            }
        }
    });
}

// ============================================================
// TDS Data Fetch
// ============================================================
async function fetchTDSDeadlines() {
    if (!NiyamAuth.isAuthenticated()) return;
    try {
        const response = await NiyamAuth.niyamFetch(`${API_URL}/tds/deadlines`);
        const result = await response.json();
        if (result.success && result.data) {
            renderTDSData(result.data);
        }
    } catch (error) {
        console.error('Error fetching TDS deadlines:', error);
    }
}

function renderTDSData(data) {
    const summary = data.summary || {};
    const deadlines = data.deadlines || [];
    const flags = data.flags || [];

    // Update metric cards
    const totalEl = document.getElementById('tds-total');
    const totalSub = document.getElementById('tds-total-sub');
    const compEl = document.getElementById('tds-completed');
    const compSub = document.getElementById('tds-completed-sub');
    const overdueEl = document.getElementById('tds-overdue');
    const overdueSub = document.getElementById('tds-overdue-sub');

    if (totalEl) totalEl.textContent = summary.total || 0;
    if (totalSub) totalSub.textContent = `${summary.upcoming || 0} upcoming`;
    if (compEl) compEl.textContent = summary.completed || 0;
    if (compSub) compSub.textContent = 'Filed this year';
    if (overdueEl) overdueEl.textContent = summary.overdue || 0;
    if (overdueSub) overdueSub.textContent = summary.overdue > 0 ? 'Action required!' : 'All on track';

    // Update deadline table
    const tbody = document.getElementById('tds-deadlines-body');
    if (tbody && deadlines.length > 0) {
        const relevant = deadlines.filter(d => d.status !== 'upcoming' || (d.days_until && d.days_until <= 30));
        const toShow = relevant.length > 0 ? relevant.slice(0, 10) : deadlines.slice(0, 10);

        tbody.innerHTML = toShow.map(dl => {
            let badgeStyle = 'background: var(--text-light); color: white;';
            let statusText = dl.status || 'upcoming';
            if (dl.status === 'completed') { badgeStyle = 'background: var(--success); color: white;'; statusText = 'Filed'; }
            else if (dl.status === 'overdue') { badgeStyle = 'background: var(--error); color: white;'; statusText = `${dl.days_late}d overdue`; }
            else if (dl.status === 'due_soon') { badgeStyle = 'background: var(--warning); color: white;'; statusText = `${dl.days_until}d left`; }
            else { badgeStyle = 'background: #3b82f6; color: white;'; statusText = 'Upcoming'; }

            const markBtn = dl.status !== 'completed'
                ? `<button class="btn-action" onclick="markTDSFiled('${escapeHtml(dl.id)}')">Mark Filed</button>`
                : '<span style="color:var(--success); font-size:0.8rem;">Done</span>';

            return `<tr>
                <td style="font-weight:600;">${escapeHtml(dl.subtype || dl.type)}</td>
                <td>${escapeHtml(dl.due_date || '-')}</td>
                <td><span class="badge" style="${badgeStyle}">${escapeHtml(statusText)}</span></td>
                <td>${markBtn}</td>
            </tr>`;
        }).join('');
    } else if (tbody) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-light); padding:30px;">No TDS deadlines found.</td></tr>';
    }

    // Update alerts
    const alertsContainer = document.getElementById('tds-alerts-container');
    if (alertsContainer && flags.length > 0) {
        alertsContainer.innerHTML = flags.slice(0, 5).map(f => {
            const sevColor = f.severity === 'critical' ? 'var(--error)' : f.severity === 'error' ? '#f59e0b' : '#3b82f6';
            const bgColor = f.severity === 'critical' ? '#fff5f5' : f.severity === 'error' ? '#fffbeb' : '#eff6ff';
            return `<div style="display: flex; align-items: start; gap: 12px; padding: 10px; background: ${bgColor}; border-radius: 8px;">
                <i data-feather="alert-circle" style="color: ${sevColor}; width: 20px; flex-shrink:0;"></i>
                <div>
                    <p style="font-weight: 600; font-size: 0.9rem;">${escapeHtml(f.message)}</p>
                    ${f.action_required ? '<p style="font-size: 0.75rem; color: var(--text-light);">' + escapeHtml(f.action_required) + '</p>' : ''}
                </div>
            </div>`;
        }).join('');
        if (window.feather) feather.replace();
    } else if (alertsContainer) {
        alertsContainer.innerHTML = '<p style="font-size: 0.85rem; color: var(--text-light);">No alerts — all TDS deadlines on track.</p>';
    }

    if (window.feather) feather.replace();
}

async function markTDSFiled(deadlineId) {
    try {
        const response = await NiyamAuth.niyamFetch(`${API_URL}/tds/deadlines/mark-filed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deadline_id: deadlineId }),
        });
        const result = await response.json();
        if (result.success) {
            showToast('TDS deadline marked as filed!');
            fetchTDSDeadlines();
        } else {
            showToast(result.detail || 'Failed to mark as filed');
        }
    } catch (error) {
        showToast('Error: ' + error.message);
    }
}

// ============================================================
// ROC Data Fetch
// ============================================================
async function fetchROCDeadlines() {
    if (!NiyamAuth.isAuthenticated()) return;
    try {
        const response = await NiyamAuth.niyamFetch(`${API_URL}/roc/deadlines`);
        const result = await response.json();
        if (result.success && result.data) {
            renderROCData(result.data);
        }
    } catch (error) {
        console.error('Error fetching ROC deadlines:', error);
    }
}

function renderROCData(data) {
    const summary = data.summary || {};
    const deadlines = data.deadlines || [];

    // KYC card
    const kycDl = deadlines.find(d => (d.subtype || '').includes('DIR-3'));
    const kycVal = document.getElementById('roc-kyc-value');
    const kycSub = document.getElementById('roc-kyc-sub');
    const kycCard = document.getElementById('roc-kyc-card');
    if (kycVal) {
        if (kycDl && kycDl.status === 'completed') {
            kycVal.textContent = 'Verified';
            if (kycSub) { kycSub.textContent = 'DIR-3 KYC Completed'; kycSub.style.color = 'var(--success)'; }
            if (kycCard) kycCard.classList.add('status-border-success');
        } else {
            kycVal.textContent = 'Pending';
            if (kycSub) { kycSub.textContent = kycDl ? `Due: ${kycDl.due_date}` : 'DIR-3 KYC required'; kycSub.style.color = 'var(--warning)'; }
        }
    }

    // Filing card
    const filingVal = document.getElementById('roc-filing-value');
    const filingSub = document.getElementById('roc-filing-sub');
    const filingCard = document.getElementById('roc-filing-card');
    const annualDls = deadlines.filter(d => (d.subtype || '').match(/AOC-4|MGT-7/));
    const annualPending = annualDls.filter(d => d.status !== 'completed');
    if (filingVal) {
        if (annualPending.length === 0 && annualDls.length > 0) {
            filingVal.textContent = 'All Filed';
            if (filingSub) { filingSub.textContent = 'AOC-4 & MGT-7 completed'; filingSub.style.color = 'var(--success)'; }
            if (filingCard) { filingCard.classList.remove('status-border-error'); filingCard.classList.add('status-border-success'); }
        } else if (annualPending.length > 0) {
            filingVal.textContent = 'Due Soon';
            if (filingSub) { filingSub.textContent = annualPending.map(d => d.subtype).join(' & ') + ' Pending'; filingSub.style.color = 'var(--error)'; }
            if (filingCard) filingCard.classList.add('status-border-error');
        } else {
            filingVal.textContent = '--';
            if (filingSub) filingSub.textContent = 'No filings found';
        }
    }

    // Disqualification card
    const disqVal = document.getElementById('roc-disq-value');
    const disqSub = document.getElementById('roc-disq-sub');
    const disqCard = document.getElementById('roc-disq-card');
    if (disqVal) {
        if (summary.disqualification_risk) {
            disqVal.textContent = 'HIGH';
            disqVal.style.color = 'var(--error)';
            if (disqSub) { disqSub.textContent = 'Overdue >1 year — risk of DIN deactivation'; disqSub.style.color = 'var(--error)'; }
            if (disqCard) disqCard.classList.add('status-border-error');
        } else {
            disqVal.textContent = 'Near Zero';
            disqVal.style.color = 'var(--success)';
            if (disqSub) { disqSub.textContent = 'Active DIN Status'; disqSub.style.color = 'var(--success)'; }
            if (disqCard) disqCard.classList.add('status-border-success');
        }
    }

    // Checklist
    const checklist = document.getElementById('roc-checklist');
    if (checklist && deadlines.length > 0) {
        checklist.innerHTML = deadlines.map(dl => {
            const isCompleted = dl.status === 'completed';
            const bg = isCompleted ? '#f0fdf4' : '#f8fafc';
            const badgeBg = isCompleted ? 'var(--success)' : dl.status === 'overdue' ? 'var(--error)' : 'var(--warning)';
            const statusText = isCompleted ? 'Completed' : dl.status === 'overdue' ? `${dl.days_late}d Overdue` : 'Pending';
            const desc = dl.description || dl.subtype;
            const dueInfo = dl.due_date ? `Due: ${dl.due_date}` : '';
            const penaltyInfo = dl.accrued_penalty ? ` | Penalty: ₹${dl.accrued_penalty.toLocaleString('en-IN')}` : '';

            const markBtn = !isCompleted
                ? `<button class="btn-action" style="font-size:0.75rem; margin-top:6px;" onclick="markROCFiled('${escapeHtml(dl.id)}')">Mark Filed</button>`
                : '';

            return `<div style="display: flex; justify-content: space-between; align-items: center; padding: 10px; background: ${bg}; border-radius: 8px;">
                <div>
                    <p style="font-weight: 600;">${escapeHtml(dl.subtype || 'Filing')}</p>
                    <p style="font-size: 0.75rem; color: var(--text-light);">${escapeHtml(desc)}</p>
                    <p style="font-size: 0.7rem; color: var(--text-light);">${escapeHtml(dueInfo)}${penaltyInfo ? escapeHtml(penaltyInfo) : ''}</p>
                    ${markBtn}
                </div>
                <span class="badge" style="background: ${badgeBg}; color: white;">${escapeHtml(statusText)}</span>
            </div>`;
        }).join('');
    }
}

async function markROCFiled(deadlineId) {
    try {
        const response = await NiyamAuth.niyamFetch(`${API_URL}/roc/deadlines/mark-filed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deadline_id: deadlineId }),
        });
        const result = await response.json();
        if (result.success) {
            showToast('ROC deadline marked as filed!');
            fetchROCDeadlines();
        } else {
            showToast(result.detail || 'Failed to mark as filed');
        }
    } catch (error) {
        showToast('Error: ' + error.message);
    }
}

// ============================================================
// Logout
// ============================================================
function logout() {
    NiyamAuth.logout();
}

// ============================================================
// Account Dropdown
// ============================================================
function toggleAccountDropdown() {
    const dd = document.getElementById('account-dropdown');
    if (dd) dd.classList.toggle('open');
}

// Close dropdown on outside click
document.addEventListener('click', (e) => {
    const dd = document.getElementById('account-dropdown');
    const trigger = document.getElementById('account-trigger');
    if (dd && trigger && !trigger.contains(e.target) && !dd.contains(e.target)) {
        dd.classList.remove('open');
    }
});

// ============================================================
// Footer dynamic year
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    const yearEl = document.getElementById('footer-year');
    if (yearEl) yearEl.textContent = new Date().getFullYear();
});

// ============================================================
// 1. Loading States — setSectionLoading
// ============================================================
function setSectionLoading(id, isLoading) {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelectorAll('.data-bound').forEach(n => {
        n.textContent = isLoading ? 'Loading\u2026' : (n.dataset.value || n.textContent);
    });
}

// ============================================================
// 2. Central "Coming Soon" Handler
// ============================================================
function comingSoon(feature) {
    feature = feature || 'This feature';
    showToast('\uD83D\uDEA7 ' + feature + ' is coming soon');
}

document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-soon]');
    if (btn) {
        e.preventDefault();
        comingSoon(btn.dataset.soon);
    }
});

// ============================================================
// 5. Empty States — actionable upgrades
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.empty-state').forEach(el => {
        const text = el.querySelector('p');
        if (text && text.textContent.trim() === 'No data yet') {
            text.textContent = 'No data yet. Upload invoices to see insights.';
            const btn = document.createElement('button');
            btn.className = 'btn btn-primary';
            btn.textContent = 'Upload Invoices';
            btn.addEventListener('click', () => {
                const sidebar = document.getElementById('sidebar-compliance');
                if (typeof switchView === 'function') switchView('compliance', sidebar);
            });
            el.appendChild(btn);
        }
    });
});

// ============================================================
// 6. Dashboard Sanity Fallbacks
// ============================================================
function applySanityFallbacks() {
    // Health bar: ensure minimum 5% width so it's always visible
    const healthBar = document.querySelector('#view-dashboard .metric-card:nth-child(2) div[style*="height: 6px"] div');
    if (healthBar) {
        const w = parseFloat(healthBar.style.width);
        if (!isNaN(w) && w < 5) healthBar.style.width = '5%';
    }

    // Risk badge colors
    const riskVal = document.querySelector('#risk-card .metric-value span');
    if (riskVal) {
        const text = (riskVal.textContent || '').toLowerCase();
        if (text.includes('low')) {
            riskVal.style.color = 'var(--success)';
        } else if (text.includes('medium')) {
            riskVal.style.color = '#f59e0b';
        } else if (text.includes('high') || text.includes('critical')) {
            riskVal.style.color = 'var(--error)';
        }
    }
}

// Re-apply after dashboard data updates
const _origUpdateDashboardUI = window.updateDashboardUI || updateDashboardUI;
window.updateDashboardUI = function (data) {
    _origUpdateDashboardUI(data);
    applySanityFallbacks();
};
document.addEventListener('DOMContentLoaded', applySanityFallbacks);

// ============================================================
// A. First-use Guide (one-time)
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    if (!localStorage.getItem('seen_onboarding')) {
        setTimeout(() => {
            showToast('Start by clicking "Try Demo" or upload invoices');
            localStorage.setItem('seen_onboarding', '1');
        }, 800);
    }
});

// ============================================================
// B. Global Error Boundary
// ============================================================
window.addEventListener('error', () => {
    showToast('Something went wrong. Please refresh.');
});
