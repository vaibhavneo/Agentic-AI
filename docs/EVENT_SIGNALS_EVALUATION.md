# Event-driven price signals — point-in-time evaluation

Generated 2026-10-02 by `backtest/event_signals_eval.py`. 43 companies, 1492 observations, quarterly 2017–2025. Mean cross-sectional rank IC with the forward return net of SPY (t-stats overstate independence at 126/252 days).

## 63 trading days

| signal | mean IC | t | IC>0 |
|---|---|---|---|
| sue | -0.0031 | -0.08 | 51% |
| reaction | +0.0131 | 0.43 | 54% |
| rel_mom | +0.0142 | 0.39 | 54% |

## 126 trading days

| signal | mean IC | t | IC>0 |
|---|---|---|---|
| sue | -0.0114 | -0.32 | 46% |
| reaction | -0.0058 | -0.21 | 49% |
| rel_mom | +0.0236 | 0.62 | 54% |

## 252 trading days

| signal | mean IC | t | IC>0 |
|---|---|---|---|
| sue | -0.0195 | -0.67 | 46% |
| reaction | +0.0066 | 0.24 | 60% |
| rel_mom | +0.0017 | 0.05 | 43% |

## Verdict

Rule: promote only if mean IC > 0 at 63, 126 and 252 days AND t >= 2 at one or more (fixed before the run).

- **sue**: stays descriptive (positive at all horizons: False; t >= 2 somewhere: False)
- **reaction**: stays descriptive (positive at all horizons: False; t >= 2 somewhere: False)
- **rel_mom**: stays descriptive (positive at all horizons: True; t >= 2 somewhere: False)

## What this means

No signal met the rule, so none enters the decision evidence. Every mean IC is within a few hundredths of zero at every horizon — no edge in this universe, not a weak one waiting for more data. That fits the literature: post-earnings drift and momentum were strongest in small, thinly followed stocks and have faded in large caps, which is all this universe holds. Earnings reactions and relative strength stay in the technicals section as context for the reader; SUE is not shown, since a number with no measured use adds noise.

Limits: today's tickers (survivorship — see SURVIVORSHIP_AUDIT.md), ~40 large companies, overlapping windows.
