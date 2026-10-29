# Source and Data Provenance

## Dataset provenance

Every generated account, quote, order, shipment, invoice, payment, dispute, status event, identifier, and ground-truth label is synthetic and produced by this repository's generator. The project does not download, embed, or transform external datasets. It contains no customer records or intentionally supplied personal information.

The generator uses the deterministic seed `20261022` by default. Configuration and generation logic are in `src/o2c_sim/settings.py`, `src/o2c_sim/entropy.py`, `src/o2c_sim/cycle_builder.py`, and `src/o2c_sim/fault_injection.py`. See `README.md` and `DATA_DICTIONARY.md` for commands, volumes, field definitions, and modeled rules.

## Generated artifacts

For each generation run, the exporter writes CSV files for the 13 ledger tables: `accounts`, `quotes`, `quote_lines`, `sales_orders`, `order_lines`, `shipments`, `invoices`, `invoice_lines`, `payments`, `payment_allocations`, `disputes`, `status_events`, and `ground_truth`. It also writes newline-delimited JSON files for those tables under `json/`, plus:

- `o2c_ledger.sqlite`, containing the exported tables and supported primary- and foreign-key constraints.
- `o2c_ledger.sql`, a SQL dump of the SQLite database.
- `checksum_manifest.csv`, with canonical table row counts and SHA-256 digests.
- `verification_report.csv`, with implemented validation results and observed evidence.

These are generated outputs, not source datasets. The repository's `.gitignore` excludes `output/`; the generated files remain local unless deliberately added elsewhere.

## External sources and licensing

No external dataset or third-party source data is used. Therefore there are no dataset URLs, retrieval dates, dataset versions, data licenses, attributions, or source-field transformations to report.

## Software dependencies

Runtime dependencies are NumPy and pandas; pytest is used for tests. Version requirements are listed in `pyproject.toml` and `requirements.txt`. Refer to those package projects for their respective licenses.
