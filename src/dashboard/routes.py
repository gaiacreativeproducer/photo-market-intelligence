"""Exact static and read-only JSON routing for the local dashboard."""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from .serializers import detail_json, product_json
from .view_models import DashboardData, ProductView


STATIC_ROUTES = {
    "/": "index.html", "/index.html": "index.html",
    "/product.html": "product.html", "/compare.html": "compare.html",
    "/app.js": "app.js", "/product.js": "product.js",
    "/compare.js": "compare.js", "/styles.css": "styles.css",
}
SORTS = {"relevance", "brand", "newest", "used_price", "new_price", "confidence", "wishlist_priority"}
PRIORITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, None: 4}


class DashboardRouter:
    def __init__(self, data: DashboardData, web_directory: Path) -> None:
        self.data = data
        self.web_directory = web_directory

    def dispatch(self, raw_path: str) -> Tuple[int, str, bytes]:
        parsed = urlsplit(raw_path)
        path = unquote(parsed.path)
        if ".." in path or "\\" in path or "%" in path:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid_path", "Path traversal is not allowed.")
        if path in STATIC_ROUTES:
            target = self.web_directory / STATIC_ROUTES[path]
            content_type = "text/html; charset=utf-8"
            if target.suffix == ".js": content_type = "text/javascript; charset=utf-8"
            if target.suffix == ".css": content_type = "text/css; charset=utf-8"
            return HTTPStatus.OK, content_type, target.read_bytes()
        if path == "/api/status":
            return self.json({"status": "OK", "service": "Photo Market Intelligence Dashboard", "mode": self.data.mode, "read_only": True, "product_count": len(self.data.products)})
        if path == "/api/context": return self.json(self.data.context)
        if path in {"/api/products", "/api/search"}:
            return self.products(parse_qs(parsed.query, keep_blank_values=True), search_endpoint=path.endswith("search"))
        if path == "/api/compare": return self.compare(parse_qs(parsed.query, keep_blank_values=True))
        prefix = "/api/products/"
        if path.startswith(prefix):
            product_id = path[len(prefix):]
            if not product_id or "/" in product_id or not re.fullmatch(r"[a-z0-9-]+", product_id):
                return self.error(HTTPStatus.BAD_REQUEST, "invalid_product_id", "Invalid product ID.")
            detail = self.data.details.get(product_id)
            if detail is None: return self.error(HTTPStatus.NOT_FOUND, "not_found", "Product not found.")
            return self.json(detail_json(detail))
        return self.error(HTTPStatus.NOT_FOUND, "not_found", "Route not found.")

    def products(self, query: Dict[str, List[str]], search_endpoint: bool = False):
        allowed = {"q", "category", "brand", "mount", "owned", "wishlist", "market", "confidence_min", "sort", "order"}
        problem = self._validate_query(query, allowed)
        if problem: return problem
        q = self._one(query, "q", "")
        if len(q) > 200: return self.error(400, "invalid_query", "Search query is too long.")
        ranked = [(item, _rank(item, q)) for item in self.data.products]
        if q: ranked = [pair for pair in ranked if pair[1] is not None]
        for field, attribute in (("category", "category"), ("brand", "brand"), ("mount", "native_mount")):
            value = self._one(query, field)
            if value is not None: ranked = [pair for pair in ranked if getattr(pair[0], attribute).casefold() == value.casefold()]
        for field in ("owned", "wishlist"):
            value = self._one(query, field)
            if value is not None:
                if value not in {"true", "false"}: return self.error(400, "invalid_query", f"{field} must be true or false.")
                expected = value == "true"; ranked = [pair for pair in ranked if getattr(pair[0], field) == expected]
        market = self._one(query, "market")
        if market is not None:
            if market not in {"new", "used"}: return self.error(400, "invalid_query", "market must be new or used.")
            ranked = [pair for pair in ranked if getattr(pair[0], f"{market}_median") is not None]
        minimum = self._one(query, "confidence_min")
        if minimum is not None:
            try: threshold = int(minimum)
            except ValueError: return self.error(400, "invalid_query", "confidence_min must be an integer.")
            if not 0 <= threshold <= 100: return self.error(400, "invalid_query", "confidence_min must be from 0 to 100.")
            ranked = [pair for pair in ranked if pair[0].market_confidence is not None and pair[0].market_confidence >= threshold]
        sort = self._one(query, "sort", "relevance")
        order = self._one(query, "order", "asc")
        if sort not in SORTS: return self.error(400, "invalid_query", "Unsupported sort.")
        if order not in {"asc", "desc"}: return self.error(400, "invalid_query", "order must be asc or desc.")
        ranked = _sort(ranked, sort, order, bool(q))
        products = [product_json(item) for item, _ in ranked]
        body = {"query": q, "products": products, "count": len(products)}
        if not search_endpoint:
            body["filters"] = {"categories": sorted({item.category for item in self.data.products}), "brands": sorted({item.brand for item in self.data.products}), "mounts": sorted({item.native_mount for item in self.data.products})}
        return self.json(body)

    def compare(self, query: Dict[str, List[str]]):
        problem = self._validate_query(query, {"ids"})
        if problem: return problem
        value = self._one(query, "ids")
        if value is None or not value: return self.error(400, "invalid_query", "Two to four product IDs are required.")
        raw = value.split(",")
        if any(not item or not re.fullmatch(r"[a-z0-9-]+", item) for item in raw): return self.error(400, "invalid_query", "Malformed product IDs.")
        ids = list(dict.fromkeys(raw))
        if len(ids) < 2: return self.error(400, "invalid_query", "Two to four product IDs are required.")
        if len(ids) > 4: return self.error(400, "comparison_limit", "A maximum of four products can be compared.")
        missing = [item for item in ids if item not in self.data.details]
        if missing: return self.error(404, "not_found", f"Product not found: {missing[0]}")
        return self.json({"products": [product_json(self.data.details[item]["product"]) for item in ids], "count": len(ids), "maximum": 4, "warnings": []})

    def _validate_query(self, query, allowed):
        unknown = set(query) - allowed
        if unknown: return self.error(400, "invalid_query", f"Unsupported query parameter: {sorted(unknown)[0]}")
        repeated = [key for key, values in query.items() if len(values) != 1]
        if repeated: return self.error(400, "invalid_query", f"Repeated query parameter: {repeated[0]}")
        return None

    @staticmethod
    def _one(query, key, default=None): return query.get(key, [default])[0]

    @staticmethod
    def json(value): return HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")

    @staticmethod
    def error(status, code, message): return status, "application/json; charset=utf-8", json.dumps({"error": {"code": code, "message": message}}, sort_keys=True).encode("utf-8")


def _normalize(value: str) -> str: return " ".join(value.casefold().replace("-", " ").split())
def _compact(value: str) -> str: return re.sub(r"[^a-z0-9]", "", value.casefold())


def _rank(product: ProductView, query: str) -> Optional[int]:
    if not query: return 0
    normalized = _normalize(query); compact = _compact(query); terms = normalized.split()
    fields = [product.id, product.brand, product.model, product.version, product.category, product.product_type, product.native_mount]
    searchable = [_normalize(field) for field in fields] + [_normalize(alias) for alias in product.aliases]
    if not all(any(term in field or _compact(term) in _compact(field) for field in searchable) for term in terms): return None
    score = 0
    aliases = [_normalize(alias) for alias in product.aliases]
    if normalized in aliases: score += 120
    if compact and compact in {_compact(alias) for alias in product.aliases}: score += 115
    if normalized == _normalize(product.id): score += 110
    identity = _normalize(product.display_name)
    if compact == _compact(identity): score += 100
    if normalized == _normalize(product.model): score += 90
    for term in terms:
        score += max((50 if field.startswith(term) else 35 if re.search(rf"\b{re.escape(term)}\b", field) else 20 for field in searchable if term in field), default=0)
    version_tokens = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "2": "2", "3": "3", "4": "4", "5": "5"}
    requested = next((version_tokens[term] for term in terms if term in version_tokens), None)
    actual = version_tokens.get(_normalize(product.version).split()[0] if product.version else "")
    if requested:
        score += 60 if actual == requested else -80 if actual else -30
    if product.brand.casefold() in normalized and _normalize(product.model).split()[0] in normalized: score += 20
    return score


def _sort(ranked, sort, order, has_query):
    reverse = order == "desc"
    if sort == "relevance" and has_query: return sorted(ranked, key=lambda pair: (-pair[1], pair[0].id))
    if sort == "brand": key = lambda item: (item.brand.casefold(), item.model.casefold(), item.id)
    elif sort == "newest": key = lambda item: item.release_year
    elif sort == "used_price": key = lambda item: item.used_median
    elif sort == "new_price": key = lambda item: item.new_median
    elif sort == "confidence": key = lambda item: item.market_confidence
    elif sort == "wishlist_priority": key = lambda item: PRIORITY[item.wishlist_priority]
    else: key = lambda item: item.display_name.casefold()
    available = [pair for pair in ranked if key(pair[0]) is not None]
    unavailable = [pair for pair in ranked if key(pair[0]) is None]
    return sorted(available, key=lambda pair: (key(pair[0]), pair[0].id), reverse=reverse) + sorted(unavailable, key=lambda pair: pair[0].id)
