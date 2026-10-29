from copy import deepcopy
from datetime import timedelta

from o2c_sim.identity import PREFIX_EVENT, PREFIX_INVOICE, SequenceDesk
from o2c_sim.money import format_cents
from o2c_sim.settings import AS_OF_TS


ANOMALY_INVOICE_EXCEEDS_FULFILLMENT = "invoice_exceeds_fulfillment"
ANOMALY_PAYMENT_ALLOCATED_TWICE = "payment_allocated_twice"
ANOMALY_CLOSED_ORDER_UNPAID = "order_closed_with_unpaid_invoice"
ANOMALY_EVENT_SKIPS_STATE = "status_event_skips_state"
ANOMALY_DISPUTE_NOT_IN_AR = "dispute_not_in_receivables"
ANOMALY_UNDERBILLING = "underbilling"
ANOMALY_DUPLICATE_INVOICE = "duplicate_invoice"


def _iso(ts) -> str:
    return ts.astimezone(AS_OF_TS.tzinfo).strftime("%Y-%m-%dT%H:%M:%SZ")


class KnownFaultInjector:
    def __init__(self, desk: SequenceDesk) -> None:
        self.desk = desk

    def apply(self, records: dict[str, list[dict]]) -> list[dict]:
        ledger: list[dict] = []
        invoice_fault = self._invoice_beyond_shipped(
            records, records["invoice_lines"]
        )
        ledger.append(invoice_fault)
        ledger.append(self._double_allocate_payment(records))
        closed_order_fault = self._close_order_while_open_ar(
            records, {invoice_fault["related_ids"]}
        )
        ledger.append(closed_order_fault)
        underbilling_fault = self._underbill_invoice(
            records,
            {
                invoice_fault["related_ids"],
                closed_order_fault["anchor_id"],
            },
        )
        ledger.append(underbilling_fault)
        duplicate_fault = self._duplicate_invoice(
            records,
            {
                invoice_fault["related_ids"],
                closed_order_fault["anchor_id"],
                underbilling_fault["anchor_id"],
            },
        )
        ledger.append(duplicate_fault)
        ledger.append(
            self._skip_order_state(
                records,
                {
                    invoice_fault["related_ids"],
                    closed_order_fault["anchor_id"],
                    underbilling_fault["anchor_id"],
                    duplicate_fault["related_ids"],
                },
            )
        )
        ledger.append(self._dispute_outside_ar(records))
        records["status_events"].sort(
            key=lambda row: (
                row["occurred_at"],
                row["entity_type"],
                row["entity_id"],
                row["event_id"],
            )
        )
        return ledger

    def _invoice_beyond_shipped(
        self, records: dict[str, list[dict]], invoice_lines: list[dict]
    ) -> dict:
        invoices = records["invoices"]
        shipped_by_order: dict[str, int] = {}
        for shipment in records["shipments"]:
            shipped_by_order[shipment["sales_order_id"]] = (
                shipped_by_order.get(shipment["sales_order_id"], 0)
                + shipment["_fulfilled_cents"]
            )
        target = None
        invoices_per_order: dict[str, int] = {}
        for invoice in invoices:
            order_id = invoice["sales_order_id"]
            invoices_per_order[order_id] = invoices_per_order.get(order_id, 0) + 1
        for invoice in invoices:
            fulfilled = shipped_by_order.get(invoice["sales_order_id"], 0)
            if (
                fulfilled > 0
                and invoices_per_order[invoice["sales_order_id"]] == 1
                and invoice["_amount_cents"] <= fulfilled
                and invoice["invoice_status"] == "open"
                and invoice["_order_ref"]["order_status"] != "closed"
            ):
                target = invoice
                break
        if target is None:
            raise RuntimeError("no invoice available for fulfillment overrun")
        fulfilled = shipped_by_order[target["sales_order_id"]]
        quantity_increase = 1
        inflated = fulfilled + target["_unit_price_cents"] * quantity_increase
        old_total = target["_total_cents"]
        target["_amount_cents"] = inflated

        tax = 0 if target["_order_ref"]["_account"]["region"].startswith("NA") else int(round(inflated * 0.08))
        target["_tax_cents"] = tax
        target["_total_cents"] = inflated + tax
        target["_balance_cents"] += target["_total_cents"] - old_total

        target["invoice_amount"] = format_cents(target["_amount_cents"])
        target["tax_amount"] = format_cents(target["_tax_cents"])
        target["total_due"] = format_cents(target["_total_cents"])
        target["balance_due"] = format_cents(max(target["_balance_cents"], 0))

        old_status = target["invoice_status"]
        if 0 < target["_balance_cents"] < target["_total_cents"]:
            target["invoice_status"] = "partial"
        if old_status != target["invoice_status"]:
            self._append_event(
                records,
                "invoice",
                target["invoice_id"],
                old_status,
                target["invoice_status"],
                _iso(AS_OF_TS),
            )

        for line in invoice_lines:
            if line["invoice_id"] == target["invoice_id"]:
                line["quantity"] += quantity_increase
                line["line_amount"] = target["invoice_amount"]
                break
        return {
            "anomaly_code": ANOMALY_INVOICE_EXCEEDS_FULFILLMENT,
            "severity": "high",
            "anchor_table": "invoices",
            "anchor_id": target["invoice_id"],
            "related_ids": target["sales_order_id"],
            "notes": (
                "invoice quantity exceeds delivered fulfillment on the parent "
                f"sales order; delta_units={quantity_increase} "
                f"delta_cents={target['_unit_price_cents'] * quantity_increase}"
            ),
        }

    def _double_allocate_payment(self, records: dict[str, list[dict]]) -> dict:
        allocations = records["payment_allocations"]
        invoices = {row["invoice_id"]: row for row in records["invoices"]}
        source = None
        for alloc in allocations:
            invoice = invoices[alloc["invoice_id"]]
            if invoice["invoice_status"] == "paid" and alloc["_allocated_cents"] > 10_000:
                source = alloc
                break
        if source is None:
            raise RuntimeError("no paid allocation available for duplication")
        twin_invoice = next(
            (
                invoice
                for invoice in records["invoices"]
                if invoice["invoice_id"] != source["invoice_id"]
                and invoice["account_id"] == invoices[source["invoice_id"]]["account_id"]
            ),
            None,
        )
        if twin_invoice is None:
            raise RuntimeError(
                "no second invoice exists for the payment double-allocation fault"
            )
        duplicate = {
            "payment_id": source["payment_id"],
            "invoice_id": twin_invoice["invoice_id"],
            "allocated_amount": source["allocated_amount"],
            "allocated_at": source["allocated_at"],
            "_allocated_cents": source["_allocated_cents"],
        }
        allocations.append(duplicate)
        return {
            "anomaly_code": ANOMALY_PAYMENT_ALLOCATED_TWICE,
            "severity": "high",
            "anchor_table": "payment_allocations",
            "anchor_id": source["payment_id"],
            "related_ids": f"{source['invoice_id']}|{twin_invoice['invoice_id']}",
            "notes": "single payment_id is applied to two invoice lines for the full amount",
        }

    def _close_order_while_open_ar(
        self,
        records: dict[str, list[dict]],
        excluded_orders: set[str],
    ) -> dict:
        by_order = {row["sales_order_id"]: row for row in records["sales_orders"]}
        target_invoice = None
        for invoice in records["invoices"]:
            order = by_order[invoice["sales_order_id"]]
            if (
                invoice["sales_order_id"] not in excluded_orders
                and order["order_status"] == "fulfilled"
                and invoice["invoice_status"] in {"open", "partial", "disputed"}
                and invoice["_balance_cents"] > 0
            ):
                target_invoice = invoice
                break
        if target_invoice is None:
            raise RuntimeError("no open receivable found for closed-order fault")
        order = by_order[target_invoice["sales_order_id"]]
        closed = target_invoice["_issued_at"] + timedelta(days=4)
        if closed > AS_OF_TS:
            closed = AS_OF_TS
        previous_status = order["order_status"]
        order["order_status"] = "closed"
        order["closed_at"] = _iso(closed)
        order["_closed_at"] = closed
        self._append_event(
            records,
            "sales_order",
            order["sales_order_id"],
            previous_status,
            "closed",
            _iso(closed),
        )
        return {
            "anomaly_code": ANOMALY_CLOSED_ORDER_UNPAID,
            "severity": "medium",
            "anchor_table": "sales_orders",
            "anchor_id": order["sales_order_id"],
            "related_ids": target_invoice["invoice_id"],
            "notes": "sales order marked closed while related invoice still carries an unpaid balance",
        }

    def _skip_order_state(
        self, records: dict[str, list[dict]], excluded_orders: set[str]
    ) -> dict:
        event = next(
            (
                row
                for row in records["status_events"]
                if row["entity_type"] == "sales_order"
                and row["entity_id"] not in excluded_orders
                and row["to_status"] == "closed"
            ),
            None,
        )
        if event is None:
            raise RuntimeError(
                "no independent closed sales order is available for the skipped-state fault"
            )
        event_id = self._append_event(
            records,
            "sales_order",
            event["entity_id"],
            "booked",
            "closed",
            _iso(AS_OF_TS),
        )
        return {
            "anomaly_code": ANOMALY_EVENT_SKIPS_STATE,
            "severity": "medium",
            "anchor_table": "status_events",
            "anchor_id": event_id,
            "related_ids": event["entity_id"],
            "notes": "status event jumps booked -> closed and omits in_fulfillment/fulfilled",
        }

    def _underbill_invoice(
        self, records: dict[str, list[dict]], excluded_orders: set[str]
    ) -> dict:
        candidate = next(
            (
                invoice
                for invoice in records["invoices"]
                if invoice["invoice_status"] == "open"
                and invoice["sales_order_id"] not in excluded_orders
                and invoice["_quantity"] > 1
            ),
            None,
        )
        if candidate is None:
            raise RuntimeError("no independent open invoice is available for underbilling")

        old_amount = candidate["_amount_cents"]
        quantity_reduction = 1
        reduction = candidate["_unit_price_cents"] * quantity_reduction
        new_amount = old_amount - reduction
        candidate["_quantity"] -= quantity_reduction
        tax = (
            0
            if candidate["_order_ref"]["_account"]["region"].startswith("NA")
            else int(round(new_amount * 0.08))
        )
        total = new_amount + tax
        candidate["_amount_cents"] = new_amount
        candidate["_tax_cents"] = tax
        candidate["_total_cents"] = total
        candidate["_balance_cents"] = total
        candidate["invoice_amount"] = format_cents(new_amount)
        candidate["tax_amount"] = format_cents(tax)
        candidate["total_due"] = format_cents(total)
        candidate["balance_due"] = format_cents(total)
        for line in records["invoice_lines"]:
            if line["invoice_id"] == candidate["invoice_id"]:
                line["quantity"] -= quantity_reduction
                line["line_amount"] = candidate["invoice_amount"]
                break

        return {
            "anomaly_code": ANOMALY_UNDERBILLING,
            "severity": "medium",
            "anchor_table": "sales_orders",
            "anchor_id": candidate["sales_order_id"],
            "related_ids": candidate["invoice_id"],
            "notes": (
                f"invoice was reduced by {format_cents(reduction)} below delivered "
                f"fulfillment; delta_units={quantity_reduction} "
                f"delta_cents={reduction}"
            ),
        }

    def _duplicate_invoice(
        self, records: dict[str, list[dict]], excluded_orders: set[str]
    ) -> dict:
        source = next(
            (
                invoice
                for invoice in records["invoices"]
                if invoice["invoice_status"] == "open"
                and invoice["sales_order_id"] not in excluded_orders
            ),
            None,
        )
        if source is None:
            raise RuntimeError(
                "no independent open invoice is available for duplicate-invoice injection"
            )

        duplicate = deepcopy(source)
        duplicate_id = self.desk.next_id(PREFIX_INVOICE)
        duplicate["invoice_id"] = duplicate_id
        records["invoices"].append(duplicate)

        source_line = next(
            (
                line
                for line in records["invoice_lines"]
                if line["invoice_id"] == source["invoice_id"]
            ),
            None,
        )
        if source_line is None:
            raise RuntimeError(
                f"source invoice has no line item: invoice_id={source['invoice_id']}"
            )
        duplicate_line = deepcopy(source_line)
        duplicate_line["invoice_line_id"] = f"ITL-2026-{len(records['invoice_lines']) + 1:06d}"
        duplicate_line["invoice_id"] = duplicate_id
        records["invoice_lines"].append(duplicate_line)
        self._append_event(
            records,
            "invoice",
            duplicate_id,
            "draft",
            "open",
            source["issued_at"],
        )

        return {
            "anomaly_code": ANOMALY_DUPLICATE_INVOICE,
            "severity": "high",
            "anchor_table": "invoices",
            "anchor_id": duplicate_id,
            "related_ids": source["invoice_id"],
            "notes": "duplicate invoice record repeats the same source, shipment, amount, and issue terms",
        }

    def _append_event(
        self,
        records: dict[str, list[dict]],
        entity_type: str,
        entity_id: str,
        from_status: str,
        to_status: str,
        occurred_at: str,
    ) -> str:
        event_id = self.desk.next_id(PREFIX_EVENT)
        records["status_events"].append(
            {
                "event_id": event_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "from_status": from_status,
                "to_status": to_status,
                "occurred_at": occurred_at,
            }
        )
        return event_id

    def _dispute_outside_ar(self, records: dict[str, list[dict]]) -> dict:
        paid = next(inv for inv in records["invoices"] if inv["invoice_status"] == "paid")
        phantom = self.desk.next_id("INV")
        dispute = records["disputes"][-1]
        original = dispute["invoice_id"]
        dispute["invoice_id"] = phantom
        dispute["account_id"] = paid["account_id"]
        return {
            "anomaly_code": ANOMALY_DISPUTE_NOT_IN_AR,
            "severity": "high",
            "anchor_table": "disputes",
            "anchor_id": dispute["dispute_id"],
            "related_ids": f"{phantom}|was:{original}|paid:{paid['invoice_id']}",
            "notes": "dispute points at an invoice identifier that is absent from open receivables",
        }


def ground_truth_frame(rows: list[dict]) -> list[dict]:
    labeled = []
    for idx, row in enumerate(rows, start=1):
        labeled.append(
            {
                "truth_id": f"GT-{idx:04d}",
                "anomaly_code": row["anomaly_code"],
                "severity": row["severity"],
                "anchor_table": row["anchor_table"],
                "anchor_id": row["anchor_id"],
                "related_ids": row["related_ids"],
                "notes": row["notes"],
                "label_only": "Y",
            }
        )
    return labeled
