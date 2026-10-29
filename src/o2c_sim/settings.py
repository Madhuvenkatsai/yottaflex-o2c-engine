from dataclasses import dataclass
from datetime import date, datetime, timezone


CHALLENGE_SEED = 20261022
FISCAL_YEAR = 2026
CURRENCY = "USD"


@dataclass(frozen=True)
class VolumePlan:
    accounts: int = 1_800
    quotes: int = 10_000
    sales_orders: int = 7_000
    invoices: int = 8_000
    duplicate_invoice_records: int = 1
    payments: int = 6_934
    # Minimum combined payment and status-event rows, not an event-row cap.
    timeline_events: int = 15_000
    disputes: int = 420


STARTER_VOLUME_PLAN = VolumePlan(
    accounts=180,
    quotes=1_000,
    sales_orders=700,
    invoices=800,
    duplicate_invoice_records=1,
    payments=693,
    timeline_events=1_500,
    disputes=42,
)


@dataclass(frozen=True)
class CalendarWindow:
    open_on: date = date(2025, 11, 3)
    books_close_on: date = date(2026, 10, 22)


VOLUME_PLAN = VolumePlan()


def volume_plan_for_scale(scale: str) -> VolumePlan:
    if scale == "full":
        return VOLUME_PLAN
    if scale == "starter":
        return STARTER_VOLUME_PLAN
    raise ValueError(f"unsupported dataset scale: {scale}")


CALENDAR = CalendarWindow()
AS_OF_TS = datetime(2026, 10, 22, 18, 0, 0, tzinfo=timezone.utc)

INDUSTRIES = (
    "industrial_automation",
    "cloud_infrastructure",
    "clinical_diagnostics",
    "freight_brokerage",
    "retail_media",
    "energy_storage",
)

REGIONS = ("NA-EAST", "NA-WEST", "EU-CORE", "APAC-SOUTH", "LATAM")

QUOTE_REASONS = ("new_logo", "expansion", "renewal", "replacement")
DISPUTE_REASONS = (
    "short_ship",
    "price_mismatch",
    "tax_coding",
    "duplicate_bill",
    "service_credit",
)
