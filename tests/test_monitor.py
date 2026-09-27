import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ADMIN_PASSWORD", "long-test-password-12345")
os.environ.setdefault("SECRET_KEY", "long-test-secret-key-123456789012345")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from monitor_app import adapters, service
from monitor_app.db import AlertHistory, Base, Product, Retailer, StatusHistory, WorkerState, make_engine, session_factory, utcnow
from monitor_app.web import create_app
from monitor_app.worker import cycle

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield session_factory(engine)
    engine.dispose()


def test_detection_and_url_guard():
    assert adapters.detect("https://www.target.com/p/item") == "Target"
    assert adapters.detect("https://target.com.evil.example/p/item") is None
    assert adapters.detect("https://www.bestbuy.com/site/item") == "Best Buy"
    assert adapters.detect("https://www.pokemoncenter.com/product/item") == "Pokemon Center"
    assert adapters.detect("https://www.gamestop.com/item") == "GameStop"
    assert adapters.detect("https://www.amazon.com/dp/item") == "Amazon"
    with pytest.raises(ValueError):
        adapters.hostname("http://user:pass@target.com/item")
    assert adapters.normalize("https://schema.org/PreOrder") == "PREORDER"
    assert adapters.normalize("mystery") == "UNKNOWN"


@pytest.mark.parametrize("name,fixture,status,price", [
    ("Target", "target.html", "IN_STOCK", "$49.99"),
    ("Best Buy", "bestbuy.html", "OUT_OF_STOCK", "$29.99"),
    ("Pokemon Center", "pokemoncenter.html", "PREORDER", "$59.99"),
    ("GameStop", "gamestop.html", "OUT_OF_STOCK", "$19.99"),
    ("Amazon", "amazon.html", "UNAVAILABLE", None),
])
def test_retailer_fixtures(name, fixture, status, price):
    result = adapters.ADAPTERS[name].parse((FIXTURES / fixture).read_text(encoding="utf-8"))
    assert (result.status, result.price) == (status, price)


def test_ambiguous_and_generic():
    assert adapters.ADAPTERS["Target"].parse("<html><body><main>Product details available here</main></body></html>").status == "UNKNOWN"
    config = SimpleNamespace(name="Example", stock_selector="main .offer", price_selector=".price",
                             in_stock_text="ready to ship", out_of_stock_text="sold out")
    adapter = adapters.Generic(config)
    result = adapter.parse("<main><h1>Deck</h1><div class='offer'>Ready to ship</div><b class='price'>$12.50</b></main>")
    assert (result.status, result.price) == ("IN_STOCK", "$12.50")
    assert adapter.parse("<main><div class='offer'>Ready to ship and sold out</div></main>").status == "UNKNOWN"
    assert adapter.parse("<main>no offer</main>").status == "UNKNOWN"


def test_fetch_rate_limit_and_block(monkeypatch):
    monkeypatch.setattr(adapters, "public_host", lambda _: True)
    class FakeSession:
        def mount(self, *args): pass
        def get(self, *args, **kwargs):
            assert kwargs["allow_redirects"] is False
            return SimpleNamespace(status_code=429, headers={"Retry-After": "600"})
    result = adapters.fetch("https://www.target.com/p/item", adapters.ADAPTERS["Target"], FakeSession())
    assert result.status == "ERROR" and result.retry_after == 600
    assert adapters.fetch("https://www.amazon.com/dp/item", adapters.ADAPTERS["Amazon"]).status == "UNAVAILABLE"


def test_transition_restart_dedup_and_persistence(factory):
    sent = []
    def fake_send(db, product, history):
        sent.append((product.id, history.id))
    with factory() as db:
        product = Product(name="Cards", url="https://www.target.com/p/cards", retailer="Target")
        db.add(product)
        db.commit()
        service.apply_result(db, product, adapters.Result("IN_STOCK", price="$49.99"), send=fake_send)
        assert not sent
        service.apply_result(db, product, adapters.Result("OUT_OF_STOCK"), send=fake_send)
        service.apply_result(db, product, adapters.Result("ERROR", error="HTTP 500"), send=fake_send)
        assert product.last_known_status == "OUT_OF_STOCK"
        product_id = product.id
    with factory() as db:
        product = db.get(Product, product_id)
        assert product.price == "$49.99"
        service.apply_result(db, product, adapters.Result("IN_STOCK"), send=fake_send)
        service.apply_result(db, product, adapters.Result("IN_STOCK"), send=fake_send)
        assert len(sent) == 1
        assert db.scalar(select(func.count()).select_from(StatusHistory)) == 3


def test_discord_payload_and_attempt(factory, monkeypatch):
    product = Product(id=1, name="Cards", url="https://www.target.com/p/cards", retailer="Target",
                      status="IN_STOCK", price="$49.99")
    payload = service.discord_payload(product, "IN_STOCK")
    assert "RESTOCK" in payload["content"] and product.url in payload["content"]
    assert payload["embeds"][0]["fields"][-1]["value"] == "$49.99"
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    with factory() as db:
        ok, _ = service.send_discord(db, test=True, post=lambda *a, **k: SimpleNamespace(status_code=204))
        assert ok
        assert db.scalar(select(func.count()).select_from(AlertHistory)) == 1


def test_web_crud_auth_health(factory, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "public_host", lambda _: True)
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}", testing=True)
    client = app.test_client()
    assert client.get("/").status_code == 302
    assert client.post("/products", data={}).status_code == 302
    assert client.get("/health").status_code == 503
    token = client.get("/login").text.split('name="csrf" value="')[1].split('"')[0]
    assert client.post("/login", data={"csrf": token, "password": "wrong"}).status_code == 200
    assert client.post("/login", data={"csrf": token, "password": os.environ["ADMIN_PASSWORD"]}).status_code == 302
    token = client.get("/").text.split('name="csrf" value="')[1].split('"')[0]
    response = client.post("/products", data={"csrf": token, "name": "Cards",
        "url": "https://www.target.com/p/cards", "retailer": ""})
    assert response.status_code == 302
    with factory() as db:
        item = db.scalar(select(Product))
        assert item.name == "Cards"
        product_id = item.id
        db.add(WorkerState(id=1, heartbeat_at=utcnow(), last_cycle_at=utcnow()))
        db.commit()
    assert client.get("/health").status_code == 200
    assert client.post(f"/products/{product_id}/toggle", data={"csrf": token}).status_code == 302
    with factory() as db:
        assert not db.get(Product, product_id).enabled
    assert client.post(f"/products/{product_id}/delete", data={"csrf": token}).status_code == 302
    with factory() as db:
        assert db.get(Product, product_id) is None
    assert client.post("/products", data={"name": "Bad"}).status_code == 400


def test_generic_retailer_config(factory, monkeypatch):
    monkeypatch.setattr(service, "public_host", lambda _: True)
    with factory() as db:
        config = service.add_retailer(db, "Toy Shop", "toy.example", "https://toy.example/p/1",
                                      "Add to cart", "Sold out", "main button", ".price")
        assert adapters.detect("https://toy.example/p/1", [config]) == "Toy Shop"
        config.enabled = False
        db.commit()
        assert adapters.detect("https://toy.example/p/1", [config]) is None


def test_worker_isolates_failed_product(factory, monkeypatch):
    monkeypatch.setattr("monitor_app.worker.resolve_adapter", lambda *a: ("Target", adapters.ADAPTERS["Target"]))
    def fake_fetch(url, adapter):
        if "bad" in url:
            raise RuntimeError("bad product")
        return adapters.Result("OUT_OF_STOCK")
    monkeypatch.setattr("monitor_app.worker.fetch", fake_fetch)
    with factory() as db:
        db.add_all([Product(name="Bad", url="https://www.target.com/p/bad", retailer="Target"),
                    Product(name="Good", url="https://www.target.com/p/good", retailer="Target")])
        db.commit()
    cycle(factory)
    with factory() as db:
        assert db.scalar(select(Product.status).where(Product.name == "Bad")) == "ERROR"
        assert db.scalar(select(Product.status).where(Product.name == "Good")) == "OUT_OF_STOCK"
        assert db.get(WorkerState, 1).last_cycle_at


def test_pending_alert_recovered_after_restart(factory, monkeypatch):
    product = Product(name="Cards", url="https://www.target.com/p/cards", retailer="Target",
                      enabled=False)
    with factory() as db:
        db.add(product)
        db.commit()
        service.apply_result(db, product, adapters.Result("OUT_OF_STOCK"))
        service.apply_result(db, product, adapters.Result("IN_STOCK"), send=lambda *args: None)
        pending = db.scalar(select(AlertHistory))
        assert pending.detail == "Pending delivery"
    deliveries = []
    def recover(db, product, history):
        deliveries.append(history.id)
        attempt = db.scalar(select(AlertHistory).where(AlertHistory.status_history_id == history.id))
        attempt.detail = "Delivered"
        attempt.success = True
        db.commit()
    monkeypatch.setattr("monitor_app.worker.send_discord", recover)
    cycle(factory)
    cycle(factory)
    assert len(deliveries) == 1


def test_migration_clean_database(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    command.upgrade(cfg, "head")
    engine = make_engine(db_url)
    with engine.connect() as connection:
        from sqlalchemy import inspect
        assert {"products", "retailers", "status_history", "alert_history", "worker_state"}.issubset(
            set(inspect(connection).get_table_names()))
    engine.dispose()
