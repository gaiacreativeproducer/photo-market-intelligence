#!/usr/bin/env python3
"""Conservative, sanitized live eBay Browse connection check."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from connectors.ebay_auth import EbayAuth
from connectors.ebay_browse import EbayBrowseConnector
from connectors.models import SearchQuery
from catalog import load_product_aliases, load_products
from knowledge import ProductMatcher


QUERY = "Sony A7 IV"
MARKETPLACE = "EBAY_IT"
SEARCH_PATH = "/buy/browse/v1/item_summary/search"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Test the official eBay Browse connection safely.")
    parser.add_argument("--debug", action="store_true", help="print sanitized request and response diagnostics")
    parser.add_argument("--limit", type=int, default=3, choices=range(1, 11), metavar="1-10")
    parser.add_argument("--classify", action="store_true", help="classify results locally without persistence")
    arguments = parser.parse_args(argv)
    parameters = {"q": QUERY, "limit": arguments.limit, "offset": 0}
    auth = EbayAuth()
    connector = EbayBrowseConnector(auth=auth)
    if arguments.debug:
        print("Endpoint:", auth.api_root + SEARCH_PATH)
        print("Marketplace:", MARKETPLACE)
        print("Query:", QUERY)
        print("GET parameters:")
        for name, value in parameters.items():
            print(f"  {name}={value}")
        print("Request URL:", auth.api_root + SEARCH_PATH + "?" + urlencode(parameters))
    try:
        listings = connector.search(SearchQuery(QUERY, arguments.limit))
    except Exception as error:
        message = getattr(error, "message", "Connection check failed.")
        print("Environment:", auth.environment)
        print("HTTP result: FAILED")
        print("Marketplace:", MARKETPLACE)
        print("Result count: 0")
        if arguments.debug:
            print("HTTP status:", connector.last_http_status if connector.last_http_status is not None else "Unavailable")
            print("First 3 titles: none")
            print("First 3 prices: none")
            print("First 3 URLs: none")
        print("Error:", message)
        return 1
    print("Environment:", auth.environment)
    print("HTTP result: OK")
    print("Marketplace:", MARKETPLACE)
    print("Result count:", len(listings))
    for item in listings:
        print("Sample:", item.title[:100], item.price, item.currency)
    if arguments.debug:
        print("HTTP status:", connector.last_http_status if connector.last_http_status is not None else "Unavailable")
        print("First 3 titles:")
        for item in listings[:3]: print(" ", item.title[:100])
        print("First 3 prices:")
        for item in listings[:3]: print(" ", item.price, item.currency)
        print("First 3 URLs:")
        for item in listings[:3]: print(" ", item.url)
    if arguments.classify:
        products = load_products(ROOT / "data/products.csv")
        aliases = load_product_aliases(ROOT / "data/product_aliases.csv", products)
        matcher = ProductMatcher(products, aliases)
        recognized = [matcher.recognize(item.title, item.description) for item in listings]
        accepted = sum(
            value.product_id is not None and value.recognized_category == "Camera"
            and value.confidence >= 70 and not value.ambiguous
            for value in recognized
        )
        review = sum(
            value.ambiguous or (
                value.product_id is None and value.candidates
                and not any("compatibility reference" in warning for warning in value.warnings)
            )
            for value in recognized
        )
        print("Accepted camera-body listings:", accepted)
        print("Ignored accessory/unmatched listings:", len(listings) - accepted - review)
        print("Needs-review listings:", review)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
