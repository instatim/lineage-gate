# Lineage Gate: PRD

A working miniature of a self-enforcing scope control for financial data. One autonomous Devin CLI run, local only.

## 1. What and why

- **What:** a small repo that shows, end to end, how a lineage-computed scope can enforce itself in CI and detect tampering:
  1. Trace lineage backward from key reports to trusted sources
  2. Check every table in that scope is locked down and has integrity tests
  3. Fail the PR when scope drifts
  4. Flag writes to locked tables by any non-system identity without a break-glass ticket
- **Why:** I'm presenting the full-scale version of this control in an interview. I want a real, runnable miniature that a security engineer can read in five minutes and watch fail and pass.
- **Audience:** security and infrastructure engineers. Code clarity beats features.
- **Not in scope:** a UI, a real warehouse, any cloud service, any account signup.

## 2. Domain (fictional grocery delivery company, no real company names)

Sources:
- `orders_db` (Postgres replica via CDC). Trusted: upstream is change-controlled.
- `payments_provider` (third-party payment processor export). Trusted: provider assurance.
- `partner_feed` (retailer SFTP feed). Not trusted. Must be locked in our warehouse.
- `event_logs` (raw app events). Not trusted. Must be locked in our warehouse.

Warehouse tables, modeled as dbt seeds or staging models: `orders_replica`, `payments`, `order_items`, `retailer_feed`, `events_raw`, `experiments`, `ml_features`.

dbt models: `order_fees`, `item_cost`, `refunds_adj`, `growth_metrics`, then `gross_revenue`, `cogs`, `adjustments`, `growth_kpis`.

Exposures (dbt `exposures:`):
- `revenue_je`, `cogs_je`, `adjustments_je` with `meta: {key_report: true}`
- `growth_dashboard` with no key_report flag. It must NOT pull its lineage into scope.

Lineage on main:
- `revenue_je` <- `gross_revenue` <- `order_fees` <- `orders_replica`, `payments`
- `cogs_je` <- `cogs` <- `item_cost` <- `order_items`, `retailer_feed`
- `adjustments_je` <- `adjustments` <- `refunds_adj` <- `orders_replica`, `events_raw`
- `growth_dashboard` <- `growth_kpis` <- `growth_metrics` <- `experiments`, `ml_features`

## 3. Components

### 3.1 dbt project (`warehouse/`)
- dbt-core + dbt-duckdb, local DuckDB file, no credentials
- Sources declare trust in `meta: {trusted: true, basis: "cdc_change_controlled" | "provider_assurance"}`
- In-scope models carry integrity tests: `not_null`, `unique` where it fits, and one freshness-style or row-count test. Call them "integrity checks" in output
- `dbt build` must pass on main

### 3.2 Lockdown config (`controls/lockdown.yml`)
- One list of locked tables and schemas
- A `consumed_by` list naming the controls that read it: `human_access_review`, `machine_user_review`, `break_glass_monitor`
- This is the single source of truth. Every other script reads it

### 3.3 Lineage gate (`controls/lineage_gate.py`)
- Runs `dbt parse`, reads `target/manifest.json`
- Walks `parent_map` backward from every exposure with `key_report: true`
- Stops at any source with `meta.trusted: true`. Everything else on the path is in scope
- For each in-scope node:
  - in `lockdown.yml`? If not, failure: `NOT_LOCKED`
  - has at least one data test? If not, failure: `NO_INTEGRITY_CHECK`
- Untrusted sources on the path are in scope too, and their tables must be locked
- Output: a readable report grouped by key report, then `PASS` or `FAIL` with each finding on its own line. Exit code 1 on any failure
- Also write `controls/out/scope.json`: key report -> list of in-scope nodes, plus the trusted boundary nodes where tracing stopped
- Deterministic: same input, same output. No network

### 3.4 Write monitor (`controls/write_monitor.py`)
- Reads `controls/sample/query_log.csv` with columns: `ts, identity, identity_type (system|human|break_glass), table, statement, ticket`
- Reads `controls/sample/break_glass_tickets.csv` with columns: `ticket, identity, table, opened, closed, approver, script_reviewed (yes|no)`
- For each write (INSERT, UPDATE, DELETE, MERGE) to a locked table:
  - `system` identity: OK
  - `break_glass` with a matching open ticket that has a reviewed script: `EXPECTED`, listed for manager review
  - anything else: `ALERT`
- Sample data must produce at least one OK, one EXPECTED and one ALERT
- Exit code 1 if any ALERT

### 3.5 CI (`.github/workflows/lineage-gate.yml`)
- On pull_request: install with uv, `dbt deps` if needed, `dbt parse`, run the lineage gate. Required check name: `lineage-gate`
- Second job runs `dbt build` (integrity checks)

### 3.6 Demo (`make demo`)
Scripted, colored terminal walkthrough, pausing for Enter between acts:
1. **Main is clean:** gate PASS, show the scope summary and the trust boundary
2. **Scope drift:** apply `demo/patches/01_ml_features_into_cogs.patch`, which joins `ml_features` into `item_cost`. Gate FAILs: `ml_features` is now in COGS lineage, not locked, no integrity check
3. **Fix:** apply `demo/patches/02_lock_and_test.patch`, which adds `ml_features` to lockdown.yml and adds tests. Gate PASSes
4. **Tamper detection:** run the write monitor on the sample log. Show OK, EXPECTED and ALERT rows
5. Reset the repo to main at the end (`git stash` or a clean checkout of the demo files only)

`make demo-auto` runs the same script with no pauses, for CI and the build report.

### 3.7 README
- One-paragraph pitch, a lineage diagram in Mermaid, how to run, and a table that maps each component to the control it represents: trust boundary, computed scope, fail closed at merge, least privilege from one config, tamper detection
- A section "What the full-scale version adds": column-level lineage, manual verification where pipelines aren't declared in dbt, quarterly publishing of the controlled report list, retroactive chain of custody for late reports, scored access requests with SME review
- No real company names anywhere

## 4. Stack
- Python 3.12, managed with `uv` (install it with the official installer if missing)
- dbt-core and dbt-duckdb, pinned
- `rich` for terminal output is fine. No other heavy dependencies
- Makefile targets: `setup`, `build`, `gate`, `monitor`, `demo`, `demo-auto`, `test`
- pytest tests for the gate (pass on main, fail on drift, trusted sources stop the walk, non-key exposures don't pull scope) and for the monitor

## 5. How the build runs
- Devin CLI, one session, in `~/Documents/Projects/lineage-gate`, bypass permission mode
- No check-ins. Decide using this PRD, log decisions in `DECISIONS.md`, keep going
- Do NOT create a GitHub repo or push anything. Local git only
- Never sign up for anything, never ask for an API key, no deployment

## 6. Acceptance criteria (score each pass or fail with evidence in BUILD_REPORT.md)
1. `make setup && make build` succeeds on a clean clone
2. `make gate` passes on main and prints the scope for all three key reports
3. `growth_dashboard` lineage is not in scope
4. The walk stops at trusted sources and says where
5. After patch 01, `make gate` fails with `NOT_LOCKED` and `NO_INTEGRITY_CHECK` for `ml_features`, exit code 1
6. After patch 02, `make gate` passes
7. `make monitor` reports at least one OK, one EXPECTED and one ALERT, exit code 1
8. `make demo-auto` runs all acts and leaves the working tree clean
9. `make test` passes
10. The GitHub Action workflow file is valid YAML and would run the gate (not executed locally)
11. The README maps every component to the control it represents
12. No real company names in the repo

## 7. Build order
1. Scaffold, uv, dbt project with seeds and models, `dbt build` green
2. lockdown.yml and the lineage gate, with tests
3. Write monitor with sample data, with tests
4. Demo patches and the demo script
5. CI workflow
6. README
7. BUILD_REPORT.md final scoring
