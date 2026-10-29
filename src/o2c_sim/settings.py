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
    timeline_events: int = 15_000
    disputes: int = 420


@dataclass(frozen=True)
class CalendarWindow:
    open_on: date = date(2025, 11, 3)
    books_close_on: date = date(2026, 10, 22)


VOLUME_PLAN = VolumePlan()
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
