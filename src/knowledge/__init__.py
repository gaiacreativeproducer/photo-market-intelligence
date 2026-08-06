"""Deterministic product-recognition public API."""

from .matcher import ProductMatcher, recognize_listing
from .models import ProductMatchCandidate, ProductRecognition

__all__ = [
    "ProductMatchCandidate", "ProductMatcher", "ProductRecognition",
    "recognize_listing",
]
