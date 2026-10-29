from dataclasses import dataclass, field
import re

import pandas as pd

from o2c_sim.money import cents_from_text


ID_PATTERNS = {
    "accounts": ("account_id", re.compile(r"^ACC-\d{4}-\d{6}$")),
    "quotes": ("quote_id", re.compile(r"^QTE-\d{4}-\d{6}$")),
    "quote_lines": ("quote_line_id", re.compile(r"^QTL-\d{4}-\d{6}$")),
    "sales_orders": ("sales_order_id", re.compile(r"^SO-\d{4}-\d{6}$")),
    "order_lines": ("order_line_id", re.compile(r"^OTL-\d{4}-\d{6}$")),
    "shipments": ("shipment_id", re.compile(r"^SHP-\d{4}-\d{6}$")),
    "invoices": ("invoice_id", re.compile(r"^INV-\d{4}-\d{6}$")),
    "invoice_lines": ("invoice_line_id", re.compile(r"^ITL-\d{4}-\d{6}$")),
    "payments": ("payment_id", re.compile(r"^PAY-\d{4}-\d{6}$")),
    "disputes": ("dispute_id", re.compile(r"^DSP-\d{4}-\d{6}$")),
    "status_events": ("event_id", re.compile(r"^EVT-\d{4}-\d{6}$")),
    "ground_truth": ("truth_id", re.compile(r"^GT-\d{4}$")),
}

PRIMARY_KEYS = {
    **{table: (column,) for table, (column, _) in ID_PATTERNS.items()},
    "payment_allocations": ("payment_id", "invoice_id"),
}

FOREIGN_KEYS = (
    ("quotes", "account_id", "accounts", "account_id"),
    ("quote_lines", "quote_id", "quotes", "quote_id"),
    ("sales_orders", "quote_id", "quotes", "quote_id"),
    ("sales_orders", "account_id", "accounts", "account_id"),
    ("order_lines", "sales_order_id", "sales_orders", "sales_order_id"),
    ("order_lines", "quote_line_id", "quote_lines", "quote_line_id"),
    ("shipments", "sales_order_id", "sales_orders", "sales_order_id"),
    ("shipments", "account_id", "accounts", "account_id"),
    ("invoices", "sales_order_id", "sales_orders", "sales_order_id"),
    ("invoices", "account_id", "accounts", "account_id"),
    ("invoices", "shipment_id", "shipments", "shipment_id"),
    ("invoice_lines", "invoice_id", "invoices", "invoice_id"),
    ("invoice_lines", "sales_order_id", "sales_orders", "sales_order_id"),
    ("invoice_lines", "order_line_id", "order_lines", "order_line_id"),
    ("invoice_lines", "shipment_id", "shipments", "shipment_id"),
    ("payments", "account_id", "accounts", "account_id"),
    ("payment_allocations", "payment_id", "payments", "payment_id"),
    ("payment_allocations", "invoice_id", "invoices", "invoice_id"),
)

OPTIONAL_REFERENCES = {
    ("invoices", "shipment_id"),
    ("invoice_lines", "shipment_id"),
    ("invoice_lines", "order_line_id"),
}

EVENT_ENTITY_KEYS = {
    "account": ("accounts", "account_id"),
    "quote": ("quotes", "quote_id"),
    "sales_order": ("sales_orders", "sales_order_id"),
    "shipment": ("shipments", "shipment_id"),
    "invoice": ("invoices", "invoice_id"),
    "payment": ("payments", "payment_id"),
    "dispute": ("disputes", "dispute_id"),
}

ALLOWED_STATES = {
    ("accounts", "account_status"): {"active", "on_hold"},
    ("quotes", "quote_status"): {"accepted", "expired", "rejected"},
    ("sales_orders", "order_status"): {
        "booked",
        "in_fulfillment",
        "fulfilled",
        "closed",
    },
    ("shipments", "shipment_status"): {"delivered"},
    ("invoices", "invoice_status"): {"open", "partial", "paid", "disputed"},
    ("payments", "payment_status"): {"allocated"},
    ("disputes", "dispute_status"): {"under_review"},
}

ALLOWED_TRANSITIONS = {
    "account": {("prospect", "active")},
    "quote": {
        ("draft", "sent"),
        ("sent", "accepted"),
        ("sent", "expired"),
        ("sent", "rejected"),
    },
    "sales_order": {
        ("none", "booked"),
        ("booked", "in_fulfillment"),
        ("in_fulfillment", "fulfilled"),
        ("fulfilled", "closed"),
    },
    "shipment": {("shipped", "delivered")},
    "invoice": {
        ("draft", "open"),
        ("draft", "partial"),
        ("draft", "paid"),
        ("draft", "disputed"),
    },
    "payment": {("received", "allocated")},
    "dispute": {("none", "under_review")},
}

ANOMALY_CODES = {
    "invoice_exceeds_fulfillment",
    "payment_allocated_twice",
    "order_closed_with_unpaid_invoice",
    "status_event_skips_state",
    "dispute_not_in_receivables",
}

MONEY_COLUMNS = {
    "accounts": ("credit_limit",),
    "quotes": ("quoted_amount",),
    "quote_lines": ("unit_price", "line_amount"),
    "sales_orders": ("order_amount",),
    "order_lines": ("unit_price", "line_amount"),
    "shipments": ("fulfilled_amount",),
    "invoices": ("invoice_amount", "tax_amount", "total_due", "balance_due"),
    "invoice_lines": ("line_amount",),
    "payments": ("payment_amount", "unapplied_amount"),
    "payment_allocations": ("allocated_amount",),
    "disputes": ("dispute_amount",),
}

MONEY_PATTERN = re.compile(r"^-?\d+\.\d{2}$")


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class VerificationReport:
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(CheckResult(name, bool(passed), detail))

    @property
    def ok(self) -> bool:
        return all(item.passed for item in self.checks)

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"check": check.name, "passed": "Y" if check.passed else "N", "detail": check.detail}
                for check in self.checks
            ]
        )


class LedgerAuditor:
    def __init__(
        self,
        tables: dict[str, pd.DataFrame],
        expected_volumes: dict[str, int],
    ) -> None:
        self.tables = tables
        self.expected_volumes = expected_volumes

    def run(self) -> VerificationReport:
        report = VerificationReport()
        self._check_volumes(report)
        self._check_primary_keys(report)
        self._check_id_formats(report)
        self._check_money_formats(report)
        self._check_foreign_keys(report)
        self._check_relationship_consistency(report)
        self._check_lifecycle_states(report)
        self._check_chronology(report)
        detections = self._detect_anomalies()
        self._check_lifecycle_transitions(report, detections)
        self._check_financials(report, detections)
        self._report_anomalies(report, detections)
        self._check_ground_truth_isolation(report)
        return report

    def _expected_count(self, table: str) -> int | None:
        if table in self.expected_volumes:
            return self.expected_volumes[table]
        parent_counts = {
            "quote_lines": "quotes",
            "order_lines": "sales_orders",
            "invoice_lines": "invoices",
        }
        if table in parent_counts:
            return len(self.tables[parent_counts[table]])
        if table == "payment_allocations":
            return len(self.tables["payments"]) + 1
        return None

    def _check_volumes(self, report: VerificationReport) -> None:
        for table, frame in self.tables.items():
            expected = self._expected_count(table)
            actual = len(frame)
            passed = actual == expected if expected is not None else actual > 0
            report.add(
                f"volume:{table}",
                passed,
                f"expected={expected if expected is not None else 'non-empty'} actual={actual}",
            )

    def _check_primary_keys(self, report: VerificationReport) -> None:
        for table, columns in PRIMARY_KEYS.items():
            frame = self.tables[table]
            values = frame.loc[:, list(columns)].astype("string")
            nonempty = values.notna().all(axis=1) & values.apply(
                lambda column: column.str.strip().ne("")
            ).all(axis=1)
            unique = not values.duplicated(keep=False).any()
            invalid_count = int((~nonempty).sum())
            duplicate_count = int(values.duplicated(keep=False).sum())
            report.add(
                f"pk:{table}.{','.join(columns)}",
                bool(nonempty.all() and unique),
                f"rows={len(frame)} duplicate_rows={duplicate_count} empty_key_rows={invalid_count}",
            )

    def _check_id_formats(self, report: VerificationReport) -> None:
        for table, (column, pattern) in ID_PATTERNS.items():
            values = self.tables[table][column].astype("string")
            malformed = ~values.str.fullmatch(pattern, na=False)
            bad_values = values[malformed].head(5).tolist()
            report.add(
                f"id_format:{table}.{column}",
                not bool(malformed.any()),
                f"malformed={int(malformed.sum())} examples={bad_values}",
            )

    def _check_money_formats(self, report: VerificationReport) -> None:
        for table, columns in MONEY_COLUMNS.items():
            for column in columns:
                values = self.tables[table][column].astype("string")
                malformed = ~values.str.fullmatch(MONEY_PATTERN, na=False)
                report.add(
                    f"money_format:{table}.{column}",
                    not bool(malformed.any()),
                    f"malformed={int(malformed.sum())} "
                    f"examples={values[malformed].head(5).tolist()}",
                )

    def _cents(self, table: str, column: str) -> pd.Series:
        values = self.tables[table][column].astype("string")
        valid = values.str.fullmatch(MONEY_PATTERN, na=False)
        return values.where(valid, "0.00").map(cents_from_text).astype("int64")

    def _check_foreign_keys(self, report: VerificationReport) -> None:
        for child, child_column, parent, parent_column in FOREIGN_KEYS:
            values = self.tables[child][child_column]
            if (child, child_column) in OPTIONAL_REFERENCES:
                values = values[values.notna() & values.astype("string").str.strip().ne("")]
            parents = set(self.tables[parent][parent_column].dropna().tolist())
            missing = [value for value in values.tolist() if value not in parents]
            report.add(
                f"fk:{child}.{child_column}->{parent}.{parent_column}",
                not missing,
                f"checked={len(values)} orphan_count={len(missing)} examples={missing[:5]}",
            )

        valid_event_types = set(EVENT_ENTITY_KEYS)
        events = self.tables["status_events"]
        invalid_types = events.loc[
            ~events["entity_type"].isin(valid_event_types), "entity_type"
        ].tolist()
        unresolved = []
        entity_ids = {
            entity_type: set(self.tables[table][column])
            for entity_type, (table, column) in EVENT_ENTITY_KEYS.items()
        }
        for row in events.itertuples(index=False):
            if row.entity_type in entity_ids and row.entity_id not in entity_ids[row.entity_type]:
                unresolved.append((row.entity_type, row.entity_id))
        report.add(
            "fk:status_events.entity_type_entity_id",
            not invalid_types and not unresolved,
            f"invalid_types={invalid_types[:5]} orphan_count={len(unresolved)} "
            f"examples={unresolved[:5]}",
        )

    def _check_relationship_consistency(self, report: VerificationReport) -> None:
        quotes = self.tables["quotes"][["quote_id", "account_id"]]
        orders = self.tables["sales_orders"][["sales_order_id", "quote_id", "account_id"]]
        shipments = self.tables["shipments"][["shipment_id", "sales_order_id", "account_id"]]
        invoices = self.tables["invoices"][["invoice_id", "sales_order_id", "account_id"]]

        order_quote = orders.merge(quotes, on="quote_id", suffixes=("_order", "_quote"))
        shipment_order = self.tables["shipments"].merge(
            orders[["sales_order_id", "account_id"]],
            on="sales_order_id",
            suffixes=("_shipment", "_order"),
        )
        invoice_order = invoices.merge(
            orders[["sales_order_id", "account_id"]],
            on="sales_order_id",
            suffixes=("_invoice", "_order"),
        )
        line_invoice = self.tables["invoice_lines"].merge(
            invoices[["invoice_id", "sales_order_id"]],
            on="invoice_id",
            suffixes=("_line", "_invoice"),
        )
        line_shipments = self.tables["invoice_lines"].loc[
            self.tables["invoice_lines"]["shipment_id"].notna()
            & self.tables["invoice_lines"]["shipment_id"].ne("")
        ].merge(
            shipments[["shipment_id", "sales_order_id"]],
            left_on="shipment_id",
            right_on="shipment_id",
            suffixes=("_line", "_shipment"),
        )
        order_line_quotes = (
            self.tables["order_lines"][["sales_order_id", "quote_line_id"]]
            .merge(orders[["sales_order_id", "quote_id"]], on="sales_order_id")
            .merge(
                self.tables["quote_lines"][["quote_line_id", "quote_id"]],
                on="quote_line_id",
                suffixes=("_order", "_line"),
            )
        )
        allocations = (
            self.tables["payment_allocations"]
            .merge(
                self.tables["payments"][["payment_id", "account_id"]],
                on="payment_id",
                suffixes=("_allocation", "_payment"),
            )
            .merge(
                invoices[["invoice_id", "account_id"]],
                on="invoice_id",
                suffixes=("_payment", "_invoice"),
            )
        )
        dispute_matches = self.tables["disputes"].merge(
            invoices[["invoice_id", "account_id"]],
            on="invoice_id",
            suffixes=("_dispute", "_invoice"),
        )

        mismatch_counts = {
            "sales_order_quote_account": int(
                order_quote["account_id_order"].ne(order_quote["account_id_quote"]).sum()
            ),
            "shipment_order_account": int(
                shipment_order["account_id_shipment"].ne(shipment_order["account_id_order"]).sum()
            ),
            "invoice_order_account": int(
                invoice_order["account_id_invoice"].ne(invoice_order["account_id_order"]).sum()
            ),
            "invoice_line_order": int(
                line_invoice["sales_order_id_line"].ne(line_invoice["sales_order_id_invoice"]).sum()
            ),
            "invoice_line_shipment": int(
                line_shipments["sales_order_id_line"].ne(line_shipments["sales_order_id_shipment"]).sum()
            ),
            "order_line_source_quote": int(
                order_line_quotes["quote_id_order"].ne(order_line_quotes["quote_id_line"]).sum()
            ),
            "allocation_account": int(
                allocations["account_id_payment"].ne(allocations["account_id_invoice"]).sum()
            ),
            "dispute_account": int(
                dispute_matches["account_id_dispute"].ne(dispute_matches["account_id_invoice"]).sum()
            ),
        }

        for name, count in mismatch_counts.items():
            report.add(
                f"relationship:{name}",
                count == 0,
                f"mismatch_count={count}",
            )

    def _check_lifecycle_states(self, report: VerificationReport) -> None:
        for (table, column), allowed in ALLOWED_STATES.items():
            values = self.tables[table][column]
            invalid = sorted(set(values.dropna()) - allowed)
            report.add(
                f"lifecycle:states:{table}.{column}",
                not invalid,
                f"allowed={sorted(allowed)} invalid_values={invalid}",
            )

    @staticmethod
    def _timestamps(frame: pd.DataFrame, column: str) -> pd.Series:
        return pd.to_datetime(frame[column], errors="coerce", utc=True)

    def _check_time_order(
        self,
        report: VerificationReport,
        table: str,
        first: str,
        second: str,
        optional_second: bool = False,
    ) -> None:
        frame = self.tables[table]
        left = self._timestamps(frame, first)
        right = self._timestamps(frame, second)
        present = frame[second].notna() & frame[second].astype("string").str.strip().ne("")
        required_valid = left.notna() & (right.notna() | (~present if optional_second else False))
        comparable = present if optional_second else pd.Series(True, index=frame.index)
        bad = (~required_valid) | (comparable & (right < left))
        report.add(
            f"chrono:{table}.{first}<={second}",
            not bool(bad.any()),
            f"violations={int(bad.sum())} "
            f"examples={frame.loc[bad, list(dict.fromkeys((first, second)))].head(3).to_dict('records')}",
        )

    def _check_chronology(self, report: VerificationReport) -> None:
        self._check_time_order(report, "quotes", "issued_at", "expires_at")
        self._check_time_order(report, "quotes", "issued_at", "decided_at")
        self._check_time_order(report, "sales_orders", "booked_at", "closed_at", True)
        self._check_time_order(report, "shipments", "packed_at", "shipped_at")
        self._check_time_order(report, "shipments", "shipped_at", "delivered_at")
        self._check_time_order(report, "invoices", "issued_at", "due_at")
        self._check_time_order(report, "payments", "posted_at", "posted_at")
        self._check_time_order(report, "disputes", "opened_at", "opened_at")

        events = self.tables["status_events"].copy()
        events["_parsed_at"] = self._timestamps(events, "occurred_at")
        invalid_timestamps = int(events["_parsed_at"].isna().sum())
        prior_times = events.groupby("entity_id", sort=False)["_parsed_at"].shift()
        out_of_order = events["_parsed_at"] < prior_times
        monotonic = invalid_timestamps == 0 and not bool(out_of_order.any())
        report.add(
            "chrono:events_per_entity",
            monotonic,
            f"stored_order_non_decreasing={monotonic} invalid_timestamps={invalid_timestamps}",
        )

        orders = self.tables["sales_orders"].set_index("sales_order_id")
        quotes = self.tables["quotes"].set_index("quote_id")
        bad_order_ids = []
        for row in self.tables["sales_orders"].itertuples(index=False):
            if row.quote_id in quotes.index:
                booked = pd.to_datetime(row.booked_at, errors="coerce", utc=True)
                issued = pd.to_datetime(quotes.at[row.quote_id, "issued_at"], errors="coerce", utc=True)
                if pd.isna(booked) or pd.isna(issued) or booked < issued:
                    bad_order_ids.append(row.sales_order_id)
        report.add(
            "chrono:sales_order_after_quote",
            not bad_order_ids,
            f"violations={len(bad_order_ids)} examples={bad_order_ids[:5]}",
        )

        quote_account_dates = self.tables["quotes"].merge(
            self.tables["accounts"][["account_id", "opened_at"]],
            on="account_id",
        )
        quote_issued = self._timestamps(quote_account_dates, "issued_at")
        account_opened = self._timestamps(quote_account_dates, "opened_at")
        bad_quote_dates = quote_issued.isna() | account_opened.isna() | (
            quote_issued < account_opened
        )
        report.add(
            "chrono:quote_after_account_open",
            not bool(bad_quote_dates.any()),
            f"violations={int(bad_quote_dates.sum())} "
            f"quote_ids={quote_account_dates.loc[bad_quote_dates, 'quote_id'].head(5).tolist()}",
        )

        bad_shipments = []
        for row in self.tables["shipments"].itertuples(index=False):
            if row.sales_order_id in orders.index:
                packed = pd.to_datetime(row.packed_at, errors="coerce", utc=True)
                booked = pd.to_datetime(orders.at[row.sales_order_id, "booked_at"], errors="coerce", utc=True)
                if pd.isna(packed) or pd.isna(booked) or packed < booked:
                    bad_shipments.append(row.shipment_id)
        report.add(
            "chrono:shipment_after_order",
            not bad_shipments,
            f"violations={len(bad_shipments)} examples={bad_shipments[:5]}",
        )

        invoice_shipments = self.tables["invoices"].loc[
            self.tables["invoices"]["shipment_id"].notna()
            & self.tables["invoices"]["shipment_id"].ne("")
        ].merge(
            self.tables["shipments"][["shipment_id", "delivered_at"]],
            on="shipment_id",
        )
        invoice_issued = self._timestamps(invoice_shipments, "issued_at")
        shipment_delivered = self._timestamps(invoice_shipments, "delivered_at")
        bad_invoice_dates = (
            invoice_issued.isna()
            | shipment_delivered.isna()
            | (invoice_issued < shipment_delivered)
        )
        report.add(
            "chrono:invoice_after_shipment",
            not bool(bad_invoice_dates.any()),
            f"violations={int(bad_invoice_dates.sum())} "
            f"invoice_ids={invoice_shipments.loc[bad_invoice_dates, 'invoice_id'].head(5).tolist()}",
        )

        allocation_dates = (
            self.tables["payment_allocations"]
            .merge(
                self.tables["invoices"][["invoice_id", "issued_at"]],
                on="invoice_id",
            )
            .merge(
                self.tables["payments"][["payment_id", "posted_at"]],
                on="payment_id",
            )
        )
        invoice_dates = self._timestamps(allocation_dates, "issued_at")
        posted_dates = self._timestamps(allocation_dates, "posted_at")
        allocated_dates = self._timestamps(allocation_dates, "allocated_at")
        bad_payments = (
            invoice_dates.isna()
            | posted_dates.isna()
            | allocated_dates.isna()
            | (posted_dates < invoice_dates)
            | (allocated_dates < posted_dates)
        )
        report.add(
            "chrono:payment_allocation_after_invoice",
            not bool(bad_payments.any()),
            f"violations={int(bad_payments.sum())} "
            f"examples={allocation_dates.loc[bad_payments, ['payment_id', 'invoice_id']].head(5).to_dict('records')}",
        )

        dispute_dates = self.tables["disputes"].merge(
            self.tables["invoices"][["invoice_id", "issued_at"]],
            on="invoice_id",
        )
        opened_dates = self._timestamps(dispute_dates, "opened_at")
        issued_dates = self._timestamps(dispute_dates, "issued_at")
        bad_disputes = (
            opened_dates.isna()
            | issued_dates.isna()
            | (opened_dates < issued_dates)
        )
        report.add(
            "chrono:dispute_after_invoice",
            not bool(bad_disputes.any()),
            f"violations={int(bad_disputes.sum())} "
            f"examples={dispute_dates.loc[bad_disputes, ['dispute_id']].head(5).to_dict('records')}",
        )

    def _detect_anomalies(self) -> dict[str, set[str]]:
        detections = {code: set() for code in ANOMALY_CODES}

        shipments = self.tables["shipments"].copy()
        shipments["_fulfilled_cents"] = self._cents("shipments", "fulfilled_amount")
        fulfilled = shipments.groupby("sales_order_id")["_fulfilled_cents"].sum().to_dict()
        invoices = self.tables["invoices"].copy()
        invoices["_amount_cents"] = self._cents("invoices", "invoice_amount")
        billed_by_order: dict[str, int] = {}
        crossed_limit: set[str] = set()
        for index, row in invoices.iterrows():
            order_id = row.sales_order_id
            amount = int(invoices.at[index, "_amount_cents"])
            billed_by_order[order_id] = billed_by_order.get(order_id, 0) + amount
            if (
                order_id not in crossed_limit
                and billed_by_order[order_id] > fulfilled.get(order_id, 0)
            ):
                detections["invoice_exceeds_fulfillment"].add(row["invoice_id"])
                crossed_limit.add(order_id)

        allocations = self.tables["payment_allocations"].copy()
        allocations["_allocated_cents"] = self._cents(
            "payment_allocations", "allocated_amount"
        )
        payments = self.tables["payments"].copy()
        payments["_payment_cents"] = self._cents("payments", "payment_amount")
        payments["_unapplied_cents"] = self._cents("payments", "unapplied_amount")
        allocated_by_payment = allocations.groupby("payment_id")["_allocated_cents"].sum()
        payment_by_id = payments.set_index("payment_id")
        for payment_id, allocated_cents in allocated_by_payment.items():
            if payment_id not in payment_by_id.index:
                continue
            available = (
                payment_by_id.at[payment_id, "_payment_cents"]
                - payment_by_id.at[payment_id, "_unapplied_cents"]
            )
            if allocated_cents > available:
                detections["payment_allocated_twice"].add(payment_id)

        order_by_id = self.tables["sales_orders"].set_index("sales_order_id")
        invoice_balances = self._cents("invoices", "balance_due")
        invoice_status = self.tables["invoices"].copy()
        invoice_status["_balance_cents"] = invoice_balances
        for _, row in invoice_status.iterrows():
            balance = int(row["_balance_cents"])
            if (
                row["sales_order_id"] in order_by_id.index
                and order_by_id.at[row["sales_order_id"], "order_status"] == "closed"
                and balance > 0
            ):
                detections["order_closed_with_unpaid_invoice"].add(row["sales_order_id"])

        events = self.tables["status_events"]
        for row in events.itertuples(index=False):
            legal = ALLOWED_TRANSITIONS.get(row.entity_type, set())
            if row.entity_type == "sales_order" and (
                row.from_status,
                row.to_status,
            ) not in legal:
                detections["status_event_skips_state"].add(row.event_id)

        invoice_ids = set(self.tables["invoices"]["invoice_id"])
        for row in self.tables["disputes"].itertuples(index=False):
            if row.invoice_id not in invoice_ids:
                detections["dispute_not_in_receivables"].add(row.dispute_id)
        return detections

    def _check_lifecycle_transitions(
        self,
        report: VerificationReport,
        detections: dict[str, set[str]],
    ) -> None:
        invalid = set()
        for row in self.tables["status_events"].itertuples(index=False):
            if (row.from_status, row.to_status) not in ALLOWED_TRANSITIONS.get(
                row.entity_type, set()
            ):
                invalid.add(row.event_id)
        expected_scenario = detections["status_event_skips_state"]
        unexpected = invalid - expected_scenario
        report.add(
            "lifecycle:status_event_transitions",
            not unexpected,
            f"observed_invalid_count={len(invalid)} "
            f"known_scenario_event_ids={sorted(expected_scenario)} "
            f"unexpected_invalid_event_ids={sorted(unexpected)}",
        )

    def _check_financials(
        self,
        report: VerificationReport,
        detections: dict[str, set[str]],
    ) -> None:
        for table, column in (
            ("accounts", "credit_limit"),
            ("quotes", "quoted_amount"),
            ("quote_lines", "unit_price"),
            ("quote_lines", "line_amount"),
            ("sales_orders", "order_amount"),
            ("order_lines", "unit_price"),
            ("order_lines", "line_amount"),
            ("shipments", "fulfilled_amount"),
            ("invoices", "invoice_amount"),
            ("invoices", "total_due"),
            ("invoice_lines", "line_amount"),
            ("payments", "payment_amount"),
            ("payment_allocations", "allocated_amount"),
            ("disputes", "dispute_amount"),
        ):
            cents = self._cents(table, column)
            nonpositive = int((cents <= 0).sum())
            report.add(
                f"financial:positive:{table}.{column}",
                nonpositive == 0,
                f"nonpositive_count={nonpositive}",
            )

        invoices = self.tables["invoices"]
        invoice_amount = self._cents("invoices", "invoice_amount")
        tax_amount = self._cents("invoices", "tax_amount")
        total_due = self._cents("invoices", "total_due")
        balance_due = self._cents("invoices", "balance_due")
        total_mismatch = total_due != invoice_amount + tax_amount
        report.add(
            "financial:invoice_total_equals_net_plus_tax",
            not bool(total_mismatch.any()),
            f"expected=invoice_amount+tax_amount observed=total_due "
            f"mismatches={int(total_mismatch.sum())} "
            f"invoice_ids={invoices.loc[total_mismatch, 'invoice_id'].head(5).tolist()}",
        )

        accounts = self.tables["accounts"].set_index("account_id")
        expected_tax = []
        for row, amount in zip(invoices.itertuples(index=False), invoice_amount.tolist()):
            region = accounts.at[row.account_id, "region"] if row.account_id in accounts.index else ""
            expected_tax.append(0 if region.startswith("NA") else int(round(amount * 0.08)))
        tax_mismatch = tax_amount != pd.Series(expected_tax, index=invoices.index)
        report.add(
            "financial:invoice_tax_rate",
            not bool(tax_mismatch.any()),
            f"expected=0% for NA, 8% otherwise mismatches={int(tax_mismatch.sum())} "
            f"invoice_ids={invoices.loc[tax_mismatch, 'invoice_id'].head(5).tolist()}",
        )

        invalid_balance = (balance_due < 0) | (balance_due > total_due)
        report.add(
            "financial:invoice_balance_bounds",
            not bool(invalid_balance.any()),
            f"expected=0<=balance_due<=total_due violations={int(invalid_balance.sum())} "
            f"invoice_ids={invoices.loc[invalid_balance, 'invoice_id'].head(5).tolist()}",
        )

        invoice_lines = self.tables["invoice_lines"].copy()
        invoice_lines["_line_cents"] = self._cents("invoice_lines", "line_amount")
        line_totals = invoice_lines.groupby("invoice_id")["_line_cents"].sum()
        invoice_amounts = pd.Series(
            invoice_amount.to_numpy(), index=invoices["invoice_id"]
        )
        missing_invoice_lines = set(invoices["invoice_id"]) - set(line_totals.index)
        line_mismatches = {
            invoice_id
            for invoice_id, amount in invoice_amounts.items()
            if line_totals.get(invoice_id, 0) != amount
        }
        report.add(
            "financial:invoice_lines_equal_invoice_amount",
            not line_mismatches,
            f"mismatches={len(line_mismatches)} missing_lines={len(missing_invoice_lines)} "
            f"invoice_ids={sorted(line_mismatches)[:5]}",
        )

        for table, parent_key, child_key, amount_column in (
            ("quote_lines", "quote_id", "quote_id", "quoted_amount"),
            ("order_lines", "sales_order_id", "sales_order_id", "order_amount"),
        ):
            lines = self.tables[table].copy()
            lines["_line_cents"] = self._cents(table, "line_amount")
            headers = self.tables["quotes" if table == "quote_lines" else "sales_orders"]
            header_amount = self._cents(
                "quotes" if table == "quote_lines" else "sales_orders",
                amount_column,
            )
            header_totals = pd.Series(
                header_amount.to_numpy(), index=headers[parent_key]
            )
            sums = lines.groupby(child_key)["_line_cents"].sum()
            mismatch_ids = [
                identifier
                for identifier, amount in header_totals.items()
                if sums.get(identifier, 0) != amount
            ]
            report.add(
                f"financial:{table}_equal_header_amount",
                not mismatch_ids,
                f"mismatches={len(mismatch_ids)} examples={mismatch_ids[:5]}",
            )

        for table, amount_column, line_amount_column in (
            ("quote_lines", "unit_price", "line_amount"),
            ("order_lines", "unit_price", "line_amount"),
        ):
            frame = self.tables[table]
            unit = self._cents(table, amount_column)
            line = self._cents(table, line_amount_column)
            quantity = pd.to_numeric(frame["quantity"], errors="coerce")
            mismatch = quantity.isna() | (line != unit * quantity.fillna(0))
            report.add(
                f"financial:{table}_quantity_times_unit_price",
                not bool(mismatch.any()),
                f"mismatches={int(mismatch.sum())} "
                f"row_indexes={frame.index[mismatch].tolist()[:5]}",
            )

        allocations = self.tables["payment_allocations"].copy()
        allocations["_allocated_cents"] = self._cents(
            "payment_allocations", "allocated_amount"
        )
        payment_fault = self.tables["ground_truth"].loc[
            self.tables["ground_truth"]["anomaly_code"]
            == "payment_allocated_twice"
        ]
        expected_invoice_drift: dict[str, int] = {}
        expected_payment_drift: dict[str, int] = {}
        if len(payment_fault) == 1:
            fault = payment_fault.iloc[0]
            related_ids = str(fault["related_ids"]).split("|")
            if len(related_ids) >= 2:
                payment_id = str(fault["anchor_id"])
                target_invoice_id = related_ids[1]
                duplicate_amount = int(
                    allocations.loc[
                        (allocations["payment_id"] == payment_id)
                        & (allocations["invoice_id"] == target_invoice_id),
                        "_allocated_cents",
                    ].sum()
                )
                if duplicate_amount > 0:
                    expected_invoice_drift[target_invoice_id] = -duplicate_amount
                    expected_payment_drift[payment_id] = -duplicate_amount

        allocated_by_invoice = allocations.groupby("invoice_id")["_allocated_cents"].sum()
        paid_from_balance = pd.Series(
            total_due.to_numpy() - balance_due.to_numpy(),
            index=invoices["invoice_id"],
        )
        invoice_drift = paid_from_balance.subtract(allocated_by_invoice).fillna(
            paid_from_balance
        )
        observed_invoice_drift = invoice_drift[invoice_drift.ne(0)].to_dict()
        invoice_mismatch_ids = set(observed_invoice_drift)
        expected_affected_invoices = set(expected_invoice_drift)
        unexpected_invoice_mismatches = invoice_mismatch_ids - expected_affected_invoices
        report.add(
            "financial:invoice_balance_reconciles_to_allocations",
            observed_invoice_drift == expected_invoice_drift,
            f"observed_mismatch_count={len(invoice_mismatch_ids)} "
            f"expected_deltas={expected_invoice_drift} "
            f"observed_deltas={observed_invoice_drift} "
            f"unexpected_mismatch_invoice_ids={sorted(unexpected_invoice_mismatches)[:10]}",
        )

        payment_amount = self._cents("payments", "payment_amount")
        unapplied_amount = self._cents("payments", "unapplied_amount")
        payment_frame = self.tables["payments"]
        allocated_by_payment = allocations.groupby("payment_id")["_allocated_cents"].sum()
        payment_total = pd.Series(payment_amount.to_numpy(), index=payment_frame["payment_id"])
        unapplied = pd.Series(
            unapplied_amount.to_numpy(), index=payment_frame["payment_id"]
        )
        applied_by_payment = allocated_by_payment.reindex(payment_total.index).fillna(0)
        payment_drift = payment_total - applied_by_payment - unapplied
        observed_payment_drift = payment_drift[payment_drift.ne(0)].to_dict()
        payment_mismatch_ids = set(observed_payment_drift)
        unexpected_payment_mismatches = (
            payment_mismatch_ids - set(expected_payment_drift)
        )
        report.add(
            "financial:payment_amount_reconciles_to_allocations",
            observed_payment_drift == expected_payment_drift,
            f"observed_mismatch_count={len(payment_mismatch_ids)} "
            f"expected_deltas={expected_payment_drift} "
            f"observed_deltas={observed_payment_drift} "
            f"unexpected_mismatch_payment_ids={sorted(unexpected_payment_mismatches)[:10]}",
        )

        duplicate_allocations = allocations.duplicated(
            ["payment_id", "invoice_id"], keep=False
        )
        report.add(
            "financial:allocation_pair_unique",
            not bool(duplicate_allocations.any()),
            f"duplicate_rows={int(duplicate_allocations.sum())}",
        )

        over_invoice_total = set(
            allocated_by_invoice.index[
                allocated_by_invoice
                > pd.Series(total_due.to_numpy(), index=invoices["invoice_id"]).reindex(
                    allocated_by_invoice.index
                )
            ]
        )
        known_allocation_targets = expected_affected_invoices
        unexpected_over_invoice_total = over_invoice_total - known_allocation_targets
        report.add(
            "financial:invoice_allocations_within_total_due",
            not unexpected_over_invoice_total,
            f"observed_overallocated_invoice_ids={sorted(over_invoice_total)} "
            f"known_fault_targets={sorted(known_allocation_targets)} "
            f"unexpected={sorted(unexpected_over_invoice_total)}",
        )

        invalid_unapplied = unapplied_amount < 0
        report.add(
            "financial:nonnegative_unapplied_amount",
            not bool(invalid_unapplied.any()),
            f"violations={int(invalid_unapplied.sum())} "
            f"payment_ids={payment_frame.loc[invalid_unapplied, 'payment_id'].head(5).tolist()}",
        )

        total_by_invoice = pd.Series(
            total_due.to_numpy(), index=invoices["invoice_id"]
        )
        short_paid = (paid_from_balance > 0) & (
            paid_from_balance < total_by_invoice
        )
        report.add(
            "financial:short_paid_invoices",
            observed_invoice_drift == expected_invoice_drift,
            f"observed_short_paid_count={int(short_paid.sum())} "
            f"invoice_ids={short_paid.index[short_paid].tolist()[:10]} "
            f"allocation_mismatches={sorted(unexpected_invoice_mismatches)[:10]}",
        )

        status_mismatches = []
        for row, total, balance in zip(
            invoices.itertuples(index=False), total_due.tolist(), balance_due.tolist()
        ):
            consistent = (
                (row.invoice_status == "paid" and balance == 0)
                or (row.invoice_status == "open" and balance == total)
                or (
                    row.invoice_status == "partial"
                    and 0 < balance < total
                )
                or (row.invoice_status == "disputed" and balance > 0)
            )
            if not consistent:
                status_mismatches.append(row.invoice_id)
        report.add(
            "financial:invoice_status_matches_balance",
            not status_mismatches,
            f"mismatches={len(status_mismatches)} examples={status_mismatches[:5]}",
        )

    def _report_anomalies(
        self,
        report: VerificationReport,
        detections: dict[str, set[str]],
    ) -> None:
        for code in sorted(ANOMALY_CODES):
            detected = detections[code]
            report.add(
                f"anomaly_detected:{code}",
                bool(detected),
                f"detected_count={len(detected)} detected_ids={sorted(detected)}",
            )

        truth = self.tables["ground_truth"]
        invalid_codes = sorted(set(truth["anomaly_code"]) - ANOMALY_CODES)
        duplicate_codes = truth["anomaly_code"].duplicated(keep=False)
        missing_codes = sorted(ANOMALY_CODES - set(truth["anomaly_code"]))
        report.add(
            "ground_truth:scenario_set",
            not invalid_codes
            and not missing_codes
            and not bool(duplicate_codes.any()),
            f"expected={sorted(ANOMALY_CODES)} observed={sorted(set(truth['anomaly_code']))} "
            f"missing={missing_codes} unexpected={invalid_codes} "
            f"duplicate_rows={int(duplicate_codes.sum())}",
        )

        for code in sorted(ANOMALY_CODES):
            expected = set(
                truth.loc[truth["anomaly_code"] == code, "anchor_id"].astype(str)
            )
            actual = detections[code]
            report.add(
                f"evaluation:{code}_matches_ground_truth",
                actual == expected,
                f"expected_ids={sorted(expected)} detected_ids={sorted(actual)} "
                f"missing={sorted(expected - actual)} unexpected={sorted(actual - expected)}",
            )

    def _check_ground_truth_isolation(self, report: VerificationReport) -> None:
        truth = self.tables["ground_truth"]
        prohibited_columns = {
            "truth_id",
            "anomaly_code",
            "severity",
            "anchor_table",
            "anchor_id",
            "related_ids",
            "notes",
            "label_only",
        }
        leaked_columns = {
            table: sorted(set(frame.columns) & prohibited_columns)
            for table, frame in self.tables.items()
            if table != "ground_truth" and set(frame.columns) & prohibited_columns
        }
        expected_columns = {
            "truth_id",
            "anomaly_code",
            "severity",
            "anchor_table",
            "anchor_id",
            "related_ids",
            "notes",
            "label_only",
        }
        observed_columns = set(truth.columns)
        report.add(
            "ground_truth:isolated_from_operational_tables",
            not leaked_columns,
            f"leaked_columns={leaked_columns}",
        )
        report.add(
            "ground_truth:schema",
            observed_columns == expected_columns,
            f"expected_columns={sorted(expected_columns)} "
            f"observed_columns={sorted(observed_columns)}",
        )
