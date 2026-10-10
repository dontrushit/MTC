"""Turn operator and client numbers into one comparable form."""


def normalize_phone(value: str | None) -> str:
    """Return +7XXXXXXXXXX for a Russian number, or digits for a short extension."""
    if value is None:
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return ""
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    return digits
