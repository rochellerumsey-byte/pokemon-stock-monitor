import os
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, event
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
