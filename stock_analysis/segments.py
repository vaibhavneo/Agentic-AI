"""
Revenue by business segment, product line and geography — from the XBRL
instance of the latest 10-K/10-Q.

SEC's company-facts API carries only consolidated (dimensionless) facts, so
segment detail needs the filing's own instance document: each fact there sits
in a context that may name a dimension member (srt:ProductOrServiceAxis =
nvda:DataCenterMember). One-dimension contexts on the segment, product and
geography axes are read for the filing's main period and the same period a
year earlier (filings carry that comparative), giving each line's growth and
share. Multi-dimension contexts (segment × product) are left out rather than
summed into something the company never reported.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

AXES = {
    "us-gaap:StatementBusinessSegmentsAxis": "business segment",
    "srt:ProductOrServiceAxis": "product or service",
    "srt:StatementGeographicalAxis": "geography",
}
REVENUE_TAGS = ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:Revenues",
                "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax", "us-gaap:SalesRevenueNet")
_CTX = re.compile(r"<(?:xbrli:)?context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</(?:xbrli:)?context>", re.S)
_MEMBER = re.compile(r"<xbrldi:explicitMember[^>]*dimension=\"([^\"]+)\"[^>]*>\s*([^<\s]+)\s*</xbrldi:explicitMember>")
_START = re.compile(r"<(?:xbrli:)?startDate>([^<]+)</")
_END = re.compile(r"<(?:xbrli:)?endDate>([^<]+)</")


def _label(member: str) -> str:
    name = member.split(":")[-1]
    name = re.sub(r"Member$", "", name)
    name = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return name.strip()


def parse_instance(xml: str) -> Dict[str, Any]:
    """Pure: instance XML -> {(axis, member, start, end): value} for revenue."""
    contexts: Dict[str, Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]] = {}
    for cid, body in _CTX.findall(xml):
        members = _MEMBER.findall(body)
        s, e = _START.search(body), _END.search(body)
        if not e:
            continue
        if len(members) == 0:
            contexts[cid] = (None, None, s.group(1) if s else None, e.group(1))
        elif len(members) == 1 and members[0][0] in AXES:
            contexts[cid] = (members[0][0], members[0][1], s.group(1) if s else None, e.group(1))
    facts: Dict[Tuple, float] = {}
    for tag in REVENUE_TAGS:
        pat = re.compile(r"<" + re.escape(tag) + r"\b[^>]*contextRef=\"([^\"]+)\"[^>]*>([^<]+)</" + re.escape(tag) + ">")
        for cid, val in pat.findall(xml):
            ctx = contexts.get(cid)
            if not ctx:
                continue
            key = ctx
            try:
                v = float(val.strip())
            except ValueError:
                continue
            facts.setdefault(key + (tag,), v)
    return {"facts": facts}


_LOC = re.compile(r"<link:loc\b[^>]*xlink:href=\"[^\"]*#([^\"]+)\"[^>]*xlink:label=\"([^\"]+)\"", re.S)
_LOC2 = re.compile(r"<link:loc\b[^>]*xlink:label=\"([^\"]+)\"[^>]*xlink:href=\"[^\"]*#([^\"]+)\"", re.S)
_LABEL_ARC = re.compile(r"<link:labelArc\b[^>]*xlink:from=\"([^\"]+)\"[^>]*xlink:to=\"([^\"]+)\"", re.S)
_LABEL = re.compile(r"<link:label\b[^>]*xlink:label=\"([^\"]+)\"[^>]*xlink:role=\"([^\"]+)\"[^>]*>([^<]*)</link:label>",
                    re.S)
_DM_ARC = re.compile(r"<link:definitionArc\b[^>]*arcrole=\"[^\"]*domain-member\"[^>]*xlink:from=\"([^\"]+)\""
                     r"[^>]*xlink:to=\"([^\"]+)\"", re.S)


def _locs(xml: str) -> Dict[str, str]:
    out = {lab: href for href, lab in _LOC.findall(xml)}
    out.update({lab: href for lab, href in _LOC2.findall(xml)})
    return out


def _qname(element_id: str) -> str:
    # "aapl_IPhoneMember" -> "aapl:IPhoneMember"
    return element_id.replace("_", ":", 1)


def parse_labels(lab_xml: str) -> Dict[str, str]:
    """Member QName -> the company's own label (terse label preferred)."""
    locs = _locs(lab_xml)
    texts: Dict[str, Dict[str, str]] = {}
    for lab, role, text in _LABEL.findall(lab_xml):
        texts.setdefault(lab, {})[role.rsplit("/", 1)[-1]] = text.strip()
    out: Dict[str, str] = {}
    for frm, to in _LABEL_ARC.findall(lab_xml):
        el = locs.get(frm)
        roles = texts.get(to) or {}
        if el and roles:
            import html as _html
            out[_qname(el)] = _html.unescape(roles.get("terseLabel") or roles.get("label")
                                             or next(iter(roles.values())))
    return out


def parse_hierarchy(def_xml: str) -> Dict[str, List[str]]:
    """Parent member -> child members, from domain-member arcs. A member with
    reported children is a subtotal (Apple's Product = iPhone + Mac + …)."""
    locs = _locs(def_xml)
    kids: Dict[str, List[str]] = {}
    for frm, to in _DM_ARC.findall(def_xml):
        a, b = locs.get(frm), locs.get(to)
        if a and b:
            kids.setdefault(_qname(a), []).append(_qname(b))
    return kids


def _arithmetic_subtotals(cur: Dict[str, float]) -> set:
    """Members equal (within 0.5%) to the sum of two or more SMALLER members on
    the same axis. Apple's filing does not declare Products as the parent of
    iPhone, Mac, iPad and Wearables, but 54.3 + 10.4 + 7.9 + 6.2 = 78.8 ≈ 78.7."""
    from itertools import combinations
    out = set()
    items = sorted(cur.items(), key=lambda kv: -kv[1])
    for i, (m, v) in enumerate(items):
        smaller = [x for x in items[i + 1:] if x[0] not in out]
        if len(smaller) < 2 or v <= 0 or len(smaller) > 14:
            continue
        found = False
        for k in range(2, len(smaller) + 1):
            for combo in combinations(smaller, k):
                if abs(sum(x[1] for x in combo) - v) <= 0.005 * v:
                    found = True
                    break
            if found:
                break
        if found:
            out.add(m)
    return out


def summarize(parsed: Dict[str, Any], period_end: str, duration_days: Tuple[int, int],
              labels: Optional[Dict[str, str]] = None,
              hierarchy: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    from .statements import _days
    facts = parsed["facts"]
    # The filing's main period: the longest-represented one ending at period_end
    # within the expected duration band; the comparative ends ~a year earlier.
    def in_band(s, e):
        n = _days(s, e)
        return n is not None and duration_days[0] <= n <= duration_days[1]
    out: Dict[str, List[Dict[str, Any]]] = {}
    for axis, label in AXES.items():
        cur: Dict[str, float] = {}
        prior: Dict[str, float] = {}
        for (ax, member, s, e, tag), v in facts.items():
            if ax != axis or not s or not in_band(s, e):
                continue
            if e == period_end:
                cur.setdefault(member, v)
            elif abs((_days(e, period_end) or 0) - 365) <= 10:
                prior.setdefault(member, v)
        if len(cur) < 2:
            continue
        subtotal = {m for m in cur if any(c in cur for c in (hierarchy or {}).get(m, []))}
        subtotal |= _arithmetic_subtotals(cur) - subtotal
        total = sum(v for m, v in cur.items() if m not in subtotal)
        rows = []
        for member, v in sorted(cur.items(), key=lambda kv: -kv[1]):
            p = prior.get(member)
            rows.append({"line": (labels or {}).get(member) or _label(member), "member": member, "revenue": v,
                         "prior_year": p, "growth": None if not p else round(v / p - 1, 4),
                         "subtotal": member in subtotal,
                         "share": None if member in subtotal or not total else round(v / total, 4)})
        out[label] = rows
    return out


def build_segments(symbol: str, filings: List[Dict[str, Any]]) -> Dict[str, Any]:
    from financial_data import gateway as gw
    from financial_data import cache
    rep = next((f for f in filings if f["form"] in ("10-Q", "10-K")), None)
    if not rep:
        return {"available": False, "reason": "no 10-K/10-Q on file (foreign filers' 20-F segment data is "
                                              "not read yet)"}
    key = f"segments_v3_{rep['accession']}"     # v3: company labels + subtotals
    hit = cache.get("stock-analysis", "segments", key)
    if hit is not None:
        return hit
    idx = gw.get("filings", symbol, concepts=["filing_documents"], accession=rep["accession"], cik=rep.get("cik"))
    docs = idx["data"][0]["extra"]["documents"] if idx["data"] else []
    inst = next((d for d in docs if d["document"].endswith("_htm.xml") or d.get("type") == "EX-101.INS"), None)
    if not inst:
        return {"available": False, "reason": "the filing has no XBRL instance document"}
    xml = gw.get("filings", symbol, concepts=["document"], accession=rep["accession"], document=inst["document"],
                 filed=rep["accepted"], cik=rep.get("cik"))["data"][0]["value"]
    band = (80, 100) if rep["form"] == "10-Q" else (350, 380)
    period_end = rep.get("report_date")
    labels, hierarchy = {}, {}
    for kind, suffix in (("lab", "_lab.xml"), ("def", "_def.xml")):
        d = next((x for x in docs if x["document"].endswith(suffix)), None)
        if not d:
            continue
        try:
            body = gw.get("filings", symbol, concepts=["document"], accession=rep["accession"],
                          document=d["document"], filed=rep["accepted"], cik=rep.get("cik"))["data"][0]["value"]
            if kind == "lab":
                labels = parse_labels(body)
            else:
                hierarchy = parse_hierarchy(body)
        except Exception:
            pass
    lines = summarize(parse_instance(xml), period_end, band, labels, hierarchy)
    out = {"available": bool(lines), "form": rep["form"], "filed": rep["filed"], "period_end": period_end,
           "period": "quarter" if rep["form"] == "10-Q" else "fiscal year", "url": rep["url"],
           "breakdowns": lines,
           "reason": None if lines else "no one-dimension revenue breakdown in this filing's XBRL"}
    cache.put("stock-analysis", "segments", key, out)
    return out
