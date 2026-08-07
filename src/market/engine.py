"""Market Intelligence Engine: facts and markets, never recommendations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import List, Mapping, Optional, Sequence

from catalog import Product
from connectors.models import Listing

from .cleaning import MarketEvidence, clean_listings
from .models import ExclusionReason, MarketSnapshot
from .snapshot import depreciation, market_confidence, trend
from .statistics import calculate_price_statistics


class MarketEngine:
    def __init__(
        self,
        target_market_country: str,
        currency: str,
        segment: str,
        recognized_product_ids: Optional[Mapping[str, Optional[str]]] = None,
        recognition_confidence: Optional[Mapping[str, int]] = None,
        description_confidence: Optional[Mapping[str, int]] = None,
        description_contradictions: Optional[Mapping[str, bool]] = None,
        description_evidence_count: Optional[Mapping[str, int]] = None,
        listing_segments: Optional[Mapping[str, str]] = None,
        source_countries: Optional[Mapping[str, str]] = None,
        landed_costs: Optional[Mapping[str, float]] = None,
        warranty_clarity: Optional[Mapping[str, bool]] = None,
        accessory_completeness: Optional[Mapping[str, bool]] = None,
        statistical_eligibility: Optional[Mapping[str, bool]] = None,
        history: Optional[Sequence[MarketSnapshot]] = None,
        created_at: Optional[datetime] = None,
    ) -> None:
        normalized_segment = segment.upper()
        if normalized_segment not in {"NEW", "USED"}:
            raise ValueError("market segment must be NEW or USED")
        self.target_market_country = target_market_country
        self.currency = currency
        self.segment = normalized_segment
        self.evidence = MarketEvidence(
            recognized_product_ids or {}, recognition_confidence or {},
            description_confidence or {}, description_contradictions or {},
            description_evidence_count or {}, listing_segments or {},
            source_countries or {}, landed_costs or {}, warranty_clarity or {},
            accessory_completeness or {}, statistical_eligibility or {},
        )
        self.history = list(history or [])
        self.created_at = created_at or datetime.now(timezone.utc)

    def build_snapshot(
        self, product: Product, listings: List[Listing]
    ) -> MarketSnapshot:
        observations = clean_listings(
            listings, product.id, self.target_market_country, self.currency,
            self.segment, self.evidence,
        )
        valid = [item for item in observations if item.included_in_statistics]
        prices = [
            item.statistical_price for item in valid
            if item.statistical_price is not None
        ]
        statistics = calculate_price_statistics(prices)
        confidence = market_confidence(observations)
        quality_average = (
            sum(item.listing_quality for item in observations) / len(observations)
            if observations else 0.0
        )
        source_countries = sorted({
            item.source_country for item in observations
            if item.source_country is not None
        })
        notes = []
        if len(source_countries) > 1 and any(
            item.source_country is not None
            and item.source_country.casefold() != self.target_market_country.casefold()
            and item.landed_cost_estimate is None
            for item in observations
        ):
            notes.append(
                "Multiple source countries are present and some foreign landed costs are not normalized."
            )
        base = MarketSnapshot(
            product.id, self.target_market_country, source_countries,
            self.currency, self.segment, self.created_at, len(observations),
            len(valid),
            sum(item.excluded_reason == ExclusionReason.OUTLIER for item in observations),
            statistics.median, statistics.mean, statistics.trimmed_mean,
            statistics.minimum, statistics.maximum,
            statistics.standard_deviation, statistics.percentile_10,
            statistics.percentile_25, statistics.percentile_75,
            statistics.percentile_90, statistics.volatility, confidence,
            None, None, None, None, None, quality_average,
            list(observations), notes,
        )
        return replace(
            base,
            trend_30d=trend(base, self.history, 30, 10),
            trend_90d=trend(base, self.history, 90, 20),
            trend_180d=trend(base, self.history, 180, 30),
            estimated_12_month_depreciation=depreciation(
                base, self.history, 365, 45
            ),
            estimated_24_month_depreciation=depreciation(
                base, self.history, 730, 60
            ),
        )
