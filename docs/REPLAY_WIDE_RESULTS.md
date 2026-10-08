# Wide point-in-time replay — results

Generated 2026-10-08T13:53:17 by `scripts/replay_wide.py` from 8,058 replayed calls (data/replay_wide.db, kept out of the live ledger).

Replay calls rebuild technical, algo and SEC point-in-time fundamentals as of each month-start; social and research pillars cannot be rebuilt. Universe = today's watchlist (survivorship applies). Verdict rules are the scorecard's: |t| ≥ 2 across call dates and ≥ 20 independent windows.

```
PREDICTION SCORECARD — predictions vs what happened (replay calls, generated 2026-10-08T13:53:17)

  • 5d direction: 55% of 4,989 directional calls moved the called way on price, 51% against SPY. The stock rose on 57% of all calls, so a hit on price mostly measures the market.
  • 5d ranking (did higher-scored names beat lower-scored ones vs SPY, same day): rank IC +0.011, t=+0.47 over 102 dates — NO_EDGE: t=+0.47: not distinguishable from zero.
  • 5d p_up: Brier 0.2491 — better than always saying 50% (0.25) and worse than the up-rate known at the time (0.248); NO_EDGE: t=-0.36: not distinguishable from zero.
  • 5d vs simple models: the composite reliably beat 1 of 6 (low_volatility); none reliably beat it. Best challenger: equal_weight_core (rank IC +0.017 vs the composite's +0.011 on the same names).
  • 5d paper portfolio (top third by composite, rebalanced every 5 trading days, 4.13 bps per trade): +57.67% after costs vs +62.59% for all covered names and +46.79% for SPY over 102 periods (ahead of the names in 51% of periods, t=-0.39).
  • 5d confidence: MEDIUM claimed 90% and was right 61% on price (49 calls) — the label overstates.
  • 20d direction: 55% of 4,989 directional calls moved the called way on price, 50% against SPY. The stock rose on 58% of all calls, so a hit on price mostly measures the market.
  • 20d ranking (did higher-scored names beat lower-scored ones vs SPY, same day): rank IC +0.006, t=+0.54 over 102 dates — NO_EDGE: t=+0.54: not distinguishable from zero.
  • 20d p_up: Brier 0.2504 — worse than always saying 50% (0.25) and worse than the up-rate known at the time (0.2468); ADVERSE: t=-2.03: reliably wrong-way.
  • 20d vs simple models: the composite reliably beat 0 of 6; none reliably beat it. Best challenger: fundamentals_only (rank IC +0.017 vs the composite's +0.006 on the same names).
  • 20d paper portfolio (top third by composite, rebalanced every 20 trading days, 4.13 bps per trade): +260.46% after costs vs +275.57% for all covered names and +188.44% for SPY over 102 periods (ahead of the names in 49% of periods, t=-0.31).
  • 20d confidence: MEDIUM claimed 90% and was right 63% on price (49 calls) — the label overstates.
  • 60d direction: 58% of 4,989 directional calls moved the called way on price, 50% against SPY. The stock rose on 62% of all calls, so a hit on price mostly measures the market.
  • 60d ranking (did higher-scored names beat lower-scored ones vs SPY, same day): rank IC +0.009, t=+0.43 over 102 dates — NO_EDGE: t=+0.43: not distinguishable from zero.
  • 60d p_up: Brier 0.2465 — better than always saying 50% (0.25) and worse than the up-rate known at the time (0.2404); NO_EDGE: t=-1.24: not distinguishable from zero.
  • 60d vs simple models: the composite reliably beat 1 of 6 (low_volatility); none reliably beat it. Best challenger: momentum_12_1 (rank IC +0.026 vs the composite's +0.009 on the same names).
  • 60d paper portfolio (top third by composite, rebalanced every 60 trading days, 4.13 bps per trade): +228.76% after costs vs +299.34% for all covered names and +210.01% for SPY over 34 periods (ahead of the names in 53% of periods, t=-1.00).
  • 60d confidence: MEDIUM claimed 90% and was right 63% on price (49 calls) — the label overstates.
  • 126d direction: 61% of 4,989 directional calls moved the called way on price, 50% against SPY. The stock rose on 66% of all calls, so a hit on price mostly measures the market.
  • 126d ranking (did higher-scored names beat lower-scored ones vs SPY, same day): rank IC -0.001, t=-0.03 over 102 dates — NO_EDGE: t=-0.03: not distinguishable from zero.
  • 126d p_up: Brier 0.2446 — better than always saying 50% (0.25) and worse than the up-rate known at the time (0.2334); ADVERSE: t=-2.63: reliably wrong-way.
  • 126d vs simple models: the composite reliably beat 0 of 6; none reliably beat it (momentum_12_1, equal_weight_core ahead, unconfirmed). Best challenger: momentum_12_1 (rank IC +0.046 vs the composite's -0.001 on the same names).
  • 126d paper portfolio (top third by composite, rebalanced every 126 trading days, 4.13 bps per trade): +298.22% after costs vs +322.16% for all covered names and +226.49% for SPY over 17 periods (ahead of the names in 53% of periods, t=-0.29).
  • 126d confidence: MEDIUM claimed 90% and was right 74% on price (49 calls) — the label overstates.

     h  calls indep  hit$ hitSPY      IC      t   L-S%  Brier ranking     p_up       
    5d   8058   102   55%    51%  +0.011  +0.47  -0.12  0.249 NO_EDGE     NO_EDGE    
   20d   8058   102   55%    50%  +0.006  +0.54  +0.52  0.250 NO_EDGE     ADVERSE    
   60d   8058    35   58%    50%  +0.009  +0.43  +2.04  0.246 NO_EDGE     NO_EDGE    
  126d   8058    16   61%    50%  -0.001  -0.03  +0.96  0.245 NO_EDGE     ADVERSE    

  feedback: p_up calibration live at 20, 60d; P(beat SPY) stated at no horizon (gate not met)
  indep = independent windows; hit$ = right on price; hitSPY = right vs SPY; IC = same-day rank correlation of composite with excess return; L-S = bullish minus bearish excess return per date.
  Reporting only — the scorecard never changes a score; calibration and P(beat SPY) carry their own out-of-sample gates.
```

## Desk vs simple models (replay)

**5d**

| model | rank IC | desk on same names | t (desk − model) | verdict |
|---|---|---|---|---|
| momentum_12_1 | +0.003 | +0.011 | 0.32 | NO_DIFFERENCE |
| reversal_1m | -0.046 | +0.011 | 1.75 | NO_DIFFERENCE |
| low_volatility | -0.052 | +0.011 | 2.28 | COMPOSITE_BETTER |
| fundamentals_only | +0.008 | +0.011 | 0.16 | NO_DIFFERENCE |
| technical_only | +0.006 | +0.011 | 0.35 | NO_DIFFERENCE |
| equal_weight_core | +0.017 | +0.011 | -1.55 | NO_DIFFERENCE |

Paper portfolio (5d, top third, 4.13 bps/trade): +57.7% vs +62.6% for all names and +46.8% for SPY over 102 periods (t vs names -0.39).

**20d**

| model | rank IC | desk on same names | t (desk − model) | verdict |
|---|---|---|---|---|
| momentum_12_1 | +0.009 | +0.006 | -0.16 | NO_DIFFERENCE |
| reversal_1m | -0.005 | +0.006 | 0.41 | NO_DIFFERENCE |
| low_volatility | -0.018 | +0.006 | 0.91 | NO_DIFFERENCE |
| fundamentals_only | +0.017 | +0.006 | -0.72 | NO_DIFFERENCE |
| technical_only | +0.003 | +0.006 | 0.32 | NO_DIFFERENCE |
| equal_weight_core | +0.006 | +0.006 | -0.15 | NO_DIFFERENCE |

Paper portfolio (20d, top third, 4.13 bps/trade): +260.5% vs +275.6% for all names and +188.4% for SPY over 102 periods (t vs names -0.31).

**60d**

| model | rank IC | desk on same names | t (desk − model) | verdict |
|---|---|---|---|---|
| momentum_12_1 | +0.026 | +0.009 | -1.06 | NO_DIFFERENCE |
| reversal_1m | -0.011 | +0.009 | 0.71 | NO_DIFFERENCE |
| low_volatility | -0.057 | +0.009 | 2.57 | COMPOSITE_BETTER |
| fundamentals_only | +0.013 | +0.009 | -0.37 | NO_DIFFERENCE |
| technical_only | +0.009 | +0.009 | -0.01 | NO_DIFFERENCE |
| equal_weight_core | +0.015 | +0.009 | -1.98 | NO_DIFFERENCE |

Paper portfolio (60d, top third, 4.13 bps/trade): +228.8% vs +299.3% for all names and +210.0% for SPY over 34 periods (t vs names -1.0).

**126d**

| model | rank IC | desk on same names | t (desk − model) | verdict |
|---|---|---|---|---|
| momentum_12_1 | +0.046 | -0.001 | -3.37 | CHALLENGER_BETTER_UNCONFIRMED |
| reversal_1m | -0.018 | -0.001 | 0.85 | NO_DIFFERENCE |
| low_volatility | -0.080 | -0.001 | 3.8 | COMPOSITE_BETTER_UNCONFIRMED |
| fundamentals_only | -0.002 | -0.001 | 0.13 | NO_DIFFERENCE |
| technical_only | +0.003 | -0.001 | -0.48 | NO_DIFFERENCE |
| equal_weight_core | +0.008 | -0.001 | -3.49 | CHALLENGER_BETTER_UNCONFIRMED |

Paper portfolio (126d, top third, 4.13 bps/trade): +298.2% vs +322.2% for all names and +226.5% for SPY over 17 periods (t vs names -0.29).

