import argparse
from pathlib import Path

from o2c_sim.orchestration import O2CPipelineSimulator
from o2c_sim.settings import CHALLENGE_SEED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic O2C ledger.")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=str(Path("output") / "ledger"),
        help="destination directory (default: output/ledger)",
    )
    parser.add_argument(
        "--scale",
        choices=("starter", "full"),
        default="full",
        help="dataset size (default: full)",
    )
    args = parser.parse_args(argv)
    target = Path(args.output_dir)
    simulator = O2CPipelineSimulator(seed=CHALLENGE_SEED, scale=args.scale)
    simulator.run(target)
    census = simulator.ledger.row_census()
    print(f"seed={CHALLENGE_SEED}")
    print(f"scale={args.scale}")
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
