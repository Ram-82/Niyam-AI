"""
Dashboard Decision Engine — converts all system outputs into actionable intelligence.

User opens dashboard → instantly sees:
    "What are the top 3 things I must fix TODAY to save money?"

Merges:
    1. Compliance flags (Rules Engine)
    2. ITC match results (ITC Matcher)
    3. Deadlines (statutory)
    4. Invoices (pending review)

Outputs:
    - Top N Actions (prioritized by severity → ₹ impact → urgency)
    - Financial Summary (penalty risk + ITC exposure)
    - Compliance Summary (score + critical issues)
    - Risk Timeline (chronological view of all risks)

Pipeline position:
    Rules Engine + ITC Matcher → **Dashboard Service** → API → Frontend
"""

import logging
from datetime import date, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ============================================================
# Severity ordering — shared across all sources
# ============================================================

_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "error": 2,      # Rules Engine uses this
    "medium": 3,
    "warning": 4,     # Rules Engine uses this
    "low": 5,
    "info": 6,
    "none": 7,
}


def _severity_rank(severity: str) -> int:
    """Lower = more urgent."""
    if not severity:
        return 99
    s = severity.lower() if isinstance(severity, str) else str(severity).split(".")[-1].lower()
    return _SEVERITY_ORDER.get(s, 99)


# ============================================================
# Top Actions Builder
# ============================================================

class TopAction:
    """A single prioritized action for the dashboard."""

    __slots__ = (
        "title",
        "type",               # recover, fix, remove, file, review, monitor
        "source",             # ITC, Rules, Invoice
        "impact",             # ₹ amount at stake
        "severity",           # critical, high, medium, low
        "action_required",    # specific instruction
        "due_date",           # ISO date string or None
        "confidence_score",   # 0-100
        "related_id",         # invoice_id, deadline_id, etc.
        "metadata",           # extra context
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))

    def to_dict(self) -> dict:
        return {slot: getattr(self, slot) for slot in self.__slots__}


def _build_actions_from_itc(itc_results: List[dict]) -> List[TopAction]:
    """Convert ITC match results into TopActions."""
    actions = []

    for r in itc_results:
        match_type = r.get("match_type", "")
        mt_str = match_type.value if hasattr(match_type, "value") else str(match_type)

        # Skip exact matches (nothing to do)
        if mt_str == "exact_match":
            continue

        severity = r.get("severity", "low")
        sev_str = severity.value if hasattr(severity, "value") else str(severity)
        action_type = r.get("action_type", "monitor")
        at_str = action_type.value if hasattr(action_type, "value") else str(action_type)

        itc_at_risk = float(r.get("itc_at_risk") or 0)
        eligible = float(r.get("eligible_itc") or 0)

        # For MISSING_IN_INVOICES, the impact is the recoverable amount
        if mt_str == "missing_in_invoices":
            impact = eligible
        else:
            impact = itc_at_risk

        if impact <= 0 and mt_str != "duplicate_claim":
            continue

        # Build action title
        inv_num = r.get("invoice_number") or "unknown"
        title = _itc_action_title(mt_str, impact, inv_num, r.get("vendor_gstin"))

        actions.append(TopAction(
            title=title,
            type=at_str,
            source="ITC",
            impact=round(impact, 2),
            severity=sev_str,
            action_required=r.get("action_required"),
            due_date=r.get("due_date"),
            confidence_score=r.get("confidence_score", 0),
            related_id=r.get("invoice_id"),
            metadata={
                "match_type": mt_str,
                "vendor_gstin": r.get("vendor_gstin"),
                "invoice_number": inv_num,
            },
        ))

    return actions


def _itc_action_title(match_type: str, impact: float, inv_num: str, gstin: str) -> str:
    """Generate human-readable title for ITC actions."""
    amt = f"₹{impact:,.0f}" if impact else ""

    if match_type == "missing_in_2b":
        return f"Recover {amt} ITC — contact vendor ({gstin or 'unknown'})"
    if match_type == "partial_match":
        return f"Fix {amt} ITC mismatch on invoice {inv_num}"
    if match_type == "duplicate_claim":
        return f"Remove duplicate ITC claim on {inv_num} ({amt} at risk)"
    if match_type == "missing_in_invoices":
        return f"Record purchase to claim {amt} ITC from {gstin or 'unknown'}"
    return f"Review invoice {inv_num}"


def _build_actions_from_flags(flags: List[dict]) -> List[TopAction]:
    """Convert Rules Engine compliance flags into TopActions."""
    actions = []

    for f in flags:
        severity = f.get("severity", "info")
        sev_str = severity.value if hasattr(severity, "value") else str(severity).split(".")[-1].lower()

        # Skip info-level (not actionable)
        if sev_str == "info":
            continue

        impact = float(f.get("impact_amount") or 0)
        category = f.get("category", "")
        cat_str = category.value if hasattr(category, "value") else str(category)
        rule_id = f.get("rule_id", "")

        # Determine action type from rule
        if "overdue" in rule_id or "late" in rule_id:
            action_type = "file"
        elif "missing" in rule_id:
            action_type = "fix"
        elif "duplicate" in rule_id:
            action_type = "remove"
        elif "imminent" in rule_id or "approaching" in rule_id:
            action_type = "file"
        else:
            action_type = "review"

        title = f.get("message") or rule_id

        actions.append(TopAction(
            title=title,
            type=action_type,
            source="Rules",
            impact=round(impact, 2),
            severity=sev_str,
            action_required=f.get("action_required"),
            due_date=f.get("due_date"),
            confidence_score=100,  # Rules are deterministic
            related_id=f.get("related_id"),
            metadata={
                "rule_id": rule_id,
                "category": cat_str,
            },
        ))

    return actions


def _deduplicate_actions(actions: List[TopAction]) -> List[TopAction]:
    """
    Remove duplicate actions that refer to the same issue.
    Keeps the higher-severity / higher-impact version.

    Dedup strategy:
    - If related_id exists: group by related_id + source + type
    - If no related_id: group by title + type
    - Cross-source dedup: if ITC and Rules flag the same related_id, keep ITC
      (more specific action_required)
    """
    seen = {}  # key → TopAction

    for action in actions:
        # Primary key: related_id is the most specific identifier
        if action.related_id:
            key = f"{action.related_id}::{action.type}"
        else:
            # Fallback: title-based (truncated to avoid minor wording diffs)
            key = f"{action.title[:40]}::{action.type}::{action.source}"

        if key in seen:
            existing = seen[key]
            # Keep higher severity, or higher impact if same severity
            if (_severity_rank(action.severity) < _severity_rank(existing.severity) or
                    (_severity_rank(action.severity) == _severity_rank(existing.severity) and
                     (action.impact or 0) > (existing.impact or 0))):
                seen[key] = action
        else:
            seen[key] = action

    return list(seen.values())


def _prioritize_actions(actions: List[TopAction], limit: int = None) -> List[TopAction]:
    """
    Sort actions by: severity → ₹ impact → due_date proximity.
    Optionally limit to top N.
    """
    today = date.today()

    def sort_key(a: TopAction):
        sev = _severity_rank(a.severity)
        impact = -(a.impact or 0)  # negative for descending
        urgency = 9999
        if a.due_date:
            try:
                due = date.fromisoformat(str(a.due_date)[:10])
                urgency = (due - today).days
            except (ValueError, TypeError):
                pass
        return (sev, impact, urgency)

    actions.sort(key=sort_key)

    if limit:
        return actions[:limit]
    return actions


# ============================================================
# Financial Summary
# ============================================================

def _build_financial_summary(
    flags: List[dict],
    itc_financials: Optional[dict],
) -> dict:
    """
    Aggregate financial exposure across all sources.

    total_penalty_risk:  sum of impact_amount from Rules Engine flags
    total_itc_at_risk:   from ITC matcher
    recoverable_itc:     ITC that can be recovered (MISSING_IN_INVOICES)
    net_exposure:        penalty_risk + itc_at_risk - recoverable
    """
    total_penalty = sum(float(f.get("impact_amount") or 0) for f in flags)

    itc_at_risk = float((itc_financials or {}).get("total_itc_at_risk", 0))
    recoverable = float((itc_financials or {}).get("recoverable_itc", 0))
    itc_claimed = float((itc_financials or {}).get("total_itc_claimed", 0))

    net_exposure = total_penalty + itc_at_risk - recoverable

    itc_available = float((itc_financials or {}).get("total_itc_available", 0))

    return {
        "total_penalty_risk": round(total_penalty, 2),
        "total_tax_liability": round(total_penalty, 2),  # alias for frontend compatibility
        "total_itc_at_risk": round(itc_at_risk, 2),
        "total_itc_available": round(itc_available, 2),
        "total_itc_claimed": round(itc_claimed, 2),
        "recoverable_itc": round(recoverable, 2),
        "net_exposure": round(max(0, net_exposure), 2),
    }


# ============================================================
# Compliance Summary
# ============================================================

def _build_compliance_summary(
    compliance_report: Optional[dict],
) -> dict:
    """
    Extract compliance health from Rules Engine report.
    Falls back to defaults if no report available.
    """
    if not compliance_report:
        return {
            "compliance_score": 100.0,
            "penalty_risk": "low",
            "critical_issues": 0,
            "upcoming_deadlines": 0,
        }

    summary = compliance_report.get("summary", {})
    return {
        "compliance_score": compliance_report.get("compliance_score", 100.0),
        "penalty_risk": compliance_report.get("penalty_risk", "low"),
        "critical_issues": summary.get("critical", 0) + summary.get("error", 0),
        "upcoming_deadlines": summary.get("warning", 0) + summary.get("info", 0),
    }


# ============================================================
# Risk Timeline
# ============================================================

def _build_risk_timeline(
    flags: List[dict],
    itc_results: List[dict],
) -> List[dict]:
    """
    Build chronological timeline of all risk events.
    Sorted by due_date (soonest first), then severity.
    """
    timeline = []

    # From Rules Engine flags
    for f in flags:
        severity = f.get("severity", "info")
        sev_str = severity.value if hasattr(severity, "value") else str(severity).split(".")[-1].lower()
        if sev_str in ("info",):
            continue

        category = f.get("category", "")
        cat_str = category.value if hasattr(category, "value") else str(category)

        rule_id = f.get("rule_id", "")
        if "deadline" in rule_id or "overdue" in rule_id or "imminent" in rule_id or "late" in rule_id:
            item_type = "deadline"
        elif "penalty" in rule_id:
            item_type = "penalty"
        else:
            item_type = "compliance"

        timeline.append({
            "type": item_type,
            "title": f.get("message", rule_id),
            "severity": sev_str,
            "due_date": f.get("due_date"),
            "impact": float(f.get("impact_amount") or 0),
            "action_required": f.get("action_required"),
            "source": "Rules",
            "category": cat_str,
        })

    # From ITC results (non-exact only)
    for r in itc_results:
        match_type = r.get("match_type", "")
        mt_str = match_type.value if hasattr(match_type, "value") else str(match_type)
        if mt_str == "exact_match":
            continue

        severity = r.get("severity", "low")
        sev_str = severity.value if hasattr(severity, "value") else str(severity)

        itc_at_risk = float(r.get("itc_at_risk") or 0)
        eligible = float(r.get("eligible_itc") or 0)
        impact = eligible if mt_str == "missing_in_invoices" else itc_at_risk

        if impact <= 0 and mt_str != "duplicate_claim":
            continue

        timeline.append({
            "type": "invoice",
            "title": f"{mt_str.replace('_', ' ').title()}: {r.get('invoice_number') or 'unknown'}",
            "severity": sev_str,
            "due_date": r.get("due_date"),
            "impact": round(impact, 2),
            "action_required": r.get("action_required"),
            "source": "ITC",
            "category": "itc",
        })

    # Sort: by due_date (soonest first, nulls last), then severity
    today_str = date.today().isoformat()

    def timeline_sort(item):
        due = item.get("due_date") or "9999-12-31"
        if isinstance(due, str):
            due_str = due[:10]
        else:
            due_str = str(due)[:10]
        sev = _severity_rank(item.get("severity", "info"))
        return (due_str, sev)

    timeline.sort(key=timeline_sort)

    return timeline


# ============================================================
# Dashboard Service (main orchestrator)
# ============================================================

class DashboardService:
    """
    Produces the complete dashboard payload.

    Usage:
        service = DashboardService()
        dashboard = service.build(
            compliance_flags=flags,
            compliance_report=report,
            itc_results=itc_results,
            itc_financials=itc_financials,
        )
    """

    def build(
        self,
        compliance_flags: List[dict] = None,
        compliance_report: Optional[dict] = None,
        itc_results: List[dict] = None,
        itc_financials: Optional[dict] = None,
        top_n: int = 3,
    ) -> dict:
        """
        Build complete dashboard payload.

        Args:
            compliance_flags: list of flag dicts from Rules Engine
            compliance_report: full report dict from RulesEngine.run_all()
            itc_results: list of match result dicts from ITC Matcher
            itc_financials: financial summary from ITC Service
            top_n: number of top actions to return (default 3)

        Returns:
            {
                "top_actions": [...],
                "financial_summary": {...},
                "compliance_summary": {...},
                "risk_timeline": [...],
                "generated_at": "YYYY-MM-DD"
            }
        """
        flags = compliance_flags or []
        itc = itc_results or []

        # ---- 1. Top Actions ----
        itc_actions = _build_actions_from_itc(itc)
        flag_actions = _build_actions_from_flags(flags)

        all_actions = itc_actions + flag_actions
        deduped = _deduplicate_actions(all_actions)
        top_actions = _prioritize_actions(deduped, limit=top_n)

        # ---- 2. Financial Summary ----
        financial = _build_financial_summary(flags, itc_financials)

        # ---- 3. Compliance Summary ----
        compliance = _build_compliance_summary(compliance_report)

        # ---- 4. Risk Timeline ----
        timeline = _build_risk_timeline(flags, itc)

        return {
            "top_actions": [a.to_dict() for a in top_actions],
            "all_actions": [a.to_dict() for a in _prioritize_actions(deduped)],
            "financial_summary": financial,
            "compliance_summary": compliance,
            "risk_timeline": timeline,
            "generated_at": date.today().isoformat(),
        }
