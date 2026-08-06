"""Deterministic orchestration for listing-description fact extraction."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from connectors.models import Listing, ListingDefect

from .models import DescriptionAnalysis, ExtractedFact
from .normalization import (
    MONTHS, add_months, month_end, normalize_shutter_number, parse_quantity,
    unique_strings,
)
from .patterns import (
    ACCESSORY_PATTERNS, BOX_NEGATIVE, BOX_POSITIVE, DEFECT_PATTERNS,
    IMPRECISE_WARRANTY_PATTERNS, INVOICE_NEGATIVE, INVOICE_POSITIVE,
    NEGATED_DEFECT_PATTERNS, SELLER_CLAIM_PATTERNS, SHUTTER_PATTERNS,
    WARRANTY_DATE_PATTERNS, WARRANTY_RELATIVE_PATTERNS, PatternDefinition,
)


class DescriptionAnalyzer:
    def __init__(self, as_of: Optional[date] = None) -> None:
        self.as_of = as_of or date.today()

    def analyze(
        self,
        title: str,
        description: str,
        product_category: Optional[str] = None,
    ) -> DescriptionAnalysis:
        text = f"{title}\n{description}"
        facts: List[ExtractedFact] = []
        warnings: List[str] = []
        deductions: Dict[str, int] = {}

        shutter_count = self._extract_shutter(text, facts, warnings, deductions)
        warranty_until, imprecise_claims = self._extract_warranty(
            text, facts, warnings, deductions
        )
        invoice_available = self._extract_boolean(
            text, INVOICE_POSITIVE, INVOICE_NEGATIVE, "invoice_available",
            facts, warnings, deductions, "invoice",
        )
        box_available = self._extract_boolean(
            text, BOX_POSITIVE, BOX_NEGATIVE, "original_box_available",
            facts, warnings, deductions, "original box",
        )
        accessories = self._extract_accessories(text, facts)
        negative_spans = self._extract_verified_negatives(text, facts)
        defects = self._extract_defects(text, facts, negative_spans)
        seller_claims = self._extract_claims(text, facts)
        seller_claims = unique_strings(seller_claims + imprecise_claims)

        self._detect_contradictions(
            defects, seller_claims, warnings, deductions
        )
        missing = self._missing_information(
            product_category, shutter_count, warranty_until,
            defects, negative_spans,
        )
        for item in missing:
            deductions[f"missing:{item}"] = 5
        if not facts:
            deductions["no facts"] = 20
        if any(defect.severity == "unknown" for defect in defects):
            deductions["unknown defect severity"] = 10

        confidence = max(10, min(100, 100 - sum(deductions.values())))
        return DescriptionAnalysis(
            shutter_count=shutter_count,
            warranty_until=warranty_until,
            invoice_available=invoice_available,
            original_box_available=box_available,
            accessories=accessories,
            defects=defects,
            seller_claims=seller_claims,
            missing_information=missing,
            extracted_facts=self._unique_facts(facts),
            warnings=unique_strings(warnings),
            confidence=confidence,
        )

    def _extract_shutter(
        self, text: str, facts: List[ExtractedFact], warnings: List[str],
        deductions: Dict[str, int],
    ) -> Optional[int]:
        values: List[int] = []
        seen_spans = set()
        for pattern in SHUTTER_PATTERNS:
            for match in pattern.pattern.finditer(text):
                if match.span() in seen_spans:
                    continue
                seen_spans.add(match.span())
                normalized = normalize_shutter_number(match.group("value"))
                facts.append(self._fact(pattern, match, match.group("value"), normalized))
                if normalized is None:
                    warnings.append(f"Implausible or ambiguous shutter count: {match.group(0)!r}.")
                    deductions["ambiguous shutter"] = 15
                else:
                    values.append(normalized)
        distinct = list(dict.fromkeys(values))
        if len(distinct) > 1:
            warnings.append("Conflicting shutter counts were found in the listing text.")
            deductions["conflicting shutter"] = 20
            return None
        return distinct[0] if distinct else None

    def _extract_warranty(
        self, text: str, facts: List[ExtractedFact], warnings: List[str],
        deductions: Dict[str, int],
    ) -> Tuple[Optional[str], List[str]]:
        dates: List[date] = []
        claims: List[str] = []
        for pattern in WARRANTY_DATE_PATTERNS:
            for match in pattern.pattern.finditer(text):
                try:
                    if "day" in match.groupdict() and match.groupdict().get("day"):
                        value = date(
                            int(match.group("year")), int(match.group("month")),
                            int(match.group("day")),
                        )
                    else:
                        month = MONTHS.get(match.group("month_name").casefold())
                        if month is None:
                            raise ValueError("unknown month")
                        value = month_end(int(match.group("year")), month)
                except ValueError:
                    warnings.append(f"Warranty date could not be normalized: {match.group(0)!r}.")
                    deductions["ambiguous warranty"] = 10
                    facts.append(self._fact(pattern, match, match.group(0), None, 50))
                    continue
                dates.append(value)
                facts.append(self._fact(pattern, match, match.group(0), value.isoformat()))
        for pattern in WARRANTY_RELATIVE_PATTERNS:
            for match in pattern.pattern.finditer(text):
                months = parse_quantity(match.group("months"))
                if months is None:
                    warnings.append(f"Relative warranty could not be normalized: {match.group(0)!r}.")
                    deductions["ambiguous warranty"] = 10
                    continue
                value = add_months(self.as_of, months)
                dates.append(value)
                facts.append(self._fact(pattern, match, match.group(0), value.isoformat()))
        for pattern in IMPRECISE_WARRANTY_PATTERNS:
            for match in pattern.pattern.finditer(text):
                source = match.group(0)
                claims.append(source)
                facts.append(self._fact(pattern, match, source, None))
                warnings.append("A warranty claim was found, but no precise expiry date can be derived.")
                deductions["imprecise warranty"] = 10
        distinct = list(dict.fromkeys(item.isoformat() for item in dates))
        if len(distinct) > 1:
            warnings.append("Conflicting warranty expiry dates were found.")
            deductions["conflicting warranty"] = 20
            return None, claims
        return distinct[0] if distinct else None, claims

    def _extract_boolean(
        self, text: str, positives: Sequence[PatternDefinition],
        negatives: Sequence[PatternDefinition], fact_type: str,
        facts: List[ExtractedFact], warnings: List[str],
        deductions: Dict[str, int], label: str,
    ) -> Optional[bool]:
        positive_matches = self._matches(text, positives)
        negative_matches = self._matches(text, negatives)
        for pattern, match in positive_matches:
            facts.append(self._fact(pattern, match, True, True))
        for pattern, match in negative_matches:
            facts.append(self._fact(pattern, match, False, False))
        if positive_matches and negative_matches:
            warnings.append(f"Contradictory {label} statements were found.")
            deductions[f"conflicting {fact_type}"] = 15
            return None
        if positive_matches:
            return True
        if negative_matches:
            return False
        return None

    def _extract_accessories(
        self, text: str, facts: List[ExtractedFact]
    ) -> List[str]:
        accessories: List[str] = []
        occupied: List[Tuple[int, int]] = []
        for pattern in ACCESSORY_PATTERNS:
            for match in pattern.pattern.finditer(text):
                if any(self._overlaps(match.span(), span) for span in occupied):
                    continue
                occupied.append(match.span())
                normalized = self._normalize_accessory(pattern.name, match)
                facts.append(self._fact(pattern, match, match.group(0), normalized))
                accessories.extend(normalized)
        return accessories

    @staticmethod
    def _normalize_accessory(name: str, match: re.Match) -> List[str]:
        source = match.group(0).strip()
        if name in {"battery_prefix_quantity", "battery_with_quantity"}:
            quantity = parse_quantity(match.group("quantity")) or 1
            normalized = source.casefold()
            brand_match = re.search(r"\b(sony|nikon|canon|panasonic|patona)\b", normalized)
            brand = brand_match.group(1).title() if brand_match else "Third-party"
            original = "original" in normalized
            model_match = re.search(r"\b[A-Z]{1,4}-[A-Z0-9-]+\b", source, re.IGNORECASE)
            model = f" {model_match.group(0).upper()}" if model_match else ""
            item = f"{brand}{' original' if original else ''}{model} battery"
            return [item] * quantity
        if name == "battery_model_quantity":
            quantity = parse_quantity(match.group("quantity")) or 1
            model = match.group("model").upper()
            brand = "Sony" if model.startswith("NP-FZ") else "Original"
            return [f"{brand} original {model} battery"] * quantity
        if name == "nisi_filter":
            words = source.replace("filtro ", "").strip()
            return [words if words.casefold().endswith("filter") else f"{words} filter"]
        if name == "dji_gimbal":
            return [f"{source} gimbal"]
        if name == "patona_charger":
            return [source]
        return [source]

    def _extract_verified_negatives(
        self, text: str, facts: List[ExtractedFact]
    ) -> List[Tuple[str, int, int]]:
        negatives: List[Tuple[str, int, int]] = []
        for pattern in NEGATED_DEFECT_PATTERNS:
            for match in pattern.pattern.finditer(text):
                category = pattern.category or "unknown"
                negatives.append((category, match.start(), match.end()))
                facts.append(self._fact(pattern, match, False, {"category": category, "present": False}))
        return negatives

    def _extract_defects(
        self, text: str, facts: List[ExtractedFact],
        negatives: Sequence[Tuple[str, int, int]],
    ) -> List[ListingDefect]:
        defects: List[ListingDefect] = []
        seen = set()
        for pattern in DEFECT_PATTERNS:
            for match in pattern.pattern.finditer(text):
                if self._is_negated(pattern.category or "unknown", match.span(), negatives):
                    continue
                component = match.groupdict().get("component") or pattern.affected_component or "other"
                key = (pattern.category, pattern.severity, component, match.start(), match.end())
                if key in seen:
                    continue
                seen.add(key)
                defect = ListingDefect(
                    category=pattern.category or "unknown",
                    description=match.group(0),
                    severity=pattern.severity or "unknown",
                    affected_component=component,
                    source_text=match.group(0),
                    confidence=pattern.confidence / 100,
                )
                defects.append(defect)
                facts.append(self._fact(pattern, match, match.group(0), {
                    "category": defect.category,
                    "severity": defect.severity,
                    "affected_component": defect.affected_component,
                }))
        return defects

    def _extract_claims(
        self, text: str, facts: List[ExtractedFact]
    ) -> List[str]:
        claims: List[str] = []
        for pattern in SELLER_CLAIM_PATTERNS:
            for match in pattern.pattern.finditer(text):
                claims.append(match.group(0))
                facts.append(self._fact(pattern, match, match.group(0), match.group(0).casefold()))
        return claims

    @staticmethod
    def _detect_contradictions(
        defects: Sequence[ListingDefect], claims: Sequence[str],
        warnings: List[str], deductions: Dict[str, int],
    ) -> None:
        normalized_claims = [claim.casefold() for claim in claims]
        if defects and any("nessun difetto" in claim for claim in normalized_claims):
            warnings.append("Seller claim 'nessun difetto' contradicts a detected defect.")
            deductions["no-defects contradiction"] = 20
        functional_defect = any(
            defect.category in {"electronic_damage", "mechanical_damage"}
            or defect.affected_component in {
                "sensor", "display", "autofocus system", "stabilization system"
            }
            for defect in defects
        )
        if functional_defect and any("perfettamente funzionante" in claim for claim in normalized_claims):
            warnings.append("A functional seller claim contradicts a detected functional defect.")
            deductions["functional contradiction"] = 20

    @staticmethod
    def _missing_information(
        category: Optional[str], shutter_count: Optional[int],
        warranty_until: Optional[str], defects: Sequence[ListingDefect],
        negatives: Sequence[Tuple[str, int, int]],
    ) -> List[str]:
        normalized = (category or "").casefold()
        negative_categories = {item[0] for item in negatives}
        defect_categories = {defect.category for defect in defects}
        missing: List[str] = []
        if normalized == "camera":
            if shutter_count is None:
                missing.append("shutter count")
            if warranty_until is None:
                missing.append("warranty status")
            if not defects and not negative_categories:
                missing.append("condition details")
        elif normalized in {"lens", "cinema lens"}:
            optical = {"scratches", "cracks", "optical_damage", "dust", "fungus", "haze"}
            mechanical = {"mechanical_damage", "electronic_damage", "missing_parts"}
            if not (defect_categories & optical or negative_categories & optical):
                missing.append("optical condition")
            if not (defect_categories & mechanical or negative_categories & mechanical):
                missing.append("mechanical condition")
            fungus_haze = {"fungus", "haze"}
            if not (defect_categories & fungus_haze or negative_categories & fungus_haze):
                missing.append("fungus/haze information")
        return missing

    @staticmethod
    def _fact(
        pattern: PatternDefinition, match: re.Match, value: Any,
        normalized: Any, confidence: Optional[int] = None,
    ) -> ExtractedFact:
        return ExtractedFact(
            fact_type=pattern.fact_type,
            value=value,
            normalized_value=normalized,
            source_text=match.group(0),
            confidence=confidence if confidence is not None else pattern.confidence,
            start_position=match.start(),
            end_position=match.end(),
        )

    @staticmethod
    def _matches(
        text: str, patterns: Iterable[PatternDefinition]
    ) -> List[Tuple[PatternDefinition, re.Match]]:
        return [
            (pattern, match)
            for pattern in patterns
            for match in pattern.pattern.finditer(text)
        ]

    @staticmethod
    def _is_negated(
        category: str, span: Tuple[int, int],
        negatives: Sequence[Tuple[str, int, int]],
    ) -> bool:
        for negative_category, start, end in negatives:
            if negative_category == category and span[0] <= end + 20 and span[1] >= start - 20:
                return True
        return False

    @staticmethod
    def _overlaps(left: Tuple[int, int], right: Tuple[int, int]) -> bool:
        return left[0] < right[1] and right[0] < left[1]

    @staticmethod
    def _unique_facts(facts: Sequence[ExtractedFact]) -> List[ExtractedFact]:
        result: List[ExtractedFact] = []
        seen = set()
        for item in sorted(facts, key=lambda fact: (fact.start_position, fact.end_position, fact.fact_type)):
            key = (item.fact_type, item.start_position, item.end_position, repr(item.normalized_value))
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result


def apply_analysis_to_listing(
    listing: Listing, analysis: DescriptionAnalysis
) -> Listing:
    shutter_count = (
        analysis.shutter_count
        if analysis.shutter_count is not None
        else listing.shutter_count
    )
    warranty_until = (
        analysis.warranty_until
        if analysis.warranty_until is not None
        else listing.warranty_until
    )
    invoice_available = (
        analysis.invoice_available
        if analysis.invoice_available is not None
        else listing.invoice_available
    )
    original_box_available = (
        analysis.original_box_available
        if analysis.original_box_available is not None
        else listing.original_box_available
    )
    accessories = _merge_strings(listing.accessories, analysis.accessories, keep_repeats=True)
    claims = _merge_strings(listing.seller_claims, analysis.seller_claims)
    missing = _merge_strings(listing.missing_information, analysis.missing_information)
    if shutter_count is not None:
        missing = [item for item in missing if item.casefold() != "shutter count"]
    if warranty_until is not None:
        missing = [item for item in missing if item.casefold() != "warranty status"]
    if listing.condition.strip().casefold() not in {"", "unknown", "not specified"}:
        missing = [item for item in missing if item.casefold() != "condition details"]
    defects = list(listing.defects)
    defect_keys = {
        (item.category, item.description.casefold(), item.affected_component.casefold())
        for item in defects
    }
    for defect in analysis.defects:
        key = (defect.category, defect.description.casefold(), defect.affected_component.casefold())
        if key not in defect_keys:
            defect_keys.add(key)
            defects.append(defect)
    return replace(
        listing,
        shutter_count=shutter_count,
        warranty_until=warranty_until,
        invoice_available=invoice_available,
        original_box_available=original_box_available,
        accessories=accessories,
        defects=defects,
        seller_claims=claims,
        missing_information=missing,
    )


def _merge_strings(
    existing: Sequence[str], extracted: Sequence[str], keep_repeats: bool = False
) -> List[str]:
    if keep_repeats:
        result = list(existing)
        existing_counts: Dict[str, int] = {}
        result_counts: Dict[str, int] = {}
        for item in existing:
            existing_counts[item.casefold()] = existing_counts.get(item.casefold(), 0) + 1
            result_counts[item.casefold()] = result_counts.get(item.casefold(), 0) + 1
        extracted_counts: Dict[str, int] = {}
        for item in extracted:
            key = item.casefold()
            extracted_counts[key] = extracted_counts.get(key, 0) + 1
            if extracted_counts[key] > result_counts.get(key, 0):
                result.append(item)
                result_counts[key] = result_counts.get(key, 0) + 1
        return result
    return unique_strings(list(existing) + list(extracted))
