"""Single polling worker. PostgreSQL advisory lock prevents duplicate workers."""
import logging
import os
import time
from datetime import timedelta

from sqlalchemy import delete, select, text

from .adapters import Result, fetch
from .db import AlertHistory, Product, StatusHistory, WorkerState, make_engine, session_factory, utcnow
from .service import apply_result, resolve_adapter, send_discord

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
log = logging.getLogger(__name__)
LOCK_ID = 706041321


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
                apply_result(db, product, result)
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
        state = db.get(WorkerState, 1)
        state.heartbeat_at = utcnow()
        state.last_cycle_at = state.heartbeat_at
        days = max(7, int(os.getenv("HISTORY_RETENTION_DAYS", "90")))
        cutoff = utcnow() - timedelta(days=days)
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
