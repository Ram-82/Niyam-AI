"""
Demo Service — instant full-pipeline demo with trust layer.

GET /api/demo/run → runs the entire pipeline on a prebuilt dataset,
returns dashboard + ITC + compliance + readiness + trust explanations.

Every flag and ITC result includes:
    - explanation: WHY it was flagged (plain English)
    - calculation: ₹ breakdown showing exact math
    - source: which invoice / rule / 2B entry triggered it

Goal: user sees the output and thinks "I understand why this is happening."
"""

import logging
import time
from datetime import date
from typing import List, Dict, Any

from app.services.itc_service import ITCService
from app.services.itc_matcher import MatchConfig
from app.services.rules import RulesEngine
from app.services.rules.deadline_rules import generate_deadlines_for_year
from app.services.dashboard_service import DashboardService
from app.services.export_service import (
    ExportService, assess_filing_readiness, _serialize,
)

logger = logging.getLogger(__name__)


# ============================================================
# Prebuilt Demo Dataset
# ============================================================

DEMO_BUSINESS = {
    "legal_name": "Sharma Textiles Pvt Ltd",
    "trade_name": "Sharma Textiles",
    "gstin": "27AABCS1234F1Z5",
    "pan": "AABCS1234F",
    "business_type": "Private Limited",
    "state": "Maharashtra",
}

DEMO_TODAY = date(2026, 3, 23)

DEMO_INVOICES = [
    # Invoice 1: Clean — exact match with 2B
    {
        "invoice_id": "demo-inv-001",
        "invoice_number": "TEX/2026/0087",
        "invoice_date": "2026-03-02",
        "vendor_name": "Mumbai Cotton Mills",
        "vendor_gstin": "27AAACM7890G1Z3",
        "taxable_value": 250000,
        "cgst": 22500,
        "sgst": 22500,
        "igst": 0,
        "total_amount": 295000,
        "confidence": 96,
        "needs_review": False,
        "invoice_type": "purchase",
    },
    # Invoice 2: Missing GSTIN — ITC cannot be claimed
    {
        "invoice_id": "demo-inv-002",
        "invoice_number": "LOCAL-442",
        "invoice_date": "2026-03-05",
        "vendor_name": "Rahul Dye Works",
        "vendor_gstin": "",
        "taxable_value": 45000,
        "cgst": 4050,
        "sgst": 4050,
        "igst": 0,
        "total_amount": 53100,
        "confidence": 72,
        "needs_review": True,
        "review_notes": ["missing_gstin", "low_confidence"],
        "invoice_type": "purchase",
    },
    # Invoice 3: Duplicate of Invoice 1 — same number
    {
        "invoice_id": "demo-inv-003",
        "invoice_number": "TEX/2026/0087",
        "invoice_date": "2026-03-02",
        "vendor_name": "Mumbai Cotton Mills",
        "vendor_gstin": "27AAACM7890G1Z3",
        "taxable_value": 250000,
        "cgst": 22500,
        "sgst": 22500,
        "igst": 0,
        "total_amount": 295000,
        "confidence": 96,
        "needs_review": False,
        "invoice_type": "purchase",
    },
    # Invoice 4: Missing in 2B — vendor didn't report
    {
        "invoice_id": "demo-inv-004",
        "invoice_number": "BLR/EXP/2026-119",
        "invoice_date": "2026-03-10",
        "vendor_name": "Bangalore Exports Ltd",
        "vendor_gstin": "29BBBBB5555B2Z6",
        "taxable_value": 180000,
        "cgst": 0,
        "sgst": 0,
        "igst": 32400,
        "total_amount": 212400,
        "confidence": 89,
        "needs_review": False,
        "invoice_type": "purchase",
    },
    # Invoice 5: Partial mismatch — amount differs slightly from 2B
    {
        "invoice_id": "demo-inv-005",
        "invoice_number": "DLH-2026-0033",
        "invoice_date": "2026-03-15",
        "vendor_name": "Delhi Hardware Supplies",
        "vendor_gstin": "07DDDDD4444D3Z9",
        "taxable_value": 92000,
        "cgst": 0,
        "sgst": 0,
        "igst": 16560,
        "total_amount": 108560,
        "confidence": 85,
        "needs_review": False,
        "invoice_type": "purchase",
    },
]

DEMO_GSTR2B = {
    "data": {"docdata": {"b2b": [
        # Matches Invoice 1 exactly
        {
            "ctin": "27AAACM7890G1Z3",
            "inv": [{
                "inum": "TEX/2026/0087",
                "idt": "2026-03-02",
                "items": [{"txval": 250000, "camt": 22500, "samt": 22500, "iamt": 0, "csamt": 0}],
            }],
        },
        # Matches Invoice 5 but amount differs (92500 vs 92000 in books)
        {
            "ctin": "07DDDDD4444D3Z9",
            "inv": [{
                "inum": "DLH-2026-0033",
                "idt": "2026-03-15",
                "items": [{"txval": 92500, "camt": 0, "samt": 0, "iamt": 16650, "csamt": 0}],
            }],
        },
        # In 2B but NOT in books — extra entry
        {
            "ctin": "33EEEEE6666E4Z2",
            "inv": [{
                "inum": "TN-2026-200",
                "idt": "2026-03-18",
                "items": [{"txval": 60000, "camt": 0, "samt": 0, "iamt": 10800, "csamt": 0}],
            }],
        },
    ]}},
}

DEMO_DEADLINES = [
    {"type": "gst", "subtype": "GSTR-3B", "due_date": "2026-03-20",
     "status": "upcoming", "penalty_rate": 50, "filing_portal": "https://gst.gov.in"},
    {"type": "gst", "subtype": "GSTR-1", "due_date": "2026-03-11",
     "status": "upcoming", "penalty_rate": 50, "filing_portal": "https://gst.gov.in"},
    {"type": "tds", "subtype": "TDS Payment", "due_date": "2026-03-07",
     "status": "upcoming", "penalty_rate": 200, "filing_portal": "https://incometax.gov.in"},
]


# ============================================================
# Trust Layer — enriches every flag and ITC result
# ============================================================

def _enrich_compliance_flags(flags: List[dict]) -> List[dict]:
    """Add explanation, calculation, and source to each compliance flag."""
    enriched = []
    for f in flags:
        ef = dict(f)
        rule_id = f.get("rule_id", "")
        severity = f.get("severity", "info")
        sev_str = severity.value if hasattr(severity, "value") else str(severity).split(".")[-1].lower()

        # Build explanation based on rule type
        explanation, calculation, source = _explain_flag(ef, sev_str)
        ef["trust"] = {
            "explanation": explanation,
            "calculation": calculation,
            "source": source,
        }
        enriched.append(ef)
    return enriched


def _explain_flag(flag: dict, severity: str) -> tuple:
    """Generate human-readable explanation for a compliance flag."""
    rule_id = flag.get("rule_id", "")
    message = flag.get("message", "")
    impact = flag.get("impact_amount", 0)
    days = flag.get("days_overdue", 0)

    # Deadline-related flags
    if "overdue" in message.lower() or "days_overdue" in str(rule_id):
        penalty_rate = flag.get("penalty_rate", 50)
        return (
            f"This filing is {days} days past its deadline. The government "
            f"charges a late fee of \u20b9{penalty_rate}/day from the due date. "
            f"Filing immediately stops the penalty from growing.",
            f"\u20b9{penalty_rate}/day \u00d7 {days} days = \u20b9{impact:,.0f} penalty accrued so far" if impact else
            f"\u20b9{penalty_rate}/day penalty applies from due date",
            f"Rule: {rule_id} | Deadline tracker | Statutory calendar",
        )

    # Missing GSTIN
    if "gstin" in message.lower() and ("missing" in message.lower() or "invalid" in message.lower()):
        inv_num = flag.get("invoice_number", "")
        return (
            f"This invoice has no valid vendor GSTIN. Under GST law, "
            f"Input Tax Credit (ITC) can ONLY be claimed if the supplier's "
            f"GSTIN appears on the invoice. This \u20b9{impact:,.0f} of ITC is blocked "
            f"until the vendor provides a valid GSTIN.",
            f"Taxable value on invoice = source of blocked ITC" if not impact else
            f"CGST + SGST on this invoice = \u20b9{impact:,.0f} ITC blocked",
            f"Rule: {rule_id} | Invoice: {inv_num or 'N/A'} | GST Section 16(2)(aa)",
        )

    # Duplicate invoice
    if "duplicate" in message.lower():
        return (
            f"The same invoice number appears more than once in your records. "
            f"Claiming ITC twice on the same invoice is a serious compliance "
            f"risk — it can trigger GST audit notices and penalties.",
            f"Duplicate claim amount = \u20b9{impact:,.0f}" if impact else
            f"Remove the duplicate entry before filing",
            f"Rule: {rule_id} | Duplicate detection | GST Section 16(2)",
        )

    # Generic fallback
    return (
        message or f"Compliance flag raised by rule {rule_id}.",
        f"Estimated impact: \u20b9{impact:,.0f}" if impact else "No direct financial impact calculated",
        f"Rule: {rule_id} | Niyam AI Rules Engine",
    )


def _enrich_itc_results(itc_results: List[dict]) -> List[dict]:
    """Add trust layer to each ITC match result."""
    enriched = []
    for r in itc_results:
        er = dict(r)
        match_type = r.get("match_type", "")
        mt_str = match_type.value if hasattr(match_type, "value") else str(match_type)

        explanation, calculation, source = _explain_itc(er, mt_str)
        er["trust"] = {
            "explanation": explanation,
            "calculation": calculation,
            "source": source,
        }
        enriched.append(er)
    return enriched


def _explain_itc(result: dict, match_type: str) -> tuple:
    """Generate human-readable explanation for an ITC match result."""
    inv_num = result.get("invoice_number", "N/A")
    vendor = result.get("vendor_gstin", "")
    eligible = float(result.get("eligible_itc") or 0)
    claimed = float(result.get("claimed_itc") or 0)
    at_risk = float(result.get("itc_at_risk") or 0)
    book_taxable = float(result.get("book_taxable") or result.get("taxable_value") or 0)
    twob_taxable = float(result.get("twob_taxable") or 0)

    if match_type == "exact_match":
        return (
            f"Invoice {inv_num} matches perfectly with GSTR-2B. The taxable "
            f"value, CGST, SGST, and IGST all align. This ITC is safe to claim.",
            f"Books: \u20b9{book_taxable:,.0f} | 2B: \u20b9{twob_taxable:,.0f} | "
            f"Difference: \u20b90 | ITC claimable: \u20b9{eligible:,.0f}",
            f"Invoice: {inv_num} | Vendor GSTIN: {vendor} | Matched in GSTR-2B",
        )

    if match_type == "partial_match":
        diff = abs(book_taxable - twob_taxable)
        return (
            f"Invoice {inv_num} exists in GSTR-2B but the amounts don't match "
            f"exactly. The taxable value differs by \u20b9{diff:,.0f}. This usually "
            f"means a rounding difference or the vendor reported a slightly "
            f"different amount. Verify with the vendor before claiming full ITC.",
            f"Books: \u20b9{book_taxable:,.0f} | 2B: \u20b9{twob_taxable:,.0f} | "
            f"Difference: \u20b9{diff:,.0f} | ITC at risk: \u20b9{at_risk:,.0f}",
            f"Invoice: {inv_num} | Vendor GSTIN: {vendor} | Amount mismatch in GSTR-2B",
        )

    if match_type == "missing_in_2b":
        return (
            f"Invoice {inv_num} is in your books but NOT in GSTR-2B. This means "
            f"the vendor ({vendor or 'unknown'}) has not reported this transaction "
            f"in their GSTR-1. Until they do, you CANNOT claim this ITC. "
            f"Contact the vendor and request they file/amend their GSTR-1.",
            f"Your books show \u20b9{eligible:,.0f} ITC on this invoice | "
            f"GSTR-2B shows: NOTHING | Full \u20b9{at_risk:,.0f} is at risk",
            f"Invoice: {inv_num} | Vendor GSTIN: {vendor} | Not found in GSTR-2B data",
        )

    if match_type == "missing_in_invoices":
        return (
            f"This entry appears in GSTR-2B (vendor GSTIN: {vendor}) but you "
            f"don't have a matching invoice in your books. Either you haven't "
            f"recorded this purchase, or the vendor reported an incorrect GSTIN. "
            f"If the purchase is legitimate, record the invoice to claim the ITC.",
            f"2B shows: \u20b9{twob_taxable:,.0f} taxable, \u20b9{eligible:,.0f} ITC available | "
            f"Your books: NO matching entry",
            f"GSTR-2B entry | Vendor GSTIN: {vendor} | Invoice: {inv_num}",
        )

    if match_type == "duplicate_claim":
        return (
            f"Invoice {inv_num} from vendor {vendor} appears MULTIPLE TIMES in "
            f"your purchase register. This means ITC of \u20b9{at_risk:,.0f} would be "
            f"claimed twice — this is a critical compliance violation. Remove the "
            f"duplicate entry BEFORE filing.",
            f"Original ITC: \u20b9{eligible:,.0f} (valid) | "
            f"Duplicate ITC: \u20b9{at_risk:,.0f} (must remove) | "
            f"Net valid claim: \u20b9{eligible:,.0f}",
            f"Invoice: {inv_num} | Vendor GSTIN: {vendor} | Duplicate detection",
        )

    return (
        f"ITC match result for invoice {inv_num}.",
        f"Eligible: \u20b9{eligible:,.0f} | Claimed: \u20b9{claimed:,.0f} | At risk: \u20b9{at_risk:,.0f}",
        f"Invoice: {inv_num} | Vendor GSTIN: {vendor}",
    )


def _enrich_top_actions(actions: List[dict]) -> List[dict]:
    """Add trust layer to dashboard top actions."""
    enriched = []
    for a in actions:
        ea = dict(a)
        amt = a.get("amount", 0)
        source_type = a.get("source_type", "")
        title = a.get("title", "")

        if "overdue" in title.lower() or "deadline" in title.lower():
            ea["trust"] = {
                "explanation": f"This deadline has passed. Every day of delay adds to the penalty.",
                "calculation": f"\u20b9{amt:,.0f} penalty so far" if amt else "Penalty accruing daily",
                "source": f"Statutory deadline | {source_type}",
            }
        elif "duplicate" in title.lower():
            ea["trust"] = {
                "explanation": "Duplicate invoice detected — remove before filing to avoid GST audit.",
                "calculation": f"\u20b9{amt:,.0f} ITC at risk from duplicate" if amt else "",
                "source": f"ITC Matcher | Duplicate detection",
            }
        elif "missing" in title.lower() and "2b" in title.lower():
            ea["trust"] = {
                "explanation": "Vendor hasn't reported this in GSTR-1. Contact them to unlock your ITC.",
                "calculation": f"\u20b9{amt:,.0f} ITC blocked" if amt else "",
                "source": f"ITC Matcher | GSTR-2B reconciliation",
            }
        elif "gstin" in title.lower():
            ea["trust"] = {
                "explanation": "No vendor GSTIN means ITC is legally blocked. Get the GSTIN from vendor.",
                "calculation": f"\u20b9{amt:,.0f} ITC blocked" if amt else "",
                "source": f"Rules Engine | Invoice validation",
            }
        else:
            ea["trust"] = {
                "explanation": a.get("description", title),
                "calculation": f"Estimated impact: \u20b9{amt:,.0f}" if amt else "See details",
                "source": source_type or "Niyam AI",
            }
        enriched.append(ea)
    return enriched


# ============================================================
# Demo Runner
# ============================================================

class DemoService:
    """Runs full pipeline on prebuilt dataset, returns enriched output."""

    def run(self, top_n: int = 3) -> dict:
        """
        Execute full demo pipeline.

        Returns complete output with trust layer in <2 seconds.
        """
        t0 = time.time()

        # ---- Step 1: Run Rules Engine ----
        engine = RulesEngine()
        compliance_report = engine.run_all(
            deadlines=DEMO_DEADLINES,
            invoices=DEMO_INVOICES,
            today=DEMO_TODAY,
        )

        # ---- Step 2: Run ITC Matcher ----
        itc_service = ITCService(MatchConfig(amount_tolerance=1.0))
        itc_report = itc_service.reconcile(
            DEMO_INVOICES,
            DEMO_GSTR2B,
            period="Mar 2026",
        )

        # ---- Step 3: Extract raw data ----
        raw_flags = compliance_report.get("flags", [])
        raw_itc = itc_report.get("match_results", [])

        # ---- Step 4: Run Dashboard Service ----
        dashboard_service = DashboardService()
        dashboard_data = dashboard_service.build(
            compliance_flags=raw_flags,
            compliance_report=compliance_report,
            itc_results=raw_itc,
            itc_financials=itc_report.get("financials"),
            top_n=top_n,
        )

        # ---- Step 5: Filing Readiness ----
        readiness = assess_filing_readiness(DEMO_INVOICES, raw_flags, raw_itc)

        # ---- Step 6: Apply Trust Layer ----
        enriched_flags = _enrich_compliance_flags(raw_flags)
        enriched_itc = _enrich_itc_results(raw_itc)
        enriched_actions = _enrich_top_actions(
            dashboard_data.get("top_actions", [])
        )

        # ---- Step 6: ITC Financial Summary ----
        itc_financials = itc_report.get("financials", {})

        elapsed_ms = round((time.time() - t0) * 1000)

        return _serialize({
            "demo": True,
            "business": DEMO_BUSINESS,
            "period": "Mar 2026",
            "elapsed_ms": elapsed_ms,

            "dashboard": {
                "top_actions": enriched_actions,
                "financials": dashboard_data.get("financial_summary", {}),
                "compliance": dashboard_data.get("compliance_summary", {}),
                "timeline": dashboard_data.get("risk_timeline", []),
            },

            "itc_results": {
                "financial_summary": itc_financials,
                "matches": enriched_itc,
                "vendor_scores": itc_report.get("vendor_scores", {}),
                "action_items": itc_report.get("action_items", []),
            },

            "compliance": {
                "flags": enriched_flags,
                "score": compliance_report.get("compliance_score", 0),
                "risk_level": compliance_report.get("risk_level", "unknown"),
                "estimated_penalties": compliance_report.get("estimated_penalties", 0),
            },

            "filing_readiness": readiness,

            "invoices": {
                "count": len(DEMO_INVOICES),
                "records": DEMO_INVOICES,
            },

            "data_summary": {
                "total_invoices": len(DEMO_INVOICES),
                "clean_invoices": readiness.get("clean_invoice_count", 0),
                "compliance_flags": len(enriched_flags),
                "itc_matches": len(enriched_itc),
                "blocking_issues": len(readiness.get("blocking_issues", [])),
            },
        })
