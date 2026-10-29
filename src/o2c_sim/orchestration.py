from pathlib import Path
import json
import sqlite3

import pandas as pd

from o2c_sim.checksums import frame_digest, write_manifest
from o2c_sim.cycle_builder import CausalCycleAssembler, strip_private_fields
from o2c_sim.entropy import StreamedEntropy
from o2c_sim.fault_injection import KnownFaultInjector, ground_truth_frame
from o2c_sim.identity import SequenceDesk
from o2c_sim.ledger import OperationalLedger
from o2c_sim.settings import CHALLENGE_SEED, VOLUME_PLAN
from o2c_sim.verification import LedgerAuditor


PRIMARY_KEYS = {
    "accounts": ["account_id"],
    "quotes": ["quote_id"],
    "quote_lines": ["quote_line_id"],
    "sales_orders": ["sales_order_id"],
    "order_lines": ["order_line_id"],
    "shipments": ["shipment_id"],
    "invoices": ["invoice_id"],
    "invoice_lines": ["invoice_line_id"],
    "payments": ["payment_id"],
    "payment_allocations": ["payment_id", "invoice_id"],
    "disputes": ["dispute_id"],
    "status_events": ["event_id"],
    "ground_truth": ["truth_id"],
}


FOREIGN_KEYS = {
    "quotes": [
        ("account_id", "accounts", "account_id"),
    ],
    "quote_lines": [
        ("quote_id", "quotes", "quote_id"),
    ],
    "sales_orders": [
        ("quote_id", "quotes", "quote_id"),
        ("account_id", "accounts", "account_id"),
    ],
    "order_lines": [
        ("sales_order_id", "sales_orders", "sales_order_id"),
        ("quote_line_id", "quote_lines", "quote_line_id"),
    ],
    "shipments": [
        ("sales_order_id", "sales_orders", "sales_order_id"),
        ("account_id", "accounts", "account_id"),
    ],
    "invoices": [
    ("sales_order_id", "sales_orders", "sales_order_id"),
    ("account_id", "accounts", "account_id"),
    ],
    "invoice_lines": [
        ("invoice_id", "invoices", "invoice_id"),
        ("sales_order_id", "sales_orders", "sales_order_id"),
        ("order_line_id", "order_lines", "order_line_id"),
        ("shipment_id", "shipments", "shipment_id"),
    ],
    "payments": [
        ("account_id", "accounts", "account_id"),
    ],
    "payment_allocations": [
        ("payment_id", "payments", "payment_id"),
        ("invoice_id", "invoices", "invoice_id"),
    ],
    # GT-0005 deliberately references a nonexistent invoice.
    # Therefore, disputes.invoice_id must not have a foreign-key constraint.
    "disputes": [
        ("account_id", "accounts", "account_id"),
    ],
}


INSERT_ORDER = [
    "accounts",
    "quotes",
    "quote_lines",
    "sales_orders",
    "order_lines",
    "shipments",
    "invoices",
    "invoice_lines",
    "payments",
    "payment_allocations",
    "disputes",
    "status_events",
    "ground_truth",
]


def sqlite_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if pd.isna(value):
        return None
    return str(value)


class O2CPipelineSimulator:
    def __init__(self, seed: int = CHALLENGE_SEED) -> None:
        self.seed = seed
        self.ledger = OperationalLedger()
        self.last_report = None

    def run(self, output_dir: Path | None = None) -> OperationalLedger:
        entropy = StreamedEntropy(self.seed)
        desk = SequenceDesk()

        records = CausalCycleAssembler(
            entropy,
            desk,
        ).assemble_initial_records()

        truth_rows = KnownFaultInjector(desk).apply(records)
        records["ground_truth"] = ground_truth_frame(truth_rows)

        for name, rows in records.items():
            self.ledger.put(name, strip_private_fields(rows))

        if output_dir is not None:
            self.persist(output_dir)

        return self.ledger

    def persist(self, output_dir: Path) -> None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Export CSV files.
        self.ledger.dump_csv(output_dir)

        # Run data-quality verification.
        expected = {
            "quotes": VOLUME_PLAN.quotes,
            "sales_orders": VOLUME_PLAN.sales_orders,
            "invoices": VOLUME_PLAN.invoices,
            "status_events": VOLUME_PLAN.timeline_events,
            "ground_truth": 5,
        }

        report = LedgerAuditor(
            self.ledger.tables,
            expected,
        ).run()

        self.last_report = report

        report.as_frame().to_csv(
            output_dir / "verification_report.csv",
            index=False,
            lineterminator="\n",
        )

        # Write row counts and CSV checksums.
        census = self.ledger.row_census()

        digests = {
            f"{name}.csv": frame_digest(frame)
            for name, frame in self.ledger.tables.items()
        }

        write_manifest(output_dir, census, digests)

        # Export newline-delimited JSON.
        json_dir = output_dir / "json"
        json_dir.mkdir(parents=True, exist_ok=True)

        for name, frame in sorted(self.ledger.tables.items()):
            frame.to_json(
                json_dir / f"{name}.json",
                orient="records",
                lines=True,
                force_ascii=False,
                date_format="iso",
            )

        database_path = output_dir / "o2c_ledger.sqlite"
        sql_path = output_dir / "o2c_ledger.sql"

        # Remove an old database so its schema cannot conflict.
        if database_path.exists():
            database_path.unlink()

        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")

            # Pass 1: create every table and its constraints.
            for name in INSERT_ORDER:
                frame = self.ledger.tables[name]
                columns = list(frame.columns)

                primary_keys = PRIMARY_KEYS.get(name, [])
                foreign_keys = FOREIGN_KEYS.get(name, [])

                definitions = [
                    f'"{column}" TEXT'
                    for column in columns
                ]

                if len(primary_keys) == 1:
                    key = primary_keys[0]
                    definitions[columns.index(key)] = (
                        f'"{key}" TEXT PRIMARY KEY'
                    )

                elif len(primary_keys) > 1:
                    keys = ", ".join(
                        f'"{key}"'
                        for key in primary_keys
                    )
                    definitions.append(
                        f"PRIMARY KEY ({keys})"
                    )

                for column, parent, parent_column in foreign_keys:
                    definitions.append(
                        f'FOREIGN KEY ("{column}") '
                        f'REFERENCES "{parent}"("{parent_column}")'
                    )

                create_sql = (
                    f'CREATE TABLE "{name}" '
                    f'({", ".join(definitions)})'
                )

                connection.execute(create_sql)

            # Pass 2: insert data after all tables exist.
            for name in INSERT_ORDER:
                frame = self.ledger.tables[name]
                columns = list(frame.columns)

                column_names = ", ".join(
                    f'"{column}"'
                    for column in columns
                )

                placeholders = ", ".join(
                    "?"
                    for _ in columns
                )

                insert_sql = (
                    f'INSERT INTO "{name}" ({column_names}) '
                    f"VALUES ({placeholders})"
                )

                # Convert blank strings and pandas missing values to SQL NULL.
                rows = [
                    tuple(sqlite_value(value) for value in row)
                    for row in frame.itertuples(index=False, name=None)
                ]

                savepoint = f"insert_{name}"
                connection.execute(
                    f'SAVEPOINT "{savepoint}"'
                )

                try:
                    connection.executemany(insert_sql, rows)
                    connection.execute(
                        f'RELEASE "{savepoint}"'
                    )

                except sqlite3.IntegrityError as exc:
                    connection.execute(
                        f'ROLLBACK TO "{savepoint}"'
                    )
                    connection.execute(
                        f'RELEASE "{savepoint}"'
                    )

                    print(
                        f"SQLite insert failed for table {name}: {exc}"
                    )

                    # Retry one record at a time to identify the exact failure.
                    for row_number, row in enumerate(rows):
                        try:
                            connection.execute(insert_sql, row)

                        except sqlite3.IntegrityError as row_exc:
                            print(f"FAILED TABLE: {name}")
                            print(f"FAILED ROW INDEX: {row_number}")
                            print(f"ERROR: {row_exc}")
                            print(dict(zip(columns, row)))
                            raise

                    # The batch failed but individual rows did not.
                    # Preserve the original exception for investigation.
                    raise

            # Verify all foreign keys after insertion.
            violations = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if violations:
                raise RuntimeError(
                    "SQLite foreign-key check failed: "
                    f"{violations[:10]}"
                )

            # Export a SQL dump of the database.
            with sql_path.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as sql_file:
                for statement in connection.iterdump():
                    sql_file.write(statement + "\n")