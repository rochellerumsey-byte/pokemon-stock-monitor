"""Rule evaluation and Zinc test-mode order boundary. Live keys are never accepted."""
import os
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import (Product, PurchaseAttempt, PurchaseCandidate, PurchaseEvent, PurchaseOrder,
                 PurchaseRule, WorkerState, utcnow)

OPEN_STATUSES = {"PENDING_APPROVAL", "SUBMITTING", "SUBMISSION_UNKNOWN", "SUBMITTED", "IN_PROGRESS", "PLACED"}
SPEND_STATUSES = {"SUBMITTING", "SUBMISSION_UNKNOWN", "SUBMITTED", "IN_PROGRESS", "PLACED"}
FINAL_PROVIDER = {"order_placed": "PLACED", "order_failed": "FAILED", "cancelled": "FAILED",
                  "cancelled_by_retailer": "FAILED"}
ADDRESS_FIELDS = ("FIRST_NAME", "LAST_NAME", "ADDRESS_LINE1", "CITY", "STATE", "POSTAL_CODE", "PHONE_NUMBER")


def cents(price):
    try:
        value = Decimal(str(price).replace("$", "").replace(",", ""))
        if value <= 0 or value.as_tuple().exponent < -2:
            return None
        return int(value * 100)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _terms(raw):
    return {term.strip().casefold() for term in (raw or "").split(",") if term.strip()}


def rule_matches(rule, product):
    """Fail closed on missing identity, seller, availability, or price."""
    price = cents(product.price)
    if not rule.enabled or not product.enabled or product.status != "IN_STOCK" or price is None or not product.price_confirmed:
        return False, "Product is not confirmed in stock with a valid price"
    if not product.retailer_product_id or not product.observed_title or not product.product_type or not product.seller:
        return False, "Product identity, type, or seller is unconfirmed"
    if rule.retailers and product.retailer.casefold() not in _terms(rule.retailers):
        return False, "Retailer is not allowed"
    if rule.product_types and product.product_type.casefold() not in _terms(rule.product_types):
        return False, "Product type is not allowed"
    title = product.observed_title.casefold()
    if _terms(rule.title_include) and not any(x in title for x in _terms(rule.title_include)):
        return False, "Title does not include a required term"
    if any(x in title for x in _terms(rule.title_exclude)):
        return False, "Title contains an excluded term"
    if rule.retailer_direct_only and product.seller.casefold() != product.retailer.casefold():
        return False, "Marketplace seller is not allowed"
    if price > rule.max_item_cents or price * rule.quantity > rule.max_order_cents:
        return False, "Item or order price exceeds the rule"
    return True, "Matched"


def budget_allows(db, rule, product, *, exclude_id=None):
    """Reserve the full order ceiling for ambiguous shipping/tax and pending orders."""
    day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = db.scalars(select(PurchaseCandidate).where(
        PurchaseCandidate.rule_id == rule.id,
        PurchaseCandidate.status.in_(OPEN_STATUSES))).all()
    spent = sum(c.reserved_cents for c in candidates if c.id != exclude_id and
                (c.created_at >= day or c.status != "PLACED"))
    if spent + rule.max_order_cents > rule.daily_spend_cents:
        return False, "Daily spend ceiling reached"
    sku = db.scalars(select(PurchaseCandidate).join(Product, PurchaseCandidate.product_id == Product.id).where(
        Product.retailer == product.retailer,
        Product.retailer_product_id == product.retailer_product_id,
        PurchaseCandidate.status.in_(OPEN_STATUSES))).all()
    if any(c.id != exclude_id for c in sku):
        return False, "A candidate or order already exists for this SKU"
    if rule.lifetime_sku_quantity is not None:
        used = sum(c.quantity for c in db.scalars(select(PurchaseCandidate).join(
            Product, PurchaseCandidate.product_id == Product.id).where(
            PurchaseCandidate.rule_id == rule.id,
            Product.retailer == product.retailer,
            Product.retailer_product_id == product.retailer_product_id,
            PurchaseCandidate.status.in_(SPEND_STATUSES))).all() if c.id != exclude_id)
        if used + rule.quantity > rule.lifetime_sku_quantity:
            return False, "Lifetime SKU quantity ceiling reached"
    return True, "Within limits"


def evaluate(db, product, event_key):
    existing = db.scalar(select(PurchaseCandidate).where(PurchaseCandidate.event_key == event_key))
    if existing:
        return existing
    for rule in db.scalars(select(PurchaseRule).where(PurchaseRule.enabled.is_(True)).order_by(PurchaseRule.id)):
        matched, _ = rule_matches(rule, product)
        if not matched or rule.mode == "MONITOR":
            continue
        allowed, _ = budget_allows(db, rule, product)
        if not allowed:
            continue
        status = "PENDING_APPROVAL" if rule.mode == "APPROVAL" else "AUTO_BLOCKED"
        candidate = PurchaseCandidate(event_key=event_key, product_id=product.id, rule_id=rule.id,
                                      mode=rule.mode, status=status, price_cents=cents(product.price),
                                      reserved_cents=rule.max_order_cents, quantity=rule.quantity,
                                      idempotency_key=str(uuid.uuid4()))
        db.add(candidate)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return db.scalar(select(PurchaseCandidate).where(PurchaseCandidate.event_key == event_key))
        db.add(PurchaseEvent(candidate_id=candidate.id, kind=status))
        db.commit()
        return candidate
    return None


def sandbox_ready(env=None):
    env = env or os.environ
    key = env.get("ZINC_API_KEY", "")
    missing = [f"ZINC_SHIPPING_{field}" for field in ADDRESS_FIELDS
               if not env.get(f"ZINC_SHIPPING_{field}")]
    if not key.startswith("zn_test_"):
        return False, "A Zinc test-mode key (zn_test_) is required"
    if missing:
        return False, "Missing sandbox shipping settings: " + ", ".join(missing)
    return True, "Zinc test mode configured"


class PurchaseProvider:
    def submit(self, product, candidate, rule):
        raise NotImplementedError

    def get_order(self, order_id):
        raise NotImplementedError


class ZincPurchaseProvider(PurchaseProvider):
    base_url = "https://api.zinc.com"

    def __init__(self, env=None, session=None):
        self.env = env or os.environ
        self.session = session or requests.Session()
        ready, detail = sandbox_ready(self.env)
        if not ready:
            raise ValueError(detail)

    def _headers(self):
        return {"Authorization": "Bearer " + self.env["ZINC_API_KEY"], "Content-Type": "application/json"}

    def submit(self, product, candidate, rule):
        address = {name.lower(): self.env[f"ZINC_SHIPPING_{name}"] for name in ADDRESS_FIELDS}
        address["country"] = "US"
        payload = {"products": [{"url": product.url, "quantity": candidate.quantity,
                                 "condition_in": ["New"]}],
                   "shipping_address": address, "max_price": candidate.reserved_cents,
                   "idempotency_key": candidate.idempotency_key,
                   "metadata": {"monitor_candidate_id": str(candidate.id)}}
        response = self.session.post(self.base_url + "/orders", json=payload,
                                     headers=self._headers(), timeout=(5, 20))
        response.raise_for_status()
        data = response.json()
        if not data.get("id"):
            raise ValueError("Zinc response had no order ID")
        return data

    def get_order(self, order_id):
        response = self.session.get(self.base_url + "/orders/" + order_id,
                                    headers=self._headers(), timeout=(5, 20))
        response.raise_for_status()
        return response.json()


def record(db, candidate, kind, detail=None):
    candidate.updated_at = utcnow()
    db.add(PurchaseEvent(candidate_id=candidate.id, kind=kind, detail=detail))
    db.commit()


def submit_candidate(db, candidate_id, provider=None):
    """Commit an irreversible attempt marker before external I/O; unknown responses never retry."""
    candidate = db.scalar(select(PurchaseCandidate).where(PurchaseCandidate.id == candidate_id).with_for_update())
    if not candidate or candidate.status not in ("APPROVED", "AUTO_BLOCKED"):
        return candidate
    rule = db.get(PurchaseRule, candidate.rule_id)
    product = db.get(Product, candidate.product_id)
    state = db.get(WorkerState, 1)
    ready, reason = sandbox_ready()
    matched, why = rule_matches(rule, product)
    allowed, cap_reason = budget_allows(db, rule, product, exclude_id=candidate.id)
    if not (state and state.purchases_enabled and ready and matched and allowed):
        candidate.status = "BLOCKED"
        record(db, candidate, "BLOCKED", next((x for x in (reason if not ready else None,
                                                          why if not matched else None,
                                                          cap_reason if not allowed else None)
                                                 if x), "Purchases are switched off"))
        return candidate
    candidate.status = "SUBMITTING"
    candidate.submitted_at = utcnow()
    candidate.price_cents = cents(product.price)
    candidate.reserved_cents = rule.max_order_cents
    attempt = PurchaseAttempt(candidate_id=candidate.id, idempotency_key=candidate.idempotency_key,
                              status="SUBMITTING")
    db.add(attempt)
    record(db, candidate, "SUBMITTING", "Zinc test mode only")
    try:
        data = (provider or ZincPurchaseProvider()).submit(product, candidate, rule)
        if not data.get("id"):
            raise ValueError("Zinc response had no order ID")
    except Exception as exc:
        candidate.status = "SUBMISSION_UNKNOWN"
        candidate.error = "Submission result unknown; reconcile in Zinc before retrying"
        attempt.status = "SUBMISSION_UNKNOWN"
        attempt.error = type(exc).__name__
        attempt.completed_at = utcnow()
        record(db, candidate, "PURCHASE_FAILED", type(exc).__name__)
        return candidate
    candidate.provider_order_id = data["id"]
    candidate.provider_status = data.get("status", "pending")
    candidate.status = "SUBMITTED"
    candidate.next_reconcile_at = utcnow() + timedelta(minutes=7)
    attempt.status = "SUBMITTED"
    attempt.completed_at = utcnow()
    db.add(PurchaseOrder(candidate_id=candidate.id, provider_order_id=data["id"],
                         status=candidate.provider_status))
    record(db, candidate, "PURCHASE_SUBMITTED", candidate.provider_status)
    return candidate


def reconcile(db, candidate, provider=None):
    if not candidate.provider_order_id or candidate.status not in ("SUBMITTED", "IN_PROGRESS"):
        return candidate
    try:
        data = (provider or ZincPurchaseProvider()).get_order(candidate.provider_order_id)
        status = data.get("status", "")
        candidate.provider_status = status
        candidate.status = FINAL_PROVIDER.get(status, "IN_PROGRESS")
        components = (data.get("job_result") or {}).get("price_components") or {}
        total = components.get("total")
        candidate.provider_total_cents = total if isinstance(total, int) and total >= 0 else None
        candidate.next_reconcile_at = (None if status in FINAL_PROVIDER
                                       else utcnow() + timedelta(minutes=5))
        raw_error = ((data.get("job_result") or {}).get("error") if candidate.status == "FAILED" else None)
        candidate.error = str(raw_error)[:300] if raw_error else None
        order = db.scalar(select(PurchaseOrder).where(PurchaseOrder.candidate_id == candidate.id))
        if order:
            order.status = status
            order.total_cents = candidate.provider_total_cents
            order.error = candidate.error
            order.updated_at = utcnow()
        record(db, candidate, "PURCHASED" if candidate.status == "PLACED" else
               "PURCHASE_FAILED" if candidate.status == "FAILED" else "RECONCILED", status)
    except Exception as exc:
        candidate.next_reconcile_at = utcnow() + timedelta(minutes=5)
        record(db, candidate, "RECONCILE_ERROR", type(exc).__name__)
    return candidate
