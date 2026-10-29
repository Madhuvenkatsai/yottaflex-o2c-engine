from pathlib import Path
import sys

from o2c_sim.orchestration import O2CPipelineSimulator
from o2c_sim.settings import CHALLENGE_SEED


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    target = Path(args[0]) if args else Path("output") / "ledger"
    simulator = O2CPipelineSimulator(seed=CHALLENGE_SEED)
    simulator.run(target)
    census = simulator.ledger.row_census()
    print(f"seed={CHALLENGE_SEED}")
    for name, count in census.items():
        print(f"{name}={count}")
    if simulator.last_report is not None:
        failed = [item for item in simulator.last_report.checks if not item.passed]
        print(f"verification_failed={len(failed)}")
        for item in failed:
            print(f"FAIL {item.name}: {item.detail}")
        return 0 if simulator.last_report.ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
