
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


LEDGER_TABLES = (
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
)


@dataclass
class OperationalLedger:
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)

    def put(self, name: str, frame: pd.DataFrame) -> None:
        self.tables[name] = frame.reset_index(drop=True)

    def get(self, name: str) -> pd.DataFrame:
        if name not in self.tables:
            raise KeyError(f"ledger table missing: {name}")
        return self.tables[name]

    def row_census(self) -> dict[str, int]:
        return {
            name: int(len(frame))
            for name, frame in self.tables.items()
        }

    def dump_csv(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)

        for name, frame in self.tables.items():
            frame.to_csv(
                folder / f"{name}.csv",
                index=False,
                lineterminator="\n",
            )
