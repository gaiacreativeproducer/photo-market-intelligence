"""Exact static and read-only JSON routing for the local dashboard."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from .serializers import detail_json, product_json
from .view_models import DashboardData, ProductView
from assistant.models import AssistantRequest


STATIC_ROUTES = {
    "/": "index.html", "/index.html": "index.html",
    "/product.html": "product.html", "/compare.html": "compare.html",
    "/app.js": "app.js", "/product.js": "product.js",
    "/compare.js": "compare.js", "/styles.css": "styles.css",
    "/assistant.css": "assistant.css",
    "/manual-listing.js": "manual-listing.js",
    "/product-association.js": "product-association.js",
    "/manual-listing.css": "manual-listing.css",
}
SORTS = {"relevance", "brand", "newest", "used_price", "new_price", "confidence", "wishlist_priority"}
PRIORITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, None: 4}


class DashboardRouter:
    def __init__(self, data: DashboardData, web_directory: Path,
                 notification_store=None, assistant_provider=None,
                 manual_service=None, data_loader=None,
                 association_service=None, ebay_refresh_service=None) -> None:
        self.data = data
        self.web_directory = web_directory
        self.notification_store = notification_store
        self.assistant_provider = assistant_provider
        self.manual_service = manual_service
        self.data_loader = data_loader
        self.association_service = association_service
        self.ebay_refresh_service = ebay_refresh_service

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
        if path == "/api/notifications":
            return self.notifications()
        if path == "/api/assistant/capabilities":
            return self.json(self.assistant_provider.capabilities())
        if path == "/api/wishlist": return self.json({"items":self.data.context.get("wishlist_items",[])})
        if path == "/api/inventory": return self.json({"items":self.data.context.get("inventory_items",[])})
        if path == "/api/decisions": return self.json({"items":self.data.context.get("decision_items",[])})
        if path in {"/api/listings", "/api/listings/live"}:
            return self.live_listings(parse_qs(parsed.query,keep_blank_values=True))
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

    def dispatch_post(self, raw_path: str, value: Dict[str, object]):
        path = unquote(urlsplit(raw_path).path)
        ebay_refresh = re.fullmatch(r"/api/products/([a-z0-9-]+)/ebay-refresh", path)
        if ebay_refresh:
            if value:
                return self.error(400, "invalid_body", "eBay refresh body must be empty.")
            try:
                result = self.ebay_refresh_service.refresh(ebay_refresh.group(1))
            except KeyError:
                return self.error(404, "not_found", "Product not found.")
            except Exception as error:
                from dashboard.ebay_refresh import EbayRefreshError, EbayRefreshFailure
                from connectors.models import ConnectorError
                if isinstance(error, EbayRefreshError):
                    return self.error(409, "ebay_not_configured", str(error))
                if isinstance(error, EbayRefreshFailure):
                    return self.error(502, "ebay_connector_error", str(error))
                if isinstance(error, ConnectorError):
                    return self.error(502, "ebay_connector_error", error.message)
                return self.error(502, "ebay_refresh_failed", "eBay refresh could not be completed.")
            self._reload_data()
            result["workspace"] = detail_json(self.data.details[ebay_refresh.group(1)])["workspace"]
            return self.json(result)
        association = re.fullmatch(r"/api/listings/([a-f0-9]{32})/product", path)
        if association:
            if set(value) != {"product_id"}:
                return self.error(400, "invalid_body", "product_id is the only supported field.")
            product_id = value["product_id"]
            if product_id is not None and (
                not isinstance(product_id, str)
                or not re.fullmatch(r"[a-z0-9-]+", product_id)
            ):
                return self.error(400, "invalid_product_id", "product_id must be a catalog ID or null.")
            try:
                saved = self.association_service.assign(association.group(1), product_id)
            except KeyError as error:
                if error.args and error.args[0] == "listing":
                    return self.error(404, "not_found", "Listing not found.")
                return self.error(400, "unknown_product", "Product ID does not exist in the catalog.")
            self._reload_data()
            listing = next(
                item for item in self.data.context.get("live_listings", [])
                if item["listing_id"] == association.group(1)
            )
            workspace = self.data.details.get(listing.get("product_id"))
            offer_count = workspace["workspace"].offer_count if workspace else 0
            return self.json({
                "listing_id": listing["listing_id"],
                "product_id": listing.get("product_id"),
                "product_name": listing.get("product_name"),
                "product_url": listing.get("product_url"),
                "needs_product_review": listing["state"]["needs_product_review"],
                "automatic_recognition": listing["automatic_recognition"],
                "manual_association": listing["manual_association"],
                "active_offer_count": offer_count,
                "comparison_available": offer_count >= 2,
                "removed": saved is None,
            })
        match = re.fullmatch(r"/api/notifications/([a-f0-9]{32})/(read|dismiss)", path)
        if match:
            if value:
                return self.error(400, "invalid_body", "Notification mutation body must be empty.")
            try: item = self.notification_store.update_state(match.group(1), match.group(2) == "dismiss")
            except KeyError: return self.error(404, "not_found", "Notification not found.")
            return self.json({"notification_id": item.notification_id, "read": item.read, "dismissed": item.dismissed})
        if path == "/api/assistant/query":
            expected = {"message", "product_id", "comparison_product_ids", "listing_id", "page_context"}
            if set(value) != expected:
                return self.error(400, "invalid_body", "Assistant request has invalid keys.")
            if not isinstance(value["message"], str) or not 1 <= len(value["message"]) <= 1000:
                return self.error(400, "invalid_body", "message is required and must not exceed 1000 characters.")
            comparisons = value["comparison_product_ids"]
            if not isinstance(comparisons, list) or len(comparisons) > 4 or any(not isinstance(x, str) for x in comparisons):
                return self.error(400, "invalid_body", "comparison_product_ids is invalid.")
            for key in ("product_id", "listing_id"):
                if value[key] is not None and not isinstance(value[key], str):
                    return self.error(400, "invalid_body", f"{key} is invalid.")
            if not isinstance(value["page_context"], str):
                return self.error(400, "invalid_body", "page_context is invalid.")
            request = AssistantRequest(value["message"], value["product_id"], comparisons,
                value["listing_id"], value["page_context"], datetime.now(timezone.utc))
            return self.json(_assistant_json(self.assistant_provider.query(request)))
        if path == "/api/listings/manual":
            try: result=self.manual_service.submit(value)
            except Exception as error:
                from radar.manual_entry import ManualEntryError
                if isinstance(error,ManualEntryError): return self.error(400,"invalid_listing",error.message,error.field)
                return self.error(500,"manual_entry_failed","Manual listing could not be saved.")
            if self.data_loader:
                self._reload_data()
                live=next((item for item in self.data.context.get("live_listings",[]) if item["listing_id"]==result["listing_id"]),None)
                detail=self.data.details.get(result.get("product_id"))
                if live:
                    result["listing_analysis"]=live.get("decision")
                    result["association_listing"]=live
                if detail:
                    workspace=detail.get("workspace")
                    result["market_context"]=detail.get("listing_market",{})
                    key=detail.get("default_comparison_key")
                    result["ownership_comparison"]=detail.get("ownership_comparisons",{}).get(key) if key else None
                    result["comparable_offer_available"]=bool(result["ownership_comparison"])
                    result["overall_conclusion"]=detail.get("overall_conclusion")
                    result["active_offer_count"]=workspace.offer_count if workspace else len(detail.get("listings",[]))
                    result["comparison_available"]=bool(workspace and workspace.offer_count>=2)
                    result["actions"]={
                        "open_product":result.get("product_url"),
                        "compare_offers":f'{result.get("product_url")}&offers={result["listing_id"]}#confronta' if result.get("product_url") else None,
                        "analyze_details":f'{result.get("product_url")}#analisi-{result["listing_id"]}' if result.get("product_url") else None,
                    }
                else:
                    result["market_context"]={};result["ownership_comparison"]=None;result["comparable_offer_available"]=False;result["overall_conclusion"]=None
                    result["active_offer_count"]=0;result["comparison_available"]=False;result["actions"]={}
            return self.json(result,201 if result["status"]=="created" else 200)
        return self.error(HTTPStatus.NOT_FOUND, "not_found", "Route not found.")

    def _reload_data(self):
        if self.data_loader:
            self.data = self.data_loader()
            if self.assistant_provider:
                self.assistant_provider.data = self.data

    def live_listings(self,query):
        allowed={"product_id","source","country","segment","active","review","price_min","price_max"};problem=self._validate_query(query,allowed)
        if problem:return problem
        values=list(self.data.context.get("live_listings",[]))
        for key in ("product_id","source","country","segment"):
            selected=self._one(query,key)
            if selected is not None:values=[item for item in values if str(item.get(key) or "").casefold()==selected.casefold()]
        active=self._one(query,"active")
        if active is not None:
            if active not in {"true","false"}:return self.error(400,"invalid_query","active must be true or false.")
            values=[item for item in values if item["active"]==(active=="true")]
        review=self._one(query,"review")
        if review is not None:
            if review not in {"true","false"}:return self.error(400,"invalid_query","review must be true or false.")
            values=[item for item in values if item["needs_review"]==(review=="true")]
        for key,operator in (("price_min","min"),("price_max","max")):
            raw=self._one(query,key)
            if raw is None:continue
            try:threshold=float(raw)
            except ValueError:return self.error(400,"invalid_query",f"{key} must be numeric.")
            if threshold<0:return self.error(400,"invalid_query",f"{key} must not be negative.")
            values=[item for item in values if item.get("price") is not None and (item["price"]>=threshold if operator=="min" else item["price"]<=threshold)]
        return self.json({"items":values,"count":len(values)})

    def notifications(self):
        values = self.notification_store.load() if self.notification_store else []
        visible = [item for item in values if not item.dismissed]
        return self.json({"notifications": [_notification_json(item) for item in visible],
                          "count": len(visible),
                          "unread_count": sum(not item.read for item in visible),
                          "read_count": sum(item.read for item in values),
                          "dismissed_count": sum(item.dismissed for item in values)})

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
    def json(value,status=HTTPStatus.OK): return status, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")

    @staticmethod
    def error(status, code, message,field=None):
        value={"code":code,"message":message}
        if field:value["field"]=field
        return status,"application/json; charset=utf-8",json.dumps({"error":value},sort_keys=True).encode("utf-8")


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


def _notification_json(item):
    return {"notification_id": item.notification_id, "notification_type": item.notification_type.value,
            "severity": item.severity.value, "title": item.title, "message": item.message,
            "product_id": item.product_id, "listing_id": item.listing_id,
            "source_id": item.source_id, "created_at": item.created_at.isoformat(),
            "read": item.read, "dismissed": item.dismissed, "action_url": item.action_url,
            "evidence": item.evidence, "delivery_status": item.delivery_status.value}


def _assistant_json(item):
    return {"answer":item.answer,"intent":item.intent.value,"confidence":item.confidence,
            "facts":[asdict(fact) for fact in item.facts],"warnings":item.warnings,
            "suggested_actions":item.suggested_actions,"related_product_ids":item.related_product_ids,
            "source_sections":item.source_sections}
