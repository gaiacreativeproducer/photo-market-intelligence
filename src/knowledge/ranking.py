"""Explicit, traceable scoring and primary-selection rules."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Set, Tuple

from .models import ProductMatchCandidate


BASE_SCORES = {
    "exact_product_id": 100,
    "exact_alias": 96,
    "exact_model": 92,
    "normalized_alias": 88,
    "brand_model_match": 75,
    "version_match": 85,
    "token_match": 60,
    "fuzzy_fallback": 55,
}
TITLE_MATCH_BONUS = 5
TITLE_DESCRIPTION_AGREEMENT_BONUS = 3
VERSION_MATCH_BONUS = 5
MOUNT_MATCH_BONUS = 3
CONFLICTING_VERSION_PENALTY = -30
CONFLICTING_BRAND_PENALTY = -40
GENERIC_ALIAS_PENALTY = -20
PRIMARY_THRESHOLD = 70
NEAR_EQUAL_MARGIN = 7


def clamp_score(value: int) -> int:
    return max(0, min(100, value))


def score_candidate(
    match_type: str,
    title_match: bool = False,
    title_description_agree: bool = False,
    version_match: bool = False,
    mount_match: bool = False,
    conflicting_version: bool = False,
    conflicting_brand: bool = False,
    generic_without_brand: bool = False,
) -> Tuple[int, List[str]]:
    score = BASE_SCORES[match_type]
    reasons = [f"Base {match_type} score: {score}."]
    adjustments = (
        (title_match, TITLE_MATCH_BONUS, "Title match"),
        (title_description_agree, TITLE_DESCRIPTION_AGREEMENT_BONUS, "Title and description agree"),
        (version_match, VERSION_MATCH_BONUS, "Matching version"),
        (mount_match, MOUNT_MATCH_BONUS, "Matching mount"),
        (conflicting_version, CONFLICTING_VERSION_PENALTY, "Conflicting version"),
        (conflicting_brand, CONFLICTING_BRAND_PENALTY, "Conflicting brand"),
        (generic_without_brand, GENERIC_ALIAS_PENALTY, "Generic alias without brand support"),
    )
    for applies, value, label in adjustments:
        if applies:
            score += value
            reasons.append(f"{label}: {value:+d}.")
    clamped = clamp_score(score)
    if clamped != score:
        reasons.append(f"Score clamped from {score} to {clamped}.")
    return clamped, reasons


def select_primary(
    candidates: Sequence[ProductMatchCandidate],
    incompatible_pairs: Iterable[frozenset],
) -> Tuple[Optional[str], bool, List[str]]:
    if not candidates:
        return None, False, ["No catalog product could be recognized."]
    best = candidates[0]
    if best.score < PRIMARY_THRESHOLD:
        return None, False, ["Insufficient evidence: the best candidate score is below 70."]
    pairs: Set[frozenset] = set(incompatible_pairs)
    for candidate in candidates[1:]:
        if frozenset((best.product_id, candidate.product_id)) not in pairs:
            continue
        difference = best.score - candidate.score
        if difference <= NEAR_EQUAL_MARGIN:
            return None, True, [
                "Near-equal candidates: incompatible candidates differ by 7 points or fewer."
            ]
    return best.product_id, False, []
