# Prediction evaluation and the feedback loop

What the desk said, graded against what happened, and how the grade is fed back.
Built 2026-10-04 on top of the existing ledger (`data/prediction_ledger.py`),
calibration (`intelligence/calibration.py`) and self-improvement loop (`selfimprove/`).

```
 call ──freeze──▶ prediction_snapshots (immutable: action, composite, pillars,
   ▲                 p_up per horizon, P(beat SPY) per horizon)
   │                         │
   │                 refresh_outcomes  ── price + SPY at 1/5/20/60/126/252 trading days
   │                         ▼
   │              prediction_outcomes (raw, excess vs SPY, MAE/MFE, call-frame Brier)
   │                         │
   │        ┌────────────────┼──────────────────────────┐
   │        ▼                ▼                          ▼
   │  evaluation/       intelligence/calibration   intelligence/outperform
   │  scorecard         p_up → isotonic map         composite → P(beat SPY)
   │  (read-only)       gate: purged CV beats raw,  gate: purged CV beats the
   │        │           ≥20 independent windows     training base rate, ≥20 windows
   │        ▼                │                          │
   │  /api/evaluation         └───────────┬──────────────┘
   │  heartbeat report                    ▼
   │  evaluation_history       next call's stated probabilities
   └──────────────────────────────────────┘     (+ selfimprove: weights, confidence map)
```

## Running it

| Where | What |
|---|---|
| `python3 run_heartbeat.py --scorecard-only` | Print the scorecard, change nothing |
| Daily heartbeat (LaunchAgent, 14:00 local weekdays) | Grades, refits both maps, freezes calls, prints the scorecard, records `evaluation_history` |
| `GET /api/evaluation?horizons=1,5,20,60&source=live` | Full report (cached 10 min; `fresh=1` to rebuild) |
| `GET /api/evaluation/history?metric=rank_ic&horizon=5` | One metric over time |
| MCP `prediction_scorecard` (at `/mcp`) | Headline, verdicts, coverage; `detail: true` for trend and reliability bins |
| UI: Advanced Analysis → 🎯 Prediction Scorecard | Summary, per-horizon table, weekly rank-IC chart, confidence labels, desk vs simple models, paper portfolio |

## What is graded, and in which frame

A claim is graded in the frame it was made in. Mixing frames is the bug class this
work kept finding (see below).

| Question | Metric | Frame |
|---|---|---|
| Did higher-scored names beat lower-scored ones? | Per-date Spearman of composite vs excess return; bullish−bearish and top−bottom-third excess spreads | Market-neutral (vs SPY, same day) |
| Did the stock move the called way? | Hit rate on price **and** vs SPY, beside the share of calls where the stock rose | Both |
| Is p_up honest? | Brier vs always-50% and vs the up-rate among outcomes **already matured at the call** (no hindsight); reliability bins; ECE | Market (did it rise) |
| Is P(beat SPY) honest? | Same, against excess > 0 | Relative |
| Do confidence labels keep their promise? | Claimed (0.5 + 0.5 × edge score, as frozen) vs delivered | Call (was it right) |
| Which pillars rank? | Per-date rank IC of each pillar | Market-neutral |
| Is it getting better? | Weekly cohort metrics; daily `evaluation_history` | — |

**Significance is across call dates, not rows.** Seventy calls on one day are one
draw of the market. Each metric is computed per call date, then averaged across
dates with a Newey–West standard error (lag h−1, because a 5-day outcome called
Monday and one called Tuesday share four days).

**Verdicts (stated before any number was read; pinned by tests):**

| Verdict | Rule |
|---|---|
| EDGE | t ≥ 2 **and** ≥ 20 independent windows among the dates used |
| PROMISING | t ≥ 2 but < 20 independent windows — the dates overlap too much to confirm |
| NO_EDGE | \|t\| < 2 |
| ADVERSE | t ≤ −2 |
| INSUFFICIENT | < 5 usable call dates (a date needs ≥ 8 names to rank) |

Independent windows = `intelligence.calibration.effective_sample_size` (calendar span ÷
horizon, capped by distinct dates). It is the same bar the calibration and
self-improvement gates use and is never lowered here.

## First results (live calls, 2026-07-19 → 2026-10-02, regraded 2026-10-04)

| h | calls | indep. windows | hit on price | hit vs SPY | stock rose | rank IC (t) | ranking | p_up Brier | p_up |
|---|---|---|---|---|---|---|---|---|---|
| 1d | 1,958 | 42 | 51% | 53% | 43% | +0.080 (2.01) | **EDGE** (20 windows, borderline) | 0.261 | NO_EDGE |
| 5d | 1,658 | 9 | 49% | 49% | 35% | +0.117 (2.00) | PROMISING (3 windows) | 0.261 | NO_EDGE |
| 20d | 465 | 1 | 43% | 43% | 30% | — | INSUFFICIENT | 0.272 | NO_EDGE |
| 60d | 0 | — | — | — | — | — | INSUFFICIENT | — | — |

Reading it:

- **Direction is mostly the market.** Over this window the stock rose on only 30–43% of
  calls, so bullish calls lost on price and bearish calls won. The hit rate on price
  says little about the engine.
- **Ranking is the part that works.** At 1 day the composite ranked the same day's names
  against SPY with IC +0.08. That passes the rule, but only just (t = 2.01, exactly 20
  windows). At 5 days the IC is +0.12, but the 18 dates hold only 3 non-overlapping
  windows, so it is unconfirmed.
- **p_up is not yet useful.** Its Brier is worse than always saying 50% at every horizon,
  and worse than the base rate known at the time.
- **Confidence labels overstate.** MEDIUM claimed 86% and was right 45–49% on price
  (515–587 calls). The self-improvement loop's confidence map is already moving this
  label down, at its bounded speed.
- **By pillar (5d):** technical +0.08, fundamentals +0.09, research +0.04; algo −0.07 and
  social −0.06. None of these is significant on this sample.

## Bugs the evaluation found and fixed

| Bug | Effect | Fix |
|---|---|---|
| Brier column scored p_up (P(price up)) against "was the call right" | Every correct SELL/REDUCE scored as a confident miss. Average 1d/5d/20d Brier was 0.284/0.307/0.338; correctly framed it is 0.265/0.269/0.303 | Bearish calls use 1 − p_up (`evaluate_outcomes`) |
| p_up calibration was fit on the same mixed target, and HOLD rows (which state a p_up) were excluded | The map that is live at 1d/5d learned "low p_up means up" on a quarter of its rows | Target = did the price rise, for every action (`_pairs_for_horizon`) |
| The web path froze **calibrated** p_up | The map was refit on its own output | `frozen_probabilities()` freezes the raw value; the calibrated value stays on the forecast for display |
| Global grading read only the newest 500 snapshots | A call older than about a week never got its 20/60/126/252-day outcome unless the heartbeat graded its ticker by name | `refresh_outcomes()` grades every snapshot that still has a horizon to mature |
| A fixed 2-year price download, and a call snapped to "the next available bar" however far away | All 256 replay calls (2022–2025) were graded from the first bar of the download: entry price from 2024, identical outcomes for different calls, values changing daily as the window moved | Download sized to the oldest call (`history_period`); a call more than 7 days before the series is not graded |
| Grading minutes after the close used the provisional bar | Oct 2's outcomes moved by up to 1.3% when the final prints landed | A bar dated today is not used; those horizons mature on the next run |

The ledger was backed up before each regrade
(`data/backups/ledger-20261004-120618-996.db`, `…-121330-961.db`). The
self-improvement loop's three active overrides were re-tested on the corrected
evidence (dry-run `review`). All three still hold, with held-out effects of +0.05 to +0.08,
so none was rolled back.

## The new feedback edge: P(beat SPY)

`intelligence/outperform.py` turns the composite's measured ranking skill into a
stated probability. It is an isotonic map from composite to the frequency of beating SPY
over the horizon. Because it is monotone, it never reorders names. It is applied only when:

1. at least 30 graded rows carry a frozen composite;
2. there are at least 20 independent windows;
3. purged, time-blocked CV Brier beats predicting the **training** base rate. A map that
   only learns "most names lagged SPY this quarter" has learned the regime, not the
   engine, and is refused.

On 2026-10-04 it passes at **1d only**: Brier 0.2439 vs 0.2445 for the base rate, a
skill of 0.25%, on exactly 20 windows. Composite 35 maps to 31% and 75 maps to 49%.
At 5d it has 3 windows. The composite has only been frozen since early September,
which is the binding constraint. The probability is frozen into each new call as
`outperform_probabilities` and graded by the scorecard against excess > 0.
It is never stamped on a back-dated or replay call, because that would be look-ahead.

## Desk vs simple models (challengers)

`evaluation/challengers.py` scores simple models on the **same calls** and grades them
against the composite, paired by date. Each date, both rank the same names, and the
difference of the two rank ICs is one observation. The rule is symmetric: "a challenger
is better" also needs |t| ≥ 2 and 20 independent windows. Below that it reads
`…_UNCONFIRMED`.

| Challenger | What it is | Where it comes from |
|---|---|---|
| `momentum_12_1` | 12-month return excluding the last month | prices up to and including the call day |
| `reversal_1m` | minus the last month's return | same |
| `low_volatility` | minus 60-day volatility | same |
| `fundamentals_only`, `technical_only` | one pillar alone | the frozen pillars |
| `equal_weight_core` | technical, algo, fundamentals at equal weight | the frozen pillars |

Price challengers are **frozen beside each new call** (`shadow_scores`, source `frozen`,
immutable by trigger). For past calls they are rebuilt from prices cut at the call day,
which is exactly what the desk knew. Bars are stamped 04:00, so the cut compares calendar
dates; a midnight cut silently dropped the call day's own close. The daily run fills in any
missing ones.

**This is also where a new data source belongs.** Add it as a challenger, let it build a
record beside the composite, and wire it into the decision only if it wins.

## Paper portfolio

`evaluation/paper.py`: equal weight in the top third by score at each rebalance date.
Rebalance dates are at least h trading days apart, so periods never overlap. It is charged
`backtest.costs.CostModel`'s per-trade cost for a liquid name (4.13 bps) on every unit of
weight traded. It is compared with SPY **and** with all names the desk covered that day;
the second is the honest benchmark for picking. A top-minus-bottom (market-neutral)
version is reported alongside. Challengers are simulated on the composite's own dates and
names.

**First read (1d, 22 trading days in September 2026, after costs):**

| Model | Top third | Top − bottom | Rank IC (same names) |
|---|---|---|---|
| **Composite (the desk)** | **+0.38%** | +4.84% | +0.080 |
| momentum 12-1 | −0.56% | +5.64% | +0.117 |
| equal-weight core | +0.07% | +5.54% | +0.079 |
| fundamentals only | −1.61% | +4.28% | +0.052 |
| technical only | −1.59% | +4.69% | +0.081 |
| low volatility | −7.15% | −9.43% | −0.079 (desk reliably better) |
| reversal 1m | −4.54% | −3.52% | −0.020 |
| *All covered names* | *−3.77%* | | |
| *SPY* | *+0.37%* | | |

The desk's top third was ahead of all covered names on 73% of days (t = 2.62), but only
matched SPY. Momentum and equal weights did as well as the composite on ranking (no
reliable difference). At 5d, equal weights led the composite with t = −2.35, but on only
3 independent windows (unconfirmed). Watch these two; they are the cheapest possible
alternative to the full engine.

## The risk pillar test (2026-10-08)

The 2017–2025 replay (`docs/REPLAY_WIDE_RESULTS.md`) found the risk pillar ranking **backwards**: IC
−0.066 with t = −4.04 at 126 days. Two challengers rebuild the desk's own formula from each frozen call:
- `composite_no_risk` = clip(core + modifiers), with no multiplier and no veto;
- `composite_risk_inverted` = the multiplier flipped, so riskier names are amplified.

| Replay (8,058 calls) | Desk IC | No-risk IC | Inverted IC | Top third: desk / no-risk / inverted |
|---|---|---|---|---|
| 5d | +0.011 | +0.016 | +0.021 | +58% / +67% / +65% |
| 20d | +0.006 | +0.007 | +0.010 | +260% / +280% / +286% |
| 60d | +0.009 | +0.013 | +0.018 (**reliably better**, t = −2.14, 35 windows) | +229% / +250% / +281% |
| 126d | −0.001 | +0.005 (t = −3.33, 16 windows) | +0.013 (t = −4.00, 16 windows) | +298% / +316% / +298% |

On the live calls (1d and 5d) there is no difference yet.

**Reading it:**
- The risk step is a consistent drag on history. Removing it helps at every horizon.
- Even without it, the ranking signal is tiny (IC ≈ 0.01–0.02), so this removes a drag; it does not
  create an edge.
- Changing the live scoring is a decision left to the owner. The challengers keep measuring it on live
  calls in the meantime.

## Daily run reliability

The 2–3 hour runs (2026-09-25, 10-01, 10-02) were not slow code; a ticker takes 5–8 s.
macOS's power log shows the laptop asleep mid-run. On 10-02 the lid closed at 14:31, and
the run crept forward only during brief maintenance wakes until 16:50. Four tickers failed
for want of a network. Changes:

- `cron_heartbeat.sh` runs under `caffeinate -i -s`, which stops idle sleep and stops
  system sleep on AC power. A lid closed on battery still sleeps, so the run reports
  `asleep_s` (wall-clock minus monotonic time) and warns when it is a minute or more.
- Failed tickers are retried once after 30 s (`retried` / `recovered` in the log).
- Every ticker's time is logged, plus the three slowest.
- **The web app's background scheduler no longer starts inside the run.** It used to start
  as a side effect of importing `web.app`. The self-improvement cycle then ran on a thread
  *concurrently* with the day's calls, so a promotion landing mid-run scored part of the
  day under old weights and part under new. Its jobs now run at fixed points:
  grade → options grading → self-improvement → challenger reconstruction → fit →
  score and freeze → scorecard → filing watch and screener (at their usual intervals).
  `.env` is loaded explicitly, so `SELFIMPROVE_APPLY=1` still reaches the loop.
  `--no-maintenance` skips the upkeep.

## Limits worth knowing

- **About 11 weeks of live calls.** Most verdicts are INSUFFICIENT or PROMISING because the
  calendar, not the row count, is short. 20 independent windows takes about 20 trading
  days at 1d, 100 at 5d and 400 at 20d. Sampling more names does not shorten it.
- Cross-sectional correlation within a date is handled by aggregating per date first.
  Correlation across consecutive dates is handled by Newey–West. Neither corrects for
  testing several metrics and horizons at once, so a single borderline EDGE (1d, t = 2.01)
  is a reason to keep watching, not to act.
- Replay calls are 10 tickers × monthly. That is too few names per date to rank, so
  they inform direction and probability only.
