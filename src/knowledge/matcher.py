"""Catalog-backed deterministic product matching."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from catalog import Product, ProductAlias
from connectors.models import Listing

from .models import ProductMatchCandidate, ProductRecognition
from .normalization import (
    meaningful_tokens, normalize_text, normalize_with_positions,
    normalized_occurrences, search_variants,
)
from .ranking import BASE_SCORES, score_candidate, select_primary


@dataclass
class _Evidence:
    product: Product
    matched_alias: str
    matched_text: str
    match_type: str
    source_start: int
    source_end: int
    title_match: bool
    description_match: bool
    provenance: str
    version_match: bool = False
    fuzzy: bool = False
    score: int = 0
    reasons: List[str] = field(default_factory=list)


class ProductMatcher:
    """Recognize catalog products without changing the listing."""

    def __init__(
        self, products: Sequence[Product], aliases: Sequence[ProductAlias]
    ) -> None:
        self.products = list(products)
        self.products_by_id = {product.id: product for product in products}
        self.aliases = list(aliases)
        self.aliases_by_product: Dict[str, List[ProductAlias]] = {}
        for alias in aliases:
            self.aliases_by_product.setdefault(alias.product_id, []).append(alias)
        self.brands = {normalize_text(product.brand) for product in products}

    def recognize(self, title: str, description: str) -> ProductRecognition:
        source = f"{title}\n{description}"
        title_end = len(title)
        normalized_source = normalize_with_positions(source)
        evidence: Dict[str, _Evidence] = {}
        warnings: List[str] = []

        for product in self.products:
            self._match_product_id(source, title_end, product, evidence)
        for alias in self.aliases:
            product = self.products_by_id[alias.product_id]
            self._match_alias(
                source, normalized_source, title_end, product, alias, evidence
            )
        for product in self.products:
            self._match_catalog_model(
                source, normalized_source, title_end, product, evidence
            )

        self._score_evidence(source, title_end, evidence)
        if not any(item.score >= 60 for item in evidence.values()):
            self._match_tokens(source, normalized_source, title_end, evidence)
            self._score_evidence(source, title_end, evidence)
        if not any(item.score >= 60 for item in evidence.values()):
            fuzzy_added = self._match_fuzzy(
                source, normalized_source, title_end, evidence
            )
            if fuzzy_added:
                warnings.append(
                    "Fuzzy fallback candidates require review and cannot select a primary product."
                )
            self._score_evidence(source, title_end, evidence)
        version_conflict = self._apply_title_description_conflicts(
            evidence, title_end, warnings
        )
        candidates = self._to_candidates(evidence)
        incompatible = self._incompatible_pairs(candidates)
        product_id, ambiguous, selection_warnings = select_primary(
            candidates, incompatible
        )
        warnings.extend(selection_warnings)

        if candidates and candidates[0].match_type == "fuzzy_fallback":
            product_id = None
            ambiguous = False
        product_id, ambiguous = self._apply_listing_structure(
            source, title, candidates, product_id, ambiguous, warnings
        )
        if version_conflict:
            product_id = None
            ambiguous = True
        selected = self.products_by_id.get(product_id) if product_id else None
        return ProductRecognition(
            product_id=product_id,
            confidence=candidates[0].score if candidates else 0,
            candidates=candidates,
            warnings=self._unique(warnings),
            ambiguous=ambiguous,
            unmatched_terms=self._unmatched_terms(source, candidates),
            recognized_brand=selected.brand if selected else None,
            recognized_model=selected.model if selected else None,
            recognized_version=selected.version if selected else None,
            recognized_mount=selected.native_mount if selected else None,
            recognized_category=selected.category if selected else None,
        )

    def _match_product_id(
        self, source: str, title_end: int, product: Product,
        evidence: Dict[str, _Evidence],
    ) -> None:
        for match in re.finditer(
            r"(?<![A-Za-z0-9])" + re.escape(product.id) + r"(?![A-Za-z0-9])",
            source, re.IGNORECASE,
        ):
            self._record(
                evidence, product, product.id, source, match.span(),
                "exact_product_id", title_end, "product ID",
            )

    def _match_alias(
        self, source: str, normalized_source, title_end: int, product: Product,
        alias: ProductAlias, evidence: Dict[str, _Evidence],
    ) -> None:
        literal_pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(alias.alias) + r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        literal_spans = [match.span() for match in literal_pattern.finditer(source)]
        for span in literal_spans:
            if (
                not self._excluded_context(source, span)
                and not self._superseded_base_version(product, source, span)
            ):
                self._record(
                    evidence, product, alias.alias, source, span, "exact_alias",
                    title_end, "stored alias",
                )
        for variant in search_variants(alias.alias):
            for span in normalized_occurrences(normalized_source, variant):
                if (
                    span in literal_spans
                    or self._excluded_context(source, span)
                    or self._superseded_base_version(product, source, span)
                ):
                    continue
                self._record(
                    evidence, product, alias.alias, source, span,
                    "normalized_alias", title_end,
                    "derived normalized form from stored alias",
                )

    def _match_catalog_model(
        self, source: str, normalized_source, title_end: int, product: Product,
        evidence: Dict[str, _Evidence],
    ) -> None:
        full_name = " ".join(
            item for item in (product.brand, product.model, product.version) if item
        )
        forms = {full_name, f"{product.brand} {product.model}"}
        for form in forms:
            for variant in search_variants(form):
                for span in normalized_occurrences(normalized_source, variant):
                    if self._excluded_context(source, span):
                        continue
                    self._record(
                        evidence, product, form, source, span, "exact_model",
                        title_end, "catalog model",
                    )

    def _match_tokens(
        self, source: str, normalized_source, title_end: int,
        evidence: Dict[str, _Evidence],
    ) -> None:
        source_tokens = set(meaningful_tokens(source))
        normalized_value = normalized_source.value
        for product in self.products:
            product_tokens = set(meaningful_tokens(
                " ".join((product.brand, product.model, product.version))
            ))
            common = source_tokens & product_tokens
            brand_present = normalize_text(product.brand) in normalized_value
            brand_tokens = set(meaningful_tokens(product.brand))
            model_common = common - brand_tokens
            if brand_present and len(model_common) >= 2:
                first = min(
                    normalized_value.find(token) for token in common
                    if normalized_value.find(token) >= 0
                )
                last_token = max(common, key=lambda token: normalized_value.find(token))
                last = normalized_value.find(last_token) + len(last_token)
                span = normalized_source.source_span(first, last)
                self._record(
                    evidence, product, " ".join(sorted(common)), source, span,
                    "token_match", title_end, "catalog model token match",
                )

    def _match_fuzzy(
        self, source: str, normalized_source, title_end: int,
        evidence: Dict[str, _Evidence],
    ) -> bool:
        normalized_value = normalized_source.value
        source_tokens = meaningful_tokens(source)
        if len(source_tokens) < 2:
            return False
        added = False
        for product in self.products:
            display = normalize_text(" ".join(
                item for item in (product.brand, product.model, product.version) if item
            ))
            product_tokens = meaningful_tokens(display)
            brand_present = normalize_text(product.brand) in normalized_value
            distinctive = any(
                any(character.isdigit() for character in token) and len(token) >= 3
                for token in product_tokens
            )
            if not brand_present and not distinctive:
                continue
            windows = self._token_windows(normalized_value, len(display.split()))
            if not windows:
                continue
            ratio, window, start = max(
                (SequenceMatcher(None, display, item).ratio(), item, position)
                for item, position in windows
            )
            if ratio < 0.82 or len(set(product_tokens) & set(source_tokens)) < 2:
                continue
            end = start + len(window)
            source_span = normalized_source.source_span(start, end)
            self._record(
                evidence, product, display, source, source_span,
                "fuzzy_fallback", title_end, "fuzzy fallback", fuzzy=True,
            )
            added = True
        return added

    @staticmethod
    def _token_windows(value: str, size: int) -> List[Tuple[str, int]]:
        matches = list(re.finditer(r"[a-z0-9]+", value))
        result = []
        for index in range(len(matches)):
            end_index = min(len(matches), index + max(2, size)) - 1
            start = matches[index].start()
            end = matches[end_index].end()
            result.append((value[start:end], start))
        return result

    def _record(
        self, evidence: Dict[str, _Evidence], product: Product,
        matched_alias: str, source: str, span: Tuple[int, int], match_type: str,
        title_end: int, provenance: str, fuzzy: bool = False,
    ) -> None:
        if self._negated(source, span):
            return
        title_match = span[0] < title_end
        description_match = span[0] > title_end
        candidate = _Evidence(
            product, matched_alias, source[span[0]:span[1]], match_type,
            span[0], span[1], title_match, description_match, provenance,
            version_match=self._version_supported(product, source[span[0]:span[1]]),
            fuzzy=fuzzy,
        )
        current = evidence.get(product.id)
        if current is None:
            evidence[product.id] = candidate
            return
        current.title_match = current.title_match or title_match
        current.description_match = current.description_match or description_match
        current.version_match = current.version_match or candidate.version_match
        if BASE_SCORES[match_type] > BASE_SCORES[current.match_type] or (
            BASE_SCORES[match_type] == BASE_SCORES[current.match_type]
            and span[0] < current.source_start
        ):
            candidate.title_match = current.title_match
            candidate.description_match = current.description_match
            candidate.version_match = current.version_match
            evidence[product.id] = candidate

    def _score_evidence(
        self, source: str, title_end: int, evidence: Dict[str, _Evidence]
    ) -> None:
        normalized = normalize_text(source)
        for item in evidence.values():
            mount_match = self._mount_supported(item.product.native_mount, normalized)
            generic = self._generic_alias(item.matched_alias) and not self._brand_near(
                item.product.brand, source, (item.source_start, item.source_end)
            )
            first_generation = "prima serie" in normalized
            conflicting_version = (
                self._is_second_generation(item.product) and first_generation
            ) or (
                not self._is_second_generation(item.product)
                and self._second_generation_near(source, item)
            )
            item.score, item.reasons = score_candidate(
                item.match_type,
                title_match=item.title_match,
                title_description_agree=item.title_match and item.description_match,
                version_match=item.version_match or (
                    first_generation and not self._is_second_generation(item.product)
                ),
                mount_match=mount_match,
                conflicting_version=conflicting_version,
                generic_without_brand=generic,
            )
            if item.fuzzy and item.score > 55:
                item.reasons.append(f"Fuzzy fallback score capped from {item.score} to 55.")
                item.score = 55
            item.reasons.append(f"Provenance: {item.provenance}.")
            if item.fuzzy:
                item.reasons.append("Fuzzy fallback is review-only and cannot select a primary product.")

    def _apply_title_description_conflicts(
        self, evidence: Dict[str, _Evidence], title_end: int,
        warnings: List[str],
    ) -> bool:
        title_items = [item for item in evidence.values() if item.title_match]
        description_items = [
            item for item in evidence.values()
            if item.description_match and not item.title_match
        ]
        conflict = False
        for left in title_items:
            for right in description_items:
                if left.product.id != right.product.id and self._family(left.product) == self._family(right.product):
                    right.score = max(0, right.score - 30)
                    right.reasons.append("Title-description incompatible version: -30.")
                    conflict = True
        if conflict:
            warnings.append("Title and description identify incompatible product versions.")
        return conflict

    def _to_candidates(
        self, evidence: Dict[str, _Evidence]
    ) -> List[ProductMatchCandidate]:
        candidates = [
            ProductMatchCandidate(
                item.product.id, item.matched_alias, item.matched_text,
                item.match_type, item.score, item.reasons,
                item.source_start, item.source_end,
            )
            for item in evidence.values()
            if item.score > 0
        ]
        return sorted(candidates, key=lambda item: (-item.score, item.source_start, item.product_id))

    def _incompatible_pairs(
        self, candidates: Sequence[ProductMatchCandidate]
    ) -> Set[frozenset]:
        result: Set[frozenset] = set()
        for index, left in enumerate(candidates):
            left_product = self.products_by_id[left.product_id]
            for right in candidates[index + 1:]:
                right_product = self.products_by_id[right.product_id]
                if (
                    self._family(left_product) == self._family(right_product)
                    or left_product.category == right_product.category == "Camera"
                ):
                    result.add(frozenset((left.product_id, right.product_id)))
        return result

    def _apply_listing_structure(
        self, source: str, title: str,
        candidates: Sequence[ProductMatchCandidate], product_id: Optional[str],
        ambiguous: bool, warnings: List[str],
    ) -> Tuple[Optional[str], bool]:
        strong = [candidate for candidate in candidates if candidate.score >= 70]
        cameras = [item for item in strong if self.products_by_id[item.product_id].category == "Camera"]
        lenses = [item for item in strong if self.products_by_id[item.product_id].category in {"Lens", "Cinema Lens"}]
        accessories = [
            item for item in strong
            if self.products_by_id[item.product_id].category in {"Flash", "Grip", "Gimbal", "Audio"}
        ]
        separated = bool(re.search(
            r"\b(?:sold separately|vendut[ioe] separatamente)\b", source,
            re.IGNORECASE,
        ))
        if separated and len(strong) > 1:
            warnings.append("Recognized products are explicitly described as sold separately.")
            return product_id, ambiguous
        if len(cameras) > 1:
            warnings.append("Multiple camera bodies prevent selection of a primary product.")
            return None, True
        if cameras and lenses:
            warnings.append("Multiple catalog products indicate a kit listing.")
            camera = cameras[0]
            first = min(strong, key=lambda item: item.source_start)
            independently_priced = bool(re.search(
                r"(?:€|eur|usd|gbp|\$|£)\s*\d+.*(?:€|eur|usd|gbp|\$|£)\s*\d+",
                source, re.IGNORECASE,
            ))
            if (
                camera.product_id == first.product_id
                and camera.source_start < len(title)
                and camera.score >= 85
                and not independently_priced
            ):
                return camera.product_id, False
            return None, True
        if not cameras and len(lenses) > 1:
            warnings.append("Multiple primary lenses indicate an ambiguous kit.")
            return None, True
        if cameras and accessories and not lenses:
            return cameras[0].product_id, False
        return product_id, ambiguous

    def _unmatched_terms(
        self, source: str, candidates: Sequence[ProductMatchCandidate]
    ) -> List[str]:
        if candidates or re.search(r"\bcompatib(?:le|ile)\b", source, re.IGNORECASE):
            return []
        normalized = normalize_text(source)
        for brand in sorted(self.brands, key=len, reverse=True):
            match = re.search(r"\b" + re.escape(brand) + r"\b(?:\s+[a-z0-9-]+){1,3}", normalized)
            if match:
                return [match.group(0)]
        distinctive = re.search(r"\b(?:a7|s5|z6)[a-z0-9 ]{1,8}\b", normalized)
        return [distinctive.group(0).strip()] if distinctive else []

    @staticmethod
    def _excluded_context(source: str, span: Tuple[int, int]) -> bool:
        prefix = source[max(0, span[0] - 35):span[0]].casefold()
        return bool(re.search(r"(?:compatible with|compatibile con)\s*$", prefix))

    @staticmethod
    def _negated(source: str, span: Tuple[int, int]) -> bool:
        prefix = source[max(0, span[0] - 28):span[0]].casefold()
        return bool(re.search(
            r"(?:\bnot(?:\s+the)?|\bnon(?:\s+è|\s+il modello)?|\bno)\s*$",
            prefix,
        ))

    @staticmethod
    def _brand_near(brand: str, source: str, span: Tuple[int, int]) -> bool:
        context = source[max(0, span[0] - 30):min(len(source), span[1] + 10)]
        return normalize_text(brand) in normalize_text(context)

    @staticmethod
    def _generic_alias(value: str) -> bool:
        tokens = meaningful_tokens(value)
        return len(tokens) < 2 and not any(any(character.isdigit() for character in token) for token in tokens)

    @staticmethod
    def _version_supported(product: Product, matched: str) -> bool:
        if not product.version:
            return False
        normalized_version = normalize_text(product.version)
        normalized_match = normalize_text(matched)
        if normalized_version in normalized_match:
            return True
        return (
            "ii" in normalized_version and bool(re.search(r"\b(?:ii|2)\b", normalized_match))
            or "iii" in normalized_version and bool(re.search(r"\biii\b", normalized_match))
            or normalized_version == "iv" and bool(re.search(r"\b(?:iv|4)\b", normalized_match))
        )

    @staticmethod
    def _mount_supported(mount: str, normalized_source: str) -> bool:
        terms = {
            "sony-e": ("sony e", "e mount", "fe"),
            "l-mount": ("l mount",),
            "nikon-z": ("nikon z", "z mount"),
            "canon-fd": ("canon fd",),
            "contax-yashica": ("contax yashica", "c y"),
            "pl": ("pl mount",),
        }
        return any(
            re.search(r"\b" + re.escape(term) + r"\b", normalized_source)
            for term in terms.get(mount, ())
        )

    @staticmethod
    def _is_second_generation(product: Product) -> bool:
        version = normalize_text(product.version)
        return bool(re.search(r"\bii\b", version))

    @staticmethod
    def _second_generation_near(source: str, item: _Evidence) -> bool:
        context = normalize_text(source[item.source_start:min(len(source), item.source_end + 12)])
        return bool(re.search(r"\b(?:ii|2)\b", context))

    @classmethod
    def _superseded_base_version(
        cls, product: Product, source: str, span: Tuple[int, int]
    ) -> bool:
        if cls._is_second_generation(product):
            return False
        suffix = normalize_text(source[span[1]:min(len(source), span[1] + 10)])
        return bool(re.match(r"^(?:ii|2)\b", suffix))

    @staticmethod
    def _family(product: Product) -> str:
        name = normalize_text(f"{product.brand} {product.model}")
        patterns = (r"\ba7\b", r"\bs5d?\b", r"\bz6\b", r"\b24 70\b", r"\b70 200\b")
        for pattern in patterns:
            if re.search(pattern, name):
                token = re.search(pattern, name).group(0)
                return f"{normalize_text(product.brand)}:{token.rstrip('d')}"
        return name

    @staticmethod
    def _unique(values: Iterable[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result


def recognize_listing(
    listing: Listing, products: Sequence[Product], aliases: Sequence[ProductAlias]
) -> ProductRecognition:
    return ProductMatcher(products, aliases).recognize(
        listing.title, listing.description
    )
