"""Models produced by deterministic description analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from connectors.models import ListingDefect


@dataclass(frozen=True)
class ExtractedFact:
    fact_type: str
    value: Any
    normalized_value: Any
    source_text: str
    confidence: int
    start_position: int
    end_position: int


@dataclass(frozen=True)
class DescriptionAnalysis:
    shutter_count: Optional[int]
    warranty_until: Optional[str]
    invoice_available: Optional[bool]
    original_box_available: Optional[bool]
    accessories: List[str] = field(default_factory=list)
    defects: List[ListingDefect] = field(default_factory=list)
    seller_claims: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    extracted_facts: List[ExtractedFact] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    confidence: int = 100
