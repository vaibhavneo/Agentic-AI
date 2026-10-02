# Stock Analysis — Phase 0 ground truth

Generated 2026-10-02 by `stock_analysis/ground_truth.py::check_against_filing`.

For each company, the latest fiscal-year figures the statement engine built from SEC XBRL were looked up as printed in the annual report document (and its EX-13/EX-99 exhibits). XBRL and the printed document are produced separately by the filer, so a figure found in both was read correctly.

**232 of 232 checkable figures found.**

| Ticker | Kind | As of | Fiscal year | Form / currency | Found | Not found in document | Not reported by the company |
|---|---|---|---|---|---|---|---|
| AAPL | domestic | latest | FY2025 | 10-K / USD | 10/10 | — | — |
| MSFT | domestic | latest | FY2026 | 10-K / USD | 10/10 | — | — |
| NVDA | domestic | latest | FY2026 | 10-K / USD | 10/10 | — | — |
| AMZN | domestic | latest | FY2025 | 10-K / USD | 10/10 | — | — |
| GOOGL | domestic | latest | FY2025 | 10-K / USD | 10/10 | — | — |
| KO | domestic | latest | FY2025 | 10-K / USD | 10/10 | — | — |
| XOM | domestic | latest | FY2025 | 10-K / USD | 9/9 | — | operating_income |
| CAT | domestic | latest | FY2025 | 10-K / USD | 10/10 | — | — |
| COST | domestic | latest | FY2025 | 10-K / USD | 10/10 | — | — |
| TSLA | domestic | latest | FY2025 | 10-K / USD | 10/10 | — | — |
| JPM | bank | latest | FY2025 | 10-K / USD | 7/7 | — | operating_income, capex, long_term_debt |
| BAC | bank | latest | FY2025 | 10-K / USD | 8/8 | — | operating_income, capex |
| PGR | insurer | latest | FY2025 | 10-K / USD | 8/8 | — | operating_income, long_term_debt |
| O | reit | latest | FY2025 | 10-K / USD | 7/7 | — | operating_income, capex, long_term_debt |
| PLD | reit | latest | FY2025 | 10-K / USD | 9/9 | — | capex |
| TSM | foreign | latest | FY2024 | 20-F / TWD | 10/10 | — | — |
| ASML | foreign | latest | FY2025 | 20-F / EUR | 10/10 | — | — |
| SAP | foreign | latest | FY2025 | 20-F / EUR | 9/9 | — | capex |
| BABA | foreign | latest | FY2026 | 20-F / CNY | 8/8 | — | capex, long_term_debt |
| TM | foreign | latest | FY2025 | 20-F / JPY | 9/9 | — | capex |
| SMCI | event | 2024-08-26 | FY2023 | 10-K / USD | 10/10 | — | — |
| KHC | event | 2019-02-20 | FY2017 | 10-K / USD | 10/10 | — | — |
| UAA | event | 2017-01-30 | FY2015 | 10-K / USD | 10/10 | — | — |
| MDXG | event | 2018-02-15 | FY2016 | 10-K / USD | 8/8 | — | capex, long_term_debt |
| BHC | event | 2015-10-15 | FY2014 | 10-K / USD | 10/10 | — | — |
