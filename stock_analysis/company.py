"""
Who the company is: SEC registrant profile and the industry type that decides
which analyses even apply.

A bank's "operating cash flow" swings by hundreds of billions with its trading
book (JPM: −$212B one quarter, +$120B another) — dividing it by net income is
not a measure of earnings quality, it is noise. Beneish and Altman were built
on industrial companies and say so. So every metric downstream asks
`industry_kind` first and reports NOT_APPLICABLE with the reason, rather than
computing a number that only looks meaningful.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# SEC Standard Industrial Classification ranges.
_BANK = [(6020, 6036)]
_CREDIT = [(6111, 6199)]
_BROKER = [(6200, 6299)]
_INSURER = [(6300, 6411)]
_REIT = [(6798, 6798)]
_OTHER_FIN = [(6700, 6797), (6799, 6799)]
_MANUFACTURING = [(2000, 3999)]


def _in(sic: int, ranges) -> bool:
    return any(lo <= sic <= hi for lo, hi in ranges)


def industry_kind(sic: Optional[str]) -> str:
    """bank | credit | broker | insurer | reit | other_financial | manufacturing | industrial | unknown"""
    try:
        n = int(sic)
    except (TypeError, ValueError):
        return "unknown"
    for kind, rng in (("bank", _BANK), ("credit", _CREDIT), ("broker", _BROKER), ("insurer", _INSURER),
                      ("reit", _REIT), ("other_financial", _OTHER_FIN), ("manufacturing", _MANUFACTURING)):
        if _in(n, rng):
            return kind
    return "industrial"


FINANCIAL_KINDS = {"bank", "credit", "broker", "insurer", "other_financial"}


def is_financial(kind: str) -> bool:
    return kind in FINANCIAL_KINDS


def profile(symbol: str) -> Dict[str, Any]:
    """Registrant profile through the gateway; never raises."""
    from financial_data import gateway as gw
    try:
        res = gw.get("filings", symbol, concepts=["company_profile"])
    except Exception as e:
        return {"symbol": symbol.upper(), "available": False, "reason": str(e), "industry_kind": "unknown"}
    if not res["data"]:
        reason = (res.get("unavailable") or [{}])[0].get("reason", "not an SEC registrant")
        return {"symbol": symbol.upper(), "available": False, "reason": reason, "industry_kind": "unknown"}
    ex = dict(res["data"][0].get("extra") or {})
    ex["symbol"] = symbol.upper()
    ex["available"] = True
    ex["industry_kind"] = industry_kind(ex.get("sic"))
    return ex
