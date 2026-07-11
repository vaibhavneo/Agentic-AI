# SKILL MARKETPLACE — the registry lifecycle

How skills are registered, discovered, versioned, depended-upon, installed,
deprecated, and upgraded. Built portions are implemented in
`aios_core/runtime/registry.py` + `packs/loader.py`; designed-but-unbuilt
portions are marked ⧗ (do not assume they exist).

## Implemented today

- **Registration** — `Registry.register(entry, persist=)` with manifest
  completeness validation; entries carry `manifest_path` or inline `manifest`.
  Production registry: `brain/skills/registry.json` (10 real skills — the
  `echo` fixture's presence there is tracked debt, M-Q1c).
- **Discovery** — `Registry.discover(query, tag)`, `list_ids()`,
  `get_manifest(id, constraint)`.
- **Semantic versioning** — semver per manifest; constraint grammar
  `>=X.Y.Z <A.B.C` / `=X.Y.Z` / `*`; loud failure on incompatibility.
- **Dependency graph** — `resolve_dependencies(id)` topological, cycle-safe,
  optional-dep aware.
- **Federation** — multiple registries merge in memory (Domain Packs, D15):
  `PackManager` builds core ∪ pack skills and injects via `dispatch(registry=)`
  with ZERO core mutation (test-enforced). `AIOS_SKILLS_DIR` re-homes the
  default library wholesale.
- **Quality gate (SDK)** — a skill enters a registry only if
  `validate_skill(dir, "full")` is VALID; recommended bar: quality ≥85 for
  new skills (legacy grandfathered at core profile per SKILL_VALIDATION.md).

## Designed (⧗ build when a real need appears — YAGNI applies)

- **⧗ Installation** — `install(source_dir) = validate(full) → copy into the
  target skill library → register(persist=True) → run the skill's tests once
  in place`. For pack-shipped skills, installation is already `PackManager.
  load()` (no copy — composite registry); a standalone `install` CLI only
  matters when third-party skill folders start arriving.
- **⧗ Compatibility matrix** — derivable on demand: for each skill × each
  dependency, evaluate `satisfies()` across available versions and emit a
  table. Becomes worth materializing only when ≥2 versions of anything
  coexist; today every skill has exactly one version.
- **⧗ Deprecation** — manifest gains optional `"deprecated": {"since": semver,
  "replacement": id|null, "removal": semver}`; registry surfaces it in
  discover(); dispatcher logs (not blocks) on dispatch of a deprecated skill
  for one major, blocks the major after `removal`. Additive manifest field =
  MINOR registry change.
- **⧗ Upgrade paths** — a skill publishing MAJOR N+1 must ship
  `CHANGELOG.md` migration notes ("breaking:" lines) and SHOULD keep an N-line
  compat shim one major long (precedent: brain/runtime shims, D14). Consumers
  pin majors, so upgrades are always explicit constraint edits, never silent.

## Lifecycle summary

author (template) → validate(full) → score ≥85 → register → discovered/
composed → versioned via CHANGELOG+semver → (⧗ deprecated with replacement)
→ (⧗ removed one major later). Every transition has a deterministic check;
none requires any particular model.
