from o2c_sim.settings import FISCAL_YEAR


PREFIX_ACCOUNT = "ACC"
PREFIX_QUOTE = "QTE"
PREFIX_SALES_ORDER = "SO"
PREFIX_SHIPMENT = "SHP"
PREFIX_INVOICE = "INV"
PREFIX_PAYMENT = "PAY"
PREFIX_DISPUTE = "DSP"
PREFIX_EVENT = "EVT"


def mint_document_id(prefix: str, ordinal: int, fiscal_year: int = FISCAL_YEAR) -> str:
    if ordinal < 1:
        raise ValueError("document ordinals start at 1")
    return f"{prefix}-{fiscal_year}-{ordinal:06d}"


class SequenceDesk:
    def __init__(self) -> None:
        self._cursors: dict[str, int] = {}

    def next_id(self, prefix: str) -> str:
        ordinal = self._cursors.get(prefix, 0) + 1
        self._cursors[prefix] = ordinal
        return mint_document_id(prefix, ordinal)

    def peek(self, prefix: str) -> int:
        return self._cursors.get(prefix, 0)
