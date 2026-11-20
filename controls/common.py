"""Shared helpers for the controls. Every control reads lockdown.yml - it is
the single source of truth for the locked-table list."""

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCKDOWN_PATH = REPO_ROOT / "controls" / "lockdown.yml"
WAREHOUSE_DIR = REPO_ROOT / "warehouse"
MANIFEST_PATH = WAREHOUSE_DIR / "target" / "manifest.json"
SCOPE_OUT_PATH = REPO_ROOT / "controls" / "out" / "scope.json"

# Make sibling imports work whether run as `python controls/x.py` or imported.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_lockdown(path=None):
    """Return (locked_tables, consumed_by) from lockdown.yml."""
    data = yaml.safe_load(Path(path or LOCKDOWN_PATH).read_text())
    return list(data.get("locked_tables") or []), list(data.get("consumed_by") or [])
