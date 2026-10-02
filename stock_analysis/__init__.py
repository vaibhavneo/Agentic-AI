"""
Stock Analysis Agent — fundamental analysis from what companies file with the SEC.

  statements  standardized income statement / balance sheet / cash flow, with
              every figure traced to its filing, quarters derived where the
              filings only give year-to-date, point-in-time via `as_of`
  quality     quality of earnings: cash conversion, accruals, working capital,
              Beneish / Piotroski / Altman, stock-based pay, one-off items
  filings     the 10-K / 10-Q / 20-F text: red flags, risk-factor changes, MD&A
  peers       industry peer set and comparables
  valuation   multiples vs peers and history, reverse DCF
  technicals  price context tied to the filing calendar
  report      the full report the agent and the API serve
  scoring     the fundamentals pillar score built from all of the above

No number in this package comes from an LLM. The one LLM step (an MD&A
summary) is checked quote-by-quote and number-by-number against the filing.
"""
