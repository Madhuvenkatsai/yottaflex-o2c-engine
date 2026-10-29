# YottaFlex Order-to-Cash Engine

This Python package deterministically generates synthetic Order-to-Cash (O2C) ledger data for development, testing, and evaluation. It models accounts, quotes, sales orders, fulfillment, invoices, payments, disputes, and status events. All business records are synthetic; no customer or external dataset is used.

## Requirements and installation

- Python 3.11 or later
- NumPy and pandas
- pytest for development and tests

Install the package and test dependency in a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

The editable-install method above installs this `src`-layout package and its test
dependencies and is the recommended setup. Installing `requirements.txt` alone
installs dependencies only; it does not install this package. If you prefer that
file, install the package separately from the repository root:

```powershell
pip install -r requirements.txt
pip install -e .
```

## Generate a ledger

From the repository root:

```powershell
python -m o2c_sim
```

The default output directory is `output/ledger/`. Pass a path to use a different directory:

```powershell
python -m o2c_sim output/ledger-run
```

The installed console entry point is also available:

```powershell
assemble-o2c-ledger output/ledger-run
```

The generator supports two deterministic sizes using the same fixed seed and rules:

```powershell
python -m o2c_sim --scale starter output\starter
python -m o2c_sim --scale full output\full
```

`full` is the default and preserves the challenge configuration. `starter` scales the account, quote, order, invoice, payment, and dispute targets to 10% (integer counts are configured explicitly); both plans retain all seven labeled anomaly scenarios. A scale fails explicitly if there are not enough eligible shipment-backed orders, payment candidates, dispute candidates, or anomaly anchors. The CLI prints the row census and failed-check count; it exits with status `0` when all checks pass and `2` when one or more checks fail. The seed is fixed at `20261022`.

## Generated files and fixed-seed volumes

Each entity and bridge table has a CSV file. The `json/` folder contains newline-delimited JSON files named `<table>.json`. The output also includes:

- `o2c_ledger.sqlite`: SQLite tables with primary keys and supported foreign keys.
- `o2c_ledger.sql`: SQL dump of the SQLite database.
- `checksum_manifest.csv`: CSV row counts and SHA-256 digests of canonical table contents.
- `verification_report.csv`: check name, pass indicator, and observed/expected evidence.

The verified fixed-seed row counts are:

| Table | Rows |
|---|---:|
| accounts | 1,800 |
| quotes | 10,000 |
| quote_lines | 10,000 |
| sales_orders | 7,000 |
| order_lines | 7,000 |
| shipments | 7,312 |
| invoices | 8,000 |
| invoice_lines | 8,000 |
| payments | 6,934 |
| payment_allocations | 6,935 |
| disputes | 420 |
| status_events | 83,455 |
| ground_truth | 7 |

The challenge statement says: “Generate the baseline volume: Generate 10,000 quotes, 7,000 orders, 8,000 invoices and 15,000 payments/events.” The phrase “payments/events” does not specify whether 15,000 is a payment-row count, an event-row count, or a combined count. This implementation interprets it as a minimum combined count of payment rows plus status-event rows; that interpretation is not officially confirmed and remains an acceptance risk. Every modeled state transition is retained, so status events are not capped at 15,000. In the fixed-seed output this yields 90,389 combined payment and status-event rows.

For the starter scale, configured targets are 180 accounts, 1,000 quotes, 700 orders, 800 invoices, 693 payments, and 42 disputes; the combined payment/event minimum is 1,500. Shipment, allocation, and status-event totals are derived from those records and the same workflow rules.

Quotes and orders contain a single synthetic line with a positive integer quantity (2–20) and a per-unit price; quantity varies deterministically by quote sequence. Each shipment records `fulfilled_quantity` and its corresponding amount. Invoices contain line quantity and unit price and are built from delivered quantities. Split shipments and split invoices are supported; unshipped orders are not invoiced. Quantity reconciliation and monetary reconciliation are separate checks. The injected over-fulfillment, underbilling, and duplicate-invoice cases remain explicitly labeled and are compared against operationally detected quantities and amounts.

The builder creates shipment-backed baseline invoices and splits eligible fulfilled orders as needed to reach the configured invoice target minus the duplicate-invoice anomaly. Generation raises an error if the target cannot be reached with at most two baseline invoices per shipped order. Payment and dispute targets also fail explicitly when there are not enough eligible records.

## Workflow, architecture, and rules

Accepted quotes become sales orders. Orders may have one or two shipment records; invoices are derived from delivered fulfillment. Payments are linked to invoices through the `payment_allocations` bridge table, and disputes reference invoices. Status changes are represented as timestamped events as well as current-state columns.

- `settings.py` defines the fixed seed, calendar cutoff, currencies, allowed source categories, and starter/full volume plans.
- `entropy.py` supplies the seeded random stream; `identity.py` mints deterministic IDs.
- `cycle_builder.py` creates linked baseline records, settlement data, and modeled status history.
- `fault_injection.py` adds labeled anomaly scenarios and creates the separate ground-truth table.
- `ledger.py` stores tables and writes CSV files.
- `verification.py` checks configured volumes, keys and relationships, state values and histories, chronology, quantity and monetary reconciliation, aging, anomaly detection, and ground-truth isolation.
- `orchestration.py` assembles, verifies, and exports the ledger; `cli.py` provides the command-line interface.

The fixed aging cutoff is `2026-10-22T18:00:00Z`. Invoice tax is 0% for `NA-*` account regions and 8% elsewhere. Currency is USD. Money is emitted as a decimal string with two fractional digits. SQLite stores exported fields as text to preserve CSV values and maps blank optional values to SQL `NULL`.

## Injected scenarios and validation

The generator adds one instance of each of the five required scenarios, plus labeled coverage scenarios for underbilling and duplicate invoices:

| Scenario | Independent detector |
|---|---|
| Invoice exceeds delivered fulfillment | Independently compares invoiced quantities and net invoice amounts with fulfilled quantities and amounts per order |
| Payment allocated twice | Finds payment allocations whose sum exceeds payment value after unapplied amount |
| Order closed with an unpaid invoice | Finds closed orders with positive related invoice balances |
| Status event skips a required state | Checks sales-order event transitions against the allowed transition set |
| Dispute not reflected in receivables | Finds dispute references absent from the invoice table |
| Underbilling | Finds fulfilled orders whose non-duplicate invoices are below fulfillment |
| Duplicate invoice | Finds repeated invoice signatures |

Detectors inspect operational tables, not ground-truth labels. A separate evaluation compares the detector IDs with the labeled anchors. The payment-allocation anomaly intentionally creates an excessive allocation; the invoice-over-fulfillment, underbilling, and duplicate-invoice cases intentionally create their respective billing deltas. Known injected discrepancies are identified and reported separately from unexpected discrepancies.

The auditor checks primary-key uniqueness and ID formats, foreign keys and cross-entity consistency, order-line quantities/prices against their source quote lines, state values and event-history completeness, timestamp chronology, line extensions, invoice net/tax/total arithmetic, allocation and unapplied-payment reconciliation, invoice balance bounds, shipment quantity × order unit price, shipment-to-order quantity limits, invoice quantity versus fulfillment, monetary fulfillment-to-invoice deltas, and receivable aging. Quantity and money checks are reported separately. Aging groups open balances by invoice due date relative to the fixed cutoff; disputed balances are separately reported. The report's passing status means all implemented checks passed, including expected anomaly evaluation; it does not mean the dataset has no intentional exceptions.

The dispute anomaly uses a deliberately nonexistent invoice ID. For this reason, `disputes.invoice_id` has no SQLite foreign-key constraint; the independent verifier detects the orphan. Polymorphic `status_events.entity_type`/`entity_id` references are checked by the verifier rather than represented as SQLite foreign keys.

## Tests and deterministic replay

Run the complete test suite:

```powershell
python -m pytest -q
```

Tests cover configured full and starter volumes, deterministic exports, all seven labeled scenarios and ground-truth isolation, quantity and monetary reconciliation, key and relationship checks, lifecycle and chronology failures, financial reconciliation and aging, insufficient eligible records and anomaly anchors, export contents, SQLite foreign keys and SQL restoration, and CLI scale and exit behavior.

For an independent replay, generate into two empty directories with the same seed (the default) and compare all files, including CSV, JSONL, SQLite contents, SQL dump, checksum manifest, and verification report. The output directories should be separate and fresh.

## Known limitations and provenance

- This is a synthetic simulator, not an accounting, tax, or production-system validation service.
- The model uses one synthetic service line per quote, order, and invoice. Quantities are synthetic item counts; they do not represent a particular physical product unit.
- The tax rule is intentionally simplified and does not model jurisdictional tax law.
- All fields are stored as text in SQLite; downstream consumers must parse dates, amounts, quantities, and booleans according to [DATA_DICTIONARY.md](DATA_DICTIONARY.md).
- The source and synthetic-data declaration is in [SOURCE_MANIFEST.md](SOURCE_MANIFEST.md).
- AI assistance and the limits of recoverable prompt history are disclosed in [AI_USAGE.md](AI_USAGE.md). The candidate should review that disclosure, add any independently verified personal review or decisions, and confirm it is accurate before submission.
