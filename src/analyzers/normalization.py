"""Small normalization helpers for multilingual listing facts."""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Iterable, List, Optional


MONTHS = {
    "january": 1, "gennaio": 1, "february": 2, "febbraio": 2,
    "march": 3, "marzo": 3, "april": 4, "aprile": 4,
    "may": 5, "maggio": 5, "june": 6, "giugno": 6,
    "july": 7, "luglio": 7, "august": 8, "agosto": 8,
    "september": 9, "settembre": 9, "october": 10, "ottobre": 10,
    "november": 11, "novembre": 11, "december": 12, "dicembre": 12,
}
NUMBER_WORDS = {
    "un": 1, "uno": 1, "una": 1, "one": 1,
    "due": 2, "two": 2, "tre": 3, "three": 3,
    "quattro": 4, "four": 4, "cinque": 5, "five": 5,
    "sei": 6, "six": 6,
}


def normalize_shutter_number(value: str) -> Optional[int]:
    cleaned = value.strip().casefold().replace(" ", "")
    multiplier = 1
    if cleaned.endswith("mila"):
        cleaned, multiplier = cleaned[:-4], 1000
    elif cleaned.endswith("k"):
        cleaned, multiplier = cleaned[:-1], 1000
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", "")
    if not cleaned.isdigit():
        return None
    number = int(cleaned) * multiplier
    return number if 1 <= number <= 2_000_000 else None


def parse_quantity(value: str) -> Optional[int]:
    normalized = value.strip().casefold()
    if normalized.isdigit():
        return int(normalized)
    return NUMBER_WORDS.get(normalized)


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def unique_strings(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
