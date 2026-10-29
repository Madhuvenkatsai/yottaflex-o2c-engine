# YottaFlex Order-to-Cash Engine

This Python package deterministically generates synthetic Order-to-Cash (O2C) ledger data for development, testing, and evaluation. It models accounts, quotes, sales orders, fulfillment, invoices, payments, disputes, and status events. All business records are synthetic.

## Requirements and installation

- Python 3.11 or later
- NumPy and pandas
- pytest for development and tests

Create a virtual environment and install the project with its test dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Alternatively, install runtime and test dependencies from `requirements.txt`:

```powershell
pip install -r requirements.txt
```

## Generate a ledger

From the repository root, run:

```powershell
python -m o2c_sim
```

The default output directory is `output/ledger/`. Pass a directory as the first argument to choose another destination:

```powershell
python -m o2c_sim output/ledger-run
```

The fixed challenge seed is `20261022`. The installed console entry point is also available:

```powershell
assemble-o2c-ledger output/ledger-run
```

The CLI prints a row census and verification result. It exits with status `0` when the report passes and `2` when one or more checks fail.

## Generated files

The output directory contains one CSV for each table described in [DATA_DICTIONARY.md](DATA_DICTIONARY.md), plus:

- `verification_report.csv`: check name, pass indicator, and observed/expected evidence.
- `checksum_manifest.csv`: CSV table row counts and SHA-256 digests of canonical table contents.
- `o2c_ledger.sqlite`: SQLite tables with primary keys and supported foreign keys.
- `o2c_ledger.sql`: SQL dump of the SQLite database.
- `json/<table>.json`: newline-delimited JSON (one JSON object per row).

SQLite stores exported values as text to preserve the CSV representation. Blank optional values are stored as SQL `NULL`. The deliberately phantom dispute reference has no SQLite foreign-key constraint; the verifier detects and evaluates it as an injected anomaly.

## Dataset volumes

The fixed-seed generator produces the following record counts:

| Dataset | Records |
|---|---:|
| Accounts | 1,800 |
| Quotes | 10,000 |
| Quote lines | 10,000 |
| Sales orders | 7,000 |
| Order lines | 7,000 |
| Shipments | 7,312 |
| Invoices | 8,000 |
| Invoice lines | 8,000 |
| Payments | 6,934 |
| Payment allocations | 6,935 |
| Disputes | 420 |
| Status events | 15,000 |
| Ground-truth entries | 5 |

The generator requires enough shipment-backed orders to produce the configured invoice target using no more than two invoices per shipped order. Orders without shipments are not invoiced. If the target cannot be achieved, generation raises an error rather than emitting unsupported invoices. The configured payment target is 6,934; eligible settlements are selected reproducibly to maintain this published dataset volume. Payment and dispute generation fail explicitly if their targets cannot be met from eligible records. In ordinary generated records, an order is closed only after fulfillment and settlement of all its invoices; the injected closed-with-unpaid scenario is the single exception.

## Architecture

- `src/o2c_sim/entropy.py` provides a single seeded random stream; `identity.py` creates deterministic document IDs.
- `cycle_builder.py` constructs the linked operational records, closes eligible settled orders, and builds the sampled status timeline.
- `fault_injection.py` injects the five documented scenarios and creates the separate ground-truth table.
- `ledger.py` stores tables and writes CSV files.
- `verification.py` checks volumes, keys and relationships, state values and transitions, chronology, financial reconciliation, anomaly detection, and label isolation.
- `orchestration.py` assembles, verifies, and exports CSV, JSONL, SQLite, and SQL.
- `cli.py` exposes the command-line entry point.

## Validation and intentional anomalies

The verification report contains independent checks for configured and derived volumes, primary-key uniqueness, ID and money formats, foreign keys, entity relationships, allowed states, event transitions, and chronology. Financial checks validate line extensions, invoice line totals, tax and total calculations, invoice balances against allocations, payment totals against allocated and unapplied amounts, and allocation limits.

The generator intentionally injects exactly one scenario of each type:

- `invoice_exceeds_fulfillment`: one invoice is inflated above its order's delivered fulfillment.
- `payment_allocated_twice`: a payment is allocated to a second invoice, exceeding the payment amount.
- `order_closed_with_unpaid_invoice`: an order is closed while a related invoice remains unpaid.
- `status_event_skips_state`: a sales-order event jumps from `booked` to `closed`.
- `dispute_not_in_receivables`: one dispute references an invoice ID absent from the invoice table.

Anomaly detectors inspect operational tables only. A separate evaluation step compares each detector's observed IDs with `ground_truth.csv`; labels are not used to find anomalies or as operational features. Intentional anomalies are visible in the report, and unexpected additional findings fail evaluation or their corresponding integrity checks.

The status event table is a sampled timeline with configured quotas, not a complete event history for every entity. It is suitable for the documented state-transition and per-entity timestamp checks, but should not be treated as a full audit log.

## Tests and reproducibility

Run the complete test suite:

```powershell
python -m pytest -v
```

Tests cover deterministic CSV/checksum replay, configured record counts, the five independently detected anomalies, label isolation, integrity and chronology failures, financial reconciliation, insufficient dispute candidates, export contents, and CLI exit behavior.

To check a fresh generation manually, generate twice into separate empty directories and compare the table CSVs and `checksum_manifest.csv`. Identical seeds and dependency behavior should produce identical outputs.

## Known limitations

- The model is synthetic and uses a simplified tax rule: 0% for `NA-*` regions and 8% elsewhere.
- The default challenge seed and configuration define the published fixed-seed record counts; stochastic table counts can vary with a different seed.
- The SQLite and SQL exports represent money and timestamps as text, matching the CSV values; consumers should parse them using the data types documented for their use.
- The generated data is not a substitute for accounting, tax, or production-system validation.
