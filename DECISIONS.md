# Decisions

Logged while building sections 5-7 of PRD.md. No check-ins were made; these
are the judgment calls.

## D1. Warehouse tables are dbt seeds, not staging models over sources

PRD 3.1 says sources declare trust in `meta.trusted`. Real dbt `sources`
cannot be `ref`'d in a local DuckDB project - the upstream relations don't
exist and `dbt build` would fail. Options considered:

- **Chosen:** the seven warehouse tables are seeds. Three carry
  `meta.trusted: true` mirroring their upstream (`orders_replica`,
  `payments`, `order_items`); the untrusted-upstream seeds
  (`retailer_feed`, `events_raw`) carry `trusted: false`. The gate's backward
  walk stops at trusted seeds and treats everything else as in scope.
- `warehouse/models/sources.yml` still declares the four upstream systems
  with their trust metadata, as documentation of the trust model (it is
  unreferenced by design - commented as such).
- Rationale: a security engineer can read the whole trust story in one file,
  `dbt build` stays green with zero mocks, and the gate semantics are
  identical to walking to real sources.

## D2. Lockdown list covers every in-scope node, including marts

PRD 3.3 requires each in-scope node to appear in `lockdown.yml`. In-scope
nodes include computed marts (`gross_revenue`, `cogs`, ...), not just base
tables, so `locked_tables` lists all warehouse relations. `ml_features` is
deliberately absent on main so the demo can show `NOT_LOCKED`.

## D3. Integrity checks = generic tests + one custom generic test

`not_null`/`unique` on fitting columns plus a custom generic test
`row_count_not_empty` (macro in `warehouse/macros/`) applied to every
in-scope node. No dbt-utils dependency - keeps the stack to what the PRD
allows.

## D4. Gate implementation details

- `controls/lineage_gate.py` runs `dbt parse`, reads
  `warehouse/target/manifest.json`, walks `parent_map` from exposures whose
  `meta.key_report` is true, and stops at nodes with `meta.trusted: true`.
- "Has an integrity check" = some `test` node's `depends_on.nodes` contains
  the node's unique_id (covers column and model-level tests uniformly).
- Writes `controls/out/scope.json` (gitignored) on every run, PASS or FAIL.
- Deterministic: all reports/nodes sorted; no network, no timestamps in
  output.

## D5. Write monitor matching rules

- Write detection: first keyword among INSERT INTO / UPDATE / DELETE FROM /
  MERGE INTO; target extracted with quoting- and schema-tolerant regex.
- Table match compares final dotted component against `locked_tables`, so
  `main.payments` matches entry `payments`.
- Break-glass validity requires: matching ticket id, same identity, same
  table, `opened <= ts <= closed` (empty closed = still open), and
  `script_reviewed: yes`. Anything else is ALERT. Sample data yields
  4 OK / 1 EXPECTED / 2 ALERT.

## D6. Demo mechanics

- Patches are real `git diff` output in `demo/patches/`, applied with
  `git apply` and reverted with `git checkout -- .` in act 5.
- `demo/demo.py` uses `rich`; `--auto` (make demo-auto) skips Enter pauses.
- Preflight refuses to run on a dirty tree so patches always apply cleanly.

## D7. Tooling pins

- Python 3.12 via uv-managed interpreter; `dbt-core==1.12.7`,
  `dbt-duckdb==1.11.1`, `rich==15.0.0`, `pyyaml==6.0.3`, `pytest==9.2.0`,
  exact pins in `pyproject.toml` + `uv.lock`.
- dbt is always invoked from the repo root with
  `--project-dir warehouse --profiles-dir warehouse`; the DuckDB file lives
  at `warehouse/target/lineage_gate.duckdb` (gitignored).
- No `dbt deps` step in CI: the project has no package dependencies
  (`dbt_utils` deliberately avoided, see D3).

## D8. Bug fix: trusted nodes are in scope (trust-boundary fix)

**Bug found after the initial build.** `compute_scope()` treated
`meta.trusted` nodes as pure boundary: it recorded them in
`trusted_boundary` and excluded them from `in_scope`, so they were never
checked against `lockdown.yml` or test coverage. Proof: deleting `payments`
from `controls/lockdown.yml` still produced `PASS`. That left
`orders_replica`, `payments` and `order_items` - the warehouse copies of the
trusted upstreams - completely undefended.

**Fix.** Trust belongs to the upstream system (`meta.upstream`: `orders_db`
via CDC, `payments_provider` via provider assurance), not to our copy. The
walk still stops at a trusted node - we do not traverse past the boundary -
but the node itself is added to `in_scope`, so `NOT_LOCKED` and
`NO_INTEGRITY_CHECK` apply to it like every other scoped node. The boundary
is now reported as the upstream system, e.g. `trusted boundary: orders_db
(via orders_replica)`, and `scope.json` records the same `upstream (via
node)` form. Regression coverage: a unit test (`payments` unlocked ->
`NOT_LOCKED`) and an integration test that drops `payments` from a copy of
`lockdown.yml`, runs the gate, and asserts exit 1.
