"""Official eBay Browse API connector and Radar source adapter."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from catalog import Product, ProductAlias
from radar.models import ImportedRecord, SourceBatch

from .base import Connector
from .ebay_auth import EbayAuth
from .marketplace_base import ExtractionMode, MarketplaceConnectorBase
from .models import ConnectorError, Listing, SearchQuery


SUPPORTED_MARKETPLACES = {"EBAY_IT", "EBAY_DE", "EBAY_FR", "EBAY_ES", "EBAY_GB"}
NEW_CONDITION_IDS = {"1000", "1500"}


class EbayBrowseConnector(Connector, MarketplaceConnectorBase):
    marketplace_name = "eBay"
    connector_version = "1.0"
    supported_countries = ("IT", "DE", "FR", "ES", "GB")
    supported_segments = ("NEW", "USED")
    extraction_mode = ExtractionMode.OFFICIAL_API
    terms_review_required = False

    def __init__(
        self, source=None, products: Sequence[Product] = (), aliases: Sequence[ProductAlias] = (),
        watches=(), auth: Optional[EbayAuth] = None, opener: Callable = urlopen,
        sleep_func: Callable[[float], None] = time.sleep,
        monotonic_func: Callable[[], float] = time.monotonic,
    ) -> None:
        name = source.source_id if source else "ebay-browse"
        super().__init__(name, "EBAY_BROWSE", bool(source.enabled) if source else True,
                         source.request_timeout_seconds if source else 15,
                         source.retry_count if source else 1)
        self.source = source
        self.products = list(products)
        self.aliases = list(aliases)
        self.watches = list(watches)
        self.auth = auth or EbayAuth(opener=opener)
        self.opener = opener
        self.sleep_func = sleep_func
        self.monotonic_func = monotonic_func
        self._last_request_at: Optional[float] = None
        self.last_http_status: Optional[int] = None

    def validate_source_configuration(self):
        if self.source is None:
            return
        if self.source.marketplace_id not in SUPPORTED_MARKETPLACES:
            raise ConnectorError("configuration", "Unsupported eBay marketplace ID.")
        if not 1 <= self.source.query_limit <= 200:
            raise ConnectorError("configuration", "eBay query_limit must be from 1 to 200.")

    def search(self, query: SearchQuery) -> List[Listing]:
        self.validate_source_configuration()
        marketplace = self.source.marketplace_id if self.source else "EBAY_IT"
        limit = min(query.limit, self.source.query_limit if self.source else 50, 200)
        records = self._search_pages(query.text, limit, marketplace)
        return [self._listing(item, marketplace) for item in records]

    def fetch_records(self):
        records: List[ImportedRecord] = []
        errors: List[str] = []
        seen = set()
        for primary, fallback in self._discovery_queries():
            try:
                items = self._search_pages(primary, self.source.query_limit, self.source.marketplace_id)
                if not items and fallback:
                    items = self._search_pages(fallback, self.source.query_limit, self.source.marketplace_id)
            except ConnectorError:
                raise
            for item in items:
                try:
                    listing = self._listing(item, self.source.marketplace_id)
                except ConnectorError as error:
                    errors.append(error.message)
                    continue
                if listing.external_id.casefold() in seen:
                    continue
                seen.add(listing.external_id.casefold())
                records.append(ImportedRecord(dict(listing.raw_data), "ebay-item:" + listing.external_id))
        return SourceBatch(records, errors)

    def normalize_record(self, record):
        return dict(record.values)

    def fetch_records_for(self, watches, products, aliases):
        self.watches = list(watches)
        self.products = list(products)
        self.aliases = list(aliases)
        return self.fetch_records()

    def get_item(self, item_id: str) -> Dict[str, object]:
        return self._request_json("/buy/browse/v1/item/" + quote(item_id, safe=""))

    def _search_pages(self, query: str, limit: int, marketplace: str) -> List[Dict[str, object]]:
        values: List[Dict[str, object]] = []
        offset = 0
        while len(values) < limit:
            page_size = min(200, limit - len(values))
            path = "/buy/browse/v1/item_summary/search?" + urlencode(
                {"q": query, "limit": page_size, "offset": offset}
            )
            payload = self._request_json(path, marketplace)
            items = payload.get("itemSummaries", [])
            if not isinstance(items, list):
                raise ConnectorError("malformed_data", "eBay search returned invalid itemSummaries.")
            values.extend(item for item in items if isinstance(item, dict))
            if not items or not payload.get("next"):
                break
            offset += len(items)
        return values[:limit]

    def _request_json(self, path: str, marketplace: Optional[str] = None) -> Dict[str, object]:
        attempts = self.retry_count + 1
        for attempt in range(attempts):
            self._throttle()
            request = Request(
                self.auth.api_root + path, method="GET",
                headers={"Authorization": "Bearer " + self.auth.access_token(),
                         "Accept": "application/json",
                         "X-EBAY-C-MARKETPLACE-ID": marketplace or self.source.marketplace_id},
            )
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    self.last_http_status = getattr(response, "status", None) or response.getcode()
                    result = json.loads(response.read(5 * 1024 * 1024).decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError
                return result
            except HTTPError as error:
                self.last_http_status = error.code
                if error.code == 429:
                    if attempt + 1 < attempts:
                        self.sleep_func(min(_retry_after(error), 30.0))
                        continue
                    raise ConnectorError("rate_limit", "eBay rate limit retry budget was exhausted.", transient=True) from error
                if error.code in {401, 403}:
                    if self.auth.environment == "PRODUCTION":
                        raise ConnectorError("authorization", "eBay Production Browse access is not enabled for this application.", proposed_action="Request eBay Production Buy API access.") from error
                    raise ConnectorError("authorization", "eBay Browse access is not authorized for the selected environment.") from error
                raise ConnectorError("http", "eBay Browse request failed.", transient=500 <= error.code < 600) from error
            except (URLError, TimeoutError) as error:
                raise ConnectorError("network", "eBay Browse service is unavailable.", transient=True) from error
            except (ValueError, TypeError) as error:
                raise ConnectorError("malformed_data", "eBay Browse returned an invalid response.") from error
        raise ConnectorError("rate_limit", "eBay rate limit retry budget was exhausted.", transient=True)

    def _listing(self, item: Dict[str, object], marketplace: str) -> Listing:
        external_id = str(item.get("itemId") or "").strip()
        title = str(item.get("title") or "").strip()
        url = str(item.get("itemWebUrl") or item.get("itemAffiliateWebUrl") or "").strip()
        if not external_id or not title or not url:
            raise ConnectorError("malformed_data", "eBay item is missing itemId, title, or URL.")
        price = item.get("price") if isinstance(item.get("price"), dict) else {}
        location = item.get("itemLocation") if isinstance(item.get("itemLocation"), dict) else {}
        condition = str(item.get("condition") or "")
        condition_id = str(item.get("conditionId") or "")
        buying = [str(value).upper() for value in item.get("buyingOptions", []) if isinstance(value, str)]
        shipping, shipping_currency = _shipping(item)
        segment = "NEW" if condition_id in NEW_CONDITION_IDS or condition.casefold().startswith("new") else "USED"
        eligible = "AUCTION" not in buying or any(value in buying for value in ("FIXED_PRICE", "BUY_IT_NOW"))
        description = str(item.get("shortDescription") or "")
        detected = datetime.now(timezone.utc)
        normalized = {
            "external_id": external_id, "source_name": "eBay", "url": url, "title": title,
            "description": description, "price": _amount(price.get("value")),
            "currency": str(price.get("currency") or (self.source.currency if self.source else "")),
            "source_country": str(location.get("country") or (self.source.country if self.source else "")),
            "segment": segment, "condition": condition, "detected_at": detected.isoformat(),
            "marketplace_id": marketplace, "original_condition": condition,
            "buying_options": buying, "shipping_cost": shipping,
            "shipping_currency": shipping_currency,
            "item_location_country": str(location.get("country") or ""),
            "market_stats_eligible": eligible,
        }
        return Listing(
            external_id, "eBay", title, url, normalized["price"],
            normalized["currency"], condition, normalized["source_country"], "",
            description, detected, normalized, self.name,
            marketplace_id=marketplace, original_condition=condition,
            buying_options=buying, shipping_cost=shipping,
            shipping_currency=shipping_currency,
            item_location_country=normalized["item_location_country"],
            market_stats_eligible=eligible,
        )

    def _discovery_queries(self):
        products = {item.id: item for item in self.products}
        aliases = {}
        for item in self.aliases:
            aliases.setdefault(item.product_id, []).append(item)
        queries = []
        for watch in self.watches:
            if not watch.active or (watch.source_ids and self.source.source_id not in watch.source_ids):
                continue
            product = products.get(watch.product_id)
            query = " ".join(value for value in (
                product.brand if product else "", product.model if product else "",
                product.version if product else "",
            ) if value) or watch.query.strip()
            fallback = ""
            if product:
                choices = sorted(aliases.get(product.id, []), key=lambda item: (0 if "code" in item.alias_type.casefold() else 1, item.alias))
                fallback = choices[0].alias if choices and choices[0].alias.casefold() != query.casefold() else ""
            if query and query.casefold() not in {value[0].casefold() for value in queries}:
                queries.append((query, fallback))
        return queries

    def _throttle(self) -> None:
        interval = self.source.minimum_request_interval_seconds if self.source else 0.0
        now = self.monotonic_func()
        if self._last_request_at is not None:
            remaining = interval - (now - self._last_request_at)
            if remaining > 0:
                self.sleep_func(remaining)
        self._last_request_at = self.monotonic_func()


def _amount(value) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _shipping(item):
    options = item.get("shippingOptions")
    if not isinstance(options, list):
        return None, ""
    for option in options:
        cost = option.get("shippingCost") if isinstance(option, dict) else None
        if isinstance(cost, dict):
            return _amount(cost.get("value")), str(cost.get("currency") or "")
    return None, ""


def _retry_after(error: HTTPError) -> float:
    try:
        return max(0.0, float(error.headers.get("Retry-After", "1")))
    except (TypeError, ValueError):
        return 1.0
