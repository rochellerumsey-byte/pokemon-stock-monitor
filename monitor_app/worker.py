"""Single polling worker. PostgreSQL advisory lock prevents duplicate workers."""
import logging
import os
import time
from datetime import timedelta

from sqlalchemy import delete, or_, select, text

from .adapters import Result, fetch
from .db import (AlertHistory, DiscoveredProduct, DiscoverySource, Product, PurchaseAttempt, PurchaseCandidate,
                 StatusHistory, WorkerState, make_engine, session_factory, utcnow)
from .service import RESTOCK_FROM, RESTOCK_TO, apply_result, resolve_adapter, send_discord, send_event
from . import discovery, purchase

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
log = logging.getLogger(__name__)
LOCK_ID = 706041321


def expire_bestbuy_content(db, now):
    """Best Buy API terms allow only temporary caching of product content."""
    cutoff = now - timedelta(hours=71)  # Leave margin for the worker cycle.
    stale = db.scalars(select(DiscoveredProduct).where(
        DiscoveredProduct.retailer == "Best Buy", DiscoveredProduct.last_seen_at < cutoff)).all()
    for item in stale:
        item.title = "Best Buy product data expired"
        item.product_type = item.price = item.seller = item.release_date = item.metadata_json = None
        item.status = "UNKNOWN"
    stale_products = db.scalars(select(Product).where(
        Product.retailer == "Best Buy",
        or_(Product.last_checked < cutoff,
            Product.last_checked.is_(None) & (Product.created_at < cutoff)))).all()
    for product in stale_products:
        if db.scalar(select(DiscoveredProduct.id).where(DiscoveredProduct.product_id == product.id)):
            product.name = f"Best Buy SKU {product.retailer_product_id}"
        product.observed_title = product.price = product.seller = product.product_type = None
        product.release_date = product.image_url = None
        product.price_confirmed = False
        product.status = "UNKNOWN"
        product.last_known_status = None
    db.execute(delete(StatusHistory).where(
        StatusHistory.checked_at < cutoff,
        StatusHistory.product_id.in_(select(Product.id).where(Product.retailer == "Best Buy"))))


def cycle(factory):
    now = utcnow()
    with factory() as db:
        state = db.get(WorkerState, 1)
        if state is None:
            state = WorkerState(id=1)
            db.add(state)
        state.heartbeat_at = now
        due = db.scalars(select(Product.id).where(Product.enabled.is_(True),
                 (Product.next_check_at.is_(None)) | (Product.next_check_at <= now))
                 .order_by(Product.next_check_at).limit(25)).all()
        db.commit()
    # Each source fails independently. An unparseable first scan never consumes its silent baseline.
    with factory() as db:
        sources = db.scalars(select(DiscoverySource.id).where(
            DiscoverySource.enabled.is_(True),
            (DiscoverySource.next_scan_at.is_(None)) | (DiscoverySource.next_scan_at <= now))
            .limit(10)).all()
    for source_id in sources:
        with factory() as db:
            source = db.get(DiscoverySource, source_id)
            try:
                listings = discovery.fetch_source(source)
                created = discovery.scan(db, source, listings)
                for item in created:
                    if not item.product_type:
                        continue
                    product = db.get(Product, item.product_id) if item.product_id else None
                    send_event(db, "NEW_PRODUCT", product,
                               f"🆕 **NEW PRODUCT**\n{item.title}\n{item.retailer}\n"
                               f"{item.price or 'Price unavailable'}\n{item.url}\n"
                               f"Seen: {item.first_seen_at:%Y-%m-%d %H:%M} UTC")
            except Exception as exc:
                db.rollback()
                source = db.get(DiscoverySource, source_id)
                source.last_error = str(exc)[:300]
                source.next_scan_at = utcnow() + timedelta(minutes=30)
                db.commit()
                log.exception("discovery_source_failed %s", source_id)
    # Recover a committed transition if the process stopped before delivery.
    with factory() as db:
        pending = db.scalars(select(AlertHistory).where(AlertHistory.detail == "Pending delivery").limit(25)).all()
        for attempt in pending:
            product = db.get(Product, attempt.product_id) if attempt.product_id else None
            history = db.get(StatusHistory, attempt.status_history_id) if attempt.status_history_id else None
            if product and history:
                send_discord(db, product, history)
    for product_id in due:
        with factory() as db:
            product = db.get(Product, product_id)
            if product is None or not product.enabled:
                continue
            try:
                _, adapter = resolve_adapter(db, product.url, product.retailer)
                result = fetch(product.url, adapter)
                history = apply_result(db, product, result)
                if result.status == "IN_STOCK":
                    try:
                        discovery_item = db.scalar(select(DiscoveredProduct).where(
                            DiscoveredProduct.product_id == product.id,
                            DiscoveredProduct.baseline.is_(False)).order_by(DiscoveredProduct.id.desc()))
                        event_key = (f"restock:{history.id}" if history and history.old_status in RESTOCK_FROM
                                     and history.new_status in RESTOCK_TO else
                                     f"discovery:{discovery_item.id}" if discovery_item else None)
                        if event_key and not db.scalar(select(PurchaseCandidate).where(
                                PurchaseCandidate.event_key == event_key)):
                            candidate = purchase.evaluate(db, product, event_key)
                            if candidate and candidate.status == "PENDING_APPROVAL":
                                send_event(db, "APPROVAL_REQUIRED", product,
                                           f"🔔 **APPROVAL REQUIRED**\n{product.name}\n{product.retailer}\n"
                                           f"{product.price}\n{product.url}\nReview in the dashboard.")
                            elif candidate and candidate.status == "AUTO_BLOCKED":
                                submitted = purchase.submit_candidate(db, candidate.id)
                                if submitted.status == "SUBMITTED":
                                    send_event(db, "PURCHASE_SUBMITTED", product,
                                               f"🧪 **SANDBOX PURCHASE SUBMITTED**\n{product.name}\n"
                                               f"{product.retailer}\n{product.price}\n{product.url}")
                                elif submitted.status == "SUBMISSION_UNKNOWN":
                                    send_event(db, "PURCHASE_FAILED", product,
                                               f"⚠️ **SANDBOX PURCHASE OUTCOME UNKNOWN**\n{product.name}\n"
                                               f"{product.retailer}\nCheck Zinc before retrying.\n{product.url}")
                    except Exception:
                        db.rollback()
                        log.exception("purchase_evaluation_failed %s", product_id)
                log.info("product_checked %s %s", product_id, result.status)
            except Exception:
                log.exception("product_check_failed %s", product_id)
                db.rollback()
                product = db.get(Product, product_id)
                if product:
                    apply_result(db, product, Result("ERROR", error="Internal check error"))
        with factory() as db:
            state = db.get(WorkerState, 1)
            state.heartbeat_at = utcnow()
            db.commit()
    with factory() as db:
        # A restart during an external request cannot infer whether Zinc accepted it.
        # Keep its idempotency key and require reconciliation instead of resubmitting.
        stranded = db.scalars(select(PurchaseCandidate).where(
            PurchaseCandidate.status == "SUBMITTING",
            PurchaseCandidate.submitted_at < utcnow() - timedelta(minutes=2))).all()
        for candidate in stranded:
            candidate.status = "SUBMISSION_UNKNOWN"
            candidate.error = "Submission interrupted; reconcile in Zinc before retrying"
            attempt = db.scalar(select(PurchaseAttempt).where(PurchaseAttempt.candidate_id == candidate.id))
            if attempt:
                attempt.status = "SUBMISSION_UNKNOWN"
                attempt.error = "Worker restarted during submission"
                attempt.completed_at = utcnow()
        db.commit()
        pending_orders = db.scalars(select(PurchaseCandidate).where(
            PurchaseCandidate.status.in_(("SUBMITTED", "IN_PROGRESS")),
            PurchaseCandidate.next_reconcile_at <= utcnow()).limit(20)).all()
        for candidate in pending_orders:
            before = candidate.status
            purchase.reconcile(db, candidate)
            if candidate.status in ("PLACED", "FAILED") and candidate.status != before:
                product = db.get(Product, candidate.product_id)
                send_event(db, "PURCHASED" if candidate.status == "PLACED" else "PURCHASE_FAILED",
                           product, f"🧪 **SANDBOX {candidate.status}**\n{product.name}\n"
                           f"{product.retailer}\nOrder: {candidate.provider_order_id}\n{product.url}")
    with factory() as db:
        state = db.get(WorkerState, 1)
        state.heartbeat_at = utcnow()
        state.last_cycle_at = state.heartbeat_at
        days = max(7, int(os.getenv("HISTORY_RETENTION_DAYS", "90")))
        cutoff = utcnow() - timedelta(days=days)
        expire_bestbuy_content(db, utcnow())
        db.execute(delete(AlertHistory).where(AlertHistory.attempted_at < cutoff))
        db.execute(delete(StatusHistory).where(StatusHistory.checked_at < cutoff))
        db.commit()


def main():
    engine = make_engine()
    factory = session_factory(engine)
    log.info("worker_start")
    if engine.dialect.name == "postgresql":
        while True:
            lock = engine.connect()
            try:
                if lock.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}):
                    lock.commit()
                    break
            except Exception:
                log.exception("worker_lock_attempt_failed")
            lock.close()
            log.info("worker_waiting_for_lock")
            time.sleep(15)
    else:
        lock = None
    try:
        while True:
            try:
                if lock is not None:
                    # A lost database connection also loses the session lock.
                    # Exit so the container supervisor restarts and reacquires it.
                    lock.execute(text("SELECT 1"))
                    lock.commit()
                cycle(factory)
            except Exception:
                log.exception("worker_cycle_failed")
                if lock is not None and lock.invalidated:
                    raise
            time.sleep(15)
    finally:
        if lock:
            if not lock.invalidated:
                lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
                lock.commit()
            lock.close()


if __name__ == "__main__":
    main()
