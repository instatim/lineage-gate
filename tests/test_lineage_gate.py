"""Tests for the lineage gate.

Unit tests build synthetic manifests to exercise the walk; one integration
test runs `dbt parse` against the real warehouse project.
"""

import json

import pytest

import lineage_gate as gate
from common import LOCKDOWN_PATH, MANIFEST_PATH, WAREHOUSE_DIR, load_lockdown


def node(name, resource_type="model", meta=None, parents=()):
    return {
        "name": name,
        "resource_type": resource_type,
        "meta": meta or {},
        "depends_on": {"nodes": list(parents), "macros": []},
    }


def data_test(name, target):
    return {
        "name": f"test_{name}",
        "resource_type": "test",
        "depends_on": {"nodes": [target], "macros": []},
    }


def exposure(name, key_report, parents):
    return {
        "name": name,
        "resource_type": "exposure",
        "meta": {"key_report": True} if key_report else {},
        "depends_on": {"nodes": list(parents), "macros": []},
    }


def make_manifest(nodes, exposures, parent_map):
    return {
        "nodes": {f"{n['resource_type']}.p.{n['name']}": n for n in nodes},
        "sources": {},
        "exposures": {f"exposure.p.{e['name']}": e for e in exposures},
        "parent_map": parent_map,
    }


def ids_of(manifest, kind="model"):
    return {k: v for k, v in manifest["nodes"].items() if v["resource_type"] == kind}


# ---------------------------------------------------------------- unit tests


def test_trusted_source_stops_the_walk():
    """A trusted node is a boundary: recorded, not scoped, and its own parents
    are never traversed."""
    trusted = node("orders_replica", "seed", meta={"trusted": True})
    upstream_of_trusted = node("orders_db_raw", "seed")
    mart = node("order_fees")
    nodes = [trusted, upstream_of_trusted, mart]
    tests = [data_test("t", "model.p.order_fees"), data_test("t2", "seed.p.orders_replica")]
    nodes += tests
    manifest = make_manifest(
        nodes,
        [exposure("revenue_je", True, ["model.p.order_fees"])],
        {
            "exposure.p.revenue_je": ["model.p.order_fees"],
            "model.p.order_fees": ["seed.p.orders_replica"],
            # trusted node claims a parent - the walk must NOT follow it
            "seed.p.orders_replica": ["seed.p.orders_db_raw"],
        },
    )
    scope, findings = gate.evaluate(manifest, ["order_fees", "orders_replica"])
    rep = scope["revenue_je"]
    assert rep["trusted_boundary"] == ["seed.p.orders_replica"]
    assert "seed.p.orders_db_raw" not in rep["in_scope"]
    assert findings == []


def test_untrusted_source_stays_in_scope():
    """Untrusted leaf nodes on the path are in scope and must be locked+tested."""
    leaf = node("retailer_feed", "seed", meta={"trusted": False})
    mart = node("item_cost")
    manifest = make_manifest(
        [leaf, mart, data_test("t", "model.p.item_cost"), data_test("t2", "seed.p.retailer_feed")],
        [exposure("cogs_je", True, ["model.p.item_cost"])],
        {
            "exposure.p.cogs_je": ["model.p.item_cost"],
            "model.p.item_cost": ["seed.p.retailer_feed"],
        },
    )
    scope, findings = gate.evaluate(manifest, ["item_cost", "retailer_feed"])
    assert "seed.p.retailer_feed" in scope["cogs_je"]["in_scope"]
    assert findings == []


def test_drift_fails_with_not_locked_and_no_integrity_check():
    """ml_features joined into COGS lineage: unlocked + untested -> both codes."""
    rogue = node("ml_features", "seed")  # no trusted meta, no tests
    item_cost = node("item_cost")
    cogs = node("cogs")
    nodes = [
        rogue, item_cost, cogs,
        data_test("t1", "model.p.item_cost"),
        data_test("t2", "model.p.cogs"),
    ]
    manifest = make_manifest(
        nodes,
        [exposure("cogs_je", True, ["model.p.cogs"])],
        {
            "exposure.p.cogs_je": ["model.p.cogs"],
            "model.p.cogs": ["model.p.item_cost"],
            "model.p.item_cost": ["seed.p.ml_features"],
        },
    )
    scope, findings = gate.evaluate(manifest, ["item_cost", "cogs"])
    codes = {(c, n) for c, _r, n in findings}
    assert ("NOT_LOCKED", "seed.p.ml_features") in codes
    assert ("NO_INTEGRITY_CHECK", "seed.p.ml_features") in codes
    assert "seed.p.ml_features" in scope["cogs_je"]["in_scope"]


def test_non_key_exposure_does_not_pull_scope():
    """growth_dashboard has no key_report flag: its unlocked, untested lineage
    must not produce findings."""
    rogue = node("ml_features", "seed")
    mart = node("growth_kpis")
    manifest = make_manifest(
        [rogue, mart],
        [exposure("growth_dashboard", False, ["model.p.growth_kpis"])],
        {
            "exposure.p.growth_dashboard": ["model.p.growth_kpis"],
            "model.p.growth_kpis": ["seed.p.ml_features"],
        },
    )
    scope, findings = gate.evaluate(manifest, [])
    assert scope == {}
    assert findings == []


def test_missing_lockdown_entry_and_missing_test_are_independent():
    """A locked but untested node fails only NO_INTEGRITY_CHECK."""
    leaf = node("events_raw", "seed")
    mart = node("refunds_adj")
    manifest = make_manifest(
        [leaf, mart, data_test("t", "model.p.refunds_adj")],
        [exposure("adjustments_je", True, ["model.p.refunds_adj"])],
        {
            "exposure.p.adjustments_je": ["model.p.refunds_adj"],
            "model.p.refunds_adj": ["seed.p.events_raw"],
        },
    )
    _scope, findings = gate.evaluate(manifest, ["refunds_adj", "events_raw"])
    assert findings == [("NO_INTEGRITY_CHECK", "adjustments_je", "seed.p.events_raw")]


# ------------------------------------------------------- integration test


@pytest.fixture(scope="module")
def real_manifest(tmp_path_factory):
    gate.run_dbt_parse()
    return json.loads(MANIFEST_PATH.read_text())


def test_gate_passes_on_main(real_manifest):
    locked, _ = load_lockdown(LOCKDOWN_PATH)
    scope, findings = gate.evaluate(real_manifest, locked)
    assert findings == []
    assert set(scope) == {"revenue_je", "cogs_je", "adjustments_je"}

    def names(report):
        return {
            gate._display_name(n, gate._lookup(real_manifest, n))
            for n in scope[report]["in_scope"]
        }

    assert names("revenue_je") == {"gross_revenue", "order_fees"}
    assert names("cogs_je") == {"cogs", "item_cost", "retailer_feed"}
    assert names("adjustments_je") == {"adjustments", "refunds_adj", "events_raw"}

    # Trusted boundary: walk stops at trusted seeds and reports where.
    boundary = {
        gate._display_name(n, gate._lookup(real_manifest, n))
        for rep in scope.values()
        for n in rep["trusted_boundary"]
    }
    assert boundary == {"orders_replica", "payments", "order_items"}

    # growth_dashboard lineage must not appear anywhere.
    all_scoped = {n for rep in scope.values() for n in rep["in_scope"]}
    assert not {"growth_kpis", "growth_metrics", "experiments", "ml_features"} & {
        gate._display_name(n, gate._lookup(real_manifest, n)) for n in all_scoped
    }
