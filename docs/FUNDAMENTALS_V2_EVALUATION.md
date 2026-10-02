# Fundamentals v2 — shadow evaluation

Generated 2026-10-02 by `backtest/fundamentals_v2_eval.py`. 43 companies × 35 quarterly dates (1492 scored observations), point-in-time.

Mean cross-sectional rank IC of each score with the forward return net of SPY (t-stat overstates independence at 126/252 days; the annual non-overlapping mean is the check).

## 63 trading days

| signal | mean IC | t | IC>0 | annual-only IC | top−bottom tercile |
|---|---|---|---|---|---|
| v1 | +0.0255 | 0.82 | 54% | +0.0415 | +0.92% |
| v2 | +0.0301 | 0.88 | 49% | +0.0194 | +1.16% |
| v2_base | +0.0290 | 0.86 | 49% | +0.0291 | +0.96% |
| sub_quality | -0.0427 | -1.55 | 37% | +0.0555 | -1.71% |
| sub_profitability | +0.0193 | 0.47 | 54% | +0.0189 | +1.15% |
| sub_cash_return | +0.0012 | 0.03 | 40% | +0.0080 | -0.68% |
| sub_growth | +0.0519 | 1.22 | 60% | +0.0052 | +1.47% |
| sub_balance_sheet | +0.0111 | 0.37 | 60% | +0.0056 | +0.84% |

## 126 trading days

| signal | mean IC | t | IC>0 | annual-only IC | top−bottom tercile |
|---|---|---|---|---|---|
| v1 | +0.0135 | 0.44 | 46% | +0.1143 | +1.60% |
| v2 | +0.0232 | 0.81 | 49% | +0.0549 | +1.92% |
| v2_base | +0.0189 | 0.67 | 51% | +0.0483 | +1.48% |
| sub_quality | -0.0615 | -2.77 | 29% | +0.0103 | -3.79% |
| sub_profitability | +0.0227 | 0.67 | 60% | +0.0898 | +2.03% |
| sub_cash_return | -0.0188 | -0.54 | 37% | -0.0579 | -2.16% |
| sub_growth | +0.0600 | 1.69 | 63% | +0.0777 | +3.29% |
| sub_balance_sheet | +0.0208 | 0.7 | 51% | -0.0247 | +3.12% |

## 252 trading days

| signal | mean IC | t | IC>0 | annual-only IC | top−bottom tercile |
|---|---|---|---|---|---|
| v1 | +0.0031 | 0.13 | 54% | -0.0148 | +1.46% |
| v2 | -0.0044 | -0.17 | 49% | +0.0119 | -1.24% |
| v2_base | -0.0080 | -0.3 | 54% | +0.0023 | -1.72% |
| sub_quality | -0.1027 | -5.93 | 14% | -0.0724 | -9.45% |
| sub_profitability | +0.0312 | 0.98 | 63% | +0.0314 | +0.54% |
| sub_cash_return | -0.0503 | -1.51 | 43% | -0.0510 | -9.65% |
| sub_growth | +0.0635 | 1.92 | 71% | +0.0755 | +5.48% |
| sub_balance_sheet | +0.0232 | 0.83 | 51% | +0.0109 | +9.59% |

## Verdict

Rule (fixed before the run): promote v2 to the live pillar when its mean IC beats v1 at >= 2 of 3 horizons AND is positive at >= 2 of 3 (stated before the run).

v2 beats v1 at 2/3 horizons and is positive at 2/3 → **PROMOTE**.

Limits: today's tickers (survivorship), ~40 names, overlapping windows; see the module docstring.

## What the result means (read before relying on it)

- **The rule passed, narrowly.** v2's mean IC beat v1's at 63 days (+0.030 vs +0.026) and 126 days
  (+0.023 vs +0.014) and lost at 252 days (−0.004 vs +0.003). No t-statistic reaches 1. Both scores
  are weak rankers of 3–12-month relative returns among these large caps; v2 is promoted because the
  rule fixed before the run said so, not because it showed a significant edge. On the annual
  non-overlapping dates v1 was ahead at 63 and 126 days.
- **The earnings-quality component ranked returns BACKWARDS in this sample** (mean IC −0.04, −0.06,
  −0.10 at 63/126/252 days; positive on only 14% of dates at 252 days). In 2017–2025 the market paid for
  growth among large caps — high-accrual, low-cash-yield growers outperformed steady cash generators.
  Growth was the only component positive at every horizon.
- **This test cannot see what the quality screen is for.** The universe is today's tickers, so the
  companies whose accounting failed and were delisted are absent. Avoiding those is the screen's job
  (Super Micro, Kraft Heinz and MiMedx are caught as of before their events — see
  docs/STOCK_ANALYSIS_AGENT.md), and a survivorship-biased cross-section scores that job at zero.
- **Weights were not adjusted after seeing this.** Re-weighting toward growth on this run would be
  fitting the evaluation set. The weights stay as stated in stock_analysis/scoring.py; changing them
  needs a walk-forward test, the same standard as every other weight in the desk.
- **Effect on today's verdicts:** across 16 large names, 6 actions change, mostly where v1 misread a
  business (Costco: thin net margin scored low by v1 although its return on capital is high, SELL→HOLD;
  Super Micro's fundamentals score falls from 45.6 to 5.6 on its filing findings).
