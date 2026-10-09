"""Normalize spoken Russian numerals (1–31) to digits in due-date phrases."""

from __future__ import annotations

import re

_CARDINAL_1_9: dict[str, int] = {
    "один": 1,
    "одна": 1,
    "одну": 1,
    "одно": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
}

_TEEN_CARD: dict[str, int] = {
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
}

_TENS_CARD: dict[str, int] = {
    "двадцать": 20,
    "тридцать": 30,
}

_UNIT_WORDS = ("один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")

# Ordinal stems for 1–9 (used to build forms)
_ORD_STEM: dict[int, tuple[str, str, str]] = {
    1: ("перв", "перв", "перв"),
    2: ("втор", "втор", "втор"),
    3: ("трет", "трет", "трет"),
    4: ("четверт", "четверт", "четверт"),
    5: ("пят", "пят", "пят"),
    6: ("шест", "шест", "шест"),
    7: ("седьм", "седьм", "седьм"),
    8: ("восьм", "восьм", "восьм"),
    9: ("девят", "девят", "девят"),
}


def _ordinal_forms(n: int) -> list[str]:
    if n == 10:
        return [
            "десятый",
            "десятого",
            "десятому",
            "десятое",
            "десятой",
            "десятую",
            "10-й",
            "10-го",
            "10-му",
            "10-ое",
        ]
    if 11 <= n <= 19:
        teens = {
            11: "одиннадцат",
            12: "двенадцат",
            13: "тринадцат",
            14: "четырнадцат",
            15: "пятнадцат",
            16: "шестнадцат",
            17: "семнадцат",
            18: "восемнадцат",
            19: "девятнадцат",
        }
        stem = teens[n]
        return [
            f"{stem}ый",
            f"{stem}ого",
            f"{stem}ому",
            f"{stem}ое",
            f"{n}-й",
            f"{n}-го",
            f"{n}-му",
        ]
    if n == 20:
        return [
            "двадцатый",
            "двадцатого",
            "двадцатому",
            "двадцатое",
            "20-й",
            "20-го",
            "20-му",
        ]
    if n == 30:
        return [
            "тридцатый",
            "тридцатого",
            "тридцатому",
            "30-й",
            "30-го",
            "30-му",
        ]
    if 21 <= n <= 29:
        unit = n - 20
        ustem = _ORD_STEM[unit][0]
        return [
            f"двадцать {ustem}ый",
            f"двадцать {ustem}ого",
            f"двадцать {ustem}ому",
            f"двадцать {ustem}ое",
            f"{n}-й",
            f"{n}-го",
            f"{n}-му",
        ]
    if n == 31:
        return [
            "тридцать первый",
            "тридцать первого",
            "тридцать первому",
            "31-й",
            "31-го",
            "31-му",
        ]
    if 1 <= n <= 9:
        s = _ORD_STEM[n][0]
        return [
            f"{s}ый",
            f"{s}ой",
            f"{s}ое",
            f"{s}ая",
            f"{s}ого",
            f"{s}ому",
            f"{s}ую",
            f"{n}-й",
            f"{n}-го",
            f"{n}-му",
        ]
    return []


def _cardinal_forms(n: int) -> list[str]:
    if n in _TEEN_CARD.values():
        for w, v in _TEEN_CARD.items():
            if v == n:
                return [w]
    if n <= 9:
        return [w for w, v in _CARDINAL_1_9.items() if v == n]
    if n == 20:
        return ["двадцать"]
    if n == 30:
        return ["тридцать"]
    if 21 <= n <= 29:
        u = n - 20
        unit_words = [w for w, v in _CARDINAL_1_9.items() if v == u and w in _UNIT_WORDS]
        uword = unit_words[0] if unit_words else str(u)
        return [f"двадцать {uword}"]
    if n == 31:
        return ["тридцать один"]
    return []


def _build_replacement_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for w, v in _CARDINAL_1_9.items():
        mapping[w] = str(v)
    for w, v in _TEEN_CARD.items():
        mapping[w] = str(v)
    for w, v in _TENS_CARD.items():
        mapping[w] = str(v)
    for n in range(1, 32):
        num = str(n)
        for phrase in _cardinal_forms(n):
            mapping[phrase] = num
        for phrase in _ordinal_forms(n):
            mapping[phrase.lower()] = num
    return mapping


_REPLACEMENTS = _build_replacement_map()

_HYPHEN_ORD = re.compile(
    r"\b(\d{1,2})\s*-\s*(?:й|го|му|ем|ом|ая|ое|ую|ым|ей|ii|iii)\b",
    re.IGNORECASE,
)


def normalize_spoken_numerals(text: str) -> str:
    """Replace spoken/cardinal/ordinal numerals (1–31) with digits."""
    t = text.lower().replace("ё", "е")
    t = _HYPHEN_ORD.sub(r"\1", t)
    for word, num in sorted(_REPLACEMENTS.items(), key=lambda x: -len(x[0])):
        t = re.sub(rf"\b{re.escape(word)}\b", num, t)
    return re.sub(r"\s+", " ", t).strip()
