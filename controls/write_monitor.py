"""Write monitor: flag writes to locked tables by non-system identities.

Reads controls/sample/query_log.csv and controls/sample/break_glass_tickets.csv,
checks every INSERT/UPDATE/DELETE/MERGE against the locked-table list from
controls/lockdown.yml, and classifies each write:

  system identity                                        -> OK
  break_glass + open ticket with reviewed script         -> EXPECTED
  anything else (human, break_glass without valid ticket) -> ALERT

Exit code 1 if any ALERT.
"""

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

from common import LOCKDOWN_PATH, REPO_ROOT, load_lockdown

SAMPLE_DIR = REPO_ROOT / "controls" / "sample"
QUERY_LOG = SAMPLE_DIR / "query_log.csv"
TICKETS = SAMPLE_DIR / "break_glass_tickets.csv"

WRITE_RE = re.compile(
    r"\b(insert\s+into|update|delete\s+from|merge\s+into)\s+([^\s,;(]+)",
    re.IGNORECASE,
)


def _parse_ts(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _unqualify(name):
    return (name or "").strip().strip("`\"'").split(".")[-1]


def is_locked_table(table, locked_tables):
    """Match a statement's table token against lockdown entries.

    Entries may be bare table names or schema-qualified; we compare on the
    final dotted component so `main.orders_replica` still matches.
    """
    locked_short = {_unqualify(t) for t in locked_tables}
    return _unqualify(table) in locked_short


def extract_write_target(statement):
    """Return the target table if the statement is a write, else None."""
    m = WRITE_RE.search(statement or "")
    if not m:
        return None
    # Strip quoting from each dotted part: `main`.`payments` -> main.payments
    return ".".join(part.strip("`\"'") for part in m.group(2).split("."))


def ticket_is_valid(ticket_row, identity, table, ts):
    """A break-glass ticket covers a write iff it matches identity+table, is
    open at ts, and its script was reviewed."""
    if not ticket_row:
        return False
    if ticket_row.get("script_reviewed", "").strip().lower() != "yes":
        return False
    if ticket_row.get("identity", "").strip() != identity:
        return False
    if _unqualify(ticket_row.get("table", "")) != _unqualify(table):
        return False
    opened, closed = _parse_ts(ticket_row.get("opened")), _parse_ts(ticket_row.get("closed"))
    when = _parse_ts(ts)
    if when is None or opened is None or when < opened:
        return False
    if closed is not None and when > closed:
        return False
    return True


def evaluate(log_rows, ticket_rows, locked_tables):
    """Classify each write to a locked table. Returns list of dicts:
    {ts, identity, identity_type, table, statement, ticket, verdict}."""
    tickets_by_id = {t.get("ticket", "").strip(): t for t in ticket_rows}
    findings = []
    for row in log_rows:
        table = extract_write_target(row.get("statement", ""))
        if table is None or not is_locked_table(table, locked_tables):
            continue
        itype = (row.get("identity_type") or "").strip().lower()
        identity = (row.get("identity") or "").strip()
        ts = row.get("ts", "")
        ticket = (row.get("ticket") or "").strip()
        if itype == "system":
            verdict = "OK"
        elif itype == "break_glass" and ticket_is_valid(
            tickets_by_id.get(ticket), identity, table, ts
        ):
            verdict = "EXPECTED"
        else:
            verdict = "ALERT"
        findings.append(
            {
                "ts": ts,
                "identity": identity,
                "identity_type": itype,
                "table": table,
                "statement": (row.get("statement") or "").strip(),
                "ticket": ticket,
                "verdict": verdict,
            }
        )
    findings.sort(key=lambda f: (f["ts"], f["identity"], f["statement"]))
    return findings


def _read_csv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write monitor for locked tables")
    ap.add_argument("--query-log", default=str(QUERY_LOG))
    ap.add_argument("--tickets", default=str(TICKETS))
    ap.add_argument("--lockdown", default=str(LOCKDOWN_PATH))
    args = ap.parse_args(argv)

    locked_tables, _ = load_lockdown(args.lockdown)
    findings = evaluate(
        _read_csv(args.query_log), _read_csv(args.tickets), locked_tables
    )

    if not findings:
        print("No writes to locked tables found.")
        return 0

    widths = {k: max(len(k), *(len(str(f[k])) for f in findings)) for k in
              ("ts", "identity", "identity_type", "table", "verdict")}
    header = f"{'ts':<{widths['ts']}}  {'identity':<{widths['identity']}}  {'type':<{widths['identity_type']}}  {'table':<{widths['table']}}  {'verdict':<{widths['verdict']}}"
    print(header)
    print("-" * len(header))
    for f in findings:
        print(
            f"{f['ts']:<{widths['ts']}}  {f['identity']:<{widths['identity']}}  "
            f"{f['identity_type']:<{widths['identity_type']}}  {f['table']:<{widths['table']}}  "
            f"{f['verdict']:<{widths['verdict']}}"
        )
        if f["verdict"] == "ALERT":
            print(f"    statement: {f['statement'][:100]}")
            if f["ticket"]:
                print(f"    ticket: {f['ticket']} (rejected)")

    counts = {v: sum(1 for f in findings if f["verdict"] == v) for v in ("OK", "EXPECTED", "ALERT")}
    print(f"\nSummary: {counts['OK']} OK, {counts['EXPECTED']} EXPECTED (manager review), {counts['ALERT']} ALERT")
    return 1 if counts["ALERT"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
