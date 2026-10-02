"""
Management guidance from the earnings press release (8-K Item 2.02, EX-99.1).

The release's "Outlook"/"Guidance" block is found and QUOTED; a value is parsed
only when the sentence states it unambiguously ("Revenue is expected to be
$108.0 billion, plus or minus 2%", "between $X and $Y", "X% to Y%"). A table
or qualitative outlook is quoted, not guessed at. Many companies (Apple,
Microsoft) guide only on the call — "no numeric guidance in the release" is
then the finding.

Credibility: for each earlier release that guided NEXT-quarter revenue, the
actual revenue of the quarter that followed (from the 10-Q/10-K) is compared
with the guidance midpoint — does this company tend to beat its own word?
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_HEAD = re.compile(r"(?im)^[ |•\-]*((?:business |financial |fiscal )?(?:outlook|guidance)\b[^\n]{0,120})$")
_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_METRICS = [
    ("revenue", r"\b(revenue|revenues|net sales|sales)\b"),
    ("gross_margin", r"\bgross margins?\b"),
    ("operating_expenses", r"\boperating expenses\b"),
    ("operating_margin", r"\boperating margins?\b"),
    ("eps", r"\b(eps|earnings per share|per diluted share)\b"),
    ("tax_rate", r"\btax rate\b"),
    ("capex", r"\bcapital expenditures?\b|\bcapex\b"),
    ("free_cash_flow", r"\bfree cash flow\b"),
]
_MONEY = r"\$\s?([\d,]+(?:\.\d+)?)\s*(thousand|million|billion|trillion)?"


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_statement(sentence: str) -> Optional[Dict[str, Any]]:
    """One guidance sentence -> {metric, low, high, mid, unit} or None. Pure."""
    low_s = sentence.lower()
    # A sentence describing what the outlook EXCLUDES ("excludes known charges
    # of $0.01 per share") is a reconciliation item, not guidance.
    if re.search(r"\bexclud(es|ing)\b|\brespectively\b", low_s):
        return None
    metric = next((m for m, pat in _METRICS if re.search(pat, low_s)), None)
    if not metric:
        return None
    m = re.search(_MONEY + r"\s*,?\s*plus or minus\s*([\d.]+)\s*%", sentence, re.I)
    if m:
        mid = _num(m.group(1)) * _SCALE.get((m.group(2) or "").lower(), 1)
        pm = float(m.group(3)) / 100
        return {"metric": metric, "low": mid * (1 - pm), "high": mid * (1 + pm), "mid": mid, "unit": "USD"}
    # "and" is a range only after "between": "$9.2 billion and $9.0 billion,
    # respectively" (Nvidia's GAAP and non-GAAP opex) is two figures, not a range.
    m = (re.search(r"between\s+" + _MONEY + r"\s*(?:and|to|-|–)\s*" + _MONEY, sentence, re.I)
         or re.search(_MONEY + r"\s*(?:to|-|–)\s*" + _MONEY, sentence, re.I))
    if m:
        s1 = _SCALE.get((m.group(2) or m.group(4) or "").lower(), 1)
        s2 = _SCALE.get((m.group(4) or m.group(2) or "").lower(), 1)
        lo, hi = _num(m.group(1)) * s1, _num(m.group(3)) * s2
        return {"metric": metric, "low": lo, "high": hi, "mid": (lo + hi) / 2, "unit": "USD"}
    m = re.search(r"([\d.]+)\s*%\s*(?:to|and|-|–)\s*([\d.]+)\s*%", sentence)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return {"metric": metric, "low": lo, "high": hi, "mid": (lo + hi) / 2, "unit": "%"}
    m = re.search(r"([\d.]+)\s*%\s*,?\s*plus or minus\s*([\d]+)\s*basis points", sentence, re.I)
    if m:
        mid, bp = float(m.group(1)), float(m.group(2)) / 100
        return {"metric": metric, "low": mid - bp, "high": mid + bp, "mid": mid, "unit": "%"}
    m = re.search(r"(?:approximately|about|of)\s+" + _MONEY, sentence, re.I)
    if m and re.search(r"\bexpect|\bguid|\boutlook|\bforecast|\banticipat", low_s):
        v = _num(m.group(1)) * _SCALE.get((m.group(2) or "").lower(), 1)
        return {"metric": metric, "low": v, "high": v, "mid": v, "unit": "USD"}
    return None


def outlook_block(text: str) -> Optional[str]:
    """The outlook section of a release: from its heading, ~2,500 characters."""
    for m in _HEAD.finditer(text):
        block = text[m.start():m.start() + 2500]
        if re.search(r"\$\s?\d|\d\s?%", block) and re.search(r"(?i)\bexpect|\banticipat|\bguid|\bforecast", block):
            return block
    return None


def extract(text: str) -> Dict[str, Any]:
    block = outlook_block(text)
    if not block:
        return {"found": False}
    from .filings import sentences
    stmts = []
    for s in sentences(block.replace(" | ", " ")):
        p = parse_statement(s)
        if p:
            stmts.append({**p, "quote": s[:400]})
    period = re.search(r"(?i)(first|second|third|fourth)\s+quarter\s+of\s+(?:fiscal\s+)?(?:year\s+)?(\d{4})|"
                       r"(?:fiscal\s+|full[\s-]year\s+)(\d{4})", block)
    return {"found": True, "period_text": period.group(0) if period else None,
            "statements": stmts, "excerpt": re.sub(r"\s+", " ", block.replace("|", " "))[:700]}


def _release_text(symbol: str, f: Dict[str, Any]) -> Optional[str]:
    from financial_data import gateway as gw
    from .filings import clean
    idx = gw.get("filings", symbol, concepts=["filing_documents"], accession=f["accession"], cik=f.get("cik"))
    docs = idx["data"][0]["extra"]["documents"] if idx["data"] else []
    ex = next((d for d in docs if (d.get("type") or "").startswith("EX-99")
               and d["document"].lower().endswith((".htm", ".html"))), None)
    if not ex:
        return None
    t = gw.get("filings", symbol, concepts=["document"], accession=f["accession"], document=ex["document"],
               filed=f["accepted"], cik=f.get("cik"))
    return clean(t["data"][0]["value"]) if t["data"] else None


def build_guidance(symbol: str, statements: Dict[str, Any], filings: List[Dict[str, Any]],
                   n_history: int = 6) -> Dict[str, Any]:
    from .statements import value
    releases = [f for f in filings if f["form"].startswith("8-K") and "2.02" in (f.get("items") or "")][:n_history]
    if not releases:
        return {"available": False, "reason": "no earnings releases (8-K Item 2.02) on file"}
    parsed = []
    for f in releases:
        try:
            text = _release_text(symbol, f)
        except Exception:
            text = None
        g = extract(text) if text else {"found": False}
        parsed.append({"filed": f["filed"], "url": f["url"], "accession": f["accession"], **g})
    latest = parsed[0]
    # Credibility: next-quarter revenue guidance vs what the next quarter delivered.
    record = []
    quarters = sorted(statements.get("quarters") or [], key=lambda q: q["end"])
    for p in parsed:
        rev = next((s for s in p.get("statements", []) if s["metric"] == "revenue" and s["unit"] == "USD"), None)
        if not rev:
            continue
        nxt = next((q for q in quarters if q["end"] > p["filed"]), None)
        if not nxt or value(nxt, "revenue") is None:
            continue
        from .statements import _days
        if (_days(p["filed"], nxt["end"]) or 999) > 130:
            continue
        actual = value(nxt, "revenue")
        record.append({"release": p["filed"], "quarter": nxt["label"], "guided_mid": rev["mid"],
                       "guided_low": rev["low"], "guided_high": rev["high"], "actual": actual,
                       "vs_mid": round(actual / rev["mid"] - 1, 4) if rev["mid"] else None,
                       "within_range": rev["low"] <= actual <= rev["high"]})
    beats = [r for r in record if r["vs_mid"] is not None and r["vs_mid"] > 0]
    return {"available": True, "latest": latest, "history": [{k: p.get(k) for k in ("filed", "found", "period_text")}
                                                            for p in parsed],
            "credibility": {"n": len(record), "beat_midpoint": len(beats),
                            "avg_vs_midpoint": None if not record else
                            round(sum(r["vs_mid"] for r in record) / len(record), 4),
                            "quarters": record},
            "note": ("quoted from the earnings press release; values parsed only where stated unambiguously"
                     if latest.get("found") else
                     "no outlook section with numbers in the latest release — guidance, if any, was given on the call")}
