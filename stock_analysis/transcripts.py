"""
The latest earnings call — transcript from Alpha Vantage or FMP (free-tier
keys), summarized by the validated LLM step (stock_analysis/narrative.py).

Without a transcript key, or when the vendor's plan excludes transcripts,
the section says which; without DeepSeek, the transcript's existence and
speakers are reported and the summary is marked unavailable.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _fiscal_quarter(statements: Dict[str, Any]) -> Optional[tuple]:
    qs = statements.get("quarters") or []
    if not qs:
        return None
    label = qs[0]["label"]              # "FY2027 Q2"
    try:
        return int(label[2:6]), int(label.split("Q")[-1])
    except (ValueError, IndexError):
        return None


def _previous(year: int, q: int) -> tuple:
    return (year, q - 1) if q > 1 else (year - 1, 4)


def build_transcript(symbol: str, statements: Dict[str, Any], summarize: bool = True) -> Dict[str, Any]:
    """The latest call on file; when the vendor does not have it yet (Alpha
    Vantage lags weeks), the one before, saying so."""
    from financial_data import gateway as gw
    fq = _fiscal_quarter(statements)
    if not fq:
        return {"available": False, "reason": "no quarterly statements to locate the latest call"}
    tried = []
    waiting = set()
    for year, q in (fq, _previous(*fq)):
        for prov, kw in (("alphavantage", {"quarter": f"{year}Q{q}"}), ("fmp", {"year": year, "quarter": q})):
            if prov in waiting:
                continue
            try:
                res = gw.get("filings", symbol, provider=prov, concepts=["call_transcript"], **kw)
            except Exception as e:
                msg = str(e)
                for var in ("ALPHAVANTAGE_API_KEY", "FMP_API_KEY"):
                    if var in msg:
                        msg = f"waiting for {var}"
                        waiting.add(prov)
                tried.append(f"{prov}: {msg[:140]}")
                continue
            if res["data"]:
                d = res["data"][0]
                out = {"available": True, "provider": prov, "fiscal_quarter": f"FY{year} Q{q}",
                       "chars": len(d["value"]), "source": d["source"]}
                if (year, q) != fq:
                    out["note"] = (f"the FY{fq[0]} Q{fq[1]} call is not available from the vendor yet; "
                                   f"this is the call before it")
                if summarize:
                    from .narrative import summarize_transcript
                    out["summary"] = summarize_transcript(d["value"], {**d["source"], "quarter": f"{year}Q{q}"})
                return out
            tried.append(f"{prov} FY{year} Q{q}: " +
                         ((res.get("unavailable") or [{}])[0].get("reason") or "no transcript"))
    return {"available": False, "reason": "; ".join(tried)}
