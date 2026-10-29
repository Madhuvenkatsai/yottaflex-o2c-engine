from dataclasses import dataclass, field
import re

import pandas as pd

from o2c_sim.money import cents_from_text


ID_PATTERN = re.compile(r"^(ACC|QTE|SO|SHP|INV|PAY|DSP|EVT)-2026-\d{6}$")


PRIMARY_KEYS = {
    "accounts": "account_id",
    "quotes": "quote_id",
    "sales_orders": "sales_order_id",
    "shipments": "shipment_id",
    "invoices": "invoice_id",
    "payments": "payment_id",
    "disputes": "dispute_id",
    "status_events": "event_id",
}


FOREIGN_KEYS = (
    ("quotes", "account_id", "accounts", "account_id"),
    ("quote_lines", "quote_id", "quotes", "quote_id"),

    ("sales_orders", "quote_id", "quotes", "quote_id"),
    ("sales_orders", "account_id", "accounts", "account_id"),
    ("order_lines", "sales_order_id", "sales_orders", "sales_order_id"),
    ("order_lines", "quote_line_id", "quote_lines", "quote_line_id"),

    ("shipments", "sales_order_id", "sales_orders", "sales_order_id"),

    ("invoices", "sales_order_id", "sales_orders", "sales_order_id"),
    ("invoices", "shipment_id", "shipments", "shipment_id"),
    ("invoices", "account_id", "accounts", "account_id"),
    ("invoice_lines", "invoice_id", "invoices", "invoice_id"),
    ("invoice_lines", "sales_order_id", "sales_orders", "sales_order_id"),
    ("invoice_lines", "order_line_id", "order_lines", "order_line_id"),
    ("invoice_lines", "shipment_id", "shipments", "shipment_id"),

    ("payments", "account_id", "accounts", "account_id"),
    ("payment_allocations", "payment_id", "payments", "payment_id"),
    ("payment_allocations", "invoice_id", "invoices", "invoice_id"),

    ("status_events", "entity_id", None, None),
)


TIME_PAIRS = (
    ("quotes", "issued_at", "decided_at"),
    ("sales_orders", "booked_at", "closed_at"),
    ("shipments", "packed_at", "shipped_at"),
    ("shipments", "shipped_at", "delivered_at"),
    ("invoices", "issued_at", "due_at"),
    ("payments", "posted_at", "posted_at"),
    ("disputes", "opened_at", "opened_at"),
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class VerificationReport:
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(CheckResult(name, passed, detail))

    @property
    def ok(self) -> bool:
        return all(item.passed for item in self.checks)

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame([{"check": c.name, "passed": "Y" if c.passed else "N", "detail": c.detail} for c in self.checks])


class LedgerAuditor:
    def __init__(self, tables: dict[str, pd.DataFrame], expected_volumes: dict[str, int]) -> None:
        self.tables = tables
        self.expected_volumes = expected_volumes

    def run(self) -> VerificationReport:
        report = VerificationReport()
        self._check_volumes(report)
        self._check_primary_keys(report)
        self._check_id_shapes(report)
        self._check_foreign_keys(report)
        self._check_chronology(report)
        self._check_balances(report)
        self._check_required_anomalies(report)
        self._check_ground_truth_isolation(report)
        return report

    def _check_volumes(self, report: VerificationReport) -> None:
        for table, expected in self.expected_volumes.items():
            actual = len(self.tables[table])
            report.add(
                f"volume:{table}",
                actual == expected,
                f"expected={expected} actual={actual}",
            )

    def _check_primary_keys(self, report: VerificationReport) -> None:
        for table, column in PRIMARY_KEYS.items():
            series = self.tables[table][column]
            unique = series.nunique(dropna=False) == len(series) and series.ne("").all()
            report.add(f"pk:{table}.{column}", bool(unique), f"rows={len(series)} unique={series.nunique()}")

    def _check_id_shapes(self, report: VerificationReport) -> None:
        for table, column in PRIMARY_KEYS.items():
            bad = self.tables[table][column].map(lambda value: ID_PATTERN.match(str(value)) is None)
            count = int(bad.sum())
            report.add(f"id_format:{table}.{column}", count == 0, f"malformed={count}")

    
    def _check_foreign_keys(self, report: VerificationReport) -> None:
        optional_references = {
            ("invoices", "shipment_id"),
            ("invoice_lines", "shipment_id"),
            ("invoice_lines", "order_line_id"),
        }

        for child, child_col, parent, parent_col in FOREIGN_KEYS:
            if parent is None:
                continue

            parent_keys = set(self.tables[parent][parent_col].dropna().tolist())
            values = self.tables[child][child_col]

            if (child, child_col) in optional_references:
                values = values[values.notna() & values.ne("")]

            missing = [
                value for value in values.tolist()
                if value not in parent_keys
            ]

            report.add(
                f"fk:{child}.{child_col}->{parent}.{parent_col}",
                len(missing) == 0,
                f"orphans={len(missing)}",
            )

        dispute_ids = set(self.tables["disputes"]["invoice_id"].tolist())
        invoice_ids = set(self.tables["invoices"]["invoice_id"].tolist())
        stranded = dispute_ids - invoice_ids

        report.add(
            "fk:disputes.invoice_id->invoices.invoice_id",
            len(stranded) == 1,
            f"non_receivable_disputes={len(stranded)} "
            "(exactly one injected phantom expected)",
        )

    def _check_chronology(self, report: VerificationReport) -> None:
        quotes = self.tables["quotes"]
        orders = self.tables["sales_orders"]
        merged = orders.merge(quotes, on="quote_id", suffixes=("_so", "_qte"))
        ordered = (merged["booked_at"] >= merged["issued_at"]).all()
        report.add("chrono:sales_order_after_quote", bool(ordered), "booked_at >= quote.issued_at")

        ships = self.tables["shipments"].merge(orders, on="sales_order_id")
        ship_ok = (ships["packed_at"] >= ships["booked_at"]).all()
        report.add("chrono:shipment_after_order", bool(ship_ok), "packed_at >= booked_at")

        events = self.tables["status_events"].copy()
        events["occurred_at"] = pd.to_datetime(events["occurred_at"], utc=True)
        grouped = events.sort_values("occurred_at").groupby("entity_id")["occurred_at"]
        monotonic = True
        for _, series in grouped:
            if not series.is_monotonic_increasing:
                monotonic = False
                break
        report.add("chrono:events_per_entity", monotonic, "occurred_at non-decreasing within entity_id")

        for table, start, end in TIME_PAIRS:
            frame = self.tables[table]
            if start == end:
                report.add(f"chrono:{table}.{start}", True, "single timestamp column")
                continue
            left = frame[start].astype(str)
            right = frame[end].astype(str)
            comparable = right.str.len() > 0
            ok = bool((right[comparable] >= left[comparable]).all()) if comparable.any() else True
            report.add(f"chrono:{table}.{start}<={end}", ok, "timestamp order")

    def _check_balances(self, report: VerificationReport) -> None:
        invoices = self.tables["invoices"].copy()
        invoices["_total"] = invoices["total_due"].map(cents_from_text)
        invoices["_balance"] = invoices["balance_due"].map(cents_from_text)
        invoices["_net"] = invoices["invoice_amount"].map(cents_from_text) + invoices["tax_amount"].map(cents_from_text)
        formula_ok = (invoices["_total"] == invoices["_net"]).all()
        report.add("balance:invoice_total_equals_net", bool(formula_ok), "total_due = invoice_amount + tax_amount")
        # Validate invoice amounts against fulfilled amounts per order.
        shipments = self.tables["shipments"].copy()
        shipments["_fulfilled"] = shipments["fulfilled_amount"].map(cents_from_text)
        fulfilled_by_order = shipments.groupby("sales_order_id")["_fulfilled"].sum()

        invoices["_amount"] = invoices["invoice_amount"].map(cents_from_text)
        billed_by_order = invoices.groupby("sales_order_id")["_amount"].sum()
        comparable_orders = billed_by_order.index.intersection(fulfilled_by_order.index)
        billed_comparable = billed_by_order.loc[comparable_orders]
        fulfilled_comparable = fulfilled_by_order.loc[comparable_orders]
        overbilled_orders = set(
            billed_comparable.index[billed_comparable > fulfilled_comparable]
        )

        truth = self.tables["ground_truth"]
        expected_faults = truth[
            truth["anomaly_code"] == "invoice_exceeds_fulfillment"
        ]
        expected_invoice_ids = set(expected_faults["anchor_id"])
        expected_orders = set(
            invoices.loc[
                invoices["invoice_id"].isin(expected_invoice_ids),
                "sales_order_id",
            ]
        )

        report.add(
            "business:invoice_exceeds_fulfillment",
            len(expected_orders) == 1 and overbilled_orders == expected_orders,
            f"detected_orders={len(overbilled_orders)} "
            f"expected_orders={len(expected_orders)} "
            f"matches_ground_truth={overbilled_orders == expected_orders}",
        )


        alloc = self.tables["payment_allocations"].copy()
        alloc["_amt"] = alloc["allocated_amount"].map(cents_from_text)
        applied = alloc.groupby("invoice_id")["_amt"].sum()
        joined = invoices.set_index("invoice_id")
        paid = joined["_total"] - joined["_balance"]
        compared = paid.subtract(applied).fillna(paid)
        # Double allocation is an injected fault, so the auditor records drift instead of failing the suite.
        drift_rows = int((compared.abs() > 0).sum())
        report.add("anomaly:expected_invoice_allocation_drift", drift_rows == 1, f"expected=1 observed={drift_rows}")

        payments = self.tables["payments"].copy()
        payments["_amt"] = payments["payment_amount"].map(cents_from_text)
        applied_pmt = alloc.groupby("payment_id")["_amt"].sum()
        pay_join = payments.set_index("payment_id")["_amt"].subtract(applied_pmt).fillna(0)
        over_applied = int((pay_join < 0).sum())
        report.add("anomaly:expected_payment_over_allocation", over_applied == 1, f"expected=1 observed={over_applied}")

    def _check_required_anomalies(self, report: VerificationReport) -> None:
        invoices = self.tables["invoices"].copy()
        orders = self.tables["sales_orders"].copy()
        invoices["_balance_cents"] = invoices["balance_due"].map(cents_from_text)

        merged = invoices.merge(
            orders[["sales_order_id", "order_status"]],
            on="sales_order_id",
            how="inner",
        )
        closed_unpaid = merged[
            (merged["order_status"] == "closed")
            & (merged["_balance_cents"] > 0)
        ]
        closed_unpaid_orders = set(closed_unpaid["sales_order_id"])
        unpaid_order_count = len(closed_unpaid_orders)

        report.add(
            "anomaly:expected_order_closed_with_unpaid_invoice",
            unpaid_order_count >= 1,
            f"closed_orders_with_unpaid_invoices={unpaid_order_count}",
        )

        events = self.tables["status_events"]
        order_events = events[events["entity_type"] == "sales_order"]
        allowed = {
            ("none", "booked"),
            ("booked", "in_fulfillment"),
            ("in_fulfillment", "fulfilled"),
            ("fulfilled", "closed"),
        }
        invalid = order_events[
            ~order_events.apply(
                lambda row: (row["from_status"], row["to_status"]) in allowed,
                axis=1,
            )
        ]
        expected_skip = (
            (order_events["from_status"] == "booked")
            & (order_events["to_status"] == "closed")
        )
        unexpected_invalid = invalid.loc[~expected_skip.loc[invalid.index]]
        expected_skips = int(expected_skip.sum())
        unexpected_count = len(unexpected_invalid)

        report.add(
            "anomaly:expected_status_event_skips_state",
            expected_skips == 1 and unexpected_count == 0,
            f"expected_skipped_transitions=1 observed={expected_skips} "
            f"unexpected_invalid_transitions={unexpected_count}",
        )

        disputes = self.tables["disputes"]
        invoice_ids = set(invoices["invoice_id"])
        missing = disputes[~disputes["invoice_id"].isin(invoice_ids)]
        report.add(
            "business:dispute_invoice_exists",
            len(missing) == 1,
            f"missing_invoice_disputes={len(missing)}",
        )

    def _check_ground_truth_isolation(self, report: VerificationReport) -> None:
        truth = self.tables["ground_truth"]
        codes = set(truth["anomaly_code"].tolist())
        expected = {
            "invoice_exceeds_fulfillment",
            "payment_allocated_twice",
            "order_closed_with_unpaid_invoice",
            "status_event_skips_state",
            "dispute_not_in_receivables",
        }
        report.add("ground_truth:five_anomalies", codes == expected, f"codes={sorted(codes)}")

        feature_tables = [name for name in self.tables if name != "ground_truth"]
        leaked = False
        for name in feature_tables:
            blob = " ".join(self.tables[name].astype(str).fillna("").values.ravel().tolist())
            if "anomaly_code" in self.tables[name].columns or "GT-0001" in blob:
                leaked = True
                break
        report.add("ground_truth:isolated_from_features", not leaked, "label columns absent from operational tables")
