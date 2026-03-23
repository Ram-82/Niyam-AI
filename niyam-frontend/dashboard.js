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
    document.querySelectorAll(".sidebar-item").forEach(item => item.classList.remove("active"));
    if (element) element.classList.add("active");

    document.querySelectorAll(".content-view").forEach(view => view.classList.remove("active"));
    const targetView = document.getElementById(`view-${viewId}`);
    if (targetView) targetView.classList.add("active");

    if (viewId === 'calendar') {
        setTimeout(() => { calendar.render(); }, 100);
    }
    if (viewId === 'reports') {
        setTimeout(() => { initCharts(); }, 100);
    }

    feather.replace();
}

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
        events: [
            { title: 'GSTR-1 Filing', start: '2025-06-11', color: '#2563eb', extendedProps: { description: 'Monthly GSTR-1 return for sales' } },
            { title: 'ROC Annual Return', start: '2025-06-15', color: '#ef4444', extendedProps: { description: 'Annual return for internal records' } },
            { title: 'GSTR-3B Filing', start: '2025-06-20', color: '#2563eb', extendedProps: { description: 'Summary return for GST payment' } },
            { title: 'TDS Payment', start: '2025-06-07', color: '#10b981', extendedProps: { description: 'Monthly TDS deposit for salary/rent' } },
            { title: 'Income Tax Audit', start: '2025-06-30', color: '#f59e0b', extendedProps: { description: 'Final tax audit submission' } }
        ],
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
// File Upload & Mock OCR
// ============================================================
function handleFileUpload(input) {
    if (!input.files || !input.files[0]) return;
    const progress = document.getElementById("upload-progress");
    const bar = document.getElementById("progress-bar-inner");
    const percent = document.getElementById("progress-percent");
    const results = document.getElementById("ocr-results");

    progress.style.display = "block";
    results.style.display = "none";
    let width = 0;
    const interval = setInterval(() => {
        if (width >= 100) {
            clearInterval(interval);
            setTimeout(() => {
                progress.style.display = "none";
                results.style.display = "block";
                showToast("AI analysis complete! Data extracted.");
            }, 500);
        } else {
            width += Math.random() * 15;
            if (width > 100) width = 100;
            bar.style.width = width + "%";
            percent.textContent = Math.floor(width) + "%";
        }
    }, 300);
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
            let response = "I'm Niyam AI. I can help with GST, TDS, ROC, or general compliance. What specific area are you inquiring about?";

            const intentMap = {
                "gst": "Your GST health is excellent! June liability is ₹42,500. You have ₹1.12 Lakhs available ITC.",
                "tds": "Your next TDS payment (Section 194I) of ₹45,200 is due on Jan 07. Use the TDS calculator for interest estimates.",
                "roc": "ROC filing for AOC-4 and MGT-7 is pending. DIR-3 KYC is verified. Need help with the MCA portal?",
                "bank": "You can connect HDFC or ICICI bank in the 'Connect Bank' section to sync your statements.",
                "deadline": "The most urgent deadline is TDS payment on Jan 07, followed by GSTR-1 on Jan 11.",
                "support": "Our experts are available for premium consultation. Would you like to book a CA session?",
                "help": "I can assist with: GST reconciliation, TDS interest calculation, ROC filing status, and document extraction."
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

function showHealthBreakdown() { showToast("Health: GST 100%, TDS 70%, ROC 0%"); }

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
            <td>${inv.date}</td>
            <td>${inv.desc}</td>
            <td>${inv.amount}</td>
            <td><span class="badge" style="background: var(--success); color: white;">${inv.status}</span></td>
            <td><button class="btn btn-outline" style="font-size: 0.7rem; padding: 4px 8px;" onclick="showToast('Downloading ${inv.id}...')">PDF</button></td>
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
let currentChartData = {
    '6M': {
        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
        taxLiability: [58000, 62000, 52000, 68000, 62000, 55000],
        cashFlow: [450000, 480000, 420000, 510000, 490000, 530000],
        itcAvailable: [32000, 28000, 35000, 41000, 38000, 42000]
    },
    '1Y': {
        labels: ['Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
        taxLiability: [45000, 48000, 52000, 60000, 58000, 65000, 58000, 62000, 52000, 68000, 62000, 55000],
        cashFlow: [410000, 430000, 460000, 480000, 450000, 520000, 450000, 480000, 420000, 510000, 490000, 530000],
        itcAvailable: [25000, 27000, 30000, 32000, 31000, 35000, 32000, 28000, 35000, 41000, 38000, 42000]
    },
    'QTD': {
        labels: ['Apr', 'May', 'Jun'],
        taxLiability: [68000, 62000, 55000],
        cashFlow: [510000, 490000, 530000],
        itcAvailable: [41000, 38000, 42000]
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

    window.complianceChartData = {
        '6M': {
            labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
            cashFlow: [720000, 680000, 750000, 710000, 730000, 690000],
            complianceCosts: [62000, 58000, 75000, 68000, 72000, 65000],
            impactScore: [78, 82, 75, 85, 80, 88]
        },
        '1Y': {
            labels: ['Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
            cashFlow: [690000, 710000, 695000, 725000, 705000, 740000, 720000, 680000, 750000, 710000, 730000, 690000],
            complianceCosts: [58000, 62000, 59000, 70000, 64000, 73000, 62000, 58000, 75000, 68000, 72000, 65000],
            impactScore: [80, 78, 82, 76, 81, 77, 78, 82, 75, 85, 80, 88]
        },
        'YTD': {
            labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
            cashFlow: [720000, 680000, 750000, 710000, 730000, 690000],
            complianceCosts: [62000, 58000, 75000, 68000, 72000, 65000],
            impactScore: [78, 82, 75, 85, 80, 88]
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
    for (let i = 0; i < data.cashFlow.length; i++) {
        totalPercentage += (data.complianceCosts[i] / data.cashFlow[i]) * 100;
    }
    const avgPercentage = (totalPercentage / data.cashFlow.length).toFixed(1);

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
// Authentication Check & Dashboard Data Fetch
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    const token = localStorage.getItem('niyam_access_token');

    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    const userName = localStorage.getItem('niyam_user_name') || 'User';
    const welcomeMsg = document.getElementById('welcome-text');
    if (welcomeMsg) {
        welcomeMsg.innerText = `Good Morning, ${userName.split(' ')[0]}`;
    }

    fetchDashboardData();
});

async function fetchDashboardData() {
    const token = localStorage.getItem('niyam_access_token');
    try {
        const response = await fetch(`${API_URL}/dashboard/summary`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await response.json();
        if (data.success) {
            updateDashboardUI(data.data);
            renderHealthChart(data.data);
        }
    } catch (error) {
        console.error('Error fetching dashboard data:', error);
    }
}

function updateDashboardUI(data) {
    const deadlineCount = document.querySelector('.metric-card:nth-child(1) .metric-value span');
    const deadlineText = document.querySelector('.metric-card:nth-child(1) p:last-child');
    if (deadlineCount) deadlineCount.innerText = data.upcoming_deadlines;
    if (deadlineText) deadlineText.innerText = `Next due: ${data.next_deadline}`;

    const healthPct = document.querySelector('.metric-card:nth-child(2) .metric-value span');
    const healthBar = document.querySelector('.metric-card:nth-child(2) .metric-value').nextElementSibling.firstElementChild;
    if (healthPct) healthPct.innerText = Math.round(data.compliance_health) + '%';
    if (healthBar) healthBar.style.width = data.compliance_health + '%';

    const riskVal = document.querySelector('#risk-card .metric-value span');
    if (riskVal) {
        riskVal.innerText = data.penalty_risk + ' Risk';
        riskVal.style.color = data.penalty_risk === 'Low' ? 'var(--success)' : 'var(--error)';
    }
}

function renderHealthChart(data) {
    const ctx = document.getElementById('healthTrendChart').getContext('2d');
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
// Logout
// ============================================================
function logout() {
    localStorage.removeItem('niyam_access_token');
    localStorage.removeItem('niyam_refresh_token');
    localStorage.removeItem('niyam_user_name');
    localStorage.removeItem('niyam_business_name');
    localStorage.removeItem('niyam_user_business');
    window.location.href = 'login.html';
}

// Add Logout Button to Sidebar
const sidebarEl = document.querySelector('.sidebar');
if (sidebarEl) {
    const logoutBtn = document.createElement('div');
    logoutBtn.className = 'sidebar-item';
    logoutBtn.style.marginTop = 'auto';
    logoutBtn.style.cursor = 'pointer';
    logoutBtn.style.color = '#ef4444';
    logoutBtn.innerHTML = '<i data-feather="log-out"></i> Log Out';
    logoutBtn.onclick = logout;
    sidebarEl.appendChild(logoutBtn);
    if (window.feather) feather.replace();
}
