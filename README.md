# Order-to-Cash Synthetic Data Generator

## Project Overview

This project generates synthetic data for an Order-to-Cash (O2C) business workflow. It models the movement of transactions from account creation and quotations through sales orders, shipments, invoicing, payments, and disputes.

The generator creates linked datasets with consistent identifiers, transaction relationships, status histories, and validation outputs. A fixed random seed is used to support reproducible generation.

## Technology Stack

- Python 3.11+
- pandas
- NumPy
- pytest

## Project Structure

```text
YOTTAFLEX (CHALLANGE)/
├── src/
│   └── o2c_sim/
│       ├── checksums.py
│       ├── cli.py
│       ├── cycle_builder.py
│       ├── entropy.py
│       ├── fault_injection.py
│       ├── identity.py
│       ├── ledger.py
│       ├── money.py
│       ├── orchestration.py
│       ├── settings.py
│       └── verification.py
├── tests/
│   ├── test_cycle_replay.py
│   └── test_identity.py
├── output/
│   └── ledger/
├── pyproject.toml
└── README.md
```

## Setup

Create and activate a virtual environment if one is not already available.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Run the Generator

Generate the datasets using the configured seed:

```powershell
python -m o2c_sim
```

The current generation seed is `20261022`.

## Run Tests

Execute the automated test suite:

```powershell
python -m pytest -v
```

The current test suite contains checks for generation replay and zero-padded document identifiers.

## Generated Dataset

The latest successful generation reported the following record counts.

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

## Output Location

Generated CSV files and validation artifacts are stored in:

```text
output/ledger/
```

The output includes the entity datasets, ground-truth records, checksum manifest, and verification report.

## Validation and Reproducibility

The latest run completed with `verification_failed=0`. The automated test suite also completed with two passing tests.

The project uses a fixed seed and includes checksum and replay functionality. These features support repeatable generation and comparison of generated datasets.

## Data Provenance

All business records are synthetically generated for software development, testing, and evaluation. They are not intended to represent real customer or financial transactions.
## Business Rules and Exception Handling

The generator models the Order-to-Cash lifecycle:
Account -> Quote -> Sales Order -> Shipment -> Invoice -> Payment Allocation.

It also records disputes and lifecycle status events. Derived financial values and balances should be calculated from their source records and reconciled by the validation process.

### Required Anomaly Scenarios

The separate ground-truth dataset identifies the following deliberately injected scenarios:

- `dispute_not_in_receivables`: A dispute is not reflected in receivables.
- `invoice_exceeds_fulfillment`: An invoice exceeds the supported fulfilled value.
- `order_closed_with_unpaid_invoice`: An order is closed while an invoice remains unpaid.
- `payment_allocated_twice`: A payment allocation anomaly is injected.
- `status_event_skips_state`: A status event skips a required lifecycle state.

Ground-truth labels are evaluation references and must not be used as ordinary input features for anomaly detection.

### Validation Expectations

Validation should cover:

- Primary-key uniqueness and valid entity relationships.
- Allowed lifecycle states and legal state transitions.
- Date ordering and deterministic identifier generation.
- Monetary calculations, invoice balances, and payment allocations.
- Traceability of exceptions to their affected entities.
- Fixed-seed regeneration and output checksum comparison.

Any deliberate anomaly must be documented and distinguishable from an unintended generator or data-integrity defect.

### Reproducibility Procedure

Run the generator twice with the configured seed, compare the record counts and checksum manifest, and investigate any unexpected differences.

### Business Evaluation Metrics

Useful operational metrics include:

- Value of fulfilled goods not yet invoiced.
- Potential over-invoicing exposure.
- Outstanding overdue receivables.
- Short-paid and over-allocated payments.
- Disputed balances and their receivables treatment.
- Exception counts and the source records supporting each finding.

These metrics should be calculated from transaction data using a documented reporting cutoff date.

