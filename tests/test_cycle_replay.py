from pathlib import Path

from o2c_sim.orchestration import O2CPipelineSimulator
from o2c_sim.settings import VOLUME_PLAN


def test_volume_targets_and_replay(tmp_path: Path):
    first = tmp_path / "run-a"
    second = tmp_path / "run-b"
    O2CPipelineSimulator().run(first)
    O2CPipelineSimulator().run(second)

    left = {path.name: path.read_bytes() for path in first.glob("*.csv")}
    right = {path.name: path.read_bytes() for path in second.glob("*.csv")}
    assert left == right

    quotes = (first / "quotes.csv").read_text(encoding="utf-8").count("\n") - 1
    orders = (first / "sales_orders.csv").read_text(encoding="utf-8").count("\n") - 1
    invoices = (first / "invoices.csv").read_text(encoding="utf-8").count("\n") - 1
    events = (first / "status_events.csv").read_text(encoding="utf-8").count("\n") - 1
    truth = (first / "ground_truth.csv").read_text(encoding="utf-8").count("\n") - 1
    assert quotes == VOLUME_PLAN.quotes
    assert orders == VOLUME_PLAN.sales_orders
    assert invoices == VOLUME_PLAN.invoices
    assert events == VOLUME_PLAN.timeline_events
    assert truth == 5

    report = (first / "verification_report.csv").read_text(encoding="utf-8")
    assert ",N," not in report
