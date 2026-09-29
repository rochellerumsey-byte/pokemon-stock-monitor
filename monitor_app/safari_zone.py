"""Safari Zone's published, read-only Shopify storefront product data."""
import re
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from .adapters import Result, price_value


COLLECTION_URL = "https://safari-zone.com/collections/pokemon"
HOST = "safari-zone.com"
HANDLE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
PRODUCT_PATH = re.compile(r"/products/([a-z0-9][a-z0-9-]*)/?\Z")
HEADERS = {"User-Agent": "PokemonStockMonitor/2.0 (personal inventory notifications)",
           "Accept": "application/json"}


def product_url(handle):
    if not isinstance(handle, str) or not HANDLE.fullmatch(handle):
        raise ValueError("Safari Zone product has no valid handle")
    return f"https://{HOST}/products/{handle}"


def product_identity(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != HOST or parts.query or parts.fragment:
        raise ValueError("Use a direct Safari Zone product URL")
    match = PRODUCT_PATH.fullmatch(parts.path)
    if not match:
        raise ValueError("Safari Zone product URL has no valid handle")
    return match.group(1)


def listing_from_product(product):
    from .discovery import Listing, classify

    if not isinstance(product, dict) or not isinstance(product.get("id"), int) or product["id"] <= 0:
        raise ValueError("Safari Zone catalog product is missing its numeric ID")
    title = product.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Safari Zone catalog product is missing its title")
    url = product_url(product.get("handle"))
    variants = product.get("variants")
    variant = variants[0] if isinstance(variants, list) and len(variants) == 1 else None
    raw_price = variant.get("price") if isinstance(variant, dict) else None
    price = price_value(raw_price) if raw_price is not None else None
    available = variant.get("available") if isinstance(variant, dict) else None
    status = "IN_STOCK" if available is True else "OUT_OF_STOCK" if available is False else "UNKNOWN"
    if status == "IN_STOCK" and re.search(r"\bpre[ -]?order\b", title, re.I):
        status = "PREORDER"
    images = product.get("images")
    image = images[0].get("src") if isinstance(images, list) and images and isinstance(images[0], dict) else None
    if image and not image.startswith("https://cdn.shopify.com/"):
        image = None
    return Listing("Safari Zone Collectibles", str(product["id"]), url, title.strip()[:200],
                   classify(title), price, status, None, None, {"image": image} if image else {})


def discover(session=None):
    """Read the store's explicitly published collection JSON; fail on partial scans."""
    client = session or requests.Session()
    listings = []
    for page in range(1, 6):
        url = f"{COLLECTION_URL}/products.json?limit=250&page={page}"
        response = client.get(url, headers=HEADERS, timeout=(5, 15), allow_redirects=False)
        if response.status_code != 200 or "application/json" not in response.headers.get("Content-Type", ""):
            raise ValueError(f"Safari Zone catalog returned HTTP {response.status_code} or non-JSON content")
        if len(response.content) > 5_000_000:
            raise ValueError("Safari Zone catalog response exceeds size limit")
        try:
            products = response.json()["products"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("Safari Zone catalog response has no product list") from exc
        if not isinstance(products, list):
            raise ValueError("Safari Zone catalog response has no product list")
        listings.extend(listing_from_product(item) for item in products)
        if len(products) < 250:
            return listings
    raise ValueError("Safari Zone catalog exceeds the configured page limit; scan was incomplete")


def parse_product(html, expected_url=None):
    """Require the primary product identity and one explicit structured offer."""
    soup = BeautifulSoup(html, "html.parser")
    primary = soup.select_one("product-info[data-product-id]")
    canonical = soup.select_one('link[rel="canonical"][href]')
    if not primary or not str(primary.get("data-product-id", "")).isdigit() or not canonical:
        return Result("UNKNOWN", error="Safari Zone page did not confirm a product ID and canonical URL")
    try:
        canonical_handle = product_identity(canonical["href"])
        if expected_url and canonical_handle != product_identity(expected_url):
            raise ValueError("Product URL changed")
    except ValueError:
        return Result("UNKNOWN", error="Safari Zone product identity could not be confirmed")
    import json
    offers = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            offers.append(data)
    if len(offers) != 1 or not isinstance(offers[0].get("offers"), dict):
        return Result("UNKNOWN", error="Safari Zone page has no single product offer")
    product = offers[0]
    offer = product["offers"]
    offer_url = offer.get("url", "")
    if (product.get("url") != canonical["href"] or offer.get("priceCurrency") != "USD"
            or not isinstance(offer_url, str) or not offer_url.startswith(canonical["href"] + "?variant=")):
        return Result("UNKNOWN", error="Safari Zone offer does not match this product")
    status = {"http://schema.org/InStock": "IN_STOCK", "https://schema.org/InStock": "IN_STOCK",
              "http://schema.org/OutOfStock": "OUT_OF_STOCK", "https://schema.org/OutOfStock": "OUT_OF_STOCK",
              "http://schema.org/PreOrder": "PREORDER", "https://schema.org/PreOrder": "PREORDER"}.get(
                  offer.get("availability"), "UNKNOWN")
    price = price_value(offer.get("price"))
    title = product.get("name") if isinstance(product.get("name"), str) else None
    if status == "IN_STOCK" and title and re.search(r"\bpre[ -]?order\b", title, re.I):
        status = "PREORDER"
    image = product.get("image") if isinstance(product.get("image"), str) else None
    return Result(status, title, price, None if status != "UNKNOWN" else "Safari Zone availability is ambiguous",
                  seller=None, image_url=image, retailer_product_id=str(primary["data-product-id"]))
