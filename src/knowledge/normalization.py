"""Conservative product-text normalization with source position mapping."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class NormalizedText:
    value: str
    source_positions: List[int]

    def source_span(self, start: int, end: int) -> Tuple[int, int]:
        return self.source_positions[start], self.source_positions[end - 1] + 1


def normalize_text(value: str) -> str:
    return normalize_with_positions(value).value


def normalize_with_positions(value: str) -> NormalizedText:
    characters: List[str] = []
    positions: List[int] = []
    pending_space: Optional[int] = None
    for source_position, character in enumerate(value):
        decomposed = unicodedata.normalize("NFKD", character.casefold())
        emitted = [item for item in decomposed if not unicodedata.combining(item)]
        for item in emitted:
            if item.isalnum():
                if pending_space is not None and characters:
                    characters.append(" ")
                    positions.append(pending_space)
                pending_space = None
                characters.append(item)
                positions.append(source_position)
            else:
                pending_space = source_position
    return NormalizedText("".join(characters), positions)


def normalized_occurrences(source: NormalizedText, needle: str) -> List[Tuple[int, int]]:
    normalized_needle = normalize_text(needle)
    if not normalized_needle:
        return []
    pattern = re.compile(r"(?<![a-z0-9])" + re.escape(normalized_needle) + r"(?![a-z0-9])")
    return [source.source_span(match.start(), match.end()) for match in pattern.finditer(source.value)]


def literal_occurrences(source: str, needle: str) -> List[Tuple[int, int]]:
    if not needle:
        return []
    pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(needle) + r"(?![A-Za-z0-9])", re.IGNORECASE)
    return [match.span() for match in pattern.finditer(source)]


def derived_forms(value: str) -> List[str]:
    """Return supported product-specific variants without general number rewriting."""
    normalized = normalize_text(value)
    forms = {normalized}
    substitutions = (
        (r"\balpha 7\b", "a7"),
        (r"\ba7iv\b", "a7 iv"),
        (r"\ba7 4\b", "a7 iv"),
        (r"\ba7iii\b", "a7 iii"),
        (r"\ba7v\b", "a7 v"),
        (r"\bs5ii\b", "s5 ii"),
        (r"\bz6iii\b", "z6 iii"),
        (r"\bgm2\b", "gm ii"),
        (r"\bdg dn 2\b", "dg dn ii"),
    )
    changed = normalized
    for pattern, replacement in substitutions:
        changed = re.sub(pattern, replacement, changed)
    forms.add(changed)
    return sorted(forms)


def search_variants(value: str) -> List[str]:
    """Expand only documented product-version spellings."""
    forms = set(derived_forms(value))
    for form in list(forms):
        replacements = (
            ("a7 iv", ("a7iv", "a7 4", "alpha 7 iv")),
            ("a7 iii", ("a7iii", "alpha 7 iii")),
            ("a7 v", ("a7v", "alpha 7 v")),
            ("s5 ii", ("s5ii",)),
            ("z6 iii", ("z6iii",)),
            ("gm ii", ("gm2",)),
            ("dg dn ii", ("dg dn 2",)),
        )
        for source, targets in replacements:
            if source in form:
                for target in targets:
                    forms.add(form.replace(source, target))
    return sorted(forms)


def canonical_product_text(value: str) -> str:
    return derived_forms(value)[-1]


def meaningful_tokens(value: str) -> List[str]:
    ignored = {
        "a", "an", "and", "body", "camera", "compatible", "con", "corpo",
        "f", "for", "il", "la", "lens", "mm", "mount", "obiettivo", "the",
        "with", "zoom",
    }
    return [token for token in canonical_product_text(value).split() if token not in ignored and len(token) > 1]
