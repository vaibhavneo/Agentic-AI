---
name: hypothesis_generation
version: 1.0.0
description: Propose falsifiable explanations or strategies from observed evidence — each with a stated test that could kill it. Use when diagnosing bugs, forming research questions, or designing trading strategies.
reference_impl: stock_agent strategy library (7 signal hypotheses, each backtestable) · debugging flow (MaxDD>1 → "absolute vs relative drawdown" hypothesis)
---
# hypothesis_generation
**Purpose:** structured guessing — hypotheses are only useful if they name their own disproof.
**Inputs:** observations/evidence (retrieved or computed) · domain constraints
**Outputs:** hypothesis list, each = {statement, mechanism (why it could be true), kill_test (deterministic check that would falsify it), prior_confidence}.
**Contract:** every hypothesis ships WITH its kill test — untestable hypotheses are discarded at generation time · generate ≥2 rivals when evidence is ambiguous (guard against anchoring) · hand to evidence_validation/evaluator before ANY hypothesis is acted on · multiplicity honesty: track how many hypotheses were tried (dSR n_trials pattern) so survivors aren't oversold.
