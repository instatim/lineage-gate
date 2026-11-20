"""Scripted terminal walkthrough of the lineage gate control.

Acts:
  1. Main is clean        - gate PASS, scope + trust boundary
  2. Scope drift          - patch 01 pulls ml_features into COGS lineage -> FAIL
  3. Fix                  - patch 02 locks + tests ml_features -> PASS
  4. Tamper detection     - write monitor over the sample query log
  5. Reset                - restore the working tree to main

`make demo` pauses for Enter between acts; `make demo-auto` does not.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_DIR = REPO_ROOT / "demo" / "patches"
SCOPE_JSON = REPO_ROOT / "controls" / "out" / "scope.json"

console = Console()
AUTO = False


def pause(msg="Press Enter for the next act"):
    if AUTO:
        time.sleep(0.4)
        return
    try:
        input(f"\n{msg}... ")
    except EOFError:
        pass


def run(cmd, check=False, capture=False):
    return subprocess.run(
        cmd, cwd=REPO_ROOT, text=True,
        capture_output=capture, check=check,
    )


def gate():
    return run([sys.executable, "controls/lineage_gate.py"], capture=True)


def banner(act, title):
    console.print()
    console.print(Panel(f"[bold]Act {act}[/bold] - {title}", style="cyan"))


def show_gate_output(proc):
    for line in (proc.stdout or "").splitlines():
        style = "red" if line.startswith(("FAIL", "  NOT", "  NO_")) else (
            "green" if line.startswith("PASS") else None
        )
        console.print(f"  [dim]{line}[/dim]" if style is None else f"  [{style}]{line}[/{style}]")


def act1():
    banner(1, "Main is clean")
    console.print("Running the lineage gate on a clean checkout of main...")
    proc = gate()
    show_gate_output(proc)
    if proc.returncode != 0:
        console.print("[red]Unexpected: gate failed on main.[/red]")
        return False

    scope = json.loads(SCOPE_JSON.read_text())
    table = Table(title="Computed scope per key report")
    table.add_column("key report")
    table.add_column("in scope")
    table.add_column("trusted boundary (walk stops here)")
    for report, data in scope.items():
        table.add_row(
            report,
            "\n".join(data["in_scope"]),
            "\n".join(data["trusted_boundary"]),
        )
    console.print(table)
    console.print(
        "[dim]growth_dashboard is not a key report, so its lineage "
        "(experiments, ml_features) stays out of scope.[/dim]"
    )
    return True


def act2():
    banner(2, "Scope drift")
    console.print(
        "A data scientist joins ml_features into item_cost to add a score. "
        "ml_features is not locked down and has no integrity checks..."
    )
    patch = PATCH_DIR / "01_ml_features_into_cogs.patch"
    proc = run(["git", "apply", str(patch)], capture=True)
    if proc.returncode != 0:
        console.print(f"[red]git apply failed:[/red]\n{proc.stderr}")
        return False
    console.print(f"[dim]applied {patch.name}[/dim]\n")
    console.print("Re-running the gate (this is what CI would do on the PR):")
    proc = gate()
    show_gate_output(proc)
    console.print(
        "\n[red]The PR fails closed: ml_features entered the COGS lineage and is "
        "both NOT_LOCKED and missing integrity checks.[/red]"
    )
    return proc.returncode == 1


def act3():
    banner(3, "Fix")
    console.print(
        "Remediation: lock ml_features down and give it integrity checks "
        "(the same thing the access-review controls consume)."
    )
    patch = PATCH_DIR / "02_lock_and_test.patch"
    proc = run(["git", "apply", str(patch)], capture=True)
    if proc.returncode != 0:
        console.print(f"[red]git apply failed:[/red]\n{proc.stderr}")
        return False
    console.print(f"[dim]applied {patch.name}[/dim]\n")
    console.print("Re-running the gate:")
    proc = gate()
    show_gate_output(proc)
    console.print("\n[green]Gate passes again - scope is locked and tested.[/green]")
    return proc.returncode == 0


def act4():
    banner(4, "Tamper detection")
    console.print(
        "Separately from merge-time enforcement, the write monitor watches the "
        "query log for writes to locked tables by non-system identities."
    )
    proc = run([sys.executable, "controls/write_monitor.py"], capture=True)
    console.print(proc.stdout)
    console.print(
        "[dim]Exit code 1 because ALERTs exist: a human deleted payment rows, "
        "and a break-glass write referenced a ticket whose script was never "
        "reviewed. The EXPECTED row had a valid open ticket.[/dim]"
    )
    return "ALERT" in proc.stdout


def act5():
    banner(5, "Reset")
    run(["git", "checkout", "--", "."])
    dirty = run(["git", "status", "--porcelain"], capture=True).stdout.strip()
    # controls/out and warehouse/target are gitignored; anything else is real.
    real_dirty = [l for l in dirty.splitlines() if not l.startswith("?? demo/")]
    if real_dirty:
        console.print(f"[red]Working tree not clean:[/red]\n{dirty}")
        return False
    console.print("[green]Working tree restored to main. Demo complete.[/green]")
    return True


def preflight():
    proc = run(["git", "status", "--porcelain"], capture=True)
    dirty = [l for l in proc.stdout.splitlines() if l.strip()]
    if dirty:
        console.print(
            "[red]Working tree is not clean. Commit or stash your changes first "
            "- the demo applies and reverts patches.[/red]"
        )
        for line in dirty:
            console.print(f"  {line}")
        return False
    return True


def main():
    global AUTO
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true", help="no pauses (CI / reports)")
    args = ap.parse_args()
    AUTO = args.auto

    console.print(
        Panel.fit(
            "[bold]Lineage Gate[/bold] - a self-enforcing scope control for "
            "financial data\nlineage -> lockdown -> integrity checks -> "
            "tamper detection",
            border_style="blue",
        )
    )
    if not preflight():
        return 1

    ok = True
    for fn in (act1, act2, act3, act4, act5):
        try:
            result = fn()
        except Exception as exc:  # keep the demo alive, report the act
            console.print(f"[red]Act failed with exception: {exc}[/red]")
            result = False
        ok = ok and bool(result)
        if fn is not act5:
            pause()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
