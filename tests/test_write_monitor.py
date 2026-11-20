"""Tests for the write monitor verdict logic."""

from write_monitor import evaluate, extract_write_target, is_locked_table

LOCKED = ["orders_replica", "payments", "item_cost", "retailer_feed"]


def row(ts, identity, itype, table, statement, ticket=""):
    return {
        "ts": ts,
        "identity": identity,
        "identity_type": itype,
        "table": table,
        "statement": statement,
        "ticket": ticket,
    }


def ticket(tid, identity, table, opened, closed, reviewed):
    return {
        "ticket": tid,
        "identity": identity,
        "table": table,
        "opened": opened,
        "closed": closed,
        "approver": "mgr",
        "script_reviewed": reviewed,
    }


def test_system_write_is_ok():
    findings = evaluate(
        [row("2026-01-01 00:00:01", "dbt", "system", "payments",
             "insert into payments values (1)")],
        [], LOCKED,
    )
    assert [f["verdict"] for f in findings] == ["OK"]


def test_break_glass_with_valid_ticket_is_expected():
    findings = evaluate(
        [row("2026-01-01 10:00:00", "bg_bot", "break_glass", "retailer_feed",
             "merge into retailer_feed using s on true", "BG-1")],
        [ticket("BG-1", "bg_bot", "retailer_feed",
                "2026-01-01 09:00:00", "2026-01-01 11:00:00", "yes")],
        LOCKED,
    )
    assert [f["verdict"] for f in findings] == ["EXPECTED"]


def test_human_write_is_alert():
    findings = evaluate(
        [row("2026-01-01 10:00:00", "analyst", "human", "payments",
             "delete from payments where id = 1")],
        [], LOCKED,
    )
    assert [f["verdict"] for f in findings] == ["ALERT"]


def test_break_glass_without_ticket_is_alert():
    findings = evaluate(
        [row("2026-01-01 10:00:00", "bg_bot", "break_glass", "payments",
             "update payments set x = 1")],
        [], LOCKED,
    )
    assert [f["verdict"] for f in findings] == ["ALERT"]


def test_break_glass_unreviewed_script_is_alert():
    findings = evaluate(
        [row("2026-01-01 10:00:00", "bg_bot", "break_glass", "payments",
             "update payments set x = 1", "BG-2")],
        [ticket("BG-2", "bg_bot", "payments",
                "2026-01-01 09:00:00", "", "no")],
        LOCKED,
    )
    assert [f["verdict"] for f in findings] == ["ALERT"]


def test_break_glass_expired_ticket_is_alert():
    findings = evaluate(
        [row("2026-01-01 12:00:00", "bg_bot", "break_glass", "payments",
             "update payments set x = 1", "BG-3")],
        [ticket("BG-3", "bg_bot", "payments",
                "2026-01-01 09:00:00", "2026-01-01 10:00:00", "yes")],
        LOCKED,
    )
    assert [f["verdict"] for f in findings] == ["ALERT"]


def test_write_to_unlocked_table_ignored():
    findings = evaluate(
        [row("2026-01-01 10:00:00", "analyst", "human", "scratch",
             "insert into scratch values (1)")],
        [], LOCKED,
    )
    assert findings == []


def test_non_write_statement_ignored():
    findings = evaluate(
        [row("2026-01-01 10:00:00", "analyst", "human", "payments",
             "select * from payments")],
        [], LOCKED,
    )
    assert findings == []


def test_schema_qualified_table_still_matches():
    assert is_locked_table("main.payments", LOCKED)
    assert extract_write_target("MERGE INTO `main`.`payments` USING s ON true") == "main.payments"
