
from pathlib import Path
import json
import sqlite3

from o2c_sim.checksums import folder_manifest, frame_digest, write_manifest
from o2c_sim.cycle_builder import CausalCycleAssembler, strip_private_fields
from o2c_sim.entropy import StreamedEntropy
from o2c_sim.fault_injection import KnownFaultInjector, ground_truth_frame
from o2c_sim.identity import SequenceDesk
from o2c_sim.ledger import OperationalLedger
from o2c_sim.settings import CHALLENGE_SEED, VOLUME_PLAN
from o2c_sim.verification import LedgerAuditor


class O2CPipelineSimulator:
    def __init__(self, seed: int = CHALLENGE_SEED) -> None:
        self.seed = seed
        self.ledger = OperationalLedger()
        self.last_report = None

    def run(self, output_dir: Path | None = None) -> OperationalLedger:
        entropy = StreamedEntropy(self.seed)
        desk = SequenceDesk()
        records = CausalCycleAssembler(
            entropy, desk
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

        self.ledger.dump_csv(output_dir)

        expected = {
            "quotes": VOLUME_PLAN.quotes,
            "sales_orders": VOLUME_PLAN.sales_orders,
            "invoices": VOLUME_PLAN.invoices,
            "status_events": VOLUME_PLAN.timeline_events,
            "ground_truth": 5,
        }

        report = LedgerAuditor(self.ledger.tables, expected).run()
        self.last_report = report
        report.as_frame().to_csv(
            output_dir / "verification_report.csv",
            index=False,
            lineterminator="\n",
        )

        census = self.ledger.row_census()
        digests = {
            f"{name}.csv": frame_digest(frame)
            for name, frame in self.ledger.tables.items()
        }
        write_manifest(output_dir, census, digests)

        json_dir = output_dir / "json"
        json_dir.mkdir(parents=True, exist_ok=True)

        database_path = output_dir / "o2c_ledger.sqlite"
        sql_path = output_dir / "o2c_ledger.sql"

        with sqlite3.connect(database_path) as connection:
            for name, frame in sorted(self.ledger.tables.items()):
                frame.to_json(
                    json_dir / f"{name}.json",
                    orient="records",
                    lines=True,
                    force_ascii=False,
                    date_format="iso",
                )
                frame.to_sql(
                    name,
                    connection,
                    if_exists="replace",
                    index=False,
                )

            with sql_path.open(
                "w", encoding="utf-8", newline="\n"
            ) as sql_file:
                for statement in connection.iterdump():
                    sql_file.write(statement + "\n")


    def replay_is_stable(
        self, first_dir: Path, second_dir: Path
    ) -> bool:
        left = folder_manifest(first_dir)
        right = folder_manifest(second_dir)

        keys = [
            name for name in left
            if name != "checksum_manifest.csv"
        ]

        return left == right and set(keys) <= set(right)
