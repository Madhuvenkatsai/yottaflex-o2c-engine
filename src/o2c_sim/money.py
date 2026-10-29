def format_cents(amount_cents: int) -> str:
    sign = "-" if amount_cents < 0 else ""
    value = abs(amount_cents)
    return f"{sign}{value // 100}.{value % 100:02d}"


def cents_from_text(text: str) -> int:
    negative = text.startswith("-")
    raw = text[1:] if negative else text
    dollars, _, pennies = raw.partition(".")
    total = int(dollars) * 100 + int((pennies + "00")[:2])
    return -total if negative else total
