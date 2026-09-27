import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from sqlalchemy import func, select

from monitor_app import adapters, discovery, worker
from monitor_app.bestbuy_api import BestBuyAPI, normalized, sku_from_url, source_filter
from monitor_app.db import Base, DiscoveredProduct, DiscoverySource, Product, make_engine, session_factory, utcnow

FIXTURE = json.loads((Path(__file__).parent / "fixtures/bestbuy-products-api.json").read_text())
SOURCE = "https://www.bestbuy.com/site/searchpage.jsp?id=pcat17071&st=pokemon+tcg"


class Session:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = self.payloads.pop(0)
        return SimpleNamespace(status_code=200, content=json.dumps(payload).encode(), json=lambda: payload)


def test_api_search_and_product_fields(monkeypatch):
    monkeypatch.setattr(discovery, "public_host", lambda _: True)
    session = Session([FIXTURE])
    source = SimpleNamespace(retailer="Best Buy", url=SOURCE)
    monkeypatch.setenv("BEST_BUY_API_KEY", "example-test-key")
    listings = discovery.fetch_source(source, session)
    assert len(listings) == 2
    assert (listings[0].retailer_product_id, listings[0].price, listings[0].status) == (
        "6608206", "$29.99", "IN_STOCK")
    assert listings[0].url == "https://www.bestbuy.com/site/6608206.p"
    assert listings[0].seller is None
    assert listings[0].metadata["image"].startswith("https://pisces.bbystatic.com/")
    assert listings[1].status == "COMING_SOON" and listings[1].release_date == "2099-10-01"
    assert session.calls[0][0].endswith("/products(search=pokemon&search=tcg)")
    assert session.calls[0][1]["params"]["apiKey"] == "example-test-key"
    assert session.calls[0][1]["allow_redirects"] is False


def test_api_known_sku_and_fail_closed(monkeypatch):
    monkeypatch.setattr(adapters, "public_host", lambda _: True)
    monkeypatch.setenv("BEST_BUY_API_KEY", "example-test-key")
    session = Session([FIXTURE["products"][0]])
    result = adapters.fetch("https://www.bestbuy.com/site/6608206.p", adapters.ADAPTERS["Best Buy"], session)
    assert (result.status, result.price, result.seller) == ("IN_STOCK", "$29.99", None)
    assert result.release_date == "2025-01-17" and result.image_url.startswith("https://pisces.bbystatic.com/")
    assert session.calls[0][0].endswith("/products/6608206.json")
    assert sku_from_url("https://www.bestbuy.com/product/name/JJG2TL23JK") is None
    assert adapters.fetch("https://www.bestbuy.com/product/name/JJG2TL23JK",
                          adapters.ADAPTERS["Best Buy"], Session([])).status == "UNKNOWN"
    missing = dict(FIXTURE["products"][0], onlineAvailability=None, salePrice=None)
    assert normalized(missing)["status"] == "UNKNOWN"
    assert normalized(missing)["price"] is None
    restricted = dict(FIXTURE["products"][0], priceRestriction="MAP", secondaryMarket=True)
    assert normalized(restricted)["price"] is None and not normalized(restricted)["sealed_eligible"]
    assert normalized(dict(FIXTURE["products"][0], orderable=False))["status"] == "UNKNOWN"


def test_api_missing_key_partial_and_incomplete(monkeypatch):
    monkeypatch.delenv("BEST_BUY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="BEST_BUY_API_KEY"):
        BestBuyAPI()
    assert source_filter(SOURCE) == "search=pokemon&search=tcg"
    assert source_filter("https://www.bestbuy.com/site/pokemon/cards/pcmcat1741200145801.c?id=pcmcat1741200145801") == (
        "categoryPath.id=pcmcat1741200145801")
    with pytest.raises(ValueError, match="needs a category URL"):
        source_filter("https://www.bestbuy.com/site/pokemon")
    with pytest.raises(ValueError, match="incomplete response"):
        BestBuyAPI("test", Session([dict(FIXTURE, partial=True)])).discover(SOURCE)
    with pytest.raises(ValueError, match="collection was incomplete"):
        BestBuyAPI("test", Session([dict(FIXTURE, total=3)]), pause=lambda _: None).discover(SOURCE)


def test_api_pagination_and_silent_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "public_host", lambda _: True)
    monkeypatch.setenv("BEST_BUY_API_KEY", "example-test-key")
    first = dict(FIXTURE, total=3, products=FIXTURE["products"], nextCursorMark="second")
    third = dict(FIXTURE["products"][0], sku=6699999, name="Pokémon Future Booster Box")
    second = {"total": 3, "partial": False, "products": [third]}
    items = discovery.fetch_source(SimpleNamespace(retailer="Best Buy", url=SOURCE), Session([first, second]))
    assert len(items) == 3
    engine = make_engine(f"sqlite:///{tmp_path / 'bestbuy.db'}")
    Base.metadata.create_all(engine)
    with session_factory(engine)() as db:
        source = DiscoverySource(retailer="Best Buy", url=SOURCE)
        db.add(source)
        db.commit()
        assert discovery.scan(db, source, items) == []
        assert source.baseline_complete
        assert db.scalar(select(func.count()).select_from(DiscoveredProduct)) == 3
        newer = discovery.Listing("Best Buy", "6688888", "https://www.bestbuy.com/site/6688888.p",
                                  "Pokémon New Booster Bundle", "Booster Bundle", "$24.99",
                                  "UNKNOWN", None)
        created = discovery.scan(db, source, items + [newer])
        assert len(created) == 1 and created[0].retailer_product_id == "6688888"
        assert created[0].product_id is not None
    engine.dispose()


def test_api_zero_or_secret_bearing_error_never_baselines(tmp_path):
    class Failure:
        def get(self, *_args, **_kwargs):
            raise requests.ReadTimeout("request failed at https://api.bestbuy.com/?apiKey=private-key")

    with pytest.raises(ValueError) as exc:
        BestBuyAPI("private-key", Failure(), pause=lambda _: None).discover(SOURCE)
    assert "private-key" not in str(exc.value)
    engine = make_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    Base.metadata.create_all(engine)
    with session_factory(engine)() as db:
        source = DiscoverySource(retailer="Best Buy", url=SOURCE)
        db.add(source)
        db.commit()
        with pytest.raises(ValueError, match="No product cards found"):
            discovery.scan(db, source, [])
        assert not source.baseline_complete
    engine.dispose()


def test_bestbuy_api_content_expires_after_72_hours(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'expiry.db'}")
    Base.metadata.create_all(engine)
    old = utcnow() - timedelta(hours=73)
    with session_factory(engine)() as db:
        source = DiscoverySource(retailer="Best Buy", url=SOURCE)
        product = Product(name="Pokémon Booster Bundle", url="https://www.bestbuy.com/site/6608206.p",
                          retailer="Best Buy", retailer_product_id="6608206", status="IN_STOCK",
                          last_known_status="IN_STOCK", last_checked=old, price="$29.99",
                          price_confirmed=True, observed_title="Pokémon Booster Bundle",
                          release_date="2025-01-17", image_url="https://pisces.bbystatic.com/a.jpg")
        db.add_all([source, product])
        db.flush()
        found = DiscoveredProduct(source_id=source.id, product_id=product.id, retailer="Best Buy",
                                  retailer_product_id="6608206", url=product.url,
                                  title=product.name, price=product.price, status="IN_STOCK",
                                  last_seen_at=old, release_date="2025-01-17", metadata_json='{"image":"a"}')
        db.add(found)
        db.commit()
        worker.expire_bestbuy_content(db, utcnow())
        db.commit()
        assert product.price is None and product.image_url is None and product.status == "UNKNOWN"
        assert product.name == "Best Buy SKU 6608206"
        assert found.title == "Best Buy product data expired" and found.metadata_json is None
    engine.dispose()
