# Build Report

Built per PRD.md sections 5-7 in a single session. Local git only; nothing
pushed. Decisions are in DECISIONS.md.

## Acceptance criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `make setup && make build` succeeds on a clean clone | **PASS** | Cloned to /tmp/lg-clone: `make setup` (uv sync) then `make build` -> `Done. PASS=53 WARN=0 ERROR=0 SKIP=0 NO-OP=4 TOTAL=57` |
| 2 | `make gate` passes on main, prints scope for all three key reports | **PASS** | Exit 0; prints `adjustments_je`, `cogs_je`, `revenue_je` sections with in-scope nodes and trusted boundary |
| 3 | `growth_dashboard` lineage is not in scope | **PASS** | `growth_kpis`, `growth_metrics`, `experiments`, `ml_features` absent from scope; unit test `test_non_key_exposure_does_not_pull_scope` + integration assertion |
| 4 | Walk stops at trusted sources and says where | **PASS** | Output shows `trusted boundary: orders_replica / payments / order_items`; `scope.json` records them per report |
| 5 | After patch 01, gate fails `NOT_LOCKED` + `NO_INTEGRITY_CHECK` for `ml_features`, exit 1 | **PASS** | `demo-auto` act 2: `FAIL lineage gate` with both codes for `seed.lineage_gate.ml_features`, exit 1 |
| 6 | After patch 02, gate passes | **PASS** | `demo-auto` act 3: `PASS lineage gate`, exit 0 |
| 7 | `make monitor` reports >=1 OK, EXPECTED, ALERT; exit 1 | **PASS** | `4 OK, 1 EXPECTED, 2 ALERT`; process exit 1 |
| 8 | `make demo-auto` runs all acts, leaves tree clean | **PASS** | All 5 acts ran, `DEMO_EXIT=0`, `git status --porcelain` empty afterwards |
| 9 | `make test` passes | **PASS** | `15 passed in 1.76s` (8 monitor + 7 gate tests incl. real `dbt parse` integration) |
| 10 | Workflow file valid YAML, would run the gate | **PASS** | `yaml.safe_load` ok; job `lineage-gate` (required check name) runs `uv sync` -> `dbt parse` -> gate `--skip-parse`; second job `dbt-build` runs `dbt build`. Not executed locally (no GitHub remote, per PRD) |
| 11 | README maps every component to the control | **PASS** | "Components -> controls" table covers trust boundary, computed scope, fail closed at merge, least privilege from one config, integrity checks, tamper detection; plus "What the full-scale version adds" section |
| 12 | No real company names | **PASS** | grep for major grocers/retailers across repo: no matches; fictional domain throughout |

## Stack actually used

- Python 3.12 (uv-managed), `dbt-core==1.12.7`, `dbt-duckdb==1.11.1`,
  `rich==15.0.0`, `pyyaml==6.0.3`, `pytest==9.2.0` - exact pins, `uv.lock`
  committed
- Local DuckDB file at `warehouse/target/lineage_gate.duckdb`; no credentials,
  no network, no `dbt deps` needed (no package deps)
- Makefile targets: `setup`, `build`, `gate`, `monitor`, `demo`, `demo-auto`,
  `test` - all exercised above

## Notable deviations (see DECISIONS.md)

- Warehouse tables modeled as **seeds** carrying `meta.trusted` rather than
  staging models over live dbt sources - real sources can't resolve in local
  DuckDB. `sources.yml` documents the four upstream systems and their trust.
- `locked_tables` includes marts as well as base tables, since the gate
  requires every in-scope node to be listed.

## Repo state

Local git repo on `main`, 3 commits, clean working tree. Nothing pushed, no
remote configured, per PRD section 5.
