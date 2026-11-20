"""Lineage gate: compute the scope of every key report and fail closed.

Walks dbt manifest lineage backward from exposures flagged meta.key_report,
stops at nodes marked meta.trusted, and requires every other node on the path
to be (a) listed in controls/lockdown.yml and (b) covered by at least one data
test. Untrusted sources on the path stay in scope.

Usage:
    python controls/lineage_gate.py [--skip-parse] [--manifest PATH]

Exit code 1 on any finding. Writes controls/out/scope.json either way.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import LOCKDOWN_PATH, MANIFEST_PATH, REPO_ROOT, SCOPE_OUT_PATH, WAREHOUSE_DIR, load_lockdown

BOUNDARY_NODE_TYPES = {"model", "seed", "snapshot", "source"}


def _meta_of(node):
    """Trust metadata lives at node['meta'] (dbt mirrors it into config.meta)."""
    return (node or {}).get("meta") or (node or {}).get("config", {}).get("meta") or {}


def _is_trusted(node):
    return _meta_of(node).get("trusted") is True


def _display_name(node_id, node):
    """Human-readable node name for reports and lockdown matching."""
    node = node or {}
    if node.get("resource_type") == "source" or "source_name" in node:
        return f"{node.get('source_name')}.{node.get('name', node_id)}"
    return node.get("name") or node_id


def _lock_keys(node_id, node):
    """All strings a lockdown.yml entry may use to name this node."""
    node = node or {}
    name = node.get("name") or node_id.split(".")[-1]
    keys = {name}
    if node.get("source_name"):
        keys.add(f"{node['source_name']}.{name}")
    return keys


def _lookup(manifest, node_id):
    for section in ("nodes", "sources", "exposures"):
        if node_id in manifest.get(section, {}):
            return manifest[section][node_id]
    return None


def compute_scope(manifest):
    """Return {key_report: {"in_scope": [node_ids], "trusted_boundary": [node_ids]}}.

    Deterministic: reports, nodes and boundary lists are all sorted.
    """
    parent_map = manifest.get("parent_map", {})
    scope = {}
    for exp_id in sorted(manifest.get("exposures", {})):
        exp = manifest["exposures"][exp_id]
        if not _meta_of(exp).get("key_report"):
            continue
        in_scope, boundary, seen = set(), set(), set()
        stack = list(exp.get("depends_on", {}).get("nodes") or parent_map.get(exp_id, []))
        while stack:
            node_id = stack.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            node = _lookup(manifest, node_id)
            if node is None or node.get("resource_type") not in BOUNDARY_NODE_TYPES | {"exposure"}:
                continue
            if _is_trusted(node):
                boundary.add(node_id)
                continue  # trust boundary: do not walk past it, do not scope it
            if node.get("resource_type") == "exposure":
                stack.extend(parent_map.get(node_id, []))
                continue
            in_scope.add(node_id)
            stack.extend(parent_map.get(node_id, []))
        scope[exp.get("name", exp_id)] = {
            "in_scope": sorted(in_scope),
            "trusted_boundary": sorted(boundary),
        }
    return scope


def evaluate(manifest, locked_tables):
    """Check scope against lockdown + test coverage. Returns (scope, findings).

    findings: list of (code, key_report, node_id); code is NOT_LOCKED or
    NO_INTEGRITY_CHECK.
    """
    locked = set(locked_tables)
    covered = set()
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") == "test":
            covered.update(node.get("depends_on", {}).get("nodes") or [])

    scope = compute_scope(manifest)
    findings = []
    for report in sorted(scope):
        for node_id in scope[report]["in_scope"]:
            node = _lookup(manifest, node_id) or {}
            if not (_lock_keys(node_id, node) & locked):
                findings.append(("NOT_LOCKED", report, node_id))
            if node_id not in covered:
                findings.append(("NO_INTEGRITY_CHECK", report, node_id))
    return scope, findings


def run_dbt_parse(project_dir=WAREHOUSE_DIR, profiles_dir=WAREHOUSE_DIR):
    cmd = ["dbt", "parse", "--project-dir", str(project_dir), "--profiles-dir", str(profiles_dir)]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"dbt parse failed ({proc.returncode})")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lineage scope gate")
    ap.add_argument("--manifest", default=str(MANIFEST_PATH))
    ap.add_argument("--lockdown", default=str(LOCKDOWN_PATH))
    ap.add_argument("--scope-out", default=str(SCOPE_OUT_PATH))
    ap.add_argument("--skip-parse", action="store_true", help="reuse existing manifest.json")
    ap.add_argument("--project-dir", default=str(WAREHOUSE_DIR))
    ap.add_argument("--profiles-dir", default=str(WAREHOUSE_DIR))
    args = ap.parse_args(argv)

    if not args.skip_parse:
        run_dbt_parse(args.project_dir, args.profiles_dir)

    manifest = json.loads(Path(args.manifest).read_text())
    locked_tables, _consumed_by = load_lockdown(args.lockdown)
    scope, findings = evaluate(manifest, locked_tables)

    # scope.json: key report -> in-scope node names + trusted boundary names.
    out_path = Path(args.scope_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        report: {
            "in_scope": sorted(_display_name(n, _lookup(manifest, n)) for n in v["in_scope"]),
            "trusted_boundary": sorted(_display_name(n, _lookup(manifest, n)) for n in v["trusted_boundary"]),
        }
        for report, v in sorted(scope.items())
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    for report in sorted(scope):
        print(f"\n== key report: {report} ==")
        for n in payload[report]["in_scope"]:
            print(f"  in scope:        {n}")
        for n in payload[report]["trusted_boundary"]:
            print(f"  trusted boundary: {n}")

    if findings:
        print("\nFAIL lineage gate")
        for code, report, node_id in findings:
            print(f"  {code} {node_id}  (in lineage of {report})")
        return 1

    print("\nPASS lineage gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
