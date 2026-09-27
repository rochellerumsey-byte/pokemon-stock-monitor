"""Conservative public listing discovery. A missing product identity is never guessed."""
import json
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from sqlalchemy import select

from .adapters import belongs, hostname, price_value, public_host
from .db import DiscoveredProduct, DiscoverySource, Product, utcnow

SOURCE_DOMAINS = {"Target": "target.com", "Best Buy": "bestbuy.com"}
TYPE_PATTERNS = (
    ("Pokemon Center ETB", r"pok[eé]mon center.*elite trainer box|elite trainer box.*pok[eé]mon center"),
    ("ETB", r"elite trainer box|\betb\b"),
    ("Booster Bundle", r"booster bundle"),
    ("Booster Box/Mega Box", r"booster box|mega box"),
    ("Premium Collection", r"premium collection"),
    ("Poster Collection", r"poster collection"),
    ("Sticker Collection", r"sticker collection"),
    ("Pin Collection", r"pin collection"),
    ("Collection/Box", r"collection|\bbox\b"),
    ("Tin", r"\btin\b"),
    ("Other Sealed TCG", r"blister|booster pack|battle deck|build.?battle|trading card game|\btcg\b"),
)
EXCLUDED = re.compile(r"binder|sleeve|playmat|plush|figure|shirt|keychain|poster only|storage|accessor|book", re.I)


@dataclass(frozen=True)
class Listing:
    retailer: str
    retailer_product_id: str
    url: str
    title: str
    product_type: str | None
    price: str | None
    status: str
    seller: str | None
    release_date: str | None = None
    metadata: dict | None = None


def classify(title):
    if not re.search(r"pok[eé]mon", title, re.I) or EXCLUDED.search(title):
        return None
    for kind, pattern in TYPE_PATTERNS:
        if re.search(pattern, title, re.I):
            return kind
    return None


def canonical(retailer, url):
    parts = urlsplit(url)
    host = hostname(url)
    if retailer not in SOURCE_DOMAINS or not belongs(host, SOURCE_DOMAINS[retailer]):
        raise ValueError("Listing URL is outside the source retailer")
    match = (re.search(r"/A-(\d+)(?:/|$)", parts.path, re.I) if retailer == "Target"
             else re.search(r"/(\d+)\.p(?:/|$)", parts.path, re.I))
    if not match:
        raise ValueError("Listing has no stable retailer product ID")
    clean = urlunsplit(("https", host, parts.path.rstrip("/"), "", ""))
    return match.group(1), clean


def validate_source(retailer, url):
    if retailer not in SOURCE_DOMAINS:
        raise ValueError("Discovery currently supports Target and Best Buy only")
    host = hostname(url)
    if not belongs(host, SOURCE_DOMAINS[retailer]) or not public_host(host):
        raise ValueError("Source must be a public URL on the selected retailer")
    return url


def parse_listings(retailer, source_url, html):
    soup = BeautifulSoup(html, "html.parser")
    listings = {}
    # Product cards are required so a site's navigation and recommendations are not inventory.
    selectors = ('[data-test="product-card"], [data-test="productCard"], [data-test="product-grid"] article'
                 if retailer == "Target" else '[data-testid="product-card"], .sku-item, article.product-card')
    for card in soup.select(selectors):
        anchor = card.select_one("a[href]")
        if not anchor:
            continue
        try:
            product_id, url = canonical(retailer, urljoin(source_url, anchor["href"]))
        except ValueError:
            continue
        title_node = card.select_one("h2, h3, [data-test='product-title'], .sku-title")
        title = (title_node or anchor).get_text(" ", strip=True)[:200]
        if not title:
            continue
        price_node = card.select_one("[data-test='current-price'], [data-testid='price'], .priceView-customer-price")
        price = price_value(price_node.get_text(" ", strip=True)) if price_node else None
        seller_node = card.select_one("[data-test='seller'], [data-testid='seller'], .seller")
        seller = seller_node.get_text(" ", strip=True)[:200] if seller_node else None
        status_text = card.get_text(" ", strip=True).lower()
        status = ("OUT_OF_STOCK" if "sold out" in status_text or "out of stock" in status_text
                  else "IN_STOCK" if "add to cart" in status_text or "add to bag" in status_text
                  else "UNKNOWN")
        date_node = card.select_one("time[datetime]")
        listings[product_id] = Listing(retailer, product_id, url, title, classify(title), price,
                                       status, seller, date_node.get("datetime") if date_node else None)
    return list(listings.values())


def fetch_source(source, session=None):
    validate_source(source.retailer, source.url)
    client = session or requests.Session()
    response = client.get(source.url, headers={"User-Agent": "PokemonStockMonitor/2.0 (personal inventory notifications)",
                                               "Accept": "text/html"}, timeout=(5, 15), allow_redirects=False)
    if response.status_code != 200 or "text/html" not in response.headers.get("Content-Type", "text/html"):
        raise ValueError(f"Source returned HTTP {response.status_code} or non-HTML content")
    if len(response.content) > 2_000_000:
        raise ValueError("Source page exceeds size limit")
    return parse_listings(source.retailer, source.url, response.text)


def scan(db, source, listings, notify=None):
    """Persist a complete scan; first successful scan is always silent."""
    now = utcnow()
    if not listings:
        raise ValueError("No product cards found; scan was not accepted as a baseline")
    baseline = not source.baseline_complete
    created = []
    for listing in listings:
        if listing.retailer != source.retailer:
            continue
        try:
            product_id, url = canonical(source.retailer, listing.url)
        except ValueError:
            continue
        if product_id != listing.retailer_product_id:
            continue
        seen = db.scalar(select(DiscoveredProduct).where(
            DiscoveredProduct.retailer == source.retailer,
            DiscoveredProduct.retailer_product_id == product_id))
        if seen:
            seen.last_seen_at = now
            seen.price, seen.status, seen.seller = listing.price, listing.status, listing.seller
            continue
        seen = DiscoveredProduct(source_id=source.id, retailer=source.retailer,
                                 retailer_product_id=product_id, url=url, title=listing.title[:200],
                                 product_type=listing.product_type, price=listing.price, status=listing.status,
                                 seller=listing.seller, release_date=listing.release_date,
                                 metadata_json=json.dumps(listing.metadata or {}), baseline=baseline)
        db.add(seen)
        db.flush()
        if listing.product_type:
            product = db.scalar(select(Product).where(Product.url == url))
            if product is None:
                product = Product(name=listing.title[:200], url=url, retailer=source.retailer,
                                  retailer_product_id=product_id, product_type=listing.product_type,
                                  seller=listing.seller, price=listing.price, next_check_at=now)
                db.add(product)
                db.flush()
            seen.product_id = product.id
        if not baseline:
            created.append(seen)
    source.baseline_complete = True
    source.last_scanned_at = now
    interval = max(300, int(os.getenv("DISCOVERY_INTERVAL_SECONDS", "1800")))
    source.next_scan_at = now + timedelta(seconds=interval)
    source.last_error = None
    db.commit()
    for item in created:
        if notify:
            notify(item)
    return created
