# YottaFlex Order-to-Cash Data Dictionary

## Conventions and scope

The CSV headers are the exported field names. Semantic types below describe the values; CSV and JSONL values are serialized as strings or numbers, and SQLite columns are all `TEXT` to retain the exported representation. Empty optional CSV values are stored as SQL `NULL`. Required means the fixed-seed generator populates the field; the verifier checks its key fields, money/date formats, declared relationships, and specific business rules, but not every descriptive field's nullability.

All timestamps are UTC ISO 8601 strings ending in `Z`. All money is USD with exactly two decimal places. Quantities and line numbers are positive integers. IDs are immutable strings in `<PREFIX>-2026-<six-digit sequence>` format, except `GT-####` ground-truth IDs. There are no external data sources; all names, transactions, and event records are synthetic.

## Entity and field definitions

### Account — `accounts.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `account_id` | string | Yes | `ACC-2026-######` | Primary key | Nonempty, unique, format checked |
| `legal_name` | string | Yes | Synthetic name | No | Generated from region, industry, and account ordinal |
| `industry` | string enum | Yes | `industrial_automation`, `cloud_infrastructure`, `clinical_diagnostics`, `freight_brokerage`, `retail_media`, `energy_storage` | No | Selected from configured industry set |
| `region` | string enum | Yes | `NA-EAST`, `NA-WEST`, `EU-CORE`, `APAC-SOUTH`, `LATAM` | No | Determines the simplified invoice tax rate |
| `currency` | string | Yes | `USD` | No | Generator-wide currency |
| `credit_limit` | decimal string | Yes | USD; positive | No | Two fractional digits; positive-value check |
| `account_status` | string enum | Yes | `active`, `on_hold` | No | Current state must agree with final status event |
| `opened_at` | UTC timestamp | Yes | ISO 8601 UTC | No | Event chronology and quote-after-account check |

### Quote — `quotes.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `quote_id` | string | Yes | `QTE-2026-######` | Primary key | Nonempty, unique, format checked |
| `account_id` | string | Yes | Account ID | No | FK to `accounts.account_id` |
| `motion` | string enum | Yes | `new_logo`, `expansion`, `renewal`, `replacement` | No | Configured quote reason |
| `quoted_amount` | decimal string | Yes | USD; positive | No | Must equal quote-line sum |
| `currency` | string | Yes | `USD` | No | Generator-wide currency |
| `quote_status` | string enum | Yes | `accepted`, `expired`, `rejected` | No | Only accepted quotes convert to generated orders |
| `issued_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after account opening |
| `expires_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after issue time |
| `decided_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after issue time |

### Quote line — `quote_lines.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `quote_line_id` | string | Yes | `QTL-2026-######` | Primary key | Nonempty, unique, format checked |
| `quote_id` | string | Yes | Quote ID | No | FK to `quotes.quote_id` |
| `line_number` | integer | Yes | Positive integer | No | Sequence within quote; generated as `1` |
| `description` | string | Yes | Synthetic item description | No | Generated service item |
| `quantity` | integer | Yes | Positive item count | No | Line amount equals quantity × unit price |
| `unit_price` | decimal string | Yes | USD per item; positive | No | Two fractional digits |
| `line_amount` | decimal string | Yes | USD; positive | No | Equals quantity × unit price; quote line sums to header |
| `currency` | string | Yes | `USD` | No | Must agree with generator currency |

### Sales order — `sales_orders.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `sales_order_id` | string | Yes | `SO-2026-######` | Primary key | Nonempty, unique, format checked |
| `quote_id` | string | Yes | Quote ID | No | FK to accepted quote; generated one order per accepted quote |
| `account_id` | string | Yes | Account ID | No | FK to account; must match source quote |
| `order_amount` | decimal string | Yes | USD; positive | No | Equals source quote amount and order-line sum |
| `currency` | string | Yes | `USD` | No | Generator-wide currency |
| `order_status` | string enum | Yes | `booked`, `in_fulfillment`, `fulfilled`, `closed` | No | Current state; normally closed only after fulfillment and settlement |
| `booked_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after quote issue |
| `closed_at` | UTC timestamp | No | ISO 8601 UTC or blank | No | Present for closed orders; exception scenario is explicitly labeled |

### Order line — `order_lines.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `order_line_id` | string | Yes | `OTL-2026-######` | Primary key | Nonempty, unique, format checked |
| `sales_order_id` | string | Yes | Sales order ID | No | FK to `sales_orders.sales_order_id` |
| `quote_line_id` | string | Yes | Quote-line ID | No | FK to source quote line; quote must match order |
| `line_number` | integer | Yes | Positive integer | No | Sequence within order; generated as `1` |
| `description` | string | Yes | Synthetic item description | No | Carried from the single generated service-item model |
| `quantity` | integer | Yes | Positive item count | No | Line amount equals quantity × unit price |
| `unit_price` | decimal string | Yes | USD per item; positive | No | Two fractional digits |
| `line_amount` | decimal string | Yes | USD; positive | No | Equals quantity × unit price; order-line sums match header |
| `currency` | string | Yes | `USD` | No | Generator-wide currency |

### Shipment — `shipments.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `shipment_id` | string | Yes | `SHP-2026-######` | Primary key | Nonempty, unique, format checked |
| `sales_order_id` | string | Yes | Sales order ID | No | FK to order; many shipments may belong to one order |
| `account_id` | string | Yes | Account ID | No | FK to account; must match order |
| `fulfilled_quantity` | integer | Yes | Positive item count | No | Quantity delivered by this shipment; sum by order cannot exceed ordered quantity |
| `fulfilled_amount` | decimal string | Yes | USD-equivalent fulfillment value; positive | No | Sum by order is the delivered fulfillment value used in invoice reconciliation |
| `shipment_status` | string enum | Yes | `delivered` | No | Current terminal status; intermediate packed/shipped states are in events |
| `packed_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after order booking |
| `shipped_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after packing |
| `delivered_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after shipping |

### Invoice — `invoices.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `invoice_id` | string | Yes | `INV-2026-######` | Primary key | Nonempty, unique, format checked |
| `sales_order_id` | string | Yes | Sales order ID | No | FK to order; one order may have multiple invoices |
| `shipment_id` | string | Optional | Shipment ID or blank | No | FK when populated; blank when one invoice covers multiple shipments; issue time is after contributing fulfillment |
| `account_id` | string | Yes | Account ID | No | FK to account; must match order |
| `invoice_amount` | decimal string | Yes | USD net amount; positive | No | Equals invoice-line sum |
| `tax_amount` | decimal string | Yes | USD; nonnegative | No | 0% for `NA-*`, otherwise simplified 8% of net |
| `total_due` | decimal string | Yes | USD; positive | No | Net amount plus tax |
| `balance_due` | decimal string | Yes | USD; zero or positive | No | Must be between zero and total due; reconciles to allocations except labeled anomaly |
| `currency` | string | Yes | `USD` | No | Generator-wide currency |
| `invoice_status` | string enum | Yes | `open`, `partial`, `paid`, `disputed` | No | Must be consistent with balance and event history, except detected injected scenarios |
| `issued_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after all fulfillment represented by the invoice |
| `due_at` | UTC timestamp | Yes | ISO 8601 UTC | No | 30 days after issue; aging uses the fixed cutoff |

### Invoice line — `invoice_lines.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `invoice_line_id` | string | Yes | `ITL-2026-######` | Primary key | Nonempty, unique, format checked |
| `invoice_id` | string | Yes | Invoice ID | No | FK to invoice |
| `sales_order_id` | string | Yes | Sales order ID | No | FK to order; must match invoice |
| `order_line_id` | string | Yes in generated data; relationship optional | Order-line ID | No | FK when populated |
| `shipment_id` | string | Optional | Shipment ID or blank | No | FK when populated; blank when an invoice combines multiple shipments; must match order |
| `line_number` | integer | Yes | Positive integer | No | Sequence within invoice; generated as `1` |
| `description` | string | Yes | Synthetic item description | No | Generated service item |
| `quantity` | integer | Yes | Positive item count | No | Invoiced quantity; sum across an order's invoices is reconciled to its fulfilled quantity |
| `unit_price` | decimal string | Yes | USD per item; positive | No | Two fractional digits; line amount equals quantity × unit price |
| `line_amount` | decimal string | Yes | USD net amount; positive | No | Invoice-line sum equals invoice net amount |
| `currency` | string | Yes | `USD` | No | Generator-wide currency |

### Payment — `payments.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `payment_id` | string | Yes | `PAY-2026-######` | Primary key | Nonempty, unique, format checked |
| `account_id` | string | Yes | Account ID | No | FK to account; must match allocated invoices |
| `instrument` | string enum | Yes | `ach`, `wire`, `card` | No | Configured payment instruments |
| `payment_amount` | decimal string | Yes | USD; positive | No | Amount received |
| `unapplied_amount` | decimal string | Yes | USD; zero or positive | No | Payment amount equals allocations plus unapplied amount, except labeled over-allocation |
| `payment_status` | string enum | Yes | `allocated` | No | Generated payments are allocated; state change retained in events |
| `posted_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after related invoice issue |

### Payment allocation bridge — `payment_allocations.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `payment_id` | string | Yes | Payment ID | Composite primary key | FK to payment |
| `invoice_id` | string | Yes | Invoice ID | Composite primary key | FK to invoice |
| `allocated_amount` | decimal string | Yes | USD; positive | No | Sum reconciles against payment and invoice balances; excess is detected |
| `allocated_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after payment posting |

The composite key `(payment_id, invoice_id)` permits one payment to cover multiple invoices and multiple payments to cover one invoice, while disallowing duplicate pairs at the database-key level. The required double-allocation scenario allocates the same payment to two distinct invoices, causing payment-level excess.

### Dispute — `disputes.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `dispute_id` | string | Yes | `DSP-2026-######` | Primary key | Nonempty, unique, format checked |
| `invoice_id` | string | Yes | Invoice ID | No | Normally references an invoice; one labeled anomaly intentionally references a nonexistent ID |
| `account_id` | string | Yes | Account ID | No | FK to account; matches invoice for ordinary disputes |
| `dispute_amount` | decimal string | Yes | USD; positive | No | Generated from remaining balance and invoice total |
| `reason_code` | string enum | Yes | `short_ship`, `price_mismatch`, `tax_coding`, `duplicate_bill`, `service_credit` | No | Configured dispute reasons |
| `dispute_status` | string enum | Yes | `under_review` | No | Current state and event history |
| `opened_at` | UTC timestamp | Yes | ISO 8601 UTC | No | At or after invoice issue for ordinary disputes |

`disputes.invoice_id` intentionally has no SQLite FK constraint because the labeled orphan dispute must be exportable; the verifier detects this reference. Other dispute relationships and ordinary dispute chronology are audited.

### Status event — `status_events.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `event_id` | string | Yes | `EVT-2026-######` | Primary key | Nonempty, unique, format checked |
| `entity_type` | string enum | Yes | `account`, `quote`, `sales_order`, `shipment`, `invoice`, `payment`, `dispute` | No | Selects the entity table used to validate `entity_id` |
| `entity_id` | string | Yes | Corresponding entity ID | No | Polymorphic reference validated by the auditor |
| `from_status` | string | Yes | Entity-specific prior state | No | Must form a valid status transition except the labeled skip-state event |
| `to_status` | string | Yes | Entity-specific next state | No | Final event state must match the entity current-state column |
| `occurred_at` | UTC timestamp | Yes | ISO 8601 UTC | No | Events are retained and ordered chronologically per entity |

Supported transitions are: account `prospect -> active/on_hold`; quote `draft -> sent -> accepted/expired/rejected`; order `none -> booked -> in_fulfillment -> fulfilled -> closed`; shipment `packed -> shipped -> delivered`; invoice `draft -> open -> partial/paid/disputed` and `partial -> paid/disputed`; payment `received -> allocated`; dispute `none -> under_review`. The deliberately invalid order transition `booked -> closed` is labeled and independently detected. The normal event table contains every modeled transition; it is not sampled or capped.

### Ground truth — `ground_truth.csv`

| Field | Type | Required | Allowed values / units | Unique | Rule |
|---|---|---:|---|---|---|
| `truth_id` | string | Yes | `GT-####` | Primary key | Nonempty and unique |
| `anomaly_code` | string enum | Yes | Five required scenarios plus `underbilling`, `duplicate_invoice` | No | Labels injected scenario type |
| `severity` | string enum | Yes | `high`, `medium` | No | Scenario metadata |
| `anchor_table` | string | Yes | Table name | No | Identifies table containing primary anchor |
| `anchor_id` | string | Yes | ID from anchor table | No | Detector anchor is evaluated against this value |
| `related_ids` | string | Yes | One or more IDs, `|`-delimited | No | Contextual traceability; format depends on scenario |
| `notes` | string | Yes | Scenario description | No | May include the expected financial delta |
| `label_only` | string enum | Yes | `Y` | No | Kept outside operational entity tables |

Ground truth is used to evaluate detected IDs and classify the explicitly injected scenarios, not as an input feature for operational anomaly detection.

## Keys, relationships, and cardinality

| Relationship | Cardinality | Constraint and optionality |
|---|---|---|
| Account → Quote | 1:N | `quotes.account_id` FK; quote requires one account |
| Quote → QuoteLine | 1:N | `quote_lines.quote_id` FK; fixed dataset has one line per quote |
| Accepted Quote → SalesOrder | 1:0..1 in generated dataset | `sales_orders.quote_id` FK; generator creates orders only from accepted quotes and exactly one per accepted quote |
| Account → SalesOrder | 1:N | `sales_orders.account_id` FK and must agree with source quote |
| SalesOrder → OrderLine | 1:N | `order_lines.sales_order_id` FK; fixed dataset has one line per order |
| QuoteLine → OrderLine | 1:0..N | `order_lines.quote_line_id` FK to the source quote line |
| SalesOrder → Shipment | 1:0..N | `shipments.sales_order_id` FK; unshipped orders are permitted |
| SalesOrder → Invoice | 1:0..N | `invoices.sales_order_id` FK; invoices are shipment-backed; duplicate-invoice scenario is labeled |
| Shipment → Invoice | 1:0..N | `invoices.shipment_id` is nullable; populated when the invoice represents one shipment, blank when it combines multiple shipments |
| Invoice → InvoiceLine | 1:N | `invoice_lines.invoice_id` FK; generated data has one line per invoice |
| InvoiceLine → OrderLine / Shipment | N:1 | `order_line_id` is populated; nullable `shipment_id` is checked when present and blank for invoices combining multiple shipments |
| Payment ↔ Invoice | N:M | `payment_allocations` bridge has composite PK and FKs to payment and invoice |
| Account → Payment | 1:N | `payments.account_id` FK |
| Account → Dispute | 1:N | `disputes.account_id` FK |
| Invoice → Dispute | 1:0..N normally | `disputes.invoice_id` is intentionally not an FK; one labeled anomaly references no invoice |
| Entity → StatusEvent | 1:N | Polymorphic entity reference validated by auditor; no static SQL FK |

All declared CSV/JSONL/SQLite relationships are checked by the verification suite. SQLite enforces declared primary and foreign keys. The orphan-dispute reference and polymorphic event reference are audited in application code; the intentionally orphaned dispute is the sole expected entity-FK exception.

## Identifier and dataset conventions

Entity IDs use the prefix/year/sequence forms `ACC`, `QTE`, `QTL`, `SO`, `OTL`, `SHP`, `INV`, `ITL`, `PAY`, `DSP`, and `EVT`, followed by `-2026-` and a six-digit counter. Ground-truth IDs use `GT-0001` onward. Prefix counters are deterministic and IDs are stable for a given seed.

Default (`full`) fixed-seed record counts:

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

The seed is `20261022`, the calendar starts on `2025-11-03`, and receivable aging uses cutoff `2026-10-22T18:00:00Z`. The 15,000 challenge target is a minimum combined number of payment and status-event rows, not an exact status-event count. The current fixed-seed combined volume is 90,389.

The CLI accepts `--scale starter` or `--scale full`; `full` is the default and uses the table above. Starter configuration is 180 accounts, 1,000 quotes/quote lines, 700 orders/order lines, 800 invoices/invoice lines, 693 payments, 42 disputes, and a minimum combined 1,500 payment and status-event rows. Shipment and status-event counts are derived from the generated workflow. Both scales preserve the same seed (`20261022`), lifecycle rules, ID conventions, and seven labeled anomaly scenarios. The scale option selects configured targets; generation fails explicitly if the targets cannot be met from eligible records.

The generated single-line quote and order quantities cycle deterministically from 2 through 20 by quote sequence, with the unit price derived from the generated line total. Shipments record delivered quantity and amount. Split shipments and split invoices may represent one order; invoiced quantities are aggregated across all its invoice lines before comparison to delivered quantities. The injected invoice-over-fulfillment, underbilling, and duplicate-invoice scenarios intentionally create separately labeled quantity and monetary deltas.

## Implemented validation and known exceptions

`verification_report.csv` records observed counts and evidence for:

- Fixed-seed volumes, entity/line/allocation row counts, combined payment/event minimum, nonempty and unique primary keys, ID formats, and money formats.
- Declared foreign keys, polymorphic event references, account/order consistency, source quote-line quantity/price consistency, and invoice/shipment relationships.
- Allowed current-state values, allowed event transitions, complete state histories, event chain continuity, and timestamp chronology across modeled stages.
- Positive amounts and quantities, quote/order/invoice line extensions and header totals, invoice net + tax = total, simplified region tax, invoice balance bounds, allocation-to-invoice balance reconciliation, payment allocation plus unapplied reconciliation, duplicate allocation pairs, and over-allocation.
- Shipment quantities and their amounts versus order lines, shipment quantities versus ordered quantities, invoice quantities versus delivered quantities, invoice net amounts versus delivered fulfillment, and separate labeled quantity and monetary overbilling/underbilling/duplicate-invoice deltas.
- Aging bucket totals at the fixed cutoff and disputed balances.
- Independent detectors for all seven anomaly categories and a separate comparison of observed detector anchors to ground-truth anchors.

Intentional exceptions are the seven labeled scenarios. The required payment allocation intentionally exceeds the payment amount; the five other required scenarios affect invoice fulfillment, order closure, event transition, or dispute linkage. Additional labeled coverage cases create one underbilling delta and one duplicate invoice. The report passes only when observed findings match the labels and no unexpected mismatches are present. Ground-truth labels evaluate the injected deltas; the operational quantity and monetary detectors inspect entity and transaction tables independently.

SQLite uses text columns for every export field. `payment_allocations` uses a composite primary key. The anomaly dispute is not represented as a SQL FK, and the event entity pair is polymorphic rather than an SQL FK. The verifier checks those relationships independently.

The simulator currently models a single synthetic service-item line per quote, order, and invoice. Quantities are synthetic item counts, and each shipment records quantity and its USD-equivalent amount. Starter and full scales are available, but arbitrary target sizes are not. Tax is a simplified rule (0% for North American regions, otherwise 8%), and dispute lifecycle is limited to `under_review`; this is not a production accounting model.
