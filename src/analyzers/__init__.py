"""Public description-intelligence API."""

from .description import DescriptionAnalyzer, apply_analysis_to_listing
from .models import DescriptionAnalysis, ExtractedFact

__all__ = [
    "DescriptionAnalysis", "DescriptionAnalyzer", "ExtractedFact",
    "apply_analysis_to_listing",
]
