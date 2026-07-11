# Skill: __SKILL_ID__ v0.1.0

**Purpose:** __the problem this solves (copy manifest.purpose)__

**What it does:** __mechanism in one sentence (copy manifest.description)__

| aspect | value |
|---|---|
| runtime | __python → `entrypoint` / agent (adapter-gated, output schema-enforced)__ |
| execution steps | __STEP_1 → STEP_2 → STEP_3__ |
| inputs / outputs | [input_schema.json](input_schema.json) / [output_schema.json](output_schema.json) |
| memory permissions | __stateless / root=`param` · write: [...] · append-only: [...]__ |
| dependencies | __none / id + semver constraint__ |
| failure modes | typed runtime failures + __skill-specific modes from execution_contract.md §Failure handling__ |
| success metrics | evaluation_contract.md E1…En |
| version | 0.1.0 — see [CHANGELOG.md](CHANGELOG.md) |
| compatibility | any executor honoring the runtime contracts (charter P8); core `>=1.0.0 <2.0.0` |

Behavioral contract: [skill.md](skill.md). Examples: [examples/](examples/). Tests: [tests/](tests/).
