"""Public models for deterministic product recognition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class ProductMatchCandidate:
    product_id: str
    matched_alias: str
    matched_text: str
    match_type: str
    score: int
    reasons: List[str]
    source_start: int
    source_end: int


@dataclass(frozen=True)
class ProductRecognition:
    product_id: Optional[str]
    confidence: int
    candidates: List[ProductMatchCandidate] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    ambiguous: bool = False
    unmatched_terms: List[str] = field(default_factory=list)
    recognized_brand: Optional[str] = None
    recognized_model: Optional[str] = None
    recognized_version: Optional[str] = None
    recognized_mount: Optional[str] = None
    recognized_category: Optional[str] = None
