from datetime import datetime, timedelta

import pandas as pd

from o2c_sim.entropy import StreamedEntropy
from o2c_sim.identity import (
    PREFIX_ACCOUNT,
    PREFIX_DISPUTE,
    PREFIX_EVENT,
    PREFIX_INVOICE,
    PREFIX_PAYMENT,
    PREFIX_QUOTE,
    PREFIX_SALES_ORDER,
    PREFIX_SHIPMENT,
    SequenceDesk,
)
from o2c_sim.money import format_cents
from o2c_sim.settings import (
    AS_OF_TS,
    CALENDAR,
    CURRENCY,
    DISPUTE_REASONS,
    INDUSTRIES,
    QUOTE_REASONS,
    REGIONS,
    VOLUME_PLAN,
)


def _iso(ts: datetime) -> str:
    return ts.astimezone(AS_OF_TS.tzinfo).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip_later(entropy: StreamedEntropy, origin: datetime, min_hours: int, max_hours: int) -> datetime:
    return entropy.later_than(origin, min_hours, max_hours, AS_OF_TS)

class CausalCycleAssembler:
    def __init__(self, entropy: StreamedEntropy, desk: SequenceDesk) -> None:
        self.entropy = entropy
        self.desk = desk

    def assemble_initial_records(self) -> dict[str, list[dict]]:
        accounts = self._build_accounts()
        quotes = self._build_quotes(accounts)

        quote_lines = []
        quote_line_by_quote = {}

        for index, quote in enumerate(quotes, start=1):
            quote_line_id = f"QTL-2026-{index:06d}"
            quote_line_by_quote[quote["quote_id"]] = quote_line_id

            quote_lines.append({
                "quote_line_id": quote_line_id,
                "quote_id": quote["quote_id"],
                "line_number": 1,
                "description": "Synthetic service item",
                "quantity": 1,
                "unit_price": quote["quoted_amount"],
                "line_amount": quote["quoted_amount"],
                "currency": quote["currency"],
            })

        sales_orders = self._build_sales_orders(quotes)

        order_lines = []
        order_line_by_order = {}

        for index, order in enumerate(sales_orders, start=1):
            order_line_id = f"OTL-2026-{index:06d}"
            order_line_by_order[order["sales_order_id"]] = order_line_id

            quote_line_id = quote_line_by_quote.get(order["quote_id"], "")

            order_lines.append({
                "order_line_id": order_line_id,
                "sales_order_id": order["sales_order_id"],
                "quote_line_id": quote_line_id,
                "line_number": 1,
                "description": "Synthetic service item",
                "quantity": 1,
                "unit_price": order["order_amount"],
                "line_amount": order["order_amount"],
                "currency": order["currency"],
            })

        shipments = self._build_shipments(sales_orders)
        invoices = self._build_invoices(sales_orders, shipments)

        invoice_lines = []

        for index, invoice in enumerate(invoices, start=1):
            invoice_lines.append({
                "invoice_line_id": f"ITL-2026-{index:06d}",
                "invoice_id": invoice["invoice_id"],
                "sales_order_id": invoice["sales_order_id"],
                "order_line_id": order_line_by_order.get(
                    invoice["sales_order_id"], ""
                ),
                "shipment_id": invoice.get("shipment_id", ""),
                "line_number": 1,
                "description": "Synthetic service item",
                "quantity": 1,
                "line_amount": invoice["invoice_amount"],
                "currency": invoice["currency"],
            })

        payments, allocations = self._build_settlements(invoices)
        self._close_settled_orders(sales_orders, invoices, payments, allocations)
        disputes = self._build_disputes(invoices)

        status_events = self._compose_timeline(
            accounts,
            quotes,
            sales_orders,
            shipments,
            invoices,
            payments,
            disputes,
        )

        return {
            "accounts": accounts,
            "quotes": quotes,
            "quote_lines": quote_lines,
            "sales_orders": sales_orders,
            "order_lines": order_lines,
            "shipments": shipments,
            "invoices": invoices,
            "invoice_lines": invoice_lines,
            "payments": payments,
            "payment_allocations": allocations,
            "disputes": disputes,
            "status_events": status_events,
        }

    def _build_accounts(self) -> list[dict]:
        rows: list[dict] = []
        for _ in range(VOLUME_PLAN.accounts):
            opened = self.entropy.stamp_between(CALENDAR.open_on, CALENDAR.open_on.replace(year=2026, month=2, day=28))
            industry = self.entropy.pick(INDUSTRIES)
            region = self.entropy.pick(REGIONS)
            account_id = self.desk.next_id(PREFIX_ACCOUNT)
            ordinal = int(account_id[-6:])
            rows.append(
                {
                    "account_id": account_id,
                    "legal_name": f"{region} {industry.replace('_', ' ')} {ordinal:04d}",
                    "industry": industry,
                    "region": region,
                    "currency": CURRENCY,
                    "credit_limit": format_cents(self.entropy.cents(75_000_00, 4_250_000_00)),
                    "account_status": "active" if self.entropy.chance(0.97) else "on_hold",
                    "opened_at": _iso(opened),
                    "_opened_at": opened,
                }
            )
        return rows

    def _build_quotes(self, accounts: list[dict]) -> list[dict]:
        rows: list[dict] = []
        accepted_budget = VOLUME_PLAN.sales_orders
        for idx in range(VOLUME_PLAN.quotes):
            account = accounts[int(self.entropy.integers(0, len(accounts)))]
            issued = _clip_later(
                self.entropy,
                account["_opened_at"] + timedelta(days=1),
                12,
                24 * 40,
            )
            amount = self.entropy.cents(18_500_00, 620_000_00)
            expires = issued + timedelta(days=int(self.entropy.integers(14, 46)))
            will_accept = idx < accepted_budget
            if will_accept:
                status = "accepted"
                decided = _clip_later(self.entropy, issued, 6, 24 * 12)
            elif self.entropy.chance(0.55):
                status = "expired"
                decided = expires if expires <= AS_OF_TS else _clip_later(self.entropy, issued, 24, 24 * 20)
            else:
                status = "rejected"
                decided = _clip_later(self.entropy, issued, 8, 24 * 10)
            rows.append(
                {
                    "quote_id": self.desk.next_id(PREFIX_QUOTE),
                    "account_id": account["account_id"],
                    "motion": self.entropy.pick(QUOTE_REASONS),
                    "quoted_amount": format_cents(amount),
                    "currency": CURRENCY,
                    "quote_status": status,
                    "issued_at": _iso(issued),
                    "expires_at": _iso(expires),
                    "decided_at": _iso(decided),
                    "_amount_cents": amount,
                    "_issued_at": issued,
                    "_decided_at": decided,
                    "_account": account,
                }
            )
        return rows

    def _build_sales_orders(self, quotes: list[dict]) -> list[dict]:
        accepted = [q for q in quotes if q["quote_status"] == "accepted"]
        if len(accepted) != VOLUME_PLAN.sales_orders:
            raise RuntimeError("accepted quote count must equal sales order target")
        rows: list[dict] = []
        for quote in accepted:
            booked = _clip_later(self.entropy, quote["_decided_at"], 1, 72)
            rows.append(
                {
                    "sales_order_id": self.desk.next_id(PREFIX_SALES_ORDER),
                    "quote_id": quote["quote_id"],
                    "account_id": quote["account_id"],
                    "order_amount": quote["quoted_amount"],
                    "currency": CURRENCY,
                    "order_status": "booked",
                    "booked_at": _iso(booked),
                    "closed_at": "",
                    "_amount_cents": quote["_amount_cents"],
                    "_booked_at": booked,
                    "_account": quote["_account"],
                    "_fulfilled_cents": 0,
                }
            )
        return rows

    def _build_shipments(self, sales_orders: list[dict]) -> list[dict]:
        rows: list[dict] = []
        for order in sales_orders:
            if self.entropy.chance(0.035):
                continue
            legs = 2 if self.entropy.chance(0.08) else 1
            remaining = order["_amount_cents"]
            cursor = order["_booked_at"]
            for leg in range(legs):
                if leg == legs - 1:
                    fulfilled = remaining
                else:
                    fulfilled = int(remaining * (0.42 + 0.2 * self.entropy.unit()))
                    remaining -= fulfilled
                packed = _clip_later(self.entropy, cursor, 4, 96)
                shipped = _clip_later(self.entropy, packed, 2, 48)
                delivered = _clip_later(self.entropy, shipped, 12, 160)
                cursor = delivered
                order["_fulfilled_cents"] += fulfilled
                rows.append(
                    {
                        "shipment_id": self.desk.next_id(PREFIX_SHIPMENT),
                        "sales_order_id": order["sales_order_id"],
                        "account_id": order["account_id"],
                        "fulfilled_amount": format_cents(fulfilled),
                        "shipment_status": "delivered",
                        "packed_at": _iso(packed),
                        "shipped_at": _iso(shipped),
                        "delivered_at": _iso(delivered),
                        "_fulfilled_cents": fulfilled,
                        "_delivered_at": delivered,
                    }
                )
            if order["_fulfilled_cents"] >= order["_amount_cents"]:
                order["order_status"] = "fulfilled"
            else:
                order["order_status"] = "in_fulfillment"
        still_open = [o for o in sales_orders if o["order_status"] == "booked"]
        for order in still_open:
            order["_fulfilled_cents"] = 0
        return rows

    def _build_invoices(self, sales_orders: list[dict], shipments: list[dict]) -> list[dict]:
        by_order: dict[str, list[dict]] = {}
        for shipment in shipments:
            by_order.setdefault(shipment["sales_order_id"], []).append(shipment)

        billed: list[dict] = []
        shipped_order_ids = [sid for sid in by_order.keys()]
        split_count = VOLUME_PLAN.invoices - len(shipped_order_ids)
        if split_count < 0 or split_count > len(shipped_order_ids):
            raise RuntimeError(
                "invoice target cannot be met with at most two invoices per "
                f"shipped order: target={VOLUME_PLAN.invoices} "
                f"shipped_orders={len(shipped_order_ids)}"
            )
        split_ids = set(shipped_order_ids[:split_count])

        for order in sales_orders:
            legs = by_order.get(order["sales_order_id"], [])
            if not legs:
                continue

            if order["sales_order_id"] in split_ids:
                first = int(order["_fulfilled_cents"] * 0.45)
                second = order["_fulfilled_cents"] - first
                t1 = _clip_later(self.entropy, legs[0]["_delivered_at"], 2, 48)
                billed.append(self._invoice_row(order, legs[0], first, t1, "open"))
                t2 = _clip_later(self.entropy, legs[-1]["_delivered_at"], 6, 72)
                billed.append(self._invoice_row(order, legs[-1], second, t2, "open"))
            else:
                amount = order["_fulfilled_cents"]
                issued = _clip_later(self.entropy, legs[-1]["_delivered_at"], 2, 60)
                billed.append(self._invoice_row(order, legs[-1], amount, issued, "open"))

        if len(billed) != VOLUME_PLAN.invoices:
            raise RuntimeError(
                "invoice assembly did not meet volume target: "
                f"expected={VOLUME_PLAN.invoices} actual={len(billed)}"
            )
        return billed

    def _invoice_row(self, order: dict, shipment: dict | None, amount: int, issued: datetime, status: str) -> dict:
        tax = 0 if order["_account"]["region"].startswith("NA") else int(round(amount * 0.08))
        total = amount + tax
        due = issued + timedelta(days=30)
        return {
            "invoice_id": self.desk.next_id(PREFIX_INVOICE),
            "sales_order_id": order["sales_order_id"],
            "shipment_id": shipment["shipment_id"] if shipment else "",
            "account_id": order["account_id"],
            "invoice_amount": format_cents(amount),
            "tax_amount": format_cents(tax),
            "total_due": format_cents(total),
            "balance_due": format_cents(total),
            "currency": CURRENCY,
            "invoice_status": status,
            "issued_at": _iso(issued),
            "due_at": _iso(due),
            "_amount_cents": amount,
            "_tax_cents": tax,
            "_total_cents": total,
            "_balance_cents": total,
            "_issued_at": issued,
            "_order_ref": order,
        }

    def _build_settlements(self, invoices: list[dict]) -> tuple[list[dict], list[dict]]:
        payments: list[dict] = []
        allocations: list[dict] = []
        eligible = []
        for invoice in invoices:
            if invoice["_order_ref"]["order_status"] == "booked" and self.entropy.chance(0.7):
                continue
            if self.entropy.chance(0.11):
                continue
            eligible.append(invoice)

        if len(eligible) < VOLUME_PLAN.payments:
            raise RuntimeError(
                "insufficient eligible invoices for payment target: "
                f"expected={VOLUME_PLAN.payments} eligible={len(eligible)}"
            )
        excess = len(eligible) - VOLUME_PLAN.payments
        skipped = set()
        while len(skipped) < excess:
            skipped.add(int(self.entropy.integers(0, len(eligible))))

        for index, invoice in enumerate(eligible):
            if index in skipped:
                continue
            posted = _clip_later(self.entropy, invoice["_issued_at"], 24, 24 * 28)
            if self.entropy.chance(0.16):
                paid = int(invoice["_total_cents"] * (0.35 + 0.4 * self.entropy.unit()))
                invoice["invoice_status"] = "partial"
            else:
                paid = invoice["_total_cents"]
                invoice["invoice_status"] = "paid"
            invoice["_balance_cents"] -= paid
            invoice["balance_due"] = format_cents(max(invoice["_balance_cents"], 0))
            payment_id = self.desk.next_id(PREFIX_PAYMENT)
            payments.append(
                {
                    "payment_id": payment_id,
                    "account_id": invoice["account_id"],
                    "instrument": self.entropy.pick(("ach", "wire", "card")),
                    "payment_amount": format_cents(paid),
                    "unapplied_amount": format_cents(0),
                    "payment_status": "allocated",
                    "posted_at": _iso(posted),
                    "_amount_cents": paid,
                    "_posted_at": posted,
                }
            )
            allocations.append(
                {
                    "payment_id": payment_id,
                    "invoice_id": invoice["invoice_id"],
                    "allocated_amount": format_cents(paid),
                    "allocated_at": _iso(posted),
                    "_allocated_cents": paid,
                }
            )
        return payments, allocations

    def _close_settled_orders(
        self,
        sales_orders: list[dict],
        invoices: list[dict],
        payments: list[dict],
        allocations: list[dict],
    ) -> None:
        invoices_by_order: dict[str, list[dict]] = {}
        for invoice in invoices:
            invoices_by_order.setdefault(invoice["sales_order_id"], []).append(invoice)

        payment_times = {
            payment["payment_id"]: payment["_posted_at"]
            for payment in payments
        }
        settlement_times: dict[str, list[datetime]] = {}
        for allocation in allocations:
            settlement_times.setdefault(allocation["invoice_id"], []).append(
                payment_times[allocation["payment_id"]]
            )

        for order in sales_orders:
            if order["order_status"] != "fulfilled":
                continue
            order_invoices = invoices_by_order.get(order["sales_order_id"], [])
            if not order_invoices or any(
                invoice["_balance_cents"] > 0 for invoice in order_invoices
            ):
                continue
            if not self.entropy.chance(0.82):
                continue

            last_payment = max(
                (
                    posted
                    for invoice in order_invoices
                    for posted in settlement_times.get(invoice["invoice_id"], [])
                ),
                default=order["_booked_at"],
            )
            close_origin = max(
                last_payment,
                order["_booked_at"] + timedelta(days=3),
            )
            closed = _clip_later(self.entropy, close_origin, 24, 24 * 25)
            order["order_status"] = "closed"
            order["closed_at"] = _iso(closed)
            order["_closed_at"] = closed

    def _build_disputes(self, invoices: list[dict]) -> list[dict]:
        candidates = [inv for inv in invoices if inv["invoice_status"] in {"open", "partial"}]
        if len(candidates) < VOLUME_PLAN.disputes:
            raise RuntimeError(
                "insufficient eligible invoices for dispute target: "
                f"expected={VOLUME_PLAN.disputes} eligible={len(candidates)}"
            )
        rows: list[dict] = []
        for invoice in candidates[:VOLUME_PLAN.disputes]:
            opened = _clip_later(self.entropy, invoice["_issued_at"], 12, 24 * 18)
            claimed = min(invoice["_balance_cents"], max(5_000, int(invoice["_total_cents"] * 0.2)))
            invoice["invoice_status"] = "disputed"
            rows.append(
                {
                    "dispute_id": self.desk.next_id(PREFIX_DISPUTE),
                    "invoice_id": invoice["invoice_id"],
                    "account_id": invoice["account_id"],
                    "dispute_amount": format_cents(claimed),
                    "reason_code": self.entropy.pick(DISPUTE_REASONS),
                    "dispute_status": "under_review",
                    "opened_at": _iso(opened),
                    "_opened_at": opened,
                }
            )
        return rows

    def _compose_timeline(
        self,
        accounts: list[dict],
        quotes: list[dict],
        sales_orders: list[dict],
        shipments: list[dict],
        invoices: list[dict],
        payments: list[dict],
        disputes: list[dict],
    ) -> list[dict]:
        sketches: list[tuple[datetime, str, str, str, str]] = []

        def add(ts: datetime, entity_type: str, entity_id: str, prior: str, current: str) -> None:
            sketches.append((ts, entity_type, entity_id, prior, current))

        for account in accounts[:1200]:
            add(account["_opened_at"], "account", account["account_id"], "prospect", "active")

        for quote in quotes:
            add(quote["_issued_at"], "quote", quote["quote_id"], "draft", "sent")
            add(quote["_decided_at"], "quote", quote["quote_id"], "sent", quote["quote_status"])

        for order in sales_orders:
            add(order["_booked_at"], "sales_order", order["sales_order_id"], "none", "booked")
            if order["order_status"] in {"in_fulfillment", "fulfilled", "closed"}:
                add(
                    order["_booked_at"] + timedelta(hours=6),
                    "sales_order",
                    order["sales_order_id"],
                    "booked",
                    "in_fulfillment",
                )
            if order["order_status"] in {"fulfilled", "closed"}:
                add(
                    order["_booked_at"] + timedelta(days=2),
                    "sales_order",
                    order["sales_order_id"],
                    "in_fulfillment",
                    "fulfilled",
                )
            if order["order_status"] == "closed" and order.get("_closed_at"):
                add(order["_closed_at"], "sales_order", order["sales_order_id"], "fulfilled", "closed")

        for shipment in shipments:
            add(shipment["_delivered_at"], "shipment", shipment["shipment_id"], "shipped", "delivered")

        for invoice in invoices:
            add(invoice["_issued_at"], "invoice", invoice["invoice_id"], "draft", invoice["invoice_status"])

        for payment in payments:
            add(payment["_posted_at"], "payment", payment["payment_id"], "received", payment["payment_status"])

        for dispute in disputes:
            add(dispute["_opened_at"], "dispute", dispute["dispute_id"], "none", dispute["dispute_status"])

        sketches.sort(key=lambda row: (row[0], row[1], row[2], row[4]))
        quotas = {
            "account": 800,
            "quote": 7_000,
            "sales_order": 3_500,
            "shipment": 1_500,
            "invoice": 1_400,
            "payment": 600,
            "dispute": 200,
        }
        if sum(quotas.values()) != VOLUME_PLAN.timeline_events:
            raise RuntimeError("event quotas must sum to the timeline target")
        chosen: list[tuple[datetime, str, str, str, str]] = []
        leftover: list[tuple[datetime, str, str, str, str]] = []
        used = {key: 0 for key in quotas}
        for sketch in sketches:
            kind = sketch[1]
            if used.get(kind, 0) < quotas.get(kind, 0):
                chosen.append(sketch)
                used[kind] += 1
            else:
                leftover.append(sketch)
        if len(chosen) < VOLUME_PLAN.timeline_events:
            need = VOLUME_PLAN.timeline_events - len(chosen)
            if len(leftover) < need:
                raise RuntimeError("timeline pool is smaller than the required event volume")
            chosen.extend(leftover[:need])
        chosen.sort(key=lambda row: (row[0], row[1], row[2], row[4]))
        events = []
        for ts, entity_type, entity_id, prior, current in chosen:
            events.append(
                {
                    "event_id": self.desk.next_id(PREFIX_EVENT),
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "from_status": prior,
                    "to_status": current,
                    "occurred_at": _iso(ts),
                }
            )
        return events


def strip_private_fields(rows: list[dict]) -> pd.DataFrame:
    cleaned = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]
    return pd.DataFrame(cleaned)
