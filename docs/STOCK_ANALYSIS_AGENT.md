# Stock Analysis Agent — fundamentals from the SEC filings

Built 2026-10-01/02. Package `stock_analysis/`, agent `mas/agents/stock_analysis.py`
(capability `fundamental_analysis`), API `/api/stock-analysis/<ticker>`, the
"📑 Stock Analysis" tab, and the v2 fundamentals pillar score.

Every number comes from a 10-K, 10-Q, 20-F or 40-F through SEC EDGAR (XBRL
company facts and the filed documents), carries the accession number of the
filing it came from, and can be computed **as of any past date** from what had
been filed by then. No LLM produces a number; the optional MD&A summary is
withheld unless every quote is in the filing word for word and every number
appears in its text.

## Phases

| Phase | What | Where |
|---|---|---|
| 0 | Ground truth: 25-company test set, figures checked against the printed filings | `stock_analysis/ground_truth.py` |
| 1 | Standardized statements: quarterly, annual, TTM; derived quarters marked; restatements and split adjustments told apart | `statements.py`, `financial_data/providers/edgar.py` |
| 2 | Quality of earnings: 11 tests with formula, threshold and source filing | `quality.py`, `company.py` |
| 3 | The filings' text: index flags, controls, going concern, auditor, risk-factor changes, customer concentration, MD&A summary | `filings.py`, `narrative.py` |
| 4 | Market inputs, valuation (multiples, history, reverse DCF), peers | `market.py`, `valuation.py`, `peers.py` |
| 5 | Price context tied to the filing calendar (earnings reactions vs SPY) | `technicals.py` |
| 6 | Report, agent, API, chat routing, UI tab | `report.py`, `mas/…`, `web/app.py`, `web/static/index.html` |
| 7 | v2 fundamentals pillar score, shadow → evaluated → promotion rule | `scoring.py`, `backtest/pillars.py`, `backtest/fundamentals_v2_eval.py` |

## Ground truth (Phase 0)

The latest fiscal-year revenue, net income, operating income, assets, equity,
cash, operating cash flow, capex, long-term debt and diluted EPS that the engine
built from XBRL were looked up, as printed, in each company's annual report
document (and its EX-13/EX-99 exhibits): AAPL, MSFT, NVDA, AMZN, GOOGL, KO,
XOM, CAT, COST, TSLA, JPM, BAC, PGR, O, PLD, TSM, ASML, SAP, BABA, TM, and the
event cases SMCI, KHC, UAA, MDXG, BHC as of before their events. After the
fixes below, **every checkable figure was found**. Items a company does not
report (a bank's operating income) are listed as not reported, not counted.

## What reading real filings forced (each pinned by a test)

- **Quarters are mostly not filed.** Q4 = FY − 9M; 10-Q cash flows are
  year-to-date. Derived cells are marked `derived` with `how`.
- **Periods are (start, end), never end alone** — a 10-Q's 3-month and 9-month
  revenue share an end date. The pre-existing v1 pillar collapses by end date
  and can divide a 9-month net income by a 3-month revenue.
- **Tags change over time**; the provider used "first tag with any data",
  losing years of history. It now ranks tags and the choice is made per period
  **after** the point-in-time cut (choosing on the full history let a later
  filing's tag hide the one on file at the time — Kraft Heinz FY2017 revenue).
- **Proxy statements carry XBRL net income** (pay-versus-performance) and,
  filed after the 10-K, won as "latest" — only statement forms count.
- **A 10-Q's trailing-twelve-month figure is not a fiscal year** (Amazon).
- **Total revenue before contract revenue** (Caterpillar, Progressive).
- **Foreign issuers** tag under `ifrs-full`, report in their own currency
  (TSMC: TWD; its USD tags are convenience translations), file annual-only.
- **A holding-company reorganization moves the ticker to a new CIK** (Exxon,
  8-K12B 2026-07-01) — documented predecessor CIKs are merged and labelled.
- **Splits** rescale EPS and share counts in later filings (SPLIT_ADJUSTMENT,
  not a restatement); share-count trends compare adjacent years only (Toyota).
- **Days-sales** is measured on the latest quarter vs the same quarter a year
  earlier (a trailing basis read Exxon's Q2 2026 revenue surge as stuffing).
- **Market values need as-traded prices**: Yahoo's "unadjusted" close is still
  split-adjusted (Nvidia Feb 2020: $6.81 vs $272.54 traded) and the default is
  dividend-adjusted (Kraft Heinz $32.67 vs $48.26). The bars provider gained a
  split-only basis and a splits feed.
- **SEC's XBRL data can lag the filings**: TSMC's April 2026 20-F is filed but
  not in company facts; the report says so, and multiples on stale figures
  carry a warning.
- **Filing text**: auditor-report boilerplate ("assessing the risk that a
  material weakness exists") and hypothetical risk-factor language are not
  findings; Item 5.02 is context; thin-space headings (TSMC) are folded;
  layouts that defeat section reading are reported as not comparable.

## The historical event cases

| Case (as of) | Earnings quality | Filings | v2 score |
|---|---|---|---|
| Super Micro (2024-08-26) | D — cash conversion, accruals, Beneish at concern | earlier auditor change, delisting-standard notice | 47.9 |
| Kraft Heinz (2019-02-20) | F — cash conversion, Beneish, receivables | 8-K Item 4.02 (Nov 2017 cash-flow restatement) | 36.4 |
| Under Armour (2017-01-30) | C — weak cash conversion | — | — |
| MiMedx (2018-02-15) | A | controls not effective, material weakness, auditor change | 53.5 |
| Valeant/Bausch (2015-10-15) | A | — | — |

Two of five are not flagged by either layer. That is reported, not tuned away.

## Beyond the build (2026-10-02, free data only)

| Step | What | Where |
|---|---|---|
| 1 | Fundamentals enter the decision: filing red flags (DECISIVE for restatement, late filing, ineffective controls, material weakness, going concern, bankruptcy) and a D/F earnings-quality grade become bearish evidence; "next 10-Q" monitoring checks for receivables, inventory, cash conversion and accruals. The portfolio brief sweeps every holding for red flags. | `decision/filings_evidence.py`, `stock_analysis/sweep.py` |
| 1 | Filing alerts: hourly check of every watched name (watchlist.txt + watched table + broker holdings); 8-K items by severity, NT filings, new 10-Q/10-K with the score move. First look baselines silently. 🔔 badge in the header. | `stock_analysis/watcher.py`, `/api/alerts`, `/api/watch` |
| 1 | Screener over the watched universe (score, grade, P/E, FCF yield, growth, no filing concerns), rebuilt every six hours | `stock_analysis/screener.py`, `/api/screener` |
| 2 | Analysts and insiders (Finnhub free tier): earnings surprises, buy-share trend, open-market insider trades only (Form 4 P/S; cluster = 3+ buyers) | `stock_analysis/street.py`, `financial_data/providers/finnhub_research.py` |
| 3 | Management guidance quoted from the earnings release (EX-99.1 of 8-K Item 2.02), parsed only when unambiguous, with a credibility record (next-quarter revenue vs the guided midpoint) | `stock_analysis/guidance.py` |
| 3 | Revenue by segment, product and geography from the XBRL instance, labels from the label linkbase, subtotals from the definition linkbase | `stock_analysis/segments.py` |
| 4 | Event signals (SUE, earnings reaction, relative momentum) measured point-in-time before use: **none passed** the pre-stated rule, so none enters the decision | `backtest/event_signals_eval.py`, `docs/EVENT_SIGNALS_EVALUATION.md` |
| 5 | Key-gated Alpha Vantage and FMP: full consensus-EPS history (tried before Finnhub's four quarters) and earnings-call transcripts with a validated summary. Without a key each section names the free key it waits for. | `financial_data/providers/alphavantage.py`, `fmp.py`, `stock_analysis/transcripts.py` |
| 6 | MCP server: the analysis as read-only tools for Claude Code / Desktop (`stock_analysis`, `compare_fundamentals`, `screener`, `filing_alerts`, `watchlist`) | `stock_analysis/mcp_server.py`, `POST /mcp` |
| 7 | Survivorship audit from SEC data: how much of the 2017 large-company universe no longer files, by its 2018 earnings-quality grade | `backtest/survivorship_audit.py`, `docs/SURVIVORSHIP_AUDIT.md` |

Connect Claude Code to the desk (read-only):

```
claude mcp add --transport http stock-desk https://agentic-ai-production-aea7.up.railway.app/mcp
```

With `MCP_TOKEN` set on the server, add `--header "Authorization: Bearer <token>"`.

Free keys the desk uses when present (each section says which one it waits for):
`FINNHUB_API_KEY` (analysts, insiders, four quarters of surprises), `ALPHAVANTAGE_API_KEY` (full
surprise history, transcripts; 25 calls/day, cached), `FMP_API_KEY` (surprises; transcripts where the
plan includes them), `TIINGO_API_KEY` (delisted prices — what the survivorship audit needs to measure
returns, not just outcomes), `DEEPSEEK_API_KEY` with credit (MD&A and call summaries).

## Known limits

- The DeepSeek key returns HTTP 402 locally; the MD&A summary path is tested
  offline with a stub and names the failure live.
- Peers are chosen by SIC code (SEC's classification, current not historical)
  and sized by SEC frames; the largest company in a code may have no peer
  within 10× of its size — the report says so.
- Banks, insurers and REITs: most earnings-quality tests do not apply; those
  companies are shown the applicable tests, ungraded.
- See `docs/FUNDAMENTALS_V2_EVALUATION.md` for the scoring evaluation. Every evaluation here
  replays today's tickers; `docs/SURVIVORSHIP_AUDIT.md` measures what that hides. The v2
  weights were fixed before the evaluation, not fitted — any future re-weighting must be
  chosen on one period and tested on a later one (walk-forward), or it is fitted to the test.
- Guidance is parsed from the press release only; companies that guide on the call (Apple,
  Microsoft) show "no numeric guidance in the release" until a transcript key is set.
