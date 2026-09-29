"""Regression coverage for Safari Zone's observed Shopify storefront shapes."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from monitor_app import adapters, discovery, safari_zone, service, worker
from monitor_app.db import Base, DiscoveredProduct, DiscoverySource, Product, make_engine, session_factory

FIXTURES = Path(__file__).parent / "fixtures"
COLLECTION = json.loads((FIXTURES / "safari-zone-collection.json").read_text(encoding="utf-8"))
PRODUCT_HTML = (FIXTURES / "safari-zone-product.html").read_text(encoding="utf-8")


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'safari.db'}")
    Base.metadata.create_all(engine)
    yield session_factory(engine)
    engine.dispose()


class Response:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, products):
        self.products = products
        self.content = json.dumps({"products": products}).encode()

    def json(self):
        return {"products": self.products}


class Session:
    def __init__(self, products=None):
        self.products = COLLECTION["products"] if products is None else products
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        assert kwargs["allow_redirects"] is False
        return Response(self.products)


def test_live_shape_discovery_classification_and_enrollment(factory, monkeypatch):
    monkeypatch.setattr(discovery, "public_host", lambda _: True)
    source_url = discovery.validate_source("Safari Zone Collectibles", safari_zone.COLLECTION_URL)
    client = Session()
    with factory() as db:
        source = DiscoverySource(retailer="Safari Zone Collectibles", url=source_url)
        db.add(source)
        db.commit()
        listings = discovery.fetch_source(source, client)
        assert len(listings) == 3
        assert client.urls == [safari_zone.COLLECTION_URL + "/products.json?limit=250&page=1"]
        assert [x.product_type for x in listings] == ["Tin", "Premium Collection", None]
        assert discovery.scan(db, source, listings) == []
        assert source.baseline_complete
        assert db.scalar(select(func.count()).select_from(DiscoveredProduct)) == 3
        assert db.scalar(select(func.count()).select_from(Product)) == 2
        assert discovery.scan(db, source, listings) == []
        extra = dict(COLLECTION["products"][1], id=8879383118999,
                     handle="pokemon-tcg-new-premium-collection-box",
                     title="Pokemon TCG: New Premium Collection Box")
        new = safari_zone.listing_from_product(extra)
        created = discovery.scan(db, source, listings + [new])
        assert len(created) == 1 and created[0].retailer_product_id == str(extra["id"])
        assert created[0].product_id and not created[0].baseline
        assert discovery.scan(db, source, listings + [new]) == []


def test_zero_and_malformed_scans_never_baseline(factory):
    with factory() as db:
        source = DiscoverySource(retailer="Safari Zone Collectibles", url=safari_zone.COLLECTION_URL)
        db.add(source)
        db.commit()
        assert safari_zone.discover(Session([])) == []
        with pytest.raises(ValueError, match="No product cards"):
            discovery.scan(db, source, [])
        with pytest.raises(ValueError, match="numeric ID"):
            safari_zone.discover(Session([dict(COLLECTION["products"][0], id=None)]))
        assert not source.baseline_complete
        assert db.scalar(select(func.count()).select_from(DiscoveredProduct)) == 0


def test_preorder_and_multiple_variants_are_conservative():
    preorder = dict(COLLECTION["products"][1], title="Pokemon TCG: New Premium Collection (PREORDER)")
    assert safari_zone.listing_from_product(preorder).status == "PREORDER"
    ambiguous = dict(COLLECTION["products"][1], variants=[
        COLLECTION["products"][1]["variants"][0], COLLECTION["products"][0]["variants"][0]])
    listing = safari_zone.listing_from_product(ambiguous)
    assert listing.status == "UNKNOWN" and listing.price is None
    assert discovery.classify("Pokemon TCG: Premium Figure Collection") == "Collection/Box"


def test_known_product_stock_and_ambiguous_page_fail_closed(monkeypatch):
    url = "https://safari-zone.com/products/pokemon-tcg-mega-zygarde-ex-premium-collection-box"
    good = safari_zone.parse_product(PRODUCT_HTML, url)
    assert (good.status, good.price, good.seller) == ("IN_STOCK", "$39.99", None)
    assert good.image_url.endswith("box.png")
    assert safari_zone.parse_product(PRODUCT_HTML.replace("InStock", "OutOfStock"), url).status == "OUT_OF_STOCK"
    for altered in (PRODUCT_HTML.replace("InStock", "Discontinued"),
                    PRODUCT_HTML.replace("data-product-id=", "data-missing-id="),
                    PRODUCT_HTML.replace("priceCurrency\":\"USD", "priceCurrency\":\"CAD"),
                    PRODUCT_HTML.replace("premium-collection-box\"", "different-product\"", 1)):
        assert safari_zone.parse_product(altered, url).status == "UNKNOWN"
    monkeypatch.setattr(adapters, "public_host", lambda _: True)
    class HtmlSession:
        def mount(self, *_):
            pass
        def get(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200, headers={"Content-Type": "text/html"},
                                   content=PRODUCT_HTML.encode(), text=PRODUCT_HTML)
    result = adapters.fetch(url, adapters.ADAPTERS["Safari Zone Collectibles"], HtmlSession())
    assert result.status == "IN_STOCK" and result.price == "$39.99"
    assert result.retailer_product_id == "8879383118006"


def test_known_product_id_mismatch_stays_unknown(factory):
    url = "https://safari-zone.com/products/pokemon-tcg-mega-zygarde-ex-premium-collection-box"
    with factory() as db:
        item = Product(name="Test", url=url, retailer="Safari Zone Collectibles",
                       retailer_product_id="9999999999999")
        db.add(item)
        db.commit()
        service.apply_result(db, item, safari_zone.parse_product(PRODUCT_HTML, url))
        assert item.status == "UNKNOWN" and not item.price_confirmed
        assert "identity changed" in item.error


def test_safari_zone_source_failure_isolated(factory, monkeypatch):
    with factory() as db:
        db.add_all([DiscoverySource(retailer="Pokemon Center", url="https://www.pokemoncenter.com/category/tcg-cards"),
                    DiscoverySource(retailer="Safari Zone Collectibles", url=safari_zone.COLLECTION_URL)])
        db.commit()
    def fetch(source):
        if source.retailer == "Pokemon Center":
            raise ValueError("blocked")
        return [safari_zone.listing_from_product(x) for x in COLLECTION["products"]]
    monkeypatch.setattr(worker.discovery, "fetch_source", fetch)
    worker.cycle(factory)
    with factory() as db:
        sources = db.scalars(select(DiscoverySource).order_by(DiscoverySource.id)).all()
        assert sources[0].last_error == "blocked" and not sources[0].baseline_complete
        assert sources[1].baseline_complete and sources[1].last_error is None


def test_source_and_product_urls_reject_other_hosts():
    with pytest.raises(ValueError):
        safari_zone.product_identity("https://safari-zone.com.evil.test/products/foo")
    with pytest.raises(ValueError):
        safari_zone.product_identity("https://safari-zone.com/products/foo?variant=1")
    with pytest.raises(ValueError):
        discovery.canonical("Safari Zone Collectibles", "https://safari-zone.com/products/foo")


def test_migration_seeds_pending_silent_source(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    url = f"sqlite:///{tmp_path / 'migrated-safari.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = make_engine(url)
    with session_factory(engine)() as db:
        source = db.scalar(select(DiscoverySource).where(
            DiscoverySource.retailer == "Safari Zone Collectibles"))
        assert source and source.enabled and not source.baseline_complete
        assert source.url == safari_zone.COLLECTION_URL
    engine.dispose()
