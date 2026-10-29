from pathlib import Path

from o2c_sim.orchestration import O2CPipelineSimulator
from o2c_sim.settings import VOLUME_PLAN


def test_volume_targets_and_replay(tmp_path: Path):
    first = tmp_path / "run-a"
    second = tmp_path / "run-b"
    O2CPipelineSimulator().run(first)
    O2CPipelineSimulator().run(second)

    left = {
        str(path.relative_to(first)): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    right = {
        str(path.relative_to(second)): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert left == right

    quotes = sum(1 for _ in (first / "quotes.csv").open(encoding="utf-8")) - 1
    orders = sum(1 for _ in (first / "sales_orders.csv").open(encoding="utf-8")) - 1
    invoices = sum(1 for _ in (first / "invoices.csv").open(encoding="utf-8")) - 1
    events = sum(1 for _ in (first / "status_events.csv").open(encoding="utf-8")) - 1
    truth = sum(1 for _ in (first / "ground_truth.csv").open(encoding="utf-8")) - 1
    assert quotes == VOLUME_PLAN.quotes
    assert orders == VOLUME_PLAN.sales_orders
    assert invoices == VOLUME_PLAN.invoices
    payments = sum(1 for _ in (first / "payments.csv").open(encoding="utf-8")) - 1
    assert events + payments >= VOLUME_PLAN.timeline_events
    assert events > VOLUME_PLAN.timeline_events
    assert truth == 7

    report = (first / "verification_report.csv").read_text(encoding="utf-8")
    assert ",N," not in report
