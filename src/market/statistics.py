"""Small deterministic statistical functions used by market snapshots."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PriceStatistics:
    median: Optional[float]
    mean: Optional[float]
    trimmed_mean: Optional[float]
    minimum: Optional[float]
    maximum: Optional[float]
    standard_deviation: Optional[float]
    percentile_10: Optional[float]
    percentile_25: Optional[float]
    percentile_75: Optional[float]
    percentile_90: Optional[float]
    volatility: Optional[float]


def percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def median(values: Sequence[float]) -> Optional[float]:
    return percentile(values, 0.5)


def trimmed_mean(values: Sequence[float], fraction: float = 0.10) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    trim_count = math.floor(len(ordered) * fraction)
    if trim_count == 0 or trim_count * 2 >= len(ordered):
        return mean(ordered)
    return mean(ordered[trim_count:-trim_count])


def population_standard_deviation(values: Sequence[float]) -> Optional[float]:
    average = mean(values)
    if average is None:
        return None
    return math.sqrt(sum((value - average) ** 2 for value in values) / len(values))


def iqr_fences(values: Sequence[float]) -> Optional[Tuple[float, float]]:
    if len(values) < 4:
        return None
    first = percentile(values, 0.25)
    third = percentile(values, 0.75)
    if first is None or third is None:
        return None
    spread = third - first
    return first - 1.5 * spread, third + 1.5 * spread


def calculate_price_statistics(values: Sequence[float]) -> PriceStatistics:
    prices = list(values)
    average = mean(prices)
    deviation = population_standard_deviation(prices)
    volatility = (
        deviation / average * 100
        if deviation is not None and average is not None and average > 0
        else None
    )
    return PriceStatistics(
        median(prices), average, trimmed_mean(prices),
        min(prices) if prices else None,
        max(prices) if prices else None,
        deviation,
        percentile(prices, 0.10),
        percentile(prices, 0.25),
        percentile(prices, 0.75),
        percentile(prices, 0.90),
        volatility,
    )
