"""
ITC Service — orchestrator for ITC matching, financial rollup, and vendor insights.

Takes purchase invoices (from DB) + GSTR-2B data (from upload/import),
runs the matcher, calculates financials, scores vendors, and produces
a complete reconciliation report.

Pipeline position:
    Invoices (DB) + GSTR-2B (upload)
        → GSTR-2B Parser
        → ITC Matcher
        → Vendor Insights
        → **ITC Service** (aggregation + report)
        → API / Dashboard
"""

import logging
from datetime import date
from typing import List, Dict, Optional

from app.services.itc_matcher import ITCMatcher, MatchConfig, MatchType
from app.services.vendor_insights import calculate_vendor_scores

logger = logging.getLogger(__name__)


# ============================================================
# GSTR-2B JSON Parser
# ============================================================

def parse_gstr2b(raw_json: dict) -> List[dict]:
    """
    Parse GSTR-2B JSON into flat invoice entries.

    Handles both:
    1. Official GST portal JSON format (nested under data.docdata.b2b)
    2. Simplified flat format (for testing / manual upload)

    Returns list of dicts with normalized field names:
        gstin, invoice_number, invoice_date, taxable_value, cgst, sgst, igst, cess
    """
    entries = []

    # ---- Format 1: Official GSTR-2B JSON ----
    # Structure: { "data": { "docdata": { "b2b": [ { "ctin": "...", "inv": [...] } ] } } }
    docdata = (raw_json.get("data") or {}).get("docdata") or {}
    b2b_suppliers = docdata.get("b2b") or []

    for supplier in b2b_suppliers:
        ctin = (supplier.get("ctin") or "").upper().strip()

        for inv in supplier.get("inv") or []:
            # Each invoice may have multiple items — sum them
            total_taxable = 0.0
            total_cgst = 0.0
            total_sgst = 0.0
            total_igst = 0.0
            total_cess = 0.0

            for item in inv.get("items") or []:
                total_taxable += float(item.get("txval") or item.get("taxable_value") or 0)
                total_cgst += float(item.get("camt") or item.get("cgst") or 0)
                total_sgst += float(item.get("samt") or item.get("sgst") or 0)
                total_igst += float(item.get("iamt") or item.get("igst") or 0)
                total_cess += float(item.get("csamt") or item.get("cess") or 0)

            # If no items, use invoice-level amounts
            if not inv.get("items"):
                total_taxable = float(inv.get("txval") or inv.get("taxable_value") or 0)
                total_cgst = float(inv.get("camt") or inv.get("cgst") or 0)
                total_sgst = float(inv.get("samt") or inv.get("sgst") or 0)
                total_igst = float(inv.get("iamt") or inv.get("igst") or 0)
                total_cess = float(inv.get("csamt") or inv.get("cess") or 0)

            entries.append({
                "gstin": ctin,
                "invoice_number": inv.get("inum") or inv.get("invoice_number") or "",
                "invoice_date": inv.get("idt") or inv.get("invoice_date") or "",
                "taxable_value": round(total_taxable, 2),
                "cgst": round(total_cgst, 2),
                "sgst": round(total_sgst, 2),
                "igst": round(total_igst, 2),
                "cess": round(total_cess, 2),
            })

    # ---- Format 2: Flat list (testing / simple upload) ----
    # If docdata was empty, check if root has a flat list
    if not entries:
        flat_list = raw_json.get("b2b") or raw_json.get("invoices") or raw_json.get("entries") or []
        if isinstance(flat_list, list):
            for item in flat_list:
                gstin = (item.get("gstin") or item.get("ctin") or "").upper().strip()
                entries.append({
                    "gstin": gstin,
                    "invoice_number": item.get("invoice_number") or item.get("inum") or "",
                    "invoice_date": item.get("invoice_date") or item.get("idt") or "",
                    "taxable_value": float(item.get("taxable_value") or item.get("txval") or 0),
                    "cgst": float(item.get("cgst") or item.get("camt") or 0),
                    "sgst": float(item.get("sgst") or item.get("samt") or 0),
                    "igst": float(item.get("igst") or item.get("iamt") or 0),
                    "cess": float(item.get("cess") or item.get("csamt") or 0),
                })

    logger.info(f"Parsed {len(entries)} entries from GSTR-2B")
    return entries


# ============================================================
# ITC Service
# ============================================================

class ITCService:
    """
    Orchestrates the full ITC reconciliation pipeline.

    Usage:
        service = ITCService()
        report = service.reconcile(invoices, gstr2b_json)
    """

    def __init__(self, config: MatchConfig = None):
        self.matcher = ITCMatcher(config)

    def reconcile(
        self,
        invoices: List[dict],
        gstr2b_json: dict,
        period: Optional[str] = None,
    ) -> dict:
        """
        Run full ITC reconciliation.

        Args:
            invoices: purchase invoices from DB (normalized)
            gstr2b_json: raw GSTR-2B JSON (any supported format)
            period: filing period label (e.g. "Mar 2026")

        Returns:
            Complete reconciliation report with:
            - match_results: per-invoice match details
            - financials: ITC summary numbers
            - vendor_scores: per-vendor reliability
            - action_summary: grouped actions by priority
        """
        # ---- Step 1: Parse GSTR-2B ----
        gstr2b_entries = parse_gstr2b(gstr2b_json)

        # ---- Step 2: Run matcher ----
        match_results = self.matcher.match(invoices, gstr2b_entries)
        results_dicts = [r.to_dict() for r in match_results]

        # ---- Step 3: Calculate financials ----
        financials = self._calculate_financials(results_dicts)

        # ---- Step 4: Vendor scoring ----
        vendor_scores = calculate_vendor_scores(results_dicts)
        vendor_dicts = [v.to_dict() for v in vendor_scores]

        # ---- Step 5: Action summary ----
        action_summary = self._build_action_summary(results_dicts)

        # ---- Step 6: Match type breakdown ----
        breakdown = self._match_breakdown(results_dicts)

        return {
            "period": period or f"{date.today().strftime('%b %Y')}",
            "match_results": results_dicts,
            "financials": financials,
            "match_breakdown": breakdown,
            "vendor_scores": vendor_dicts,
            "action_summary": action_summary,
            "metadata": {
                "total_invoices": len(invoices),
                "total_2b_entries": len(gstr2b_entries),
                "total_matches": len(results_dicts),
            },
        }

    def _calculate_financials(self, results: List[dict]) -> dict:
        """
        Calculate ITC financial summary.

        total_itc_available:  sum of eligible_itc across all matches
        total_itc_claimed:    sum of claimed_itc (actually claimable)
        total_itc_at_risk:    sum of itc_at_risk (may be denied)
        recoverable_itc:      ITC from MISSING_IN_INVOICES (can be recovered)
        net_itc_position:     claimed - at_risk (what you can safely file)
        """
        total_available = 0.0
        total_claimed = 0.0
        total_at_risk = 0.0
        recoverable = 0.0

        for r in results:
            total_available += float(r.get("eligible_itc") or 0)
            total_claimed += float(r.get("claimed_itc") or 0)
            total_at_risk += float(r.get("itc_at_risk") or 0)

            if r.get("match_type") == MatchType.MISSING_IN_INVOICES:
                recoverable += float(r.get("eligible_itc") or 0)

        return {
            "total_itc_available": round(total_available, 2),
            "total_itc_claimed": round(total_claimed, 2),
            "total_itc_at_risk": round(total_at_risk, 2),
            "recoverable_itc": round(recoverable, 2),
            "net_itc_position": round(total_claimed - total_at_risk, 2),
            "utilization_rate": (
                round((total_claimed / total_available) * 100, 1)
                if total_available > 0 else 0.0
            ),
        }

    def _match_breakdown(self, results: List[dict]) -> dict:
        """Count results by match type."""
        breakdown = {mt.value: 0 for mt in MatchType}
        for r in results:
            mt = r.get("match_type", "")
            if mt in breakdown:
                breakdown[mt] += 1
            elif hasattr(mt, 'value'):
                breakdown[mt.value] = breakdown.get(mt.value, 0) + 1
        return breakdown

    def _build_action_summary(self, results: List[dict]) -> dict:
        """
        Group results by action priority for the dashboard.

        critical: DUPLICATE_CLAIM (remove immediately)
        high:     MISSING_IN_2B (contact vendors)
        medium:   PARTIAL_MATCH (reconcile amounts)
        low:      MISSING_IN_INVOICES (record purchase)
        none:     EXACT_MATCH (no action needed)
        """
        summary = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
        }

        for r in results:
            mt = r.get("match_type", "")
            # Normalize enum values
            mt_str = mt.value if hasattr(mt, 'value') else str(mt)

            entry = {
                "invoice_id": r.get("invoice_id"),
                "vendor_gstin": r.get("vendor_gstin"),
                "invoice_number": r.get("invoice_number"),
                "action_required": r.get("action_required"),
                "itc_at_risk": r.get("itc_at_risk", 0),
            }

            if mt_str == MatchType.DUPLICATE_CLAIM:
                summary["critical"].append(entry)
            elif mt_str == MatchType.MISSING_IN_2B:
                summary["high"].append(entry)
            elif mt_str == MatchType.PARTIAL_MATCH:
                summary["medium"].append(entry)
            elif mt_str == MatchType.MISSING_IN_INVOICES:
                summary["low"].append(entry)

        # Sort each group by ITC at risk (descending)
        for key in summary:
            summary[key].sort(key=lambda x: float(x.get("itc_at_risk") or 0), reverse=True)

        return summary
