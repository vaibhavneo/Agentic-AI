"""
Reading the filings themselves — what the numbers cannot say.

Three sources, cheapest first:

  1. THE FILING INDEX (no document fetched). A late-filing notice (NT 10-K), an
     8-K under Item 4.02 ("previously issued financial statements should no
     longer be relied upon"), Item 4.01 (auditor change), 1.03 (bankruptcy),
     3.01 (delisting notice) — each is a structured fact the SEC records. Super
     Micro's NT 10-K of 2024-08-29 is in the index the day it was filed.

  2. THE ANNUAL REPORT TEXT (10-K / 20-F). Rule-based, quoted findings: a
     material weakness or "not effective" conclusion in the controls section,
     going-concern language, the auditor and how long it has served, customer
     concentration, and how the risk factors changed against the prior year's
     report. Every finding carries the sentence it came from and the document.

  3. AN MD&A SUMMARY (optional, LLM). Bullets must each cite a sentence copied
     word-for-word from the MD&A, and every number must appear in the MD&A
     text. Either check failing withholds the summary — the deterministic
     findings above never depend on it.

Rule-based text reading is deliberately conservative: risk-factor language is
hypothetical ("a material weakness could..."), so control and going-concern
findings are read only from the sections where a company states facts about
itself, and hypothetical phrasing is excluded.
"""
from __future__ import annotations

import difflib
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

CONCERN, WATCH, INFO = "CONCERN", "WATCH", "INFO"
ANNUAL = ("10-K", "20-F", "40-F", "10-KT")
AMENDED_ANNUAL = ("10-K/A", "20-F/A", "40-F/A")
LATE = ("NT 10-K", "NT 10-Q", "NT 20-F")

# 8-K items worth surfacing, with how much they matter on their own.
EIGHT_K_ITEMS = {
    "4.02": (CONCERN, "Non-reliance on previously issued financial statements (restatement)"),
    "1.03": (CONCERN, "Bankruptcy or receivership"),
    "4.01": (WATCH, "Change in the company's auditor"),
    "3.01": (WATCH, "Notice of delisting or failure to meet a listing standard"),
    "2.06": (WATCH, "Material impairment"),
    "2.04": (WATCH, "Event accelerating a debt obligation"),
    "5.02": (INFO, "Director or executive officer departure/appointment"),
    "2.05": (INFO, "Exit or restructuring costs"),
}

_AUDIT_FIRMS = ("Young", "Deloitte", "KPMG", "Pricewaterhouse", "PwC", "BDO", "Grant Thornton", "Marcum",
                "Moss Adams", "Crowe", "RSM", "Baker Tilly", "Mazars", "Forvis", "Ernst", "Friedman",
                "Withum", "Cherry Bekaert", "Plante", "MaloneBailey", "Haskell", "UHY", "Armanino", "Wipfli")


def _years_before(as_of: Optional[str], n: int) -> str:
    d = date.fromisoformat(as_of[:10]) if as_of else date.today()
    return f"{d.year - n}-{d.month:02d}-{min(d.day, 28):02d}"


# ── 1. the filing index ─────────────────────────────────────────────────────

def filing_index(symbol: str, as_of: Optional[str] = None, fresh: bool = False) -> Dict[str, Any]:
    from financial_data import gateway as gw
    res = gw.get("filings", symbol, as_of=as_of, concepts=["filing"], fresh=fresh)
    rows = []
    for d in res["data"]:
        ex = d.get("extra") or {}
        rows.append({"form": d["value"], "filed": ex.get("filing_date") or str(d["available_at"])[:10],
                     "accepted": d["available_at"], "accession": d["source"]["document"], "url": d["source"]["url"],
                     "primary_document": ex.get("primary_document"), "report_date": d.get("period_end"),
                     "items": ex.get("items") or "", "description": ex.get("description"), "cik": ex.get("cik")})
    rows.sort(key=lambda r: r["accepted"], reverse=True)
    return {"filings": rows, "as_of_honored": res.get("as_of_honored"),
            "unavailable": res.get("unavailable") or []}


def index_flags(filings: List[Dict[str, Any]], as_of: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict]]:
    """Flags and notable events from the index alone, last three years."""
    since = _years_before(as_of, 3)
    flags, events = [], []
    for f in filings:
        if f["filed"] < since:
            continue
        form = f["form"]
        if form in LATE:
            flags.append({"severity": CONCERN, "code": "LATE_FILING",
                          "title": f"Late-filing notice ({form})",
                          "detail": f"Filed {f['filed']}: the company told the SEC it could not file its "
                                    f"{form[3:]} on time.",
                          "evidence": {"accession": f["accession"], "url": f["url"], "filed": f["filed"]}})
        if form.startswith("8-K"):
            for item in [i.strip() for i in (f["items"] or "").split(",") if i.strip()]:
                if item in EIGHT_K_ITEMS:
                    sev, label = EIGHT_K_ITEMS[item]
                    ev = {"date": f["filed"], "form": form, "item": item, "label": label, "severity": sev,
                          "accession": f["accession"], "url": f["url"]}
                    events.append(ev)
                    if sev in (CONCERN, WATCH):
                        flags.append({"severity": sev, "code": f"8K_ITEM_{item.replace('.', '_')}",
                                      "title": label, "detail": f"8-K Item {item} filed {f['filed']}.",
                                      "evidence": {"accession": f["accession"], "url": f["url"], "filed": f["filed"]}})
    # Item 5.02 also covers board appointments and pay arrangements, so a count
    # of them is context, never a flag on its own.
    recent_502 = [e for e in events if e["item"] == "5.02" and e["date"] >= _years_before(as_of, 1)]
    if len(recent_502) >= 3:
        flags.append({"severity": INFO, "code": "MANAGEMENT_CHANGES",
                      "title": f"{len(recent_502)} director/officer change filings in the last year",
                      "detail": "8-K Item 5.02 filed " + ", ".join(e["date"] for e in recent_502[:6]) + ".",
                      "evidence": {"accession": recent_502[0]["accession"], "url": recent_502[0]["url"]}})
    return flags, events


# ── 2. the annual report text ───────────────────────────────────────────────

_ITEM_LINE = re.compile(r"(?im)^[ |]*item[ ]*(\d{1,2}[a-d]?)[ ]*[\.:\-–—|]?[ |]*([^\n]{0,120})$")
# Filings typeset headings with thin, em and no-break spaces ("ITEM\u20095." in
# TSMC's 20-F); without folding them, only the table of contents matched.
_ODD_SPACES = re.compile(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]")


def clean(text: str) -> str:
    return _ODD_SPACES.sub(" ", text)

SECTIONS_10K = {"risk_factors": "1A", "legal": "3", "mdna": "7", "controls": "9A"}
SECTIONS_20F = {"risk_factors": "3", "legal": "8", "mdna": "5", "controls": "15"}


def split_sections(text: str, form: str) -> Dict[str, str]:
    """The body of each named Item. The table of contents lists every Item
    too, so the occurrence that opens the LONGEST span is taken as the body."""
    heads = [(m.start(), m.group(1).upper()) for m in _ITEM_LINE.finditer(text)]
    spans: Dict[str, str] = {}
    want = SECTIONS_20F if form.startswith("20-F") else SECTIONS_10K
    for name, item in want.items():
        best = ""
        for i, (pos, it) in enumerate(heads):
            if it != item:
                continue
            nxt = next((p for p, x in heads[i + 1:] if x != item), len(text))
            body = text[pos:nxt]
            if len(body) > len(best):
                best = body
        if name == "risk_factors" and form.startswith("20-F") and best:
            m = re.search(r"(?im)^[ |]*(?:3\.)?D\.?[ |]*Risk Factors", best)
            if m:
                best = best[m.start():]
        spans[name] = best
    return spans


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(“\"])")


def sentences(text: str) -> List[str]:
    out = []
    for para in text.split("\n"):
        para = para.replace(" | ", " ").strip()
        if len(para) < 20:
            continue
        out.extend(s.strip() for s in _SENT.split(para) if len(s.strip()) > 20)
    return out


_HYPOTHETICAL = re.compile(r"\b(could|may|might|would|if we|if the company|in the event|any failure|"
                           r"cannot assure|no assurance)\b", re.I)
# The auditor's report defines the term and describes testing for it in every
# audit ("assessing the risk that a material weakness exists") — boilerplate,
# not a finding.
_MW_BOILERPLATE = re.compile(r"risk that a material weakness exists|a material weakness is a deficiency|"
                             r"definition of a material weakness|reasonable possibility that a material misstatement",
                             re.I)
_NEGATED_MW = re.compile(r"\b(no|not|did not identify|have not identified|were no|are no|without)\b[^.]{0,60}"
                         r"material weakness", re.I)


def control_findings(controls: str) -> List[Dict[str, Any]]:
    found = []
    for s in sentences(controls):
        low = s.lower()
        if re.search(r"(internal control over financial reporting|disclosure controls and procedures)"
                     r"[^.]{0,80}\b(was|were)\s+not\s+effective", low):
            found.append({"severity": CONCERN, "code": "CONTROLS_NOT_EFFECTIVE",
                          "title": "Management concluded its controls were not effective", "quote": s})
        elif "material weakness" in low and not _NEGATED_MW.search(s) and not _HYPOTHETICAL.search(s) \
                and not _MW_BOILERPLATE.search(s) \
                and re.search(r"\b(identified|identify|existed|exists|resulted|remediat|due to)\b", low):
            found.append({"severity": CONCERN, "code": "MATERIAL_WEAKNESS",
                          "title": "Material weakness in internal control disclosed", "quote": s})
    # One finding per code, with the clearest sentence.
    seen, out = set(), []
    for f in found:
        if f["code"] not in seen:
            seen.add(f["code"])
            out.append(f)
    return out


def going_concern(text: str) -> Optional[Dict[str, Any]]:
    for s in sentences(text):
        low = s.lower()
        if "substantial doubt" in low and "going concern" in low:
            if _HYPOTHETICAL.search(s) or re.search(r"\b(no|not)\b[^.]{0,30}substantial doubt", low):
                continue
            if re.search(r"(there is|there exists|raises?|raised|exists)\b[^.]{0,40}substantial doubt", low) or \
                    "alleviat" in low:
                sev = WATCH if "alleviat" in low else CONCERN
                return {"severity": sev, "code": "GOING_CONCERN",
                        "title": "Going-concern doubt stated" + (" (and alleviated)" if sev == WATCH else ""),
                        "quote": s}
    return None


def auditor(text: str) -> Dict[str, Any]:
    name = None
    for m in re.finditer(r"/s/\s*([^\n/|]{3,90})", text):
        cand = m.group(1).strip().rstrip(",")
        if any(k.lower() in cand.lower() for k in _AUDIT_FIRMS):
            name = re.sub(r"\s+", " ", cand)
            break
    since = re.search(r"served as the (?:Company['’]s|Corporation['’]s|Group['’]s|Partnership['’]s|Trust['’]s|"
                      r"Fund['’]s|our|its)?\s*auditors?\s+since\s+(\d{4})", text, re.I)
    cams = []
    for m in re.finditer(r"(?im)^[ |]*([A-Z][^\n|]{8,120})\s*[|]?\s*\n[^\n]{0,40}\n?.{0,300}?"
                         r"(?:Description of the Matter|Why the matter was determined|"
                         r"principal considerations for our determination)", text):
        title = m.group(1).strip(" |")
        if 8 < len(title) < 120 and title not in cams and not title.lower().startswith(("critical audit", "item")):
            cams.append(title)
    return {"name": name, "since": int(since.group(1)) if since else None, "critical_audit_matters": cams[:8]}


_CUSTOMER = re.compile(
    r"([^.]{0,120}?)\baccount(?:ed|s|ing)? for (?:approximately |about |roughly |over )?(\d{1,2}(?:\.\d)?)\s?%"
    r"[^.]{0,40}?of (?:our |the company['’]s |its |total |net |consolidated )*(?:net )?"
    r"(?:revenue|revenues|sales|net sales|total revenue)", re.I)


def customer_concentration(text: str) -> List[Dict[str, Any]]:
    out = []
    for s in sentences(text):
        m = _CUSTOMER.search(s)
        if m and re.search(r"customer|distributor|reseller|client", s, re.I):
            pct = float(m.group(2))
            if 10 <= pct <= 100:
                out.append({"pct": pct, "quote": s})
    out.sort(key=lambda x: -x["pct"])
    dedup, seen = [], set()
    for o in out:
        k = o["quote"][:80]
        if k not in seen:
            seen.add(k)
            dedup.append(o)
    return dedup[:6]


_NORM = re.compile(r"[^a-z ]+")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", _NORM.sub(" ", s.lower())).strip()


def risk_headings(section: str) -> List[str]:
    """Risk-factor headings: the short standalone lines in the section (a
    heading is one sentence on its own line; body text runs to paragraphs)."""
    out, seen = [], set()
    for line in section.split("\n"):
        # The risk-factor SUMMARY repeats each heading as a bullet.
        line = re.sub(r"^[•●◦▪\-–·o]\s+", "", line.replace(" | ", " ").strip(" |"))
        if 40 <= len(line) <= 350 and not line.lower().startswith(("item ", "table of contents")) \
                and re.search(r"[a-z]", line):
            k = _norm(line)
            if k not in seen:
                seen.add(k)
                out.append(line)
    return out


_RISK_TERMS = ("investigation", "subpoena", "restat", "material weakness", "going concern", "covenant",
               "default", "liquidity", "litigation", "lawsuit", "regulat", "tariff", "export control",
               "sanction", "customer concentration", "single customer", "cyber", "auditor", "impair", "short seller",
               "delist", "bankrupt", "fraud", "whistleblower", "department of justice", "sec ")


_MAX_PLAUSIBLE_HEADINGS = 250


def risk_factor_changes(current: str, prior: str) -> Dict[str, Any]:
    cur_h, pri_h = risk_headings(current), risk_headings(prior)
    # Some documents break every printed line into its own block (TSMC's
    # 20-F), so "short standalone lines" are just wrapped text and nothing
    # distinguishes a heading. Comparing those would report hundreds of
    # "new" risk factors.
    if len(cur_h) > _MAX_PLAUSIBLE_HEADINGS or len(pri_h) > _MAX_PLAUSIBLE_HEADINGS:
        return {"comparable": False, "headings_now": None, "headings_prior": None, "added": [], "removed": [],
                "n_added": 0, "n_removed": 0, "new_text_share": None, "added_with_red_flag_terms": [],
                "reason": "the document's layout splits paragraphs into separate lines, so risk-factor "
                          "headings cannot be told apart from body text"}
    pri_norm = [_norm(h) for h in pri_h]
    cur_norm = [_norm(h) for h in cur_h]
    added = [h for h, n in zip(cur_h, cur_norm) if not difflib.get_close_matches(n, pri_norm, n=1, cutoff=0.8)]
    removed = [h for h, n in zip(pri_h, pri_norm) if not difflib.get_close_matches(n, cur_norm, n=1, cutoff=0.8)]

    def weight(h: str) -> int:
        low = h.lower()
        return sum(t in low for t in _RISK_TERMS)
    added.sort(key=lambda h: -weight(h))
    cur_s, pri_s = set(_norm(s) for s in sentences(current)), set(_norm(s) for s in sentences(prior))
    new_share = (len(cur_s - pri_s) / len(cur_s)) if cur_s else None
    return {"comparable": True, "headings_now": len(cur_h), "headings_prior": len(pri_h),
            "added": added[:15], "removed": removed[:10],
            "n_added": len(added), "n_removed": len(removed),
            "new_text_share": None if new_share is None else round(new_share, 3),
            "added_with_red_flag_terms": [h for h in added if weight(h)][:8]}


def _annual_text(symbol: str, f: Dict[str, Any]) -> str:
    """The annual report's text, plus an EX-13 annual-report exhibit when the
    10-K incorporates its financial sections by reference (Progressive)."""
    from financial_data import gateway as gw
    doc = gw.get("filings", symbol, concepts=["document"], accession=f["accession"],
                 document=f["primary_document"], filed=f["accepted"], cik=f.get("cik"))
    text = clean(doc["data"][0]["value"] if doc["data"] else "")
    try:
        idx = gw.get("filings", symbol, concepts=["filing_documents"], accession=f["accession"], cik=f.get("cik"))
        for d in (idx["data"][0]["extra"]["documents"] if idx["data"] else []):
            if re.match(r"EX-13", d.get("type") or "") and d["document"].lower().endswith((".htm", ".html")):
                t = gw.get("filings", symbol, concepts=["document"], accession=f["accession"],
                           document=d["document"], filed=f["accepted"], cik=f.get("cik"))
                text += "\n" + clean(t["data"][0]["value"] if t["data"] else "")
    except Exception:
        pass
    return text


def amended_report_flag(symbol: str, f: Dict[str, Any]) -> Dict[str, Any]:
    """A 10-K/A that only adds Part III (directors, pay) is routine; one that
    restates is not. The text says which."""
    from financial_data import gateway as gw
    sev, detail = WATCH, f"Amended annual report filed {f['filed']}."
    try:
        doc = gw.get("filings", symbol, concepts=["document"], accession=f["accession"],
                     document=f["primary_document"], filed=f["accepted"], cik=f.get("cik"))
        head = (doc["data"][0]["value"] if doc["data"] else "")[:12000].lower()
        if re.search(r"\brestat(e|ed|ement)\b", head):
            sev, detail = CONCERN, detail + " Its opening pages discuss a restatement."
        elif "part iii" in head and len(doc["data"][0]["value"]) < 300000:
            sev, detail = INFO, detail + " It amends Part III (directors, executive pay) — routine."
    except Exception:
        pass
    return {"severity": sev, "code": "AMENDED_ANNUAL_REPORT", "title": f"Amended annual report ({f['form']})",
            "detail": detail, "evidence": {"accession": f["accession"], "url": f["url"], "filed": f["filed"]}}


def review(symbol: str, as_of: Optional[str] = None, mdna_summary: bool = False) -> Dict[str, Any]:
    """Everything the filings say, as known on `as_of`."""
    idx = filing_index(symbol, as_of)
    filings = idx["filings"]
    out: Dict[str, Any] = {"symbol": symbol.upper(), "as_of": as_of, "available": bool(filings)}
    if not filings:
        out["reason"] = (idx["unavailable"] or [{}])[0].get("reason", "no filings on record")
        return out
    flags, events = index_flags(filings, as_of)
    since = _years_before(as_of, 3)
    for f in filings:
        if f["form"] in AMENDED_ANNUAL and f["filed"] >= since:
            flags.append(amended_report_flag(symbol, f))

    annuals = [f for f in filings if f["form"] in ANNUAL]
    out["latest_annual"] = annuals[0] if annuals else None
    out["prior_annual"] = annuals[1] if len(annuals) > 1 else None
    out["recent_filings"] = [{k: f[k] for k in ("form", "filed", "accession", "url", "items")}
                             for f in filings[:15]]
    out["events"] = events[:25]

    if annuals:
        latest = annuals[0]
        form = latest["form"]
        text = _annual_text(symbol, latest)
        secs = split_sections(text, form)
        # A "section" of a few hundred characters is a cross-reference, not the
        # section (ASML's 20-F is organized by its own index, not by Item).
        secs = {k: (v if len(v) >= 2000 else "") for k, v in secs.items()}
        out["sections"] = {k: {"chars": len(v), "found": bool(v)} for k, v in secs.items()}
        missing = [k for k, v in secs.items() if not v]
        if missing:
            out["sections_note"] = ("not located in this document's layout: " + ", ".join(missing)
                                    + " — findings from those sections are not available, not clean")
        for f in control_findings(secs.get("controls") or ""):
            f["evidence"] = {"accession": latest["accession"], "url": latest["url"], "filed": latest["filed"],
                             "section": "controls"}
            flags.append(f)
        gc = going_concern(text)
        if gc:
            gc["evidence"] = {"accession": latest["accession"], "url": latest["url"], "filed": latest["filed"]}
            flags.append(gc)
        aud = auditor(text)
        if out["prior_annual"]:
            prior_text = _annual_text(symbol, out["prior_annual"])
            prior_aud = auditor(prior_text)
            aud["prior_name"] = prior_aud.get("name")
            aud["changed"] = bool(aud.get("name") and prior_aud.get("name")
                                  and _norm(aud["name"])[:12] != _norm(prior_aud["name"])[:12])
            if aud["changed"]:
                flags.append({"severity": WATCH, "code": "AUDITOR_CHANGED",
                              "title": "Auditor changed since the prior annual report",
                              "detail": f"{prior_aud['name']} → {aud['name']}",
                              "evidence": {"accession": latest["accession"], "url": latest["url"]}})
            prior_secs = split_sections(prior_text, out["prior_annual"]["form"])
            if secs.get("risk_factors") and len(prior_secs.get("risk_factors") or "") >= 2000:
                out["risk_factor_changes"] = risk_factor_changes(secs["risk_factors"], prior_secs["risk_factors"])
                rf = out["risk_factor_changes"]
                if rf["added_with_red_flag_terms"]:
                    flags.append({"severity": INFO, "code": "NEW_RISK_FACTORS",
                                  "title": f"{rf['n_added']} new risk-factor headings vs the prior report",
                                  "detail": "Including: " + " / ".join(h[:140] for h in rf["added_with_red_flag_terms"][:3]),
                                  "evidence": {"accession": latest["accession"], "url": latest["url"]}})
        out["auditor"] = aud
        conc = customer_concentration(text)
        out["customer_concentration"] = conc
        if conc and conc[0]["pct"] >= 25:
            flags.append({"severity": WATCH, "code": "CUSTOMER_CONCENTRATION",
                          "title": f"A single customer (or channel) at {conc[0]['pct']:.0f}% of revenue",
                          "quote": conc[0]["quote"],
                          "evidence": {"accession": latest["accession"], "url": latest["url"]}})
        if mdna_summary:
            from .narrative import summarize_mdna
            out["mdna_summary"] = summarize_mdna(secs.get("mdna") or "", latest)
        out["mdna_excerpt_chars"] = len(secs.get("mdna") or "")

    order = {CONCERN: 0, WATCH: 1, INFO: 2}
    flags.sort(key=lambda f: (order[f["severity"]], -(int((f.get("evidence") or {}).get("filed", "0")[:4] or 0))))
    out["flags"] = flags
    out["summary"] = {"concerns": sum(f["severity"] == CONCERN for f in flags),
                      "watch": sum(f["severity"] == WATCH for f in flags),
                      "info": sum(f["severity"] == INFO for f in flags)}
    return out
