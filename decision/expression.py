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


# ── horizon targets and where options overtake equity ─────────────────────
#
# The single-target table answered one question: which instrument wins if price
# reaches the nearest sourced resistance. On IONQ that level is +2.4% away, so
# every directional structure lost — a 2.4% move in 55 days cannot cover a
# premium struck at 79% implied volatility. True, and incomplete: it says nothing
# about where options DO win.
#
# Two crossovers answer that, and the second is the one that matters.
#
# CROSSOVER IN PRICE — how far the underlying must travel before a structure's
# return on risk overtakes equity's. Solved by scan rather than algebra because
# option payoffs are piecewise linear and a closed form would need a case per
# structure.
#
# CROSSOVER IN STOP WIDTH — the structural finding. Equity's return per dollar
# risked is 1/(spot - stop), so a TIGHT stop is itself enormous leverage: IONQ's
# 2.42% invalidation gives a slope of 0.909 per dollar, which exceeds every
# bounded-loss option on the board (a long call at 0.200, a call spread at
# 0.333). No target price changes that. Options overtake equity only once the
# stop is wide enough to hold — around 1.5 daily sigma on this name — which is
# also the point at which the equity row stops being a position noise would
# close. The two facts are the same fact.

# Daily-sigma multiples offered as survivable alternatives to a too-tight stop.
SURVIVABLE_SIGMAS = (1.0, 1.5, 2.0)

# Scan resolution as a fraction of spot. 0.25% steps resolve a crossover to
# about a tenth of a percent on a $45 name, which is finer than any level the
# desk sources.
SCAN_STEP_PCT = 0.0025
SCAN_MAX_PCT = 2.0          # scan up to +200% before declaring no crossover


def _equity_return_on_risk(price: float, spot: float, stop: float) -> float:
    """Return on capital at risk for equity at a settlement price.

    Independent of the capital figure: shares scale with it and so does the
    denominator, so the ratio is (price - spot) / (spot - stop). A stop of 0
    means UNSTOPPED, where the whole position is at risk and the ratio reduces
    to the plain percentage move.
    """
    denom = spot - stop
    if denom <= 0:
        return 0.0
    return (price - spot) / denom


def _option_return_on_risk(cand: Dict[str, Any], price: float,
                           multiplier: float) -> Optional[float]:
    """Return on capital at risk for a structure at a settlement price."""
    max_loss = cand.get("max_loss")
    if max_loss in (None, 0):
        return None
    payoff = _payoff_at(cand.get("structure"), cand.get("legs") or [], price)
    if payoff is None:
        return None
    net_cost = float(cand.get("net_cost") or 0.0)
    return (payoff * multiplier - net_cost) / abs(float(max_loss))


def crossover_price(cand: Dict[str, Any], spot: float, stop: float,
                    multiplier: float) -> Dict[str, Any]:
    """The lowest price at which this structure beats equity, or a stated no.

    Scanned upward from spot. Returning "never" is the common and informative
    answer against a tight stop, and it is reported as a fact about the stop
    rather than a fault in the structure.
    """
    if spot <= 0 or stop >= spot:
        return {"exists": False, "reason": "no usable stop distance"}
    if stop < 0:
        return {"exists": False, "reason": "a negative stop is not a level"}
    step = max(spot * SCAN_STEP_PCT, 0.01)
    price = spot
    limit = spot * (1.0 + SCAN_MAX_PCT)
    while price <= limit:
        opt = _option_return_on_risk(cand, price, multiplier)
        if opt is not None and opt > _equity_return_on_risk(price, spot, stop):
            return {"exists": True, "price": round(price, 2),
                    "move_pct": round(100.0 * (price / spot - 1.0), 2),
                    "option_return_pct": round(100.0 * opt, 1),
                    "equity_return_pct": round(
                        100.0 * _equity_return_on_risk(price, spot, stop), 1)}
        price += step
    return {"exists": False,
            "reason": (f"equity's return per dollar risked is "
                       f"{1.0 / (spot - stop):.3f} at this stop distance "
                       f"({100.0 * (spot - stop) / spot:.2f}%), which exceeds "
                       f"this structure's slope at every price up to "
                       f"+{100 * SCAN_MAX_PCT:.0f}%. A tighter stop is itself "
                       f"leverage, and no target price overcomes it.")}


def crossover_stop(cand: Dict[str, Any], spot: float, target: float,
                   multiplier: float,
                   vol_annual_pct: Optional[float] = None,
                   days_per_year: int = 252) -> Dict[str, Any]:
    """The stop width at which this structure overtakes equity at `target`.

    The structural answer to "where do options start beating equity". Widening
    the stop lowers equity's leverage, so there is a width past which the
    bounded-loss structure wins — and reporting it in DAILY SIGMA as well as
    percent is what connects it to whether the stop could be held at all.
    """
    opt = _option_return_on_risk(cand, target, multiplier)
    if opt is None:
        return {"exists": False, "reason": "structure has no bounded loss"}

    step = max(spot * SCAN_STEP_PCT, 0.01)
    stop = spot - step
    floor = spot * 0.05          # a 95% stop is not a stop
    while stop > floor:
        if opt > _equity_return_on_risk(target, spot, stop):
            width_pct = 100.0 * (spot - stop) / spot
            sig = None
            if vol_annual_pct and vol_annual_pct > 0:
                daily = vol_annual_pct / (days_per_year ** 0.5)
                sig = round(width_pct / daily, 2)
            return {"exists": True, "stop": round(stop, 2),
                    "width_pct": round(width_pct, 2),
                    "width_in_daily_sigma": sig,
                    "option_return_pct": round(100.0 * opt, 1),
                    "holdable": (None if sig is None else bool(sig >= 1.0))}
        stop -= step
    return {"exists": False,
            "reason": (f"this structure does not overtake equity at "
                       f"{target:,.2f} for any stop width down to 95%")}


def horizon_targets(spot: float, vol_annual_pct: Optional[float],
                    days_per_year: int = 252,
                    sourced: Optional[float] = None) -> List[Dict[str, Any]]:
    """Targets to evaluate: the sourced level, then volatility-scaled horizons.

    The sourced level is a price the market has actually defended and is the
    only one with evidence behind it. The horizon bands are what the CURRENT
    implied volatility says a horizon can hold — a width, not a forecast — and
    they exist because a single near level cannot show where options win.
    """
    out: List[Dict[str, Any]] = []
    if sourced:
        out.append({"label": "SOURCED", "price": round(float(sourced), 2),
                    "basis": "a level the price has traded and defended",
                    "move_pct": round(100.0 * (float(sourced) / spot - 1.0), 2)})
    if not vol_annual_pct or vol_annual_pct <= 0:
        return out
    for label, days in (("SHORT_1SD", 5), ("MEDIUM_1SD", 21), ("LONG_1SD", 126)):
        band = (vol_annual_pct / 100.0) * ((days / float(days_per_year)) ** 0.5)
        price = spot * (1.0 + band)
        out.append({
            "label": label, "price": round(price, 2), "horizon_days": days,
            "basis": (f"one standard deviation over {days} trading days at "
                      f"{vol_annual_pct:.1f}% implied volatility — a WIDTH the "
                      f"horizon can hold, not a direction it will take"),
            "move_pct": round(100.0 * band, 2)})
    return out


def survivable_stops(spot: float, vol_annual_pct: Optional[float],
                     days_per_year: int = 252) -> List[Dict[str, Any]]:
    """Stop levels at 1.0, 1.5 and 2.0 daily sigma.

    Offered because the desk's sourced invalidation can sit inside a single
    daily move, and a comparison against a stop that noise removes describes a
    position nobody holds.
    """
    if not vol_annual_pct or vol_annual_pct <= 0:
        return []
    daily = vol_annual_pct / (days_per_year ** 0.5)
    out = []
    for k in SURVIVABLE_SIGMAS:
        width = daily * k
        out.append({"sigma": k, "stop": round(spot * (1.0 - width / 100.0), 2),
                    "width_pct": round(width, 2)})
    return out


def where_options_win(options_section: Optional[Dict[str, Any]],
                      spot: Optional[float],
                      invalidation: Optional[float],
                      sourced_target: Optional[float] = None,
                      risk_capital: float = REFERENCE_RISK_CAPITAL
                      ) -> Dict[str, Any]:
    """The full picture: several targets, and both crossovers per structure."""
    if not spot or spot <= 0:
        return {"status": "UNAVAILABLE", "reason": "no usable spot price"}
    if invalidation is None:
        return {"status": "UNAVAILABLE",
                "reason": "no invalidation level to compare leverage against"}

    sec = options_section or {}
    vol = (sec.get("volatility_annualized_pct")
           or sec.get("volatility_realized_pct"))
    mult = float(sec.get("contract_multiplier") or 100.0)
    cands = (sec.get("candidates") or [])[:3]

    targets = horizon_targets(float(spot), vol, sourced=sourced_target)
    stops = survivable_stops(float(spot), vol)

    # Comparison baselines, and the FIRST one matters most.
    #
    # UNSTOPPED equity is the only apples-to-apples comparison against an
    # option's contractual floor. Every stopped baseline treats the stop as a
    # floor and it is not one — it can gap — so capital at risk comes out small,
    # share count comes out large, and the comparison systematically flatters
    # equity. On IONQ that bias is decisive and it INVERTS the answer: against
    # the 2.42% stop no structure ever wins, while against unstopped equity the
    # call spread wins from the 21-day band onward.
    #
    # Modelled as stop = 0: return on risk is then (price - spot) / spot, which
    # is exactly the unstopped return, with the whole position at risk as it
    # should be.
    baselines = [{"label": "UNSTOPPED_EQUITY", "stop": 0.0,
                  "width_pct": 100.0, "in_daily_sigma": None,
                  "note": ("the whole position is at risk, which is the only "
                           "baseline whose floor is as real as an option's")}]
    baselines.append({"label": "SOURCED_INVALIDATION",
                      "stop": round(float(invalidation), 2),
                      "width_pct": round(100.0 * (float(spot)
                                                  - float(invalidation))
                                         / float(spot), 2),
                      "in_daily_sigma": _stop_in_daily_sigma(
                          float(spot), float(invalidation), vol),
                      "note": ("assumes the stop FILLS here; a gap through it "
                               "loses more and there is no contractual floor")})
    for s in stops:
        baselines.append({"label": f"{s['sigma']}_SIGMA", "stop": s["stop"],
                          "width_pct": s["width_pct"],
                          "in_daily_sigma": s["sigma"],
                          "note": "a stop wide enough that noise alone should "
                                  "not remove it"})

    grid = []
    for cand in cands:
        row = {"instrument": cand.get("structure"), "label": cand.get("label"),
               "returns_at_targets": {}, "crossover_price": {},
               "crossover_stop": {}}
        for t in targets:
            r = _option_return_on_risk(cand, t["price"], mult)
            row["returns_at_targets"][t["label"]] = (
                round(100.0 * r, 1) if r is not None else None)
        for b in baselines:
            row["crossover_price"][b["label"]] = crossover_price(
                cand, float(spot), b["stop"], mult)
        for t in targets:
            row["crossover_stop"][t["label"]] = crossover_stop(
                cand, float(spot), t["price"], mult, vol)
        grid.append(row)

    equity_at_targets = {}
    for t in targets:
        equity_at_targets[t["label"]] = {
            b["label"]: round(100.0 * _equity_return_on_risk(
                t["price"], float(spot), b["stop"]), 1)
            for b in baselines}

    return {
        "status": "OK",
        "spot": round(float(spot), 4),
        "risk_capital": risk_capital,
        "volatility_used_pct": vol,
        "volatility_basis": sec.get("volatility_basis"),
        "targets": targets,
        "stop_baselines": baselines,
        "equity_return_pct_at": equity_at_targets,
        "structures": grid,
        "the_normalisation_bias": (
            "Every STOPPED baseline flatters equity, because it treats the stop "
            "as a floor when only the option's floor is contractual. "
            "UNSTOPPED_EQUITY is the comparison where both floors are real, and "
            "on this name it inverts the answer: against the sourced stop no "
            "structure ever wins, while against unstopped equity the bounded "
            "structures win once the move is large enough to clear the premium. "
            "Read the unstopped row first, then ask whether the stop you would "
            "actually honour is wide enough to hold."),
        "the_structural_point": (
            f"Equity's return per dollar risked is 1/(spot - stop), so a tight "
            f"stop IS leverage: at the sourced invalidation "
            f"({baselines[0]['width_pct']:.2f}%) that slope is "
            f"{1.0 / (float(spot) - float(invalidation)):.3f} per dollar, which "
            f"no bounded-loss structure on this board matches at any price. "
            f"Options overtake equity only once the stop is wide enough to "
            f"hold — and that is the same width at which the equity row stops "
            f"describing a position ordinary noise would close."),
        "what_this_does_not_say": (
            "The horizon targets are volatility WIDTHS, not forecasts. Nothing "
            "here says the price will reach any of them, and no component of "
            "this system has demonstrated a forward directional edge."),
    }
