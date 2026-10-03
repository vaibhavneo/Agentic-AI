# Survivorship audit

Generated 2026-10-02 by `backtest/survivorship_audit.py` from SEC data only. Universe: the 300 largest US filers by CY2017 revenue (XBRL frames), 246 with public equity (a 2017–18 proxy statement). Earnings-quality grade on what had been filed by 2018-04-30; 209 could be graded.

## Where they are now

| outcome | companies |
|---|---|
| still filing | 232 |
| reorganized | 0 |
| acquired | 12 |
| bankruptcy | 2 |
| other stopped | 0 |

**6% of the 2017 large-company universe no longer exists as a listed company** (acquired, bankrupt or otherwise gone; reorganizations whose successor still trades are not counted). The evaluations in this repo (`FUNDAMENTALS_V2_EVALUATION.md`, `EVENT_SIGNALS_EVALUATION.md`) use today's tickers, so none of those companies is in them.

Counted once — an earlier registrant of a company already in the universe: TWDC Enterprises 18 Corp. → Walt Disney Co (DIS); BUNGELTD → Bunge Global SA (BG); Cigna Holding Co → Cigna Group (CI); Baker Hughes Holdings LLC → Baker Hughes Co (BKR); WRKCo Inc. → WestRock Co.

Left out — last report before 2018-04-30, so never in the universe being graded: Accenture Holdings plc, WARNER MEDIA, LLC, BNSF RAILWAY CO, Broadcom Pte. Ltd., WHOLE FOODS MARKET INC.

## Outcome by the 2018 earnings-quality grade

| grade | n | still filing or reorganized | acquired | bankruptcy | other stopped |
|---|---|---|---|---|---|
| A/B | 197 | 94.4% | 5.1% (10) | 0.5% (1) | 0.0% |
| C | 7 | 100.0% | 0.0% (0) | 0.0% (0) | 0.0% |
| D/F | 5 | 80.0% | 0.0% (0) | 20.0% (1) | 0.0% |

**Direction of the bias.** Bankruptcy was more common in the D/F names and acquisitions (usually at a premium) in the A/B names — both missing from survivors-only tests, and both in the screen's favour. Those tests are, if anything, conservative for the quality screen. With 5 D/F companies this is a direction, not a measurement.

Grades: A 151, B 46, C 7, D 2, F 3. **94% of large companies grade A or B**, so among large caps the grade separates very little — the same picture as the quality component's negative IC in `FUNDAMENTALS_V2_EVALUATION.md`. The grade's use is flagging the few outliers, not ranking the many.

## Companies that stopped filing

| company | outcome | last 10-K/10-Q | 2018 grade |
|---|---|---|---|
| Walgreens Boots Alliance, Inc. | acquired | 2025-06-26 | A |
| Express Scripts Holding Co. | acquired | 2018-10-31 | A |
| AETNA INC /PA/ | acquired | 2018-10-30 | — |
| TECH DATA CORP | acquired | 2020-06-03 | B |
| SPRINT LLC | acquired | 2020-01-27 | B |
| TWENTY-FIRST CENTURY FOX, INC. | acquired | 2019-02-06 | B |
| RAYTHEON CO/ | acquired | 2020-02-12 | A |
| NEW RITE AID, LLC | bankruptcy | 2023-10-18 | A |
| WELLCARE HEALTH PLANS, INC. | acquired | 2019-10-30 | — |
| SEARS HOLDINGS CORP | bankruptcy | 2018-12-13 | F |
| Allergan plc | acquired | 2020-05-07 | B |
| Core-Mark Holding Company, LLC | acquired | 2021-08-05 | B |
| NORDSTROM INC | acquired | 2025-03-21 | A |
| WestRock Co | acquired | 2024-05-03 | B |

## Reading it

- A bankruptcy rate that rises as the grade falls means the survivors-only tests UNDERSTATE the quality screen: the blow-ups it would have avoided are missing from them.
- Acquisitions usually close at a premium. If they cluster in the better grades, survivors-only tests miss gains the screen would have kept; if in the worse grades, the reverse.
- Counts per grade are small; this is the direction and size of a bias, not a measured edge. Measuring the edge needs the non-survivors' prices to their last trading day (TIINGO_API_KEY covers delisted tickers) — until then the survivorship caveat stands on every evaluation here.
- Outcome classes come from each company's own filings (8-K Item 1.03; merger proxy / tender response / Rule 425). "Other stopped" includes going-private deals without a merger proxy and deregistrations.

