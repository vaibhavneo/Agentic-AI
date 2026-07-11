---
name: critic
version: 1.0.0
description: Adversarial review of produced work against evidence and constraints — runs AFTER generation, BEFORE acceptance. Use on distilled insights, analyses, and recommendations.
reference_impl: second_brain/critic.py (deterministic scorer) · stock_agent positive-edge filter · brain/agents CriticAgent
---
# critic
**Purpose:** break the self-confirmation loop — the generator never grades its own homework.
**Inputs:** claims/artifacts to review · evidence source (retrieval index, computed facts)
**Outputs:** per-claim verdict {confidence 0-1, status supported|partial|unsupported, evidence[], flags[]} + critic_report.md.
**Contract:** verdicts computed FROM retrieved/computed evidence, never from the critic's own priors (deterministic scoring preferred: e.g. 0.5·retrieval_support + 0.5·source_corroboration) · scores must discriminate (uniform 1.0 = broken critic) · unverifiable provenance gets FLAGGED not rejected or accepted · fixing a low score means acquiring evidence, never editing the verdict (D11).
