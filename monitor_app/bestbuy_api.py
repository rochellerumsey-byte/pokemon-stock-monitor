"""Best Buy's documented Products API. A missing key never falls back to page scraping."""
import os
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit

import requests

BASE = "https://api.bestbuy.com/v1"
FIELDS = ("sku,name,salePrice,priceRestriction,onlineAvailability,orderable,"
          "releaseDate,image,url,active,condition,preowned,secondaryMarket")
MAX_PAGES = 20


def sku_from_url(url):
    match = re.fullmatch(r"/(?:site/(?:[^/]+/)?|product/[^/]+/)(\d+)(?:\.p)?/?",
                         urlsplit(url).path, re.I)
    return match.group(1) if match else None


def sku_url(sku):
    return f"https://www.bestbuy.com/site/{sku}.p"


def source_filter(url):
    query = parse_qs(urlsplit(url).query)
    category = query.get("id", [""])[0]
    if re.fullmatch(r"pcmcat\d+", category):
        return f"categoryPath.id={category}"
    terms = re.findall(r"[a-z0-9]+", query.get("st", [""])[0].lower())
    if not 1 <= len(terms) <= 6 or any(len(term) > 30 for term in terms):
        raise ValueError("Best Buy API discovery needs a category URL with id=pcmcat... "
                         "or a search URL with st=keywords")
    return "&".join(f"search={term}" for term in terms)


def price(raw, restriction=None):
    if restriction or isinstance(raw, bool):
        return None
    try:
        amount = Decimal(str(raw))
        if amount <= 0 or amount.as_tuple().exponent < -2:
            return None
        return f"${amount:.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalized(item):
    """Return only supported fields; seller is not documented by this API."""
    sku = item.get("sku")
    if isinstance(sku, bool) or not re.fullmatch(r"\d{5,12}", str(sku)):
        return None
    sku = str(sku)
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    raw_date = item.get("releaseDate")
    try:
        release = date.fromisoformat(str(raw_date)[:10]) if raw_date else None
    except ValueError:
        release = None
    available = item.get("onlineAvailability")
    if item.get("active") is False:
        status = "UNAVAILABLE"
    elif item.get("orderable") is False and available is True:
        status = "UNKNOWN"  # Conflicting purchasability signals.
    elif available is True or available is False:
        if release and release > date.today():
            status = "COMING_SOON"  # Future release does not prove preorders are accepted.
        else:
            status = "IN_STOCK" if available is True else "OUT_OF_STOCK"
    else:
        status = "UNKNOWN"
    image = item.get("image")
    image_host = urlsplit(image).hostname if isinstance(image, str) else None
    if not isinstance(image, str) or urlsplit(image).scheme != "https" or not image_host or not (image_host == "bbystatic.com" or image_host.endswith(".bbystatic.com")):
        image = None
    # API click links expire; derive a stable public link from the SKU.
    return {"sku": sku, "url": sku_url(sku), "title": name.strip()[:200],
            "price": price(item.get("salePrice"), item.get("priceRestriction")),
            "status": status, "seller": None,
            "release_date": release.isoformat() if release else None,
            "image": image,
            "sealed_eligible": item.get("preowned") is not True and item.get("secondaryMarket") is not True
            and str(item.get("condition", "New")).lower() == "new"}


class BestBuyAPI:
    def __init__(self, key=None, session=None, pause=time.sleep):
        self.key = key if key is not None else os.getenv("BEST_BUY_API_KEY", "")
        if not self.key:
            raise ValueError("BEST_BUY_API_KEY is missing; obtain a Best Buy developer Products API key")
        self.session = session or requests.Session()
        self.pause = pause

    def _get(self, path, **params):
        params.update(apiKey=self.key, format="json")
        try:
            self.pause(0.25)  # Serial worker stays below the documented five-call-per-second limit.
            response = self.session.get(BASE + path, params=params, timeout=(5, 15), allow_redirects=False)
            if response.status_code != 200:
                raise ValueError(f"Best Buy API returned HTTP {response.status_code}; check key or quota")
            if len(response.content) > 4_000_000:
                raise ValueError("Best Buy API response exceeds size limit")
            payload = response.json()
        except requests.RequestException as exc:
            # Request exceptions may contain the query-string key; never expose their text.
            raise ValueError(f"Best Buy API request failed ({type(exc).__name__})") from None
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("Best Buy API"):
                raise
            raise ValueError("Best Buy API returned invalid JSON") from None
        if not isinstance(payload, dict) or payload.get("partial") is True:
            raise ValueError("Best Buy API returned an incomplete response")
        return payload

    def product(self, sku):
        if not re.fullmatch(r"\d{5,12}", str(sku)):
            raise ValueError("Best Buy product URL has no numeric SKU")
        return self._get(f"/products/{sku}.json", show=FIELDS)

    def discover(self, source_url):
        expression = source_filter(source_url)
        products = []
        cursor = "*"
        seen = set()
        for page in range(MAX_PAGES):
            data = self._get(f"/products({expression})", show=FIELDS, pageSize=100, cursorMark=cursor)
            batch = data.get("products")
            if not isinstance(batch, list) or not isinstance(data.get("total"), int):
                raise ValueError("Best Buy API returned an invalid product collection")
            products.extend(batch)
            next_cursor = data.get("nextCursorMark")
            if len(products) >= data["total"]:
                return products
            if not batch or not next_cursor or next_cursor == cursor or next_cursor in seen:
                raise ValueError("Best Buy API collection was incomplete; baseline remains pending")
            seen.add(cursor)
            cursor = next_cursor
        raise ValueError("Best Buy API collection exceeds scan limit; baseline remains pending")
