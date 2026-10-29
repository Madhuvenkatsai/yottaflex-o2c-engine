from pathlib import Path

import pytest
import pandas as pd

from o2c_sim.cycle_builder import CausalCycleAssembler
from o2c_sim.entropy import StreamedEntropy
from o2c_sim.identity import SequenceDesk
from o2c_sim.money import cents_from_text
from o2c_sim.orchestration import O2CPipelineSimulator
from o2c_sim.settings import STARTER_VOLUME_PLAN, VOLUME_PLAN
from o2c_sim.verification import ANOMALY_CODES, CheckResult, LedgerAuditor


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
    "ground_truth": len(ANOMALY_CODES),
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
    "ground_truth": len(ANOMALY_CODES),
}


@pytest.fixture(scope="module")
def generated_tables():
    return O2CPipelineSimulator().run().tables


def audit(tables, volume_plan=VOLUME_PLAN):
    return LedgerAuditor(tables, EXPECTED_VOLUMES, volume_plan).run()


def copy_tables(tables):
    return {name: frame.copy(deep=True) for name, frame in tables.items()}


def by_name(report):
    return {check.name: check for check in report.checks}


def test_required_and_coverage_anomalies_are_detected_and_evaluated(generated_tables):
    report = audit(generated_tables)
    checks = by_name(report)

    assert report.ok
    for code in (
        "invoice_exceeds_fulfillment",
        "payment_allocated_twice",
        "order_closed_with_unpaid_invoice",
        "status_event_skips_state",
        "dispute_not_in_receivables",
        "underbilling",
        "duplicate_invoice",
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
    assert len(truth) == len(ANOMALY_CODES)

    shipments_by_order = generated_tables["shipments"].groupby("sales_order_id").size()
    assert (shipments_by_order > 1).any()
    assert checks["financial:short_paid_invoices"].passed
    assert checks["financial:aging_at_fixed_cutoff"].passed
    assert "over_90_days" in checks["financial:aging_at_fixed_cutoff"].detail

    skipped_event_id = truth.at["status_event_skips_state", "anchor_id"]
    skipped_event = generated_tables["status_events"].set_index("event_id").loc[
        skipped_event_id
    ]
    assert skipped_event["from_status"] == "booked"
    assert skipped_event["to_status"] == "closed"
    assert (
        generated_tables["status_events"]["entity_id"]
        .eq(skipped_event["entity_id"])
        .any()
    )


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
        "underbilling",
        "duplicate_invoice",
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


def test_all_stateful_entities_have_complete_event_history(generated_tables):
    checks = by_name(audit(generated_tables))
    assert checks["lifecycle:event_history_complete"].passed
    assert len(generated_tables["status_events"]) > VOLUME_PLAN.timeline_events
    assert (
        len(generated_tables["status_events"])
        + len(generated_tables["payments"])
        >= VOLUME_PLAN.timeline_events
    )


def test_quantity_reconciliation_handles_split_shipments_and_invoices(generated_tables):
    checks = by_name(audit(generated_tables))
    assert checks["quantity:fulfillment_to_invoice_reconciliation"].passed
    assert checks["quantity:shipment_not_exceed_ordered"].passed
    assert checks["quantity:ordinary_invoice_quantity_not_exceed_fulfilled"].passed
    assert checks["financial:invoice_line_quantity_times_unit_price"].passed
    assert checks["financial:shipment_quantity_times_order_unit_price"].passed
    assert checks[
        "relationship:order_line_quantity_price_matches_quote_line"
    ].passed

    shipment_counts = generated_tables["shipments"].groupby("sales_order_id").size()
    invoice_counts = generated_tables["invoices"].groupby("sales_order_id").size()
    assert (shipment_counts > 1).any()
    assert (invoice_counts > 1).any()


def test_quantity_overbilling_is_detected_without_ground_truth(generated_tables):
    tables = copy_tables(generated_tables)
    shipment_qty = tables["shipments"].groupby("sales_order_id")[
        "fulfilled_quantity"
    ].sum()
    invoice_qty = tables["invoice_lines"].merge(
        tables["invoices"][["invoice_id", "sales_order_id"]],
        on="invoice_id",
        suffixes=("", "_invoice"),
    ).groupby("sales_order_id")["quantity"].sum()
    invoice_counts = tables["invoices"].groupby("sales_order_id").size()
    orders = tables["sales_orders"].set_index("sales_order_id")
    candidate = next(
        row
        for _, row in tables["invoices"].loc[
            tables["invoices"]["invoice_status"] == "open"
        ].iterrows()
        if row["sales_order_id"] in shipment_qty.index
        and shipment_qty[row["sales_order_id"]]
        == invoice_qty.get(row["sales_order_id"], 0)
        and invoice_counts.get(row["sales_order_id"], 0) == 1
        and orders.at[row["sales_order_id"], "order_status"] != "closed"
    )
    invoice_id = candidate["invoice_id"]
    line_index = tables["invoice_lines"].index[
        tables["invoice_lines"]["invoice_id"] == invoice_id
    ][0]
    unit_price_cents = cents_from_text(
        tables["invoice_lines"].at[line_index, "unit_price"]
    )
    new_amount = cents_from_text(candidate["invoice_amount"]) + unit_price_cents
    account_region = tables["accounts"].set_index("account_id").at[
        candidate["account_id"], "region"
    ]
    tax = 0 if account_region.startswith("NA") else int(round(new_amount * 0.08))
    total = new_amount + tax
    tables["invoice_lines"].at[line_index, "quantity"] += 1
    tables["invoice_lines"].at[line_index, "line_amount"] = (
        f"{new_amount / 100:.2f}"
    )
    invoice_index = tables["invoices"].index[
        tables["invoices"]["invoice_id"] == invoice_id
    ][0]
    tables["invoices"].at[invoice_index, "invoice_amount"] = f"{new_amount / 100:.2f}"
    tables["invoices"].at[invoice_index, "tax_amount"] = f"{tax / 100:.2f}"
    tables["invoices"].at[invoice_index, "total_due"] = f"{total / 100:.2f}"
    tables["invoices"].at[invoice_index, "balance_due"] = f"{total / 100:.2f}"
    tables["ground_truth"]["anchor_id"] = "not-a-real-entity"

    checks = by_name(audit(tables))
    assert invoice_id in checks[
        "anomaly_detected:invoice_exceeds_fulfillment"
    ].detail
    assert not checks["quantity:fulfillment_to_invoice_reconciliation"].passed
    assert checks["financial:invoice_line_quantity_times_unit_price"].passed


def test_order_and_shipment_quantities_reconcile_to_source_lines(generated_tables):
    tables = copy_tables(generated_tables)
    tables["order_lines"].at[0, "quantity"] += 1

    checks = by_name(audit(tables))
    assert not checks[
        "relationship:order_line_quantity_price_matches_quote_line"
    ].passed
    assert not checks["financial:order_lines_quantity_times_unit_price"].passed

    tables = copy_tables(generated_tables)
    tables["shipments"].at[0, "fulfilled_amount"] = "0.01"
    checks = by_name(audit(tables))
    assert not checks[
        "financial:shipment_quantity_times_order_unit_price"
    ].passed


def test_starter_scale_has_expected_volumes_and_detects_required_anomalies():
    from o2c_sim.settings import STARTER_VOLUME_PLAN

    tables = O2CPipelineSimulator(scale="starter").run().tables
    expected = {
        "accounts": STARTER_VOLUME_PLAN.accounts,
        "quotes": STARTER_VOLUME_PLAN.quotes,
        "quote_lines": STARTER_VOLUME_PLAN.quotes,
        "sales_orders": STARTER_VOLUME_PLAN.sales_orders,
        "order_lines": STARTER_VOLUME_PLAN.sales_orders,
        "shipments": 753,
        "invoices": STARTER_VOLUME_PLAN.invoices,
        "invoice_lines": STARTER_VOLUME_PLAN.invoices,
        "payments": STARTER_VOLUME_PLAN.payments,
        "payment_allocations": STARTER_VOLUME_PLAN.payments + 1,
        "disputes": STARTER_VOLUME_PLAN.disputes,
        "status_events": 8_419,
        "ground_truth": len(ANOMALY_CODES),
    }
    report = LedgerAuditor(tables, expected, STARTER_VOLUME_PLAN).run()
    assert report.ok, [check for check in report.checks if not check.passed]
    checks = by_name(report)
    for code in ANOMALY_CODES:
        assert checks[f"anomaly_detected:{code}"].passed
        assert checks[f"evaluation:{code}_matches_ground_truth"].passed
    assert (
        len(tables["payments"]) + len(tables["status_events"])
        >= STARTER_VOLUME_PLAN.timeline_events
    )


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


def test_underbilling_duplicate_invoice_and_aging_are_reported(generated_tables):
    checks = by_name(audit(generated_tables))
    assert checks["anomaly_detected:underbilling"].passed
    assert checks["anomaly_detected:duplicate_invoice"].passed
    assert checks["financial:fulfillment_to_invoice_reconciliation"].passed
    assert checks["financial:aging_at_fixed_cutoff"].passed

    tables = copy_tables(generated_tables)
    tables["invoices"]["due_at"] = "2026-10-22T18:00:00Z"
    aged = by_name(audit(tables))["financial:aging_at_fixed_cutoff"]
    assert not aged.passed
    assert "over_90_days" in aged.detail


def test_expected_volumes_and_insufficient_dispute_candidates(generated_tables):
    actual_fixed_counts = {
        table: len(frame) for table, frame in generated_tables.items()
        if table in EXPECTED_COUNTS
    }
    assert actual_fixed_counts == EXPECTED_COUNTS
    assert (
        len(generated_tables["status_events"])
        + len(generated_tables["payments"])
        >= VOLUME_PLAN.timeline_events
    )

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
    starter_assembler = CausalCycleAssembler(
        StreamedEntropy(1), SequenceDesk(), STARTER_VOLUME_PLAN
    )
    with pytest.raises(RuntimeError, match="insufficient eligible invoices"):
        starter_assembler._build_disputes(
            [{"invoice_status": "open"} for _ in range(STARTER_VOLUME_PLAN.disputes - 1)]
        )
    with pytest.raises(RuntimeError, match="insufficient eligible invoices for payment target"):
        starter_assembler._build_settlements(
            [
                {"_order_ref": {"order_status": "fulfilled"}}
                for _ in range(STARTER_VOLUME_PLAN.payments - 1)
            ]
        )
    with pytest.raises(RuntimeError, match="invoice target cannot be met"):
        starter_assembler._build_invoices([], [])

    from o2c_sim.fault_injection import KnownFaultInjector

    with pytest.raises(RuntimeError, match="no invoice available for fulfillment overrun"):
        KnownFaultInjector(SequenceDesk())._invoice_beyond_shipped(
            {"invoices": [], "shipments": []}, []
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
    reconciliation = checks[
        "financial:fulfillment_to_invoice_reconciliation"
    ].detail
    assert "expected_deltas_cents=" in reconciliation
    assert "observed_deltas_cents=" in reconciliation
    assert "unexpected_orders=[]" in reconciliation


def test_cli_returns_nonzero_when_verification_fails(monkeypatch, tmp_path: Path, capsys):
    from o2c_sim import cli

    class FailedSimulator:
        def __init__(self, seed, scale):
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
        def __init__(self, seed, scale):
            assert seed == 20261022
            assert scale == "starter"
            self.last_report = None
            self.ledger = type("Ledger", (), {"row_census": lambda self: {"accounts": 1}})()

        def run(self, target):
            self.last_report = type(
                "Report",
                (),
                {"ok": True, "checks": [CheckResult("test:success", True, "rows=1")]},
            )()

    monkeypatch.setattr(cli, "O2CPipelineSimulator", SuccessfulSimulator)
    assert cli.main(["--scale", "starter", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "scale=starter" in output
    assert "verification_failed=0" in output


def test_csv_jsonl_sqlite_and_sql_exports(generated_tables, tmp_path: Path):
    import json
    import sqlite3

    simulator = O2CPipelineSimulator()
    simulator.ledger.tables = generated_tables
    simulator.persist(tmp_path)

    assert simulator.last_report is not None and simulator.last_report.ok
    for table, frame in generated_tables.items():
        count = len(frame)
        jsonl = tmp_path / "json" / f"{table}.json"
        rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == count
        assert set(rows[0]) == set(generated_tables[table].columns)
        csv_rows = pd.read_csv(
            tmp_path / f"{table}.csv", dtype=str, keep_default_na=False
        ).to_dict("records")
        json_rows = [
            {key: "" if value is None else str(value) for key, value in row.items()}
            for row in rows
        ]
        assert json_rows == csv_rows

    database = tmp_path / "o2c_ledger.sqlite"
    assert database.is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        for table, frame in generated_tables.items():
            count = len(frame)
            observed = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            assert observed == count
            sqlite_rows = connection.execute(
                f'SELECT * FROM "{table}"'
            ).fetchall()
            normalized = [
                ["" if value is None else str(value) for value in row]
                for row in sqlite_rows
            ]
            assert normalized == [
                ["" if pd.isna(value) else str(value) for value in row]
                for row in frame.itertuples(index=False, name=None)
            ]
    sql_dump = (tmp_path / "o2c_ledger.sql").read_text(encoding="utf-8")
    assert 'CREATE TABLE "accounts"' in sql_dump
    assert 'CREATE TABLE "ground_truth"' in sql_dump
    restored = tmp_path / "restored.sqlite"
    with sqlite3.connect(restored) as connection:
        connection.executescript(sql_dump)
        for table, frame in generated_tables.items():
            assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == len(frame)
