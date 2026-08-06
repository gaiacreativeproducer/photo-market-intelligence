"""Allowlisted dashboard context and catalog-alias product resolution."""
from __future__ import annotations

import re


def normalize(value): return re.sub(r"[^a-z0-9]+", "", value.casefold())


def resolve_products(message, data):
    compact = normalize(message); candidates = []
    for product in data.products:
        names = [product.id, product.display_name, product.model] + list(product.aliases)
        matches = [normalize(name) for name in names if normalize(name) and normalize(name) in compact]
        if matches: candidates.append((max(map(len, matches)), product.id))
    if not candidates: return []
    candidates.sort(reverse=True)
    best = candidates[0][0]
    return [product_id for score, product_id in candidates if score >= max(3, best - 2)][:4]


def safe_detail(data, product_id):
    return data.details.get(product_id) if product_id else None
