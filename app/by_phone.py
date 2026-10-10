"""Belarus client numbers: +375, a 2-digit operator code, and 7 digits."""

from __future__ import annotations

_OPERATOR = 2
_LOCAL = 7
_NATIONAL = _OPERATOR + _LOCAL


def join_by_phone(operator: str, local: str) -> str | None:
    """Return +375XXXXXXXXX or None when the parts are not 2 and 7 digits."""
    op = _digits(operator)
    number = _digits(local)
    if len(op) != _OPERATOR or len(number) != _LOCAL:
        return None
    return f"+375{op}{number}"


def split_by_phone(value: str) -> tuple[str, str]:
    """Split a stored number into operator code and 7 digits, or two empty strings."""
    digits = _digits(value)
    if digits.startswith("375") and len(digits) == 3 + _NATIONAL:
        rest = digits[3:]
        return rest[:_OPERATOR], rest[_OPERATOR:]
    if len(digits) == _NATIONAL:
        return digits[:_OPERATOR], digits[_OPERATOR:]
    return "", ""


def normalize_by_phone(value: str) -> str | None:
    operator, local = split_by_phone(value)
    if not operator:
        return None
    return join_by_phone(operator, local)


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())
