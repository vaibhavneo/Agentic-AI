"""
Outcome tracking for options recommendations — the half of the desk that has
never been graded at all.

The equity side freezes a call and grades it; the options side produced
structures, quoted a probability of profit, and never once checked. The brief
even says so in every candidate it emits: `probability_basis` reads "not a
measured frequency and not the market's own number". This is the module that
makes it one.

An options recommendation carries TWO separable claims, and grading them
together would hide which one is wrong:

  DIRECTION   did the underlying finish where the structure needed it to?
  VOLATILITY  was the volatility the engine priced with anything like what
              the underlying actually delivered over the holding period?

Keeping them apart matters because they have different fixes. A desk that is
right on direction and systematically wrong on vol is mispricing every
structure in a predictable direction — and since this engine prices from
REALIZED_30_BAR volatility, a persistent gap between trailing realized vol and
forward realized vol is a correctable bias, not bad luck. A desk that is right
on vol and wrong on direction has a signal problem instead.

Payoff is computed at EXPIRY from the settled close, through the same
mas.pricing.payoff the recommendation was built with. Marking to an
intermediate price would be a different claim than the one that was made.

As everywhere else in this system: nothing here places, closes or simulates
an order. It scores a recommendation that was already made.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS options_snapshots (
    snapshot_id   TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    epoch         REAL NOT NULL,
    ticker        TEXT NOT NULL,
    asset_class   TEXT,
    structure     TEXT NOT NULL,
    legs_json     TEXT NOT NULL,
    expiry        TEXT NOT NULL,
    days_to_expiry INTEGER,
    spot_at_call  REAL NOT NULL,
    net_cost      REAL,
    max_gain      REAL,
    max_loss      REAL,
    breakevens_json TEXT,
    stated_pop    REAL,
    vol_used_pct  REAL,
    vol_basis     TEXT,
    view          TEXT,
    is_model_priced INTEGER,
    source_json   TEXT
);
CREATE TABLE IF NOT EXISTS options_outcomes (
    snapshot_id        TEXT PRIMARY KEY,
    evaluated_at       TEXT NOT NULL,
    matured            INTEGER NOT NULL DEFAULT 0,
    spot_at_expiry     REAL,
    payoff             REAL,
    profit             REAL,
    profitable         INTEGER,
    return_on_risk_pct REAL,
    realized_vol_pct   REAL,
    vol_error_pct      REAL,
    n_bars             INTEGER,
    reason             TEXT
);
CREATE INDEX IF NOT EXISTS idx_options_snapshots_expiry
    ON options_snapshots(expiry);

CREATE TRIGGER IF NOT EXISTS options_snapshots_no_update
BEFORE UPDATE ON options_snapshots
BEGIN SELECT RAISE(ABORT, 'a frozen options recommendation is immutable'); END;
CREATE TRIGGER IF NOT EXISTS options_snapshots_no_delete
BEFORE DELETE ON options_snapshots
BEGIN SELECT RAISE(ABORT, 'a frozen options recommendation is immutable'); END;
"""

_ready: set = set()

TRADING_DAYS = 252


def _conn() -> sqlite3.Connection:
    from data import prediction_ledger as PL
    path = PL._db()
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    if path not in _ready:
        conn.executescript(_SCHEMA)
        conn.commit()
        _ready.add(path)
    return conn


def _fingerprint(payload: Dict[str, Any]) -> str:
    import hashlib
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def freeze(brief: Dict[str, Any], candidate: Optional[Dict[str, Any]] = None
           ) -> Optional[str]:
    """Freeze one options recommendation. Idempotent on content.

    `candidate` defaults to the top-ranked one — the recommendation actually
    made. Freezing all of them would grade ideas nobody was given.
    """
    cands = brief.get("candidates") or []
    cand = candidate or (cands[0] if cands else None)
    if not cand or not brief.get("ticker") or not brief.get("expiry"):
        return None
    spot = brief.get("spot")
    if not spot:
        return None

    payload = {
        "ticker": str(brief["ticker"]).upper(),
        "structure": cand.get("structure"),
        "legs": cand.get("legs"),
        "expiry": str(brief["expiry"])[:10],
        "spot": round(float(spot), 6),
        "net_cost": cand.get("net_cost"),
    }
    sid = _fingerprint(payload)
    now = time.time()
    try:
        conn = _conn()
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO options_snapshots
                   (snapshot_id, created_at, epoch, ticker, asset_class,
                    structure, legs_json, expiry, days_to_expiry, spot_at_call,
                    net_cost, max_gain, max_loss, breakevens_json, stated_pop,
                    vol_used_pct, vol_basis, view, is_model_priced, source_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                 now, payload["ticker"], brief.get("asset_class"),
                 cand.get("structure"), json.dumps(cand.get("legs") or []),
                 payload["expiry"], brief.get("days_to_expiry"),
                 float(spot), cand.get("net_cost"), cand.get("max_gain"),
                 cand.get("max_loss"),
                 json.dumps(cand.get("breakevens") or []),
                 cand.get("probability_of_profit"),
                 brief.get("volatility_annualized_pct"),
                 brief.get("volatility_basis"), brief.get("view"),
                 1 if brief.get("is_model_priced") else 0,
                 json.dumps(brief.get("source") or {}, default=str)))
        conn.close()
        return sid
    except sqlite3.Error:
        return None


def _payoff(structure_name: str, legs: List[Dict[str, Any]], spot: float
            ) -> Optional[float]:
    """Intrinsic value of the legs at settlement, per contract-set."""
    try:
        from mas.pricing.structures import Leg, Structure
        from mas.pricing.payoff import payoff_at
        built = Structure(name=structure_name or "custom",
                          legs=[Leg(kind=l["kind"], strike=float(l["strike"]),
                                    qty=float(l["qty"])) for l in legs])
        return float(payoff_at(built, float(spot)))
    except Exception:
        # Fall back to the arithmetic directly rather than dropping the row:
        # a structure that cannot be reconstructed is still gradeable, and
        # refusing to grade it would quietly bias the record toward the
        # structures that happen to rebuild cleanly.
        try:
            total = 0.0
            for l in legs:
                k, strike, qty = l["kind"], float(l["strike"]), float(l["qty"])
                intrinsic = (max(0.0, spot - strike) if k == "call"
                             else max(0.0, strike - spot))
                total += qty * intrinsic
            return total
        except Exception:
            return None


def _realized_vol_pct(ticker: str, start: str, end: str) -> Optional[tuple]:
    """Annualised realised volatility of daily closes over [start, end]."""
    try:
        from financial_data.gateway import get_bars_df
        df = get_bars_df(ticker, start=start, end=end)
        if df is None or len(df) < 5:
            return None
        closes = [float(c) for c in df["Close"].tolist() if c and float(c) > 0]
        if len(closes) < 5:
            return None
        rets = [math.log(b / a) for a, b in zip(closes, closes[1:])]
        n = len(rets)
        mean = sum(rets) / n
        var = sum((r - mean) ** 2 for r in rets) / (n - 1)
        return (math.sqrt(var * TRADING_DAYS) * 100.0, n)
    except Exception:
        return None


def grade(limit: int = 500, today: Optional[str] = None) -> Dict[str, Any]:
    """Grade every frozen recommendation whose expiry has passed. Idempotent.

    A multiplier of 100 is applied to the payoff because legs are quoted per
    share while net_cost is per contract. Getting that wrong would make every
    structure look like it moved a hundredth of what it did.
    """
    from financial_data.gateway import get_bars_df

    day = today or time.strftime("%Y-%m-%d")
    graded = errors = skipped = 0
    try:
        conn = _conn()
        rows = conn.execute(
            """SELECT s.* FROM options_snapshots s
               LEFT JOIN options_outcomes o ON o.snapshot_id = s.snapshot_id
               WHERE s.expiry <= ? AND (o.matured IS NULL OR o.matured = 0)
               ORDER BY s.expiry ASC LIMIT ?""", (day, int(limit))).fetchall()
    except sqlite3.Error as e:
        return {"graded": 0, "error": str(e)}

    for r in rows:
        sid = r["snapshot_id"]
        reason = ""
        spot_exp = payoff = profit = ror = rv = verr = None
        n_bars = None
        try:
            df = get_bars_df(r["ticker"], start=r["expiry"], end=None)
            closes = ([float(c) for c in df["Close"].tolist()]
                      if df is not None and len(df) else [])
            if not closes:
                reason = "no settled bar at or after expiry"
                skipped += 1
            else:
                spot_exp = closes[0]
                legs = json.loads(r["legs_json"] or "[]")
                raw = _payoff(r["structure"], legs, spot_exp)
                if raw is None:
                    reason = "the structure could not be valued at settlement"
                    errors += 1
                else:
                    # net_cost is per contract (already x100); the leg payoff
                    # is per share.
                    payoff = raw * 100.0
                    profit = payoff + float(r["net_cost"] or 0.0)
                    risk = abs(float(r["max_loss"] or 0.0)) or None
                    ror = (profit / risk * 100.0) if risk else None
                    rvn = _realized_vol_pct(r["ticker"],
                                            str(r["created_at"])[:10], r["expiry"])
                    if rvn:
                        rv, n_bars = rvn
                        if r["vol_used_pct"]:
                            # Signed: positive means the engine priced with
                            # MORE vol than the underlying delivered, which
                            # makes long premium look better than it was.
                            verr = float(r["vol_used_pct"]) - rv
                    graded += 1
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
            errors += 1

        try:
            with conn:
                conn.execute(
                    """INSERT OR REPLACE INTO options_outcomes
                       (snapshot_id, evaluated_at, matured, spot_at_expiry,
                        payoff, profit, profitable, return_on_risk_pct,
                        realized_vol_pct, vol_error_pct, n_bars, reason)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, time.strftime("%Y-%m-%dT%H:%M:%S"),
                     1 if profit is not None else 0, spot_exp, payoff, profit,
                     (1 if (profit or 0) > 0 else 0) if profit is not None else None,
                     ror, rv, verr, n_bars, reason))
        except sqlite3.Error:
            errors += 1
    conn.close()
    return {"graded": graded, "skipped": skipped, "errors": errors,
            "considered": len(rows)}


def report() -> Dict[str, Any]:
    """The options track record, decomposed into its two claims."""
    try:
        conn = _conn()
        rows = [dict(r) for r in conn.execute(
            """SELECT s.structure, s.stated_pop, s.vol_used_pct, s.vol_basis,
                      o.profitable, o.return_on_risk_pct, o.realized_vol_pct,
                      o.vol_error_pct
                 FROM options_snapshots s
                 JOIN options_outcomes o ON o.snapshot_id = s.snapshot_id
                WHERE o.matured = 1""").fetchall()]
        conn.close()
    except sqlite3.Error:
        return {"available": False}

    if not rows:
        return {"available": True, "n": 0,
                "statement": ("No options recommendation has matured yet. The "
                              "record starts the first time a frozen structure "
                              "passes its expiry.")}

    def _mean(vs):
        vs = [v for v in vs if v is not None]
        return round(sum(vs) / len(vs), 4) if vs else None

    wins = [r for r in rows if r["profitable"]]
    stated = _mean([r["stated_pop"] for r in rows])
    realized_rate = round(len(wins) / len(rows), 4)

    by_structure: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        b = by_structure.setdefault(r["structure"] or "unknown",
                                    {"n": 0, "wins": 0, "ror": []})
        b["n"] += 1
        b["wins"] += 1 if r["profitable"] else 0
        if r["return_on_risk_pct"] is not None:
            b["ror"].append(r["return_on_risk_pct"])
    for b in by_structure.values():
        b["win_rate"] = round(b["wins"] / b["n"], 4)
        b["mean_return_on_risk_pct"] = _mean(b.pop("ror"))

    vol_err = _mean([r["vol_error_pct"] for r in rows])
    return {
        "available": True, "n": len(rows),
        "direction_claim": {
            "stated_probability_of_profit": stated,
            "realized_win_rate": realized_rate,
            "gap": (round(stated - realized_rate, 4)
                    if stated is not None else None),
        },
        "volatility_claim": {
            "mean_vol_error_pct": vol_err,
            "interpretation": (
                None if vol_err is None else
                (f"the engine priced with {abs(vol_err):.2f} points MORE "
                 f"volatility than the underlying delivered, which flatters "
                 f"long premium and penalises short premium"
                 if vol_err > 0 else
                 f"the engine priced with {abs(vol_err):.2f} points LESS "
                 f"volatility than the underlying delivered, which "
                 f"under-prices long premium")),
        },
        "by_structure": by_structure,
    }
