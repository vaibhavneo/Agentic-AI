"""
Equity or options — the same view, on the same terms.

The brief already decided WHETHER to look at options ("the desk has a bullish
view, and options are how that view is expressed with a defined worst case") and
then offered three structures. What it never did was put the equity and the
option side by side on terms a reader could compare, so "stock or option" was
implied and never answered.

The comparison is only meaningful under a COMMON NORMALISATION, and the choice
of normalisation is the whole design. One share against one contract compares
nothing: a contract controls a hundred shares, so the option always looks
enormous. Equal NOTIONAL hides the leverage that is the point of the option.
This normalises on EQUAL CAPITAL AT RISK — the amount a reader is actually
deciding to put at risk — and then asks what each does with it. Leverage then
shows up where it belongs: as notional exposure per dollar risked.

Three asymmetries the table states rather than smoothing over, because each can
reverse the decision:

  THE STOP IS NOT A CONTRACT. Equity risk to an invalidation level assumes the
  stop fills there. A gap through it loses more, and on a name at beta 3.3 that
  is not a remote case. An option's maximum loss is contractual and cannot be
  exceeded.

  OPTIONS EXPIRE. A thesis that is right on the wrong schedule loses the entire
  premium and costs the equity holder nothing. That is not a risk premium, it is
  a different bet, and theta per day prices it.

  PRICING SOURCE IS NOT FORECAST QUALITY. Using the market's implied volatility
  makes the PREMIUM right — it is what you would actually pay. It does not make
  the direction more predictable, and nothing in this system has demonstrated a
  directional edge that would justify claiming otherwise.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# The capital-at-risk figure every row is normalised to. A round number is used
# deliberately: the table is a comparison of shapes, not a position size, and
# sizing is gated elsewhere by the statistical bar.
REFERENCE_RISK_CAPITAL = 1000.0

MARKET = "MARKET"
MODEL = "MODEL"


def _payoff_at(structure: str, legs: List[Dict[str, Any]],
               spot: float) -> Optional[float]:
    """Intrinsic value of the legs at a settlement price, per share."""
    try:
        from mas.pricing.payoff import payoff_at
        from mas.pricing.structures import Leg, Structure
        built = Structure(name=structure or "custom",
                          legs=[Leg(kind=l["kind"], strike=float(l["strike"]),
                                    qty=float(l["qty"])) for l in legs])
        return float(payoff_at(built, float(spot)))
    except Exception:
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


def _stop_in_daily_sigma(spot: float, stop: float,
                         vol_annual_pct: Optional[float],
                         days_per_year: int = 252) -> Optional[float]:
    """How many daily standard deviations away the stop sits.

    This is the number that decides whether the equity row means anything. Equal
    capital at risk turns a TIGHT stop into enormous leverage — a 2.4% stop on a
    $45 name buys 909 shares for $1,000 of stated risk, which is 41x notional —
    and that leverage is only real if the stop is not taken out by noise.

    At 79% implied volatility a day is about 4.98%, so a 2.4% stop is HALF a
    daily move. It would be hit by ordinary noise almost immediately, and the
    1,320% return-on-risk the arithmetic produces describes a position nobody
    would still hold. Reporting the ratio makes that visible instead of leaving
    it to be discovered.
    """
    if not vol_annual_pct or vol_annual_pct <= 0 or spot <= 0:
        return None
    daily_sigma_pct = vol_annual_pct / (days_per_year ** 0.5)
    stop_pct = abs(spot - stop) / spot * 100.0
    if daily_sigma_pct <= 0:
        return None
    return round(stop_pct / daily_sigma_pct, 2)


def _equity_row(spot: float, stop: float, target: float,
                risk_capital: float,
                vol_annual_pct: Optional[float] = None) -> Dict[str, Any]:
    risk_per_share = spot - stop
    if risk_per_share <= 0:
        return {"instrument": "EQUITY", "status": "NOT_COMPARABLE",
                "reason": (f"the invalidation level {stop:,.2f} is not below the "
                           f"price {spot:,.2f}, so there is no defined risk per "
                           f"share to normalise on")}
    shares = risk_capital / risk_per_share
    gain_at_target = shares * (target - spot)
    sigmas = _stop_in_daily_sigma(spot, stop, vol_annual_pct)
    caveats = [
        "the maximum loss assumes the stop FILLS at the invalidation level; "
        "a gap through it loses more, and there is no contractual floor",
        "no expiry — a thesis that is right late still pays",
    ]
    if sigmas is not None and sigmas < 1.0:
        caveats.insert(0, (
            f"THE STOP IS INSIDE ONE DAILY MOVE ({sigmas:.2f} sigma). At this "
            f"volatility it is likely to be hit by ordinary noise before the "
            f"thesis resolves either way, so the leverage this row shows — and "
            f"the return-on-risk with it — describes a position that would not "
            f"survive to reach the target."))
    return {
        "instrument": "EQUITY",
        "status": "OK",
        "how": (f"{shares:,.1f} shares at {spot:,.2f}, exiting at the "
                f"{stop:,.2f} invalidation"),
        "capital_at_risk": round(risk_capital, 2),
        "notional_exposure": round(shares * spot, 2),
        "leverage_x": round(shares * spot / risk_capital, 2),
        "max_loss": round(-risk_capital, 2),
        "max_loss_is_contractual": False,
        "max_gain": None,                      # unbounded
        "max_gain_unbounded": True,
        "gain_at_target": round(gain_at_target, 2),
        "return_on_risk_at_target_pct": round(100.0 * gain_at_target
                                              / risk_capital, 1),
        "breakeven": round(spot, 2),
        "expires": None,
        "theta_per_day": 0.0,
        "stop_distance_pct": round(100.0 * risk_per_share / spot, 2),
        "stop_in_daily_sigma": sigmas,
        "stop_survivable": (None if sigmas is None else bool(sigmas >= 1.0)),
        "pricing_source": MARKET,
        "pricing_note": "the traded price of the share; nothing is modelled",
        "caveats": caveats,
    }


def _option_row(cand: Dict[str, Any], spot: float, target: float,
                risk_capital: float, expiry: Optional[str],
                multiplier: float, pricing_source: str,
                vol_basis: Optional[str]) -> Dict[str, Any]:
    max_loss = cand.get("max_loss")
    if max_loss in (None, 0):
        return {"instrument": cand.get("structure"), "status": "NOT_COMPARABLE",
                "reason": ("this structure has no bounded maximum loss, so it "
                           "cannot be normalised on capital at risk")}
    per_set_risk = abs(float(max_loss))
    sets = risk_capital / per_set_risk

    payoff = _payoff_at(cand.get("structure"), cand.get("legs") or [], target)
    net_cost = float(cand.get("net_cost") or 0.0)

    # P&L = settlement payoff MINUS what the position cost, and the sign of
    # net_cost is the trap: it is negative for a CREDIT structure (-189.41 means
    # 189.41 received). Adding it instead of subtracting turned a kept credit
    # into a paid debit and reported a 130% loss on a structure whose maximum
    # loss is contractually 100% — checkable against max_gain, which is exactly
    # -net_cost for a credit structure that expires worthless.
    gain_at_target = ((payoff * multiplier - net_cost) * sets
                      if payoff is not None else None)

    # A contractual maximum loss cannot be exceeded, so a computed loss beyond
    # it is arithmetic error rather than a worse outcome. Clamping silently
    # would hide the next such bug, so it is asserted into the row instead.
    if gain_at_target is not None and gain_at_target < -risk_capital * 1.001:
        return {"instrument": cand.get("structure"), "status": "INCONSISTENT",
                "reason": (f"computed loss at target "
                           f"({gain_at_target:,.2f}) exceeds the contractual "
                           f"maximum ({-risk_capital:,.2f}); the structure's "
                           f"payoff and its stated max_loss disagree")}

    greeks = cand.get("greeks") or {}
    theta = greeks.get("theta")
    bes = cand.get("breakevens") or []

    return {
        "instrument": cand.get("structure"),
        "label": cand.get("label"),
        "status": "OK",
        "how": (f"{sets:,.2f} contract set(s) — {cand.get('legs_text') or ''}"),
        "capital_at_risk": round(risk_capital, 2),
        "notional_exposure": round(sets * abs(
            sum(abs(float(l.get("qty") or 0)) * float(l.get("strike") or 0)
                for l in (cand.get("legs") or []))) * multiplier, 2),
        "leverage_x": None,
        "max_loss": round(-risk_capital, 2),
        "max_loss_is_contractual": True,
        "max_gain": (round(float(cand["max_gain"]) * sets, 2)
                     if cand.get("max_gain") is not None else None),
        "max_gain_unbounded": bool(cand.get("max_gain_unbounded")),
        "gain_at_target": (round(gain_at_target, 2)
                           if gain_at_target is not None else None),
        "return_on_risk_at_target_pct": (
            round(100.0 * gain_at_target / risk_capital, 1)
            if gain_at_target is not None else None),
        "breakeven": (round(float(bes[0]), 2) if bes else None),
        "breakevens": [round(float(b), 2) for b in bes],
        "expires": expiry,
        "theta_per_day": (round(float(theta) * multiplier * sets, 2)
                          if theta is not None else None),
        "probability_of_profit": cand.get("probability_of_profit"),
        "probability_basis": cand.get("probability_basis"),
        "pricing_source": pricing_source,
        "pricing_note": (
            "premium from the market's own implied volatility"
            if vol_basis == "IMPLIED_BY_CHAIN" else
            "premium MODELLED from realized volatility — the market may charge "
            "materially more or less than this"),
        "caveats": [
            "the maximum loss is contractual and cannot be exceeded",
            (f"expires {expiry} — a thesis that is right after that date pays "
             f"nothing" if expiry else "expiry unknown"),
        ],
    }


def compare(options_section: Optional[Dict[str, Any]],
            spot: Optional[float],
            invalidation: Optional[float],
            target: Optional[float],
            risk_capital: float = REFERENCE_RISK_CAPITAL) -> Dict[str, Any]:
    """Equity against each option structure, normalised on capital at risk."""
    if not spot or spot <= 0:
        return {"status": "UNAVAILABLE",
                "reason": "no usable spot price to normalise against"}
    if invalidation is None or target is None:
        missing = [n for n, v in (("invalidation", invalidation),
                                  ("target", target)) if v is None]
        return {"status": "UNAVAILABLE",
                "reason": (f"a comparison needs both a downside and an upside "
                           f"reference; missing: {', '.join(missing)}. Inventing "
                           f"either would make every row a guess wearing the "
                           f"same formatting as a measurement.")}

    sec = options_section or {}
    vol_basis = sec.get("volatility_basis")
    # The market's implied volatility, where there is one, is the right scale for
    # judging whether a stop survives — it is what the market expects to happen,
    # not what already did.
    vol_pct = (sec.get("volatility_annualized_pct")
               or sec.get("volatility_realized_pct"))

    rows = [_equity_row(float(spot), float(invalidation), float(target),
                        risk_capital, vol_annual_pct=vol_pct)]
    pricing_source = MARKET if vol_basis == "IMPLIED_BY_CHAIN" else MODEL
    mult = float(sec.get("contract_multiplier") or 100.0)
    expiry = sec.get("expiry")
    for cand in (sec.get("candidates") or [])[:3]:
        rows.append(_option_row(cand, float(spot), float(target), risk_capital,
                                expiry, mult, pricing_source, vol_basis))

    # A stop inside one daily move makes the equity row's leverage notional
    # rather than achievable, so it must not silently win the comparison.
    eq = rows[0]
    if eq.get("status") == "OK" and eq.get("stop_survivable") is False:
        eq["return_on_risk_at_target_pct_note"] = (
            "computed, but not achievable at this stop distance")

    comparable = [r for r in rows if r.get("status") == "OK"]
    best = None
    if len(comparable) > 1:
        scored = [r for r in comparable
                  if r.get("return_on_risk_at_target_pct") is not None
                  and r.get("stop_survivable") is not False]
        if scored:
            best = max(scored,
                       key=lambda r: r["return_on_risk_at_target_pct"])["instrument"]

    return {
        "status": "OK",
        "normalised_on": "EQUAL_CAPITAL_AT_RISK",
        "risk_capital": risk_capital,
        "spot": round(float(spot), 4),
        "invalidation": round(float(invalidation), 4),
        "target": round(float(target), 4),
        "target_move_pct": round(100.0 * (float(target) / float(spot) - 1.0), 2),
        "downside_move_pct": round(
            100.0 * (float(invalidation) / float(spot) - 1.0), 2),
        "rows": rows,
        "highest_return_at_target": best,
        "pricing_source": pricing_source,
        "how_to_read": (
            f"Every row risks the same {risk_capital:,.0f}. The equity row "
            f"converts that into shares using the distance to the invalidation; "
            f"each option row converts it into contract sets using the "
            f"structure's contractual maximum loss. `gain_at_target` is what "
            f"each returns if the price reaches {float(target):,.2f}."),
        "what_this_does_not_say": (
            "Nothing here forecasts the target being reached. Pricing options "
            "from the market's implied volatility makes the PREMIUM right, not "
            "the direction predictable — and no component of this system has "
            "demonstrated a forward directional edge. The table compares the "
            "SHAPE of two exposures to the same view, and the view itself is "
            "still the reader's."
            if pricing_source == MARKET else
            "The option premiums here are MODELLED from realized volatility "
            "because no chain was reachable, so they may differ materially from "
            "what the market charges. Treat the option rows as indicative shapes "
            "rather than prices."),
    }
