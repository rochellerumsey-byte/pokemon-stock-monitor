import os
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Retailer(Base):
    __tablename__ = "retailers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True)
    example_url: Mapped[str | None] = mapped_column(Text)
    in_stock_text: Mapped[str | None] = mapped_column(Text)
    out_of_stock_text: Mapped[str | None] = mapped_column(Text)
    stock_selector: Mapped[str | None] = mapped_column(String(255))
    price_selector: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text, unique=True)
    retailer: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    last_known_status: Mapped[str | None] = mapped_column(String(30))
    price: Mapped[str | None] = mapped_column(String(30))
    price_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    seller: Mapped[str | None] = mapped_column(String(200))
    retailer_product_id: Mapped[str | None] = mapped_column(String(100))
    product_type: Mapped[str | None] = mapped_column(String(50))
    observed_title: Mapped[str | None] = mapped_column(String(200))
    release_date: Mapped[str | None] = mapped_column(String(40))
    image_url: Mapped[str | None] = mapped_column(Text)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime)
    last_successful_check: Mapped[datetime | None] = mapped_column(DateTime)
    last_status_change: Mapped[datetime | None] = mapped_column(DateTime)
    last_alert: Mapped[datetime | None] = mapped_column(DateTime)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    history: Mapped[list["StatusHistory"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    alerts: Mapped[list["AlertHistory"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class StatusHistory(Base):
    __tablename__ = "status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30))
    price: Mapped[str | None] = mapped_column(String(30))
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    product: Mapped[Product] = relationship(back_populates="history")


class AlertHistory(Base):
    __tablename__ = "alert_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), index=True)
    status_history_id: Mapped[int | None] = mapped_column(ForeignKey("status_history.id", ondelete="SET NULL"), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    success: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str | None] = mapped_column(String(300))
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    product: Mapped[Product | None] = relationship(back_populates="alerts")


class WorkerState(Base):
    __tablename__ = "worker_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_cycle_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    purchases_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class DiscoverySource(Base):
    __tablename__ = "discovery_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    retailer: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(Text, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    baseline_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DiscoveredProduct(Base):
    __tablename__ = "discovered_products"
    __table_args__ = (UniqueConstraint("retailer", "retailer_product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("discovery_sources.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    retailer: Mapped[str] = mapped_column(String(100))
    retailer_product_id: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(200))
    product_type: Mapped[str | None] = mapped_column(String(50))
    price: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    seller: Mapped[str | None] = mapped_column(String(200))
    release_date: Mapped[str | None] = mapped_column(String(40))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PurchaseRule(Base):
    __tablename__ = "purchase_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str] = mapped_column(String(10), default="MONITOR")
    retailers: Mapped[str] = mapped_column(String(300), default="")
    product_types: Mapped[str] = mapped_column(String(500), default="")
    title_include: Mapped[str] = mapped_column(String(300), default="")
    title_exclude: Mapped[str] = mapped_column(String(300), default="")
    max_item_cents: Mapped[int] = mapped_column(Integer)
    max_order_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    retailer_direct_only: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_spend_cents: Mapped[int] = mapped_column(Integer)
    lifetime_sku_quantity: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PurchaseCandidate(Base):
    __tablename__ = "purchase_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(100), unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("purchase_rules.id"))
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30), default="PENDING_APPROVAL")
    price_cents: Mapped[int] = mapped_column(Integer)
    reserved_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(36), unique=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_status: Mapped[str | None] = mapped_column(String(50))
    provider_total_cents: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_reconcile_at: Mapped[datetime | None] = mapped_column(DateTime)


class PurchaseEvent(Base):
    __tablename__ = "purchase_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("purchase_candidates.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PurchaseAttempt(Base):
    __tablename__ = "purchase_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("purchase_candidates.id"), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(30))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("purchase_candidates.id"), unique=True)
    provider_order_id: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(50))
    total_cents: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def make_engine(url=None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///monitor.db")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
