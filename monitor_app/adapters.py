"""Public page adapters. Ambiguous pages are deliberately UNKNOWN."""
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

STATUSES = {"UNKNOWN", "OUT_OF_STOCK", "IN_STOCK", "PREORDER", "COMING_SOON", "UNAVAILABLE", "ERROR"}
BUILTINS = {
    "Target": ("target.com",),
    "Best Buy": ("bestbuy.com",),
    "Pokemon Center": ("pokemoncenter.com",),
    "GameStop": ("gamestop.com",),
    "Amazon": ("amazon.com",),
}


@dataclass(frozen=True)
class Result:
    status: str
    name: str | None = None
    price: str | None = None
    error: str | None = None
    retry_after: int | None = None
    seller: str | None = None


def hostname(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.port:
        raise ValueError("Use a public HTTP(S) product URL without credentials or a custom port")
    host = (parsed.hostname or "").lower().rstrip(".")
    if len(url) > 1500:
        raise ValueError("Product URL is too long; use a shorter direct product link")
    if not host or "." not in host:
        raise ValueError("Invalid product URL")
    return host


def belongs(host, domain):
    return host == domain or host.endswith("." + domain)


def public_host(host):
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (OSError, ValueError):
        return False


def detect(url, retailers=()):
    host = hostname(url)
    for name, domains in BUILTINS.items():
        if any(belongs(host, d) for d in domains):
            return name
    for retailer in retailers:
        if retailer.enabled and belongs(host, retailer.domain.lower()):
            return retailer.name
    return None


def normalize(value):
    value = str(value).rsplit("/", 1)[-1].replace("_", "").replace("-", "").lower()
    return {
        "instock": "IN_STOCK",
        "limitedavailability": "IN_STOCK",
        "outofstock": "OUT_OF_STOCK",
        "soldout": "OUT_OF_STOCK",
        "preorder": "PREORDER",
        "presale": "PREORDER",
        "discontinued": "UNAVAILABLE",
    }.get(value, "UNKNOWN")


def price_value(raw):
    if raw is None:
        return None
    match = re.search(r"(?:\$\s*)?(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)", str(raw))
    return "$" + match.group(1).replace(",", "") if match else None


def _products(node):
    if isinstance(node, list):
        for item in node:
            yield from _products(item)
    elif isinstance(node, dict):
        typ = node.get("@type", "")
        if "Product" in (typ if isinstance(typ, list) else [typ]):
            yield node
        for key in ("@graph", "mainEntity"):
            if key in node:
                yield from _products(node[key])


def structured(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for product in _products(data):
            offers = product.get("offers")
            if isinstance(offers, list):
                offers = next((o for o in offers if isinstance(o, dict) and o.get("availability")), offers[0] if offers else None)
            if not isinstance(offers, dict):
                continue
            status = normalize(offers.get("availability", ""))
            if status != "UNKNOWN":
                seller = offers.get("seller")
                if isinstance(seller, dict):
                    seller = seller.get("name")
                return Result(status, product.get("name"), price_value(offers.get("price")),
                              seller=str(seller)[:200] if seller else None)
    return None


class Adapter:
    name = ""
    in_text = ("add to cart", "add to bag")
    out_text = ("out of stock", "sold out")
    selector = "main button, [role=main] button, button.add-to-cart, button[data-button-state]"

    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        if not soup.select("body") or len(soup.get_text(" ", strip=True)) < 10:
            return Result("UNKNOWN", error="Empty or unexpected product page")
        title = soup.select_one("h1")
        title = title.get_text(" ", strip=True) if title else None
        found = structured(soup)
        if found:
            return Result(found.status, title or found.name, found.price)
        controls = soup.select(self.selector)
        signals = set()
        for control in controls:
            label = control.get_text(" ", strip=True).lower()
            if any(x in label for x in self.in_text) and not control.has_attr("disabled") and control.get("aria-disabled") != "true":
                signals.add("IN_STOCK")
            if any(x in label for x in self.out_text):
                signals.add("OUT_OF_STOCK")
            if "preorder" in label or "pre-order" in label:
                signals.add("PREORDER")
            if "coming soon" in label:
                signals.add("COMING_SOON")
        status = next(iter(signals)) if len(signals) == 1 else "UNKNOWN"
        price = soup.select_one('[itemprop="price"], [data-testid="price"]')
        raw_price = price.get("content") if price and price.get("content") else price.get_text(" ", strip=True) if price else None
        return Result(status, title, price_value(raw_price), None if status != "UNKNOWN" else "No unambiguous primary product signal")


class Target(Adapter):
    name = "Target"
    selector = 'main button, [data-test="shipItButton"], [data-test="addToCartButton"]'


class BestBuy(Adapter):
    name = "Best Buy"
    selector = 'main button, button[data-button-state], .fulfillment-add-to-cart-button button'


class PokemonCenter(Adapter):
    name = "Pokemon Center"
    selector = 'main button, .product-add-to-cart button, button.add-to-cart'


class GameStop(Adapter):
    name = "GameStop"
    selector = 'main button, button.add-to-cart, [data-testid="add-to-cart"]'


class Amazon(Adapter):
    name = "Amazon"

    def parse(self, html):
        return Result("UNAVAILABLE", error="Amazon public pages are unsupported for reliable monitoring")


class Generic(Adapter):
    def __init__(self, config):
        self.name = config.name
        self.config = config
        self.selector = config.stock_selector or "main button"

    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        try:
            nodes = soup.select(self.selector)
            area = " ".join(n.get_text(" ", strip=True) for n in nodes).lower()
            price_node = soup.select_one(self.config.price_selector) if self.config.price_selector else None
        except Exception:
            return Result("ERROR", error="Invalid CSS selector; custom adapter may be required")
        if not nodes:
            return Result("UNKNOWN", error="Configured selector found no product element; custom adapter may be required")
        ins = [x.strip().lower() for x in (self.config.in_stock_text or "").splitlines() if x.strip()]
        outs = [x.strip().lower() for x in (self.config.out_of_stock_text or "").splitlines() if x.strip()]
        yes = any(x in area for x in ins)
        no = any(x in area for x in outs)
        status = "IN_STOCK" if yes and not no else "OUT_OF_STOCK" if no and not yes else "UNKNOWN"
        title = soup.select_one("h1")
        return Result(status, title.get_text(" ", strip=True) if title else None,
                      price_value(price_node.get_text(" ", strip=True)) if price_node else None,
                      None if status != "UNKNOWN" else "Generic indicators ambiguous; custom adapter may be required")


ADAPTERS = {x.name: x() for x in (Target, BestBuy, PokemonCenter, GameStop, Amazon)}


def fetch(url, adapter, session=None):
    host = hostname(url)
    if not public_host(host):
        return Result("ERROR", error="Product host does not resolve to a public address")
    if isinstance(adapter, Amazon):
        return Result("UNAVAILABLE", error="Amazon public pages are unsupported for reliable monitoring")
    session = session or requests.Session()
    retry = Retry(total=1, backoff_factor=1, status_forcelist=(500, 502, 503, 504), respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    try:
        response = session.get(url, headers={"User-Agent": "PokemonStockMonitor/1.0 (personal stock notifications)", "Accept": "text/html"},
                               timeout=(5, 15), allow_redirects=False)
        if response.status_code == 429:
            raw = response.headers.get("Retry-After", "")
            delay = int(raw) if raw.isdigit() else 1800
            return Result("ERROR", error="Rate limited (HTTP 429)", retry_after=min(max(delay, 300), 86400))
        if response.status_code in (301, 302, 303, 307, 308):
            return Result("UNKNOWN", error="Redirect requires review")
        if response.status_code != 200:
            return Result("ERROR", error=f"HTTP {response.status_code}")
        if "text/html" not in response.headers.get("Content-Type", "text/html"):
            return Result("UNKNOWN", error="Unexpected content type")
        if len(response.content) > 2_000_000:
            return Result("ERROR", error="Page exceeds size limit")
        # Retailer scripts may mention CAPTCHA even on a real product page.
        page = BeautifulSoup(response.text, "html.parser")
        title = page.title.get_text(" ", strip=True).lower() if page.title else ""
        if any(x in title for x in ("captcha", "access denied", "verify you are human")) or (
            not page.select_one("h1") and any(x in page.get_text(" ", strip=True).lower()[:500]
                                             for x in ("captcha", "access denied", "verify you are human"))
        ):
            return Result("UNKNOWN", error="Retailer challenge or access restriction")
        return adapter.parse(response.text)
    except requests.RequestException as exc:
        return Result("ERROR", error=type(exc).__name__)
