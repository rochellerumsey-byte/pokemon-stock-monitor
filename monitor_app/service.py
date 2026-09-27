"""Product validation, state transitions, and Discord notifications."""
import logging
import os
import random
from datetime import timedelta

import requests
from sqlalchemy import select

from .adapters import ADAPTERS, Generic, Result, detect, hostname, belongs, public_host
from .db import AlertHistory, Product, Retailer, StatusHistory, utcnow

log = logging.getLogger(__name__)
RESTOCK_FROM = {"OUT_OF_STOCK", "COMING_SOON"}
RESTOCK_TO = {"IN_STOCK", "PREORDER"}


def resolve_adapter(db, url, selected=None):
    host = hostname(url)
    retailer_list = db.scalars(select(Retailer)).all()
    name = detect(url, retailer_list)
    if not name or (selected and selected != name):
        raise ValueError("URL does not match an enabled retailer")
    if not public_host(host):
        raise ValueError("Product URL must resolve to a public address")
    if name in ADAPTERS:
        return name, ADAPTERS[name]
    config = next(r for r in retailer_list if r.name == name)
    return name, Generic(config)


def add_product(db, name, url, selected=None):
    name, url = name.strip(), url.strip()
    if not name or len(name) > 200:
        raise ValueError("Enter a friendly name up to 200 characters")
    retailer, _ = resolve_adapter(db, url, selected)
    if db.scalar(select(Product).where(Product.url == url)):
        raise ValueError("Product URL is already monitored")
    item = Product(name=name, url=url, retailer=retailer, next_check_at=utcnow())
    db.add(item)
    db.commit()
    return item


def add_retailer(db, name, domain, example_url, in_text, out_text, stock_selector, price_selector):
    name, domain = name.strip(), domain.strip().lower().rstrip(".")
    if not name or len(name) > 100 or not domain or "/" in domain or ":" in domain:
        raise ValueError("Enter a valid retailer name and domain")
    if name in ADAPTERS or db.scalar(select(Retailer).where((Retailer.name == name) | (Retailer.domain == domain))):
        raise ValueError("Retailer name or domain already exists")
    if not in_text.strip() or not out_text.strip() or not stock_selector.strip():
        raise ValueError("Both indicators and a product-specific CSS selector are required")
    if len(in_text) > 1000 or len(out_text) > 1000 or len(stock_selector) > 255 or len(price_selector) > 255:
        raise ValueError("Retailer configuration is too long")
    from bs4 import BeautifulSoup
    try:
        BeautifulSoup("<main></main>", "html.parser").select(stock_selector)
        if price_selector:
            BeautifulSoup("<main></main>", "html.parser").select(price_selector)
    except Exception as exc:
        raise ValueError("Invalid CSS selector") from exc
    if example_url:
        if not belongs(hostname(example_url), domain):
            raise ValueError("Example URL must match the retailer domain")
    if not public_host(domain):
        raise ValueError("Retailer domain must resolve publicly")
    config = Retailer(name=name, domain=domain, example_url=example_url or None,
                      in_stock_text=in_text, out_of_stock_text=out_text,
                      stock_selector=stock_selector, price_selector=price_selector or None)
    db.add(config)
    db.commit()
    return config


def discord_payload(product, status, at=None, test=False):
    at = at or utcnow()
    label = "TEST NOTIFICATION" if test else "RESTOCK / " + status.replace("_", " ")
    fields = [
        {"name": "Retailer", "value": product.retailer, "inline": True},
        {"name": "Status", "value": status.replace("_", " "), "inline": True},
    ]
    if product.price:
        fields.append({"name": "Price", "value": product.price, "inline": True})
    return {
        "content": f"🚨 **{label}**: {product.name}\n**Product link:** {product.url}",
        "embeds": [{
            "title": product.name, "url": product.url, "color": 0x2F8F46,
            "fields": fields, "timestamp": at.isoformat() + "Z",
        }],
        "allowed_mentions": {"parse": []},
    }


def send_discord(db, product=None, history=None, test=False, post=None):
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        detail, success = "Discord webhook is not configured", False
    else:
        try:
            sender = post or requests.post
            payload = discord_payload(product, product.status if product else "IN_STOCK", test=test) if product else {
                "content": "✅ Pokemon Stock Monitor TEST notification", "allowed_mentions": {"parse": []}}
            response = sender(webhook, json=payload, timeout=10)
            success = 200 <= response.status_code < 300
            detail = "Delivered" if success else f"Discord HTTP {response.status_code}"
        except requests.RequestException as exc:
            success, detail = False, type(exc).__name__
    attempt = db.scalar(select(AlertHistory).where(AlertHistory.status_history_id == history.id)) if history else None
    if attempt:
        attempt.success = success
        attempt.detail = detail
        attempt.attempted_at = utcnow()
    else:
        db.add(AlertHistory(product_id=product.id if product else None,
                            status_history_id=history.id if history else None,
                            kind="TEST" if test else "RESTOCK", success=success, detail=detail))
    if product and success:
        product.last_alert = utcnow()
    db.commit()
    log.info("discord_attempt", extra={"success": success, "detail": detail})
    return success, detail


def apply_result(db, product, result: Result, now=None, send=None):
    now = now or utcnow()
    old = product.last_known_status
    product.last_checked = now
    product.status = result.status
    product.error = result.error
    alert_history = None
    if result.status in ("ERROR", "UNKNOWN"):
        product.failure_count += 1
    else:
        product.failure_count = 0
        product.last_successful_check = now
        if result.price:
            product.price = result.price
        if result.status != old:
            alert_history = StatusHistory(product=product, old_status=old, new_status=result.status,
                                          price=product.price, checked_at=now)
            db.add(alert_history)
            product.last_status_change = now
        product.last_known_status = result.status
    base = max(300, int(os.getenv("CHECK_INTERVAL_SECONDS", "900")))
    if product.retailer == "Amazon":
        base = max(base, 86400)
    elif product.retailer in ("Target", "Pokemon Center"):
        base = max(base, 1200)
    if result.retry_after:
        delay = max(base, result.retry_after)
    elif result.status in ("ERROR", "UNKNOWN"):
        delay = min(86400, base * 2 ** min(product.failure_count, 6))
    else:
        delay = base
    product.next_check_at = now + timedelta(seconds=delay + random.uniform(0, min(120, delay * 0.1)))
    db.flush()
    if alert_history and old in RESTOCK_FROM and result.status in RESTOCK_TO:
        db.add(AlertHistory(product_id=product.id, status_history_id=alert_history.id,
                            kind="RESTOCK", success=False, detail="Pending delivery"))
    db.commit()
    if alert_history and old in RESTOCK_FROM and result.status in RESTOCK_TO:
        (send or send_discord)(db, product, alert_history)
    return alert_history
