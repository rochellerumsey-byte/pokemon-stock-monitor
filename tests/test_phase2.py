import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from monitor_app import adapters, discovery, purchase, service, worker
from monitor_app.db import (AlertHistory, Base, DiscoveredProduct, DiscoverySource, Product,
                            PurchaseAttempt, PurchaseCandidate, PurchaseEvent, PurchaseOrder, PurchaseRule, WorkerState,
                            make_engine, session_factory, utcnow)
from monitor_app.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"
TARGET_URL = "https://www.target.com/c/pokemon-cards"
TEST_ENV = {"ZINC_API_KEY": "zn_test_example",
            **{f"ZINC_SHIPPING_{key}": "test" for key in purchase.ADDRESS_FIELDS}}


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'phase2.db'}")
    Base.metadata.create_all(engine)
    yield session_factory(engine)
    engine.dispose()


def listing(retailer="Target"):
    source = TARGET_URL if retailer == "Target" else "https://www.bestbuy.com/site/pokemon"
    fixture = "target-listing.html" if retailer == "Target" else "bestbuy-listing.html"
    return discovery.parse_listings(retailer, source, (FIXTURES / fixture).read_text())


def add_rule(db, **changes):
    values = dict(name="sealed", enabled=True, mode="APPROVAL", retailers="Target",
                  product_types="ETB", title_include="scarlet", title_exclude="damaged",
                  max_item_cents=5000, max_order_cents=7000, quantity=1,
                  retailer_direct_only=True, daily_spend_cents=14000,
                  lifetime_sku_quantity=1)
    values.update(changes)
    rule = PurchaseRule(**values)
    db.add(rule)
    db.commit()
    return rule


def product(db, **changes):
    values = dict(name="Pokemon Scarlet Elite Trainer Box",
                  url="https://www.target.com/p/pokemon-scarlet-elite-trainer-box/-/A-12345",
                  retailer="Target", retailer_product_id="12345", product_type="ETB",
                  observed_title="Pokemon Scarlet Elite Trainer Box", seller="Target",
                  status="IN_STOCK", price="$49.99", price_confirmed=True)
    values.update(changes)
    item = Product(**values)
    db.add(item)
    db.commit()
    return item


def test_classification_and_canonical_fixture():
    target = listing()
    assert target[0].retailer_product_id == "12345"
    assert target[0].product_type == "ETB"
    assert target[1].product_type is None
    assert listing("Best Buy")[0].product_type == "Booster Bundle"
    assert discovery.canonical("Best Buy", "https://www.bestbuy.com/product/pokemon-bundle/6608206")[0] == "6608206"
    assert discovery.canonical("Best Buy", "https://www.bestbuy.com/site/pokemon-bundle/6608206.p?skuId=6608206")[0] == "6608206"
    with pytest.raises(ValueError):
        discovery.canonical("Best Buy", "https://www.bestbuy.com/sale/2026")
    for title, expected in (("Pokemon Center Elite Trainer Box", "Pokemon Center ETB"),
                            ("Pokemon booster box", "Booster Box/Mega Box"),
                            ("Pokemon premium collection", "Premium Collection"),
                            ("Pokemon tin", "Tin"),
                            ("Pokemon poster collection", "Poster Collection"),
                            ("Pokemon sticker collection", "Sticker Collection"),
                            ("Pokemon pin collection", "Pin Collection"),
                            ("Pokemon collection box", "Collection/Box"),
                            ("Pokemon TCG blister", "Other Sealed TCG")):
        assert discovery.classify(title) == expected
    with pytest.raises(ValueError):
        discovery.canonical("Target", "https://target.com.evil.test/p/x/-/A-12345")


def test_ambiguous_price_is_not_purchase_ready(factory):
    assert adapters.price_value("$49.99") == "$49.99"
    assert adapters.price_value("$49.99 - $79.99") is None
    assert adapters.price_value("From $49.99") is None
    assert adapters.price_value("Save $10, now $49.99") is None
    with factory() as db:
        item, rule = product(db), add_rule(db, mode="AUTO")
        service.apply_result(db, item, adapters.Result(
            "IN_STOCK", name="Pokemon Scarlet Elite Trainer Box",
            price=adapters.price_value("$49.99 - $79.99"), seller="Target"))
        assert not purchase.rule_matches(rule, item)[0]


def test_structured_offer_preserves_seller_and_rejects_multiple_offers():
    def page(offers):
        return ('<html><body><h1>Pokemon Scarlet Elite Trainer Box</h1>'
                '<script type="application/ld+json">'
                '{"@type":"Product","name":"Pokemon Scarlet Elite Trainer Box",'
                f'"offers":{offers}'
                '}'
                '</script></body></html>')

    offer = ('{"availability":"https://schema.org/InStock","price":"49.99",'
             '"seller":{"name":"Target"}}')
    result = adapters.ADAPTERS["Target"].parse(page(offer))
    assert (result.status, result.price, result.seller) == ("IN_STOCK", "$49.99", "Target")
    result = adapters.ADAPTERS["Target"].parse(page(f"[{offer},{offer}]"))
    assert result.status == "UNKNOWN"
    assert result.price is None
    assert result.seller is None


def test_silent_baseline_new_discovery_dedupe_and_auto_enroll(factory):
    with factory() as db:
        source = DiscoverySource(retailer="Target", url=TARGET_URL)
        db.add(source)
        db.commit()
        assert discovery.scan(db, source, listing()) == []
        assert source.baseline_complete
        assert db.scalar(select(func.count()).select_from(DiscoveredProduct)) == 2
        assert db.scalar(select(func.count()).select_from(Product)) == 1
        assert discovery.scan(db, source, listing()) == []
        newer = discovery.Listing("Target", "54321", "https://www.target.com/p/new/-/A-54321",
                                  "Pokemon new Booster Bundle", "Booster Bundle", "$24.99",
                                  "IN_STOCK", "Target")
        created = discovery.scan(db, source, [newer])
        assert len(created) == 1 and not created[0].baseline
        assert created[0].product_id
        assert discovery.scan(db, source, [newer]) == []
        assert db.scalar(select(func.count()).select_from(DiscoveredProduct)) == 3
        assert db.scalar(select(func.count()).select_from(Product)) == 2


def test_unparseable_scan_keeps_baseline(factory):
    with factory() as db:
        source = DiscoverySource(retailer="Target", url=TARGET_URL)
        db.add(source)
        db.commit()
        with pytest.raises(ValueError):
            discovery.scan(db, source, [])
        assert not source.baseline_complete
        invalid = discovery.Listing("Target", "wrong-id", "https://www.target.com/p/x/-/A-12345",
                                    "Pokemon ETB", "ETB", "$49.99", "IN_STOCK", "Target")
        with pytest.raises(ValueError):
            discovery.scan(db, source, [invalid])
        assert not source.baseline_complete


def test_rule_fail_closed_and_caps(factory):
    with factory() as db:
        rule = add_rule(db)
        item = product(db)
        assert purchase.rule_matches(rule, item)[0]
        for changes in ({"price": None}, {"seller": None}, {"seller": "Third-party shop"},
                        {"retailer_product_id": None}, {"observed_title": None}, {"status": "UNKNOWN"},
                        {"price_confirmed": False},
                        {"price": "$99.00"}, {"observed_title": "Pokemon damaged Scarlet ETB"}):
            original = {key: getattr(item, key) for key in changes}
            for key, value in changes.items():
                setattr(item, key, value)
            assert not purchase.rule_matches(rule, item)[0]
            for key, value in original.items():
                setattr(item, key, value)
        first = purchase.evaluate(db, item, "discovery:123")
        assert first.status == "PENDING_APPROVAL"
        assert purchase.evaluate(db, item, "discovery:123").id == first.id
        assert not purchase.budget_allows(db, rule, item)[0]
        assert purchase.budget_allows(db, rule, item, exclude_id=first.id)[0]
        same_sku = product(db, url="https://www.target.com/p/alternate/-/A-12345")
        assert not purchase.budget_allows(db, rule, same_sku)[0]
        other = product(db, url="https://www.target.com/p/other/-/A-67890", retailer_product_id="67890")
        assert purchase.budget_allows(db, rule, other)[0]
        rule.daily_spend_cents = 7000
        db.commit()
        assert not purchase.budget_allows(db, rule, other)[0]


def test_zinc_provider_uses_test_key_idempotency_and_hard_cap(factory):
    class FakeHTTP:
        def post(self, url, **kwargs):
            assert url == "https://api.zinc.com/orders"
            assert kwargs["headers"]["Authorization"] == "Bearer zn_test_example"
            body = kwargs["json"]
            assert body["max_price"] == 7000
            assert body["idempotency_key"] == candidate.idempotency_key
            assert body["products"][0]["condition_in"] == ["New"]
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {"id": "sandbox-1", "status": "pending"})
        def get(self, url, **kwargs):
            assert url.endswith("/orders/sandbox-1")
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {"status": "order_placed"})
    with factory() as db:
        item, rule = product(db), add_rule(db)
        candidate = purchase.evaluate(db, item, "restock:1")
        provider = purchase.ZincPurchaseProvider(TEST_ENV, FakeHTTP())
        assert provider.submit(item, candidate, rule)["id"] == "sandbox-1"
        assert provider.get_order("sandbox-1")["status"] == "order_placed"
    with pytest.raises(ValueError):
        purchase.ZincPurchaseProvider({**TEST_ENV, "ZINC_API_KEY": "zn_live_forbidden"})


def test_submission_failure_and_restart_never_resubmit(factory, monkeypatch):
    monkeypatch.setattr(purchase, "sandbox_ready", lambda env=None: (True, "test"))
    with factory() as db:
        item, rule = product(db), add_rule(db)
        db.add(WorkerState(id=1, purchases_enabled=True))
        db.commit()
        candidate = purchase.evaluate(db, item, "restock:2")
        candidate.status = "APPROVED"
        db.commit()
        class Fails:
            def submit(self, *_):
                raise TimeoutError("unknown outcome")
        assert purchase.submit_candidate(db, candidate.id, Fails()).status == "SUBMISSION_UNKNOWN"
        assert purchase.submit_candidate(db, candidate.id, Fails()).status == "SUBMISSION_UNKNOWN"
        assert db.scalar(select(func.count()).select_from(PurchaseEvent).where(
            PurchaseEvent.kind == "SUBMITTING")) == 1
        assert db.scalar(select(func.count()).select_from(PurchaseAttempt)) == 1
        candidate.status = "SUBMITTING"
        candidate.submitted_at = utcnow() - timedelta(minutes=3)
        db.commit()
    monkeypatch.setattr(worker, "fetch", lambda *a: adapters.Result("UNKNOWN"))
    worker.cycle(factory)
    with factory() as db:
        assert db.get(PurchaseCandidate, candidate.id).status == "SUBMISSION_UNKNOWN"


def test_source_failure_isolated(factory, monkeypatch):
    with factory() as db:
        db.add_all([DiscoverySource(retailer="Target", url=TARGET_URL),
                    DiscoverySource(retailer="Best Buy", url="https://www.bestbuy.com/site/pokemon")])
        db.commit()
    def fake_fetch(source):
        if source.retailer == "Target":
            raise ValueError("blocked")
        return listing("Best Buy")
    monkeypatch.setattr(worker.discovery, "fetch_source", fake_fetch)
    worker.cycle(factory)
    with factory() as db:
        sources = db.scalars(select(DiscoverySource).order_by(DiscoverySource.id)).all()
        assert sources[0].last_error == "blocked"
        assert not sources[0].baseline_complete
        assert sources[1].baseline_complete
        assert db.scalar(select(func.count()).select_from(Product)) == 1


@pytest.mark.parametrize("recheck", [
    adapters.Result("OUT_OF_STOCK", price="$49.99"),
    adapters.Result("IN_STOCK", price=None, seller="Target"),
])
def test_dashboard_approval_rechecks_and_csrf(factory, tmp_path, monkeypatch, recheck):
    monkeypatch.setenv("ADMIN_PASSWORD", "long-test-password-12345")
    monkeypatch.setenv("SECRET_KEY", "long-test-secret-key-123456789012345")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setattr(purchase, "sandbox_ready", lambda env=None: (True, "test"))
    with factory() as db:
        item, rule = product(db), add_rule(db)
        db.add(WorkerState(id=1, purchases_enabled=True))
        db.commit()
        candidate = purchase.evaluate(db, item, "restock:3")
    app = create_app(f"sqlite:///{tmp_path / 'phase2.db'}", testing=True)
    client = app.test_client()
    token = client.get("/login").text.split('name="csrf" value="')[1].split('"')[0]
    client.post("/login", data={"csrf": token, "password": os.environ["ADMIN_PASSWORD"]})
    token = client.get("/").text.split('name="csrf" value="')[1].split('"')[0]
    assert "Pending approvals" in client.get("/").text
    assert client.post(f"/purchase/candidates/{candidate.id}/approve").status_code == 400
    monkeypatch.setattr(service, "public_host", lambda _: True)
    monkeypatch.setattr(adapters, "fetch", lambda *a: recheck)
    assert client.post(f"/purchase/candidates/{candidate.id}/approve", data={"csrf": token}).status_code == 302
    with factory() as db:
        assert db.get(PurchaseCandidate, candidate.id).status == "BLOCKED"
        assert db.get(PurchaseCandidate, candidate.id).provider_order_id is None


def test_dashboard_approval_rechecks_then_submits_sandbox(factory, tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "long-test-password-12345")
    monkeypatch.setenv("SECRET_KEY", "long-test-secret-key-123456789012345")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setattr(purchase, "sandbox_ready", lambda env=None: (True, "test"))
    monkeypatch.setattr(service, "public_host", lambda _: True)
    monkeypatch.setattr(adapters, "fetch", lambda *a: adapters.Result(
        "IN_STOCK", name="Pokemon Scarlet Elite Trainer Box", price="$49.99", seller="Target"))
    calls = []
    class FakeProvider:
        def submit(self, item, candidate, rule):
            calls.append(candidate.id)
            return {"id": "sandbox-approved", "status": "pending"}
    monkeypatch.setattr(purchase, "ZincPurchaseProvider", FakeProvider)
    with factory() as db:
        item, rule = product(db), add_rule(db)
        db.add(WorkerState(id=1, purchases_enabled=True))
        db.commit()
        candidate = purchase.evaluate(db, item, "restock:4")
    app = create_app(f"sqlite:///{tmp_path / 'phase2.db'}", testing=True)
    client = app.test_client()
    token = client.get("/login").text.split('name="csrf" value="')[1].split('"')[0]
    client.post("/login", data={"csrf": token, "password": os.environ["ADMIN_PASSWORD"]})
    token = client.get("/").text.split('name="csrf" value="')[1].split('"')[0]
    assert client.post(f"/purchase/candidates/{candidate.id}/approve", data={"csrf": token}).status_code == 302
    assert client.post(f"/purchase/candidates/{candidate.id}/approve", data={"csrf": token}).status_code == 302
    with factory() as db:
        updated = db.get(PurchaseCandidate, candidate.id)
        assert updated.status == "SUBMITTED" and updated.provider_order_id == "sandbox-approved"
        assert db.scalar(select(PurchaseOrder).where(PurchaseOrder.candidate_id == candidate.id)).status == "pending"
        assert calls == [candidate.id]
        another = product(db, url="https://www.target.com/p/second/-/A-67891",
                          retailer_product_id="67891")
        rejected = purchase.evaluate(db, another, "restock:reject")
    assert client.post(f"/purchase/candidates/{rejected.id}/reject", data={"csrf": token}).status_code == 302
    with factory() as db:
        assert db.get(PurchaseCandidate, rejected.id).status == "REJECTED"
        assert calls == [candidate.id]


def test_worker_new_discovery_evaluates_after_confirmed_check(factory, monkeypatch):
    monkeypatch.setattr(worker.discovery, "fetch_source", lambda source: [
        discovery.Listing("Target", "54321", "https://www.target.com/p/new/-/A-54321",
                          "Pokemon new Booster Bundle", "Booster Bundle", "$24.99", "IN_STOCK", "Target")])
    monkeypatch.setattr(worker, "resolve_adapter", lambda *args: ("Target", adapters.ADAPTERS["Target"]))
    monkeypatch.setattr(worker, "fetch", lambda *args: adapters.Result(
        "IN_STOCK", name="Pokemon new Booster Bundle", price="$24.99", seller="Target"))
    with factory() as db:
        source = DiscoverySource(retailer="Target", url=TARGET_URL, baseline_complete=True)
        db.add(source)
        add_rule(db, product_types="Booster Bundle", title_include="new")
        db.commit()
    worker.cycle(factory)  # Discover and auto-enroll.
    worker.cycle(factory)  # Confirm availability on the product page.
    with factory() as db:
        candidate = db.scalar(select(PurchaseCandidate))
        assert candidate and candidate.status == "PENDING_APPROVAL"
        assert db.scalar(select(func.count()).select_from(AlertHistory).where(
            AlertHistory.kind == "NEW_PRODUCT")) == 1


def test_auto_mode_is_stopped_by_default_switch(factory, monkeypatch):
    with factory() as db:
        item, rule = product(db), add_rule(db, mode="AUTO")
        db.add(WorkerState(id=1))
        db.commit()
        candidate = purchase.evaluate(db, item, "restock:auto")
        assert candidate.status == "AUTO_BLOCKED"
        assert purchase.submit_candidate(db, candidate.id).status == "BLOCKED"
        assert candidate.provider_order_id is None


def test_auto_mode_submits_once_with_sandbox_switch(factory, monkeypatch):
    monkeypatch.setattr(purchase, "sandbox_ready", lambda env=None: (True, "test"))
    calls = []
    class FakeProvider:
        def submit(self, item, candidate, rule):
            calls.append(candidate.id)
            assert candidate.reserved_cents == 7000
            return {"id": "sandbox-auto", "status": "pending"}
    with factory() as db:
        item, rule = product(db), add_rule(db, mode="AUTO")
        db.add(WorkerState(id=1, purchases_enabled=True))
        db.commit()
        candidate = purchase.evaluate(db, item, "restock:auto-on")
        assert purchase.submit_candidate(db, candidate.id, FakeProvider()).status == "SUBMITTED"
        assert purchase.submit_candidate(db, candidate.id, FakeProvider()).status == "SUBMITTED"
        assert calls == [candidate.id]


def test_restocks_run_same_purchase_rule_once(factory, monkeypatch):
    monkeypatch.setattr(worker, "resolve_adapter", lambda *args: ("Target", adapters.ADAPTERS["Target"]))
    monkeypatch.setattr(worker, "fetch", lambda *args: adapters.Result(
        "IN_STOCK", name="Pokemon Scarlet Elite Trainer Box", price="$49.99", seller="Target"))
    with factory() as db:
        item = product(db, status="OUT_OF_STOCK", last_known_status="OUT_OF_STOCK",
                       next_check_at=utcnow())
        add_rule(db)
    worker.cycle(factory)
    worker.cycle(factory)
    with factory() as db:
        candidates = db.scalars(select(PurchaseCandidate)).all()
        assert len(candidates) == 1
        assert candidates[0].event_key.startswith("restock:")


def test_migration_head_includes_phase2(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    command.upgrade(config, "efe55f71222d")
    legacy_engine = make_engine(url)
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO worker_state (id) VALUES (1)")
    legacy_engine.dispose()
    command.upgrade(config, "head")
    engine = make_engine(url)
    assert {"discovery_sources", "discovered_products", "purchase_rules",
            "purchase_candidates", "purchase_events", "purchase_attempts",
            "purchase_orders"}.issubset(inspect(engine).get_table_names())
    with session_factory(engine)() as db:
        assert db.get(WorkerState, 1).purchases_enabled is False
    engine.dispose()


def test_reconciliation_records_sandbox_order_total(factory, monkeypatch):
    monkeypatch.setattr(purchase, "sandbox_ready", lambda env=None: (True, "test"))
    class FakeProvider:
        def submit(self, *_):
            return {"id": "sandbox-reconcile", "status": "pending"}
        def get_order(self, *_):
            return {"status": "order_placed", "job_result": {"price_components": {"total": 5632}}}
    with factory() as db:
        item, rule = product(db), add_rule(db)
        db.add(WorkerState(id=1, purchases_enabled=True))
        db.commit()
        candidate = purchase.evaluate(db, item, "restock:reconcile")
        candidate.status = "APPROVED"
        db.commit()
        purchase.submit_candidate(db, candidate.id, FakeProvider())
        purchase.reconcile(db, candidate, FakeProvider())
        assert candidate.status == "PLACED" and candidate.provider_total_cents == 5632
        order = db.scalar(select(PurchaseOrder))
        assert order.status == "order_placed" and order.total_cents == 5632
