# Pokémon Stock Monitor

A private web dashboard that checks public Pokémon TCG product pages, attempts listing discovery on configured Target and Best Buy source pages, and sends Discord notifications. Phase 2 includes rule evaluation, owner approval, and Zinc **test-mode-only** order integration. Live purchasing is unavailable. It does not bypass retailer controls. Current Target public pages do not provide the inventory, price, and availability signals this app needs; see [RETAILER_SUPPORT.md](RETAILER_SUPPORT.md) before relying on Target monitoring.

## Retailers

Target, Best Buy, Pokémon Center, and GameStop have conservative public-page adapters. Amazon is present but reports `UNAVAILABLE` because reliable public monitoring has not been established. Simple additional sites can be configured in the dashboard. See [RETAILER_SUPPORT.md](RETAILER_SUPPORT.md) for actual validation, which is distinct from fixture tests.

## How it works

The Flask dashboard manages products, discovery sources, simple retailer selectors, and purchase rules. SQLAlchemy and Alembic persist state in PostgreSQL (SQLite locally). One advisory-locked worker scans configured source pages, checks due products, evaluates rules, and reconciles Zinc test orders. A source's first successful scan is a silent baseline. Later unseen listings are recorded and qualifying sealed TCG products are auto-enrolled for stock checks. A stock check must confirm availability before rule evaluation. Uncertain results stay `UNKNOWN` or `ERROR`. Restock alerts require an observed transition. The sandbox purchase switch starts OFF, and Zinc live keys are rejected.

## Local setup

1. Install Python 3.12 and run `python -m pip install -r requirements.txt`.
2. Set `DATABASE_URL` (for example `sqlite:///monitor.db`), `ADMIN_PASSWORD` (16+ characters), `SECRET_KEY` (32+ characters), `SESSION_COOKIE_SECURE=false` for local HTTP, and optionally `DISCORD_WEBHOOK_URL`. See `.env.example`. The app reads environment variables; it does not automatically load `.env`.
3. Run `python -m alembic upgrade head`.
4. In one terminal run `python -m monitor_app.worker`; in another run `python -m flask --app monitor_app.web:app run --port 8000`.
5. Open `http://localhost:8000`, sign in, and add a real product URL. The health endpoint is at `/health`.

The legacy `watchlist.txt` is no longer used by production. If it contains real URLs, import them once after migration with `python -m monitor_app.import_watchlist watchlist.txt`. The current file contains only comments/examples.

## Phase 2 boundaries

- Discovery uses conservative product-card parsing and stable retailer product IDs. Target and Best Buy discovery is **fixture tested only**; live source pages can change or block requests.
- Rules can monitor, request approval, or submit **sandbox** orders. Missing price, seller, identity, or confirmed stock blocks the order path. The dashboard approval action rechecks the product page and rules immediately before submission.
- Zinc requests use a `zn_test_` key, an idempotency key, and a hard total `max_price`. A timed-out submission is marked unknown and never blindly resubmitted. Confirm it in Zinc before any intervention.
- The dashboard never asks for card data or retailer passwords. No live order path exists in this phase.

## Tests

Run `python -m pip install pytest` then `python -m pytest -q`. Tests use local fixtures and mocks; they do not poll retailers or place Zinc orders.

## Guides

- [Deployment](DEPLOYMENT.md)
- [Operations](OPERATIONS.md)
- [Adding retailers](ADDING_RETAILERS.md)
- [Handoff](HANDOFF.md)
- [Implementation audit](IMPLEMENTATION_PLAN.md)
