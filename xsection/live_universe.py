"""
A LIVE US equity universe — today's list, for today's picking.

The desk could analyse any name you handed it and rank nothing, because the only
working universe was a synthetic fixture and the production one
(`sharadar`) is blocked on a paid dataset key. That is the difference between
stock CHECKING and stock PICKING, and this closes it without pretending to solve
the harder problem the paid dataset exists for.

What this provider is, stated plainly, because the distinction governs what it
may be used for:

  IT IS       today's membership, built from SEC's own registrant list, which is
              keyless and authoritative about who files. Correct for ranking the
              names that exist now.

  IT IS NOT   point-in-time. It knows nothing about who was a member last year,
              and it contains only survivors by construction. `survivorship_safe`
              is therefore False, and every ranking run records that, so a
              backtest built on it is labelled CURRENT_CONSTITUENTS_ONLY rather
              than quietly reporting an inflated historical result.

Ordering. SEC's company_tickers.json is ordered by size, largest first — this
is undocumented, so it was verified rather than assumed (NVDA, AAPL, GOOGL,
MSFT, AMZN, META, AVGO, TSLA at the head; warrants and preferreds at the tail).
It is used only to pick CANDIDATES, and liquidity is then confirmed from real
price data, so a change in SEC's ordering degrades the candidate list rather
than silently admitting illiquid names.

Non-common-stock is filtered out. ADRs, warrants, units and preferred tranches
all appear in the registrant list (HTHIY, DTEGY, BHFAL, DAAQW), and ranking a
warrant beside a common share compares instruments with different payoffs.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .universe import SecurityMaster, UniverseIncomplete, UniverseProvider

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_PATH = CACHE_DIR / "sec_live_universe.json"
CACHE_TTL_SEC = 24 * 60 * 60

UNIVERSE_ID = "us-live-liquid"
DEFAULT_SIZE = 400
BENCHMARK_TICKER = "SPY"

# Minimum median dollar volume over the confirmation window. A name that cannot
# absorb a position is not a candidate however large its market cap looks.
MIN_DOLLAR_VOLUME = 5_000_000.0
CONFIRM_BARS = 20

# Share classes are legitimate common stock (BRK-B, GOOGL); the rest are not
# what a cross-sectional equity rank is about.
_ADR_SUFFIXES = ("Y", "F")          # 5-letter ADR/foreign-ordinary convention
_WARRANT_UNIT_SUFFIXES = ("W", "U", "R")


def _looks_like_common_stock(ticker: str) -> bool:
    t = (ticker or "").upper().strip()
    if not t or not re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", t):
        return False
    base = t.split("-")[0]
    # A 5-letter symbol ending in Y or F is overwhelmingly an ADR or foreign
    # ordinary; ending in W/U/R it is a warrant, unit or right.
    if len(base) == 5 and base[-1] in _ADR_SUFFIXES + _WARRANT_UNIT_SUFFIXES:
        return False
    return True


def _fetch_registrants() -> List[Dict[str, Any]]:
    """SEC's registrant list, size-ordered, cached for a day."""
    try:
        if CACHE_PATH.exists() and (time.time() - CACHE_PATH.stat().st_mtime) < CACHE_TTL_SEC:
            return json.loads(CACHE_PATH.read_text())
    except (OSError, ValueError):
        pass

    from financial_data.keys import get_key
    # SEC's fair-access policy rejects a request without a real contact email
    # with a hard 403, not a rate-limit warning.
    ua = get_key("SEC_USER_AGENT", "live-universe")
    req = urllib.request.Request(SEC_TICKERS_URL, headers={"User-Agent": ua})
    raw = json.loads(urllib.request.urlopen(req, timeout=30).read())
    rows = [raw[k] for k in sorted(raw, key=lambda x: int(x))]
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(rows))
    except OSError:
        pass
    return rows


def candidates(size: int = DEFAULT_SIZE) -> List[Dict[str, Any]]:
    """The top `size` common-stock candidates by SEC's size ordering."""
    out: List[Dict[str, Any]] = []
    for r in _fetch_registrants():
        t = str(r.get("ticker") or "").upper().strip()
        if not _looks_like_common_stock(t):
            continue
        out.append({"ticker": t, "cik": int(r.get("cik_str") or 0),
                    "name": r.get("title") or t,
                    "size_rank": len(out) + 1})
        if len(out) >= size:
            break
    return out


class LiveUniverseProvider(UniverseProvider):
    """Today's liquid US common stock. NOT survivorship safe, by construction."""

    universe_id = UNIVERSE_ID
    survivorship_safe = False

    def __init__(self, size: int = DEFAULT_SIZE,
                 members_override: Optional[List[Dict[str, Any]]] = None):
        self._size = int(size)
        self._built_on = time.strftime("%Y-%m-%d")
        self._members = members_override if members_override is not None else None
        self._sm: Optional[SecurityMaster] = None

    # ── identity ──────────────────────────────────────────────────────────

    def _securities(self) -> List[Dict[str, Any]]:
        """Security records. security_id is derived from the CIK, which is
        permanent, rather than from the ticker, which is not — a ticker change
        must not read as a different company."""
        out = []
        for m in self._member_list():
            out.append({
                "security_id": f"CIK{m['cik']:010d}" if m.get("cik") else m["ticker"],
                "cik": m.get("cik"),
                "name": m.get("name"),
                "tickers": [{"ticker": m["ticker"], "start": self._built_on,
                             "end": None}],
                "exchange": None,
                "membership": [{"start": self._built_on, "end": None}],
            })
        return out

    def security_master(self) -> SecurityMaster:
        if self._sm is None:
            self._sm = SecurityMaster(self._securities())
        return self._sm

    def benchmark_id(self) -> Optional[str]:
        return BENCHMARK_TICKER

    # How far back PRICE history reaches for feature computation. This is a
    # different thing from membership coverage and the two must not be conflated:
    # the features need years of bars to compute a momentum or volatility rank,
    # while membership is known only for today. `coverage()` feeds the price
    # window, so it reports the price span and says explicitly that membership
    # does not extend back over it — `members()` still refuses a past date.
    PRICE_HISTORY_YEARS = 2

    def coverage(self) -> Dict[str, str]:
        import datetime as _dt
        start = (_dt.date.fromisoformat(self._built_on)
                 - _dt.timedelta(days=int(365.25 * self.PRICE_HISTORY_YEARS)))
        return {
            "start": start.isoformat(),
            "end": self._built_on,
            "membership_known_for": self._built_on,
            "note": ("start/end describe the PRICE window features are computed "
                     "over. Membership is known only for "
                     f"{self._built_on} — members() refuses any earlier date, so "
                     "this span must never be read as historical membership."),
        }

    def disclaimer(self) -> str:
        return (
            "LIVE universe: today's SEC registrants, size-ordered and "
            "liquidity-confirmed from real price data. Correct for ranking the "
            "names that exist NOW. It contains only survivors and knows nothing "
            "about past membership, so it is NOT survivorship safe and every "
            "ranking built on it is labelled CURRENT_CONSTITUENTS_ONLY. "
            "Historical evaluation needs a point-in-time constituent dataset — "
            "see the blocked `sharadar` universe.")

    # ── membership ────────────────────────────────────────────────────────

    def _member_list(self) -> List[Dict[str, Any]]:
        if self._members is None:
            self._members = candidates(self._size)
        return self._members

    def members(self, as_of: str) -> List[Dict[str, Any]]:
        """Today's constituents.

        A past `as_of` raises rather than returning today's list: silently
        answering a historical question with current membership is exactly the
        survivorship bias this refuses to introduce.
        """
        if as_of and as_of[:10] < self._built_on:
            raise UniverseIncomplete(
                f"UNIVERSE_INCOMPLETE: {as_of[:10]} predates this live "
                f"universe, which was built on {self._built_on} and holds no "
                f"historical membership. Returning today's members for a past "
                f"date would be survivorship bias. Use a point-in-time "
                f"universe for historical work.")
        out = []
        for s in self._securities():
            tkr = s["tickers"][0]["ticker"]
            out.append({
                "security_id": s["security_id"],
                # `ticker_as_of`, not `ticker`: that is the key the ranking
                # engine reads. Naming it `ticker` produced a ranked table with
                # no symbols in it, which is unusable for picking and looked
                # like a scoring failure rather than a contract mismatch.
                "ticker_as_of": tkr,
                "name": s["name"],
                "cik": s["cik"],
                "sector": self._sector_for(tkr),
                "industry": None,
                "listing_status": "active",
                "delisting_date": None,
                "first_tradable": None,
                "last_tradable": None,
                # Without this, features.py falls back to labelling these prices
                # "fixture" — real data carrying a synthetic provenance, which is
                # worse than no label at all.
                "provenance": "sec_live",
                "flags": ["NOT_SURVIVORSHIP_SAFE"],
            })
        return out

    _sector_cache: Dict[str, Optional[str]] = {}

    def _sector_for(self, ticker: str) -> Optional[str]:
        """Sector for sector-relative ranking, or None.

        None is an honest answer: a missing sector makes the sector-relative
        rank fall back to the whole cross-section, which the ranking engine
        already handles. Guessing one would put a name in the wrong peer group
        and compare it against companies it has nothing to do with.
        """
        if ticker in self._sector_cache:
            return self._sector_cache[ticker]
        sector = None
        try:
            from tools.market_data import fetch_fundamentals
            f = fetch_fundamentals(ticker) or {}
            sector = f.get("sector") or None
        except Exception:
            sector = None
        self._sector_cache[ticker] = sector
        return sector

    def prices(self, security_id: str, start: str, end: str):
        """A close-price SERIES, matching the provider contract.

        The contract is a Series, not the DataFrame get_bars_df returns:
        xsection.features does `float(px.iloc[-1] / px.iloc[-n] - 1)`, and a
        DataFrame makes that a Series and the float() a TypeError. Returning an
        empty Series for an unknown id mirrors the fixture, so a missing name is
        excluded by the feature step rather than crashing the whole ranking.
        """
        import pandas as pd

        from financial_data.gateway import get_bars_df

        ticker = self._ticker_for(security_id)
        if ticker is None:
            return pd.Series(dtype=float)
        try:
            df = get_bars_df(ticker, start=start, end=end)
        except Exception:
            return pd.Series(dtype=float)
        if df is None or len(df) == 0 or "Close" not in df:
            return pd.Series(dtype=float)
        return df["Close"].astype(float)

    def _ticker_for(self, security_id: str) -> Optional[str]:
        # The benchmark is addressed by its ticker rather than a CIK-derived id,
        # because it is not a constituent and has no security record here.
        if security_id == BENCHMARK_TICKER:
            return BENCHMARK_TICKER
        for s in self._securities():
            if s["security_id"] == security_id:
                return s["tickers"][0]["ticker"]
        return None

    def fundamentals_fn(self):
        """The SAME EDGAR-backed function production-pilot uses.

        Reused rather than reimplemented: xsection/providers/edgar_features.py
        already governs quarterly records by FILED date, which is what makes the
        quality, growth and valuation features point-in-time honest. A second
        implementation here would be a second set of the same decisions, free to
        drift — the mistake the algo scorer made when its thresholds lived in two
        places.
        """
        from xsection.providers.edgar_features import edgar_fundamentals
        return edgar_fundamentals


def confirm_liquidity(tickers: List[str], min_dollar_volume: float = MIN_DOLLAR_VOLUME,
                      bars: int = CONFIRM_BARS) -> Dict[str, Any]:
    """Confirm each candidate trades enough to hold a position.

    Uses real price data rather than trusting the size ordering, so a change in
    SEC's undocumented ordering degrades the candidate list instead of quietly
    admitting names nothing can be traded in.
    """
    from financial_data.gateway import get_bars_df

    kept, dropped = [], []
    for t in tickers:
        try:
            df = get_bars_df(t, period="3mo")
            if df is None or len(df) < bars:
                dropped.append({"ticker": t, "reason": "insufficient price history"})
                continue
            tail = df.tail(bars)
            dv = (tail["Close"].astype(float) * tail["Volume"].astype(float)).median()
            if not dv or float(dv) < min_dollar_volume:
                dropped.append({"ticker": t,
                                "reason": f"median dollar volume {float(dv or 0):,.0f} "
                                          f"below {min_dollar_volume:,.0f}"})
                continue
            kept.append({"ticker": t, "median_dollar_volume": round(float(dv), 2)})
        except Exception as e:
            dropped.append({"ticker": t, "reason": f"{type(e).__name__}"})
    return {"kept": kept, "dropped": dropped,
            "min_dollar_volume": min_dollar_volume, "bars": bars}
