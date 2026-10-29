from pathlib import Path

import pytest

from o2c_sim.cycle_builder import CausalCycleAssembler
from o2c_sim.entropy import StreamedEntropy
from o2c_sim.identity import SequenceDesk
from o2c_sim.money import cents_from_text
from o2c_sim.orchestration import O2CPipelineSimulator
from o2c_sim.settings import VOLUME_PLAN
from o2c_sim.verification import CheckResult, LedgerAuditor


EXPECTED_COUNTS = {
    "accounts": 1_800,
    "quotes": 10_000,
    "quote_lines": 10_000,
    "sales_orders": 7_000,
    "order_lines": 7_000,
    "shipments": 7_312,
    "invoices": 8_000,
    "invoice_lines": 8_000,
    "payments": 6_934,
    "payment_allocations": 6_935,
    "disputes": 420,
    "status_events": 15_000,
    "ground_truth": 5,
}

EXPECTED_VOLUMES = {
    "accounts": VOLUME_PLAN.accounts,
    "quotes": VOLUME_PLAN.quotes,
    "quote_lines": VOLUME_PLAN.quotes,
    "sales_orders": VOLUME_PLAN.sales_orders,
    "order_lines": VOLUME_PLAN.sales_orders,
    "invoices": VOLUME_PLAN.invoices,
    "invoice_lines": VOLUME_PLAN.invoices,
    "disputes": VOLUME_PLAN.disputes,
    "status_events": VOLUME_PLAN.timeline_events,
    "ground_truth": 5,
}


@pytest.fixture(scope="module")
def generated_tables():
    return O2CPipelineSimulator().run().tables


def audit(tables):
    return LedgerAuditor(tables, EXPECTED_VOLUMES).run()


def copy_tables(tables):
    return {name: frame.copy(deep=True) for name, frame in tables.items()}


def by_name(report):
    return {check.name: check for check in report.checks}


def test_all_five_anomalies_are_detected_and_evaluated(generated_tables):
    report = audit(generated_tables)
    checks = by_name(report)

    assert report.ok
    for code in (
        "invoice_exceeds_fulfillment",
        "payment_allocated_twice",
        "order_closed_with_unpaid_invoice",
        "status_event_skips_state",
        "dispute_not_in_receivables",
    ):
        assert checks[f"anomaly_detected:{code}"].passed
        assert checks[f"evaluation:{code}_matches_ground_truth"].passed
        assert "detected_ids=" in checks[f"anomaly_detected:{code}"].detail

    truth = generated_tables["ground_truth"].set_index("anomaly_code")
    invoice_order = truth.at["invoice_exceeds_fulfillment", "related_ids"]
    closed_order = truth.at[
        "order_closed_with_unpaid_invoice", "anchor_id"
    ]
    skipped_order = truth.at["status_event_skips_state", "related_ids"]
    assert invoice_order != closed_order
    assert skipped_order not in {invoice_order, closed_order}


def test_detectors_do_not_use_ground_truth_as_input(generated_tables):
    tables = copy_tables(generated_tables)
    tables["ground_truth"]["anchor_id"] = "not-a-real-entity"

    checks = by_name(audit(tables))
    for code in (
        "invoice_exceeds_fulfillment",
        "payment_allocated_twice",
        "order_closed_with_unpaid_invoice",
        "status_event_skips_state",
        "dispute_not_in_receivables",
    ):
        assert checks[f"anomaly_detected:{code}"].passed
        assert not checks[f"evaluation:{code}_matches_ground_truth"].passed


def test_line_item_keys_and_foreign_keys_are_checked(generated_tables):
    tables = copy_tables(generated_tables)
    tables["quote_lines"].at[1, "quote_line_id"] = tables["quote_lines"].at[
        0, "quote_line_id"
    ]
    tables["order_lines"].at[0, "quote_line_id"] = "QTL-2026-999999"

    checks = by_name(audit(tables))
    assert not checks["pk:quote_lines.quote_line_id"].passed
    assert not checks[
        "fk:order_lines.quote_line_id->quote_lines.quote_line_id"
    ].passed


def test_lifecycle_transitions_and_timestamp_order_are_checked(generated_tables):
    tables = copy_tables(generated_tables)
    order_events = tables["status_events"].index[
        (tables["status_events"]["entity_type"] == "sales_order")
        & (tables["status_events"]["from_status"] == "none")
    ]
    tables["status_events"].at[order_events[1], "from_status"] = "unknown"
    tables["shipments"].at[0, "delivered_at"] = tables["shipments"].at[
        0, "packed_at"
    ]
    tables["invoices"].at[0, "issued_at"] = "2000-01-01T00:00:00Z"
    tables["accounts"].at[0, "opened_at"] = "2099-01-01T00:00:00Z"

    checks = by_name(audit(tables))
    assert not checks["evaluation:status_event_skips_state_matches_ground_truth"].passed
    assert not checks["chrono:shipments.shipped_at<=delivered_at"].passed
    assert not checks["chrono:invoice_after_shipment"].passed
    assert not checks["chrono:quote_after_account_open"].passed


def test_financial_reconciliation_detects_unexpected_balance_drift(generated_tables):
    tables = copy_tables(generated_tables)
    payment_amounts = tables["payments"].set_index("payment_id")["payment_amount"]
    allocations = tables["payment_allocations"]
    applied = allocations.groupby("payment_id")["allocated_amount"].apply(
        lambda amounts: sum(cents_from_text(amount) for amount in amounts)
    )
    overallocated = set(
        payment_id
        for payment_id, amount in applied.items()
        if amount > cents_from_text(payment_amounts.at[payment_id])
    )
    known_targets = set(
        allocations.loc[
            allocations["payment_id"].isin(overallocated), "invoice_id"
        ]
    )
    candidate = tables["invoices"].loc[
        (tables["invoices"]["invoice_status"] == "paid")
        & ~tables["invoices"]["invoice_id"].isin(known_targets),
        "invoice_id",
    ].iloc[0]
    index = tables["invoices"].index[
        tables["invoices"]["invoice_id"] == candidate
    ][0]
    tables["invoices"].at[index, "balance_due"] = "0.01"

    checks = by_name(audit(tables))
    assert not checks["financial:invoice_balance_reconciles_to_allocations"].passed
    assert not checks["financial:invoice_status_matches_balance"].passed


def test_financial_reconciliation_does_not_exempt_the_source_invoice(generated_tables):
    tables = copy_tables(generated_tables)
    fault = tables["ground_truth"].loc[
        tables["ground_truth"]["anomaly_code"] == "payment_allocated_twice"
    ].iloc[0]
    source_invoice = str(fault["related_ids"]).split("|")[0]
    index = tables["invoices"].index[
        tables["invoices"]["invoice_id"] == source_invoice
    ][0]
    tables["invoices"].at[index, "balance_due"] = "0.01"

    checks = by_name(audit(tables))
    assert not checks["financial:invoice_balance_reconciles_to_allocations"].passed


def test_invoice_tax_and_totals_are_independently_validated(generated_tables):
    tables = copy_tables(generated_tables)
    tables["invoices"].at[0, "tax_amount"] = "1.00"

    checks = by_name(audit(tables))
    assert not checks["financial:invoice_total_equals_net_plus_tax"].passed
    assert not checks["financial:invoice_tax_rate"].passed


def test_expected_volumes_and_insufficient_dispute_candidates(generated_tables):
    assert {
        table: len(frame) for table, frame in generated_tables.items()
    } == EXPECTED_COUNTS

    tables = copy_tables(generated_tables)
    tables["disputes"] = tables["disputes"].iloc[:-1].reset_index(drop=True)
    assert not by_name(audit(tables))["volume:disputes"].passed

    assembler = CausalCycleAssembler(StreamedEntropy(1), SequenceDesk())
    with pytest.raises(RuntimeError, match="insufficient eligible invoices"):
        assembler._build_disputes(
            [{"invoice_status": "open"} for _ in range(VOLUME_PLAN.disputes - 1)]
        )
    with pytest.raises(RuntimeError, match="invoice target cannot be met"):
        assembler._build_invoices([], [])
    with pytest.raises(RuntimeError, match="insufficient eligible invoices for payment target"):
        assembler._build_settlements(
            [
                {"_order_ref": {"order_status": "fulfilled"}}
                for _ in range(VOLUME_PLAN.payments - 1)
            ]
        )


def test_report_includes_expected_and_observed_evidence(generated_tables):
    checks = by_name(audit(generated_tables))
    assert checks["volume:disputes"].detail == "expected=420 actual=420"
    assert "observed_mismatch_count=" in checks[
        "financial:invoice_balance_reconciles_to_allocations"
    ].detail
    assert "detected_ids=" in checks[
        "anomaly_detected:payment_allocated_twice"
    ].detail


def test_cli_returns_nonzero_when_verification_fails(monkeypatch, tmp_path: Path, capsys):
    from o2c_sim import cli

    class FailedSimulator:
        def __init__(self, seed):
            self.last_report = None
            self.ledger = type("Ledger", (), {"row_census": lambda self: {"accounts": 1}})()

        def run(self, target):
            self.last_report = type(
                "Report",
                (),
                {
                    "ok": False,
                    "checks": [CheckResult("test:failure", False, "observed=bad")],
                },
            )()

    monkeypatch.setattr(cli, "O2CPipelineSimulator", FailedSimulator)
    assert cli.main([str(tmp_path)]) == 2
    assert "FAIL test:failure: observed=bad" in capsys.readouterr().out


def test_cli_returns_zero_when_verification_passes(monkeypatch, tmp_path: Path, capsys):
    from o2c_sim import cli

    class SuccessfulSimulator:
        def __init__(self, seed):
            self.last_report = None
            self.ledger = type("Ledger", (), {"row_census": lambda self: {"accounts": 1}})()

        def run(self, target):
            self.last_report = type(
                "Report",
                (),
                {"ok": True, "checks": [CheckResult("test:success", True, "rows=1")]},
            )()

    monkeypatch.setattr(cli, "O2CPipelineSimulator", SuccessfulSimulator)
    assert cli.main([str(tmp_path)]) == 0
    assert "verification_failed=0" in capsys.readouterr().out


def test_csv_jsonl_sqlite_and_sql_exports(generated_tables, tmp_path: Path):
    import json
    import sqlite3

    simulator = O2CPipelineSimulator()
    simulator.ledger.tables = generated_tables
    simulator.persist(tmp_path)

    assert simulator.last_report is not None and simulator.last_report.ok
    for table, count in EXPECTED_COUNTS.items():
        jsonl = tmp_path / "json" / f"{table}.json"
        rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == count
        assert set(rows[0]) == set(generated_tables[table].columns)

    database = tmp_path / "o2c_ledger.sqlite"
    assert database.is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        for table, count in EXPECTED_COUNTS.items():
            observed = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            assert observed == count
    sql_dump = (tmp_path / "o2c_ledger.sql").read_text(encoding="utf-8")
    assert 'CREATE TABLE "accounts"' in sql_dump
    assert 'CREATE TABLE "ground_truth"' in sql_dump
