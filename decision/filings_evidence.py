"""
The Stock Analysis Agent's findings as decision evidence.

Two items, both read from stock_analysis/report.py so the decision and the
Stock Analysis tab can never disagree:

  filing_red_flags   what the filings themselves disclose — a restatement
                     notice, a late filing, ineffective controls, a going-
                     concern doubt. BEARISH risk evidence when present.
  earnings_quality   the earnings-quality grade. A low grade is BEARISH risk
                     evidence; a high grade is CONTEXT and NOT_DIRECTIONAL,
                     because the 2026-10-02 evaluation measured no return edge
                     from high quality among large caps (its IC was negative)
                     — calling it bullish would claim what was not measured.

Validation status is stated as measured: the filing findings have no testable
history here (TRACKED_FORWARD); the quality grade was backtested and did not
clear significance (BACKTESTED_ONLY).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from decision.evidence import DecisionEvidence

# Findings serious enough to decide on by themselves.
DECISIVE_CODES = {"8K_ITEM_4_02", "LATE_FILING", "CONTROLS_NOT_EFFECTIVE", "MATERIAL_WEAKNESS",
                  "GOING_CONCERN", "8K_ITEM_1_03"}


def evidence_from_fundamentals(report: Optional[Dict[str, Any]]) -> List[DecisionEvidence]:
    if not report or not report.get("available"):
        return []
    items: List[DecisionEvidence] = []
    as_of = report.get("as_of") or (report.get("generated_at") or "")[:10] or None

    fl = report.get("filings") or {}
    if fl.get("available") and fl.get("flags") is not None:
        flags = fl.get("flags") or []
        concerns = [f for f in flags if f.get("severity") == "CONCERN"]
        watch = [f for f in flags if f.get("severity") == "WATCH"]
        if concerns:
            decisive = any(f.get("code") in DECISIVE_CODES for f in concerns)
            items.append(DecisionEvidence(
                source="stock_analysis", category="RISK", metric="filing_red_flags",
                observation=(f"The filings disclose {len(concerns)} concern(s): "
                             + "; ".join(f.get("title", "") for f in concerns[:3])
                             + (f" (and {len(watch)} item(s) to watch)" if watch else "") + "."),
                direction="BEARISH", magnitude=min(0.9, 0.5 + 0.15 * len(concerns)), horizon="LONG",
                reliability=0.8, validation_status="TRACKED_FORWARD", as_of=as_of,
                provenance={"module": "stock_analysis/filings.py",
                            "documents": [((f.get("evidence") or {}).get("url")) for f in concerns[:5]]},
                decision_relevance="DECISIVE" if decisive else "SUPPORTING",
                raw_value=len(concerns), flags=[f.get("code", "") for f in concerns]))
        elif watch:
            items.append(DecisionEvidence(
                source="stock_analysis", category="RISK", metric="filing_red_flags",
                observation=f"No filing concerns; {len(watch)} item(s) to watch: "
                            + "; ".join(f.get("title", "") for f in watch[:3]) + ".",
                direction="NOT_DIRECTIONAL", magnitude=0.0, horizon="LONG", reliability=0.8,
                validation_status="TRACKED_FORWARD", as_of=as_of,
                provenance={"module": "stock_analysis/filings.py"}, decision_relevance="CONTEXT",
                raw_value=0, flags=[f.get("code", "") for f in watch]))
        else:
            items.append(DecisionEvidence(
                source="stock_analysis", category="RISK", metric="filing_red_flags",
                observation="No red flags in the last three years of SEC filings.",
                direction="NOT_DIRECTIONAL", magnitude=0.0, horizon="LONG", reliability=0.8,
                validation_status="TRACKED_FORWARD", as_of=as_of,
                provenance={"module": "stock_analysis/filings.py"}, decision_relevance="CONTEXT",
                raw_value=0))

    q = report.get("quality") or {}
    if q.get("available") and q.get("grade"):
        grade = q["grade"]
        concerns = [f["test"] for f in q.get("flags", []) if f.get("status") == "CONCERN"]
        low = grade in ("D", "F")
        items.append(DecisionEvidence(
            source="stock_analysis", category="FUNDAMENTAL", metric="earnings_quality",
            observation=(f"Earnings quality grade {grade} ({q.get('score'):.0f}/100)"
                         + (f": concerns — {', '.join(concerns[:3])}." if concerns else ".")),
            direction="BEARISH" if low else "NOT_DIRECTIONAL",
            magnitude=(0.6 if grade == "F" else 0.4) if low else 0.0,
            horizon="LONG", reliability=0.6, validation_status="BACKTESTED_ONLY", as_of=as_of,
            provenance={"module": "stock_analysis/quality.py",
                        "evaluation": "docs/FUNDAMENTALS_V2_EVALUATION.md"},
            decision_relevance="SUPPORTING" if low else "CONTEXT",
            raw_value=q.get("score"), flags=concerns[:5]))
    return items


def monitoring_checks(report: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What to watch in the next filings, from what the last ones showed."""
    if not report or not report.get("available"):
        return []
    checks = [{
        "what": "New SEC filings: restatement notice (8-K 4.02), late-filing notice, auditor change",
        "when": "Daily (filing watcher)",
        "changes_state_if": "Any CONCERN finding → re-score fundamentals and review the position",
        "source": "SEC EDGAR filing index", "automatable": True}]
    for t in ((report.get("quality") or {}).get("tests") or []):
        if t.get("status") in ("WATCH", "CONCERN") and t.get("key") in ("receivables", "inventory",
                                                                          "cash_conversion", "accruals"):
            checks.append({
                "what": f"Next 10-Q: {t['name']} (now {t.get('display')})",
                "when": "On the next quarterly filing",
                "changes_state_if": f"Still {t['status']} → the earnings-quality concern persists",
                "source": "SEC 10-Q via stock_analysis", "automatable": True})
    return checks
