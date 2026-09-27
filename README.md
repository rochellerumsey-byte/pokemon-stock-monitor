# Pokémon Stock Monitor

A private web dashboard that checks public Pokémon TCG product pages and sends Discord notifications on meaningful restock transitions. It does not purchase products or attempt to bypass retailer controls.

## Retailers

Target, Best Buy, Pokémon Center, and GameStop have conservative public-page adapters. Amazon is present but reports `UNAVAILABLE` because reliable public monitoring has not been established. Simple additional sites can be configured in the dashboard. See [RETAILER_SUPPORT.md](RETAILER_SUPPORT.md) for actual validation, which is distinct from fixture tests.

## How it works

The Flask dashboard manages products and simple retailer rules. SQLAlchemy and Alembic store products, last known state, status changes, alert attempts, and worker health in PostgreSQL (SQLite locally). One worker checks due products with bounded requests, backoff, and retailer-aware intervals. Adapters parse public pages; uncertain results stay `UNKNOWN` or `ERROR`. Discord alerts are sent only when a previously observed `OUT_OF_STOCK` or `COMING_SOON` product becomes `IN_STOCK` or `PREORDER`. Initial observations do not alert.

## Local setup

1. Install Python 3.12 and run `python -m pip install -r requirements.txt`.
2. Set `DATABASE_URL` (for example `sqlite:///monitor.db`), `ADMIN_PASSWORD` (16+ characters), `SECRET_KEY` (32+ characters), `SESSION_COOKIE_SECURE=false` for local HTTP, and optionally `DISCORD_WEBHOOK_URL`. See `.env.example`. The app reads environment variables; it does not automatically load `.env`.
3. Run `python -m alembic upgrade head`.
4. In one terminal run `python -m monitor_app.worker`; in another run `python -m flask --app monitor_app.web:app run --port 8000`.
5. Open `http://localhost:8000`, sign in, and add a real product URL. The health endpoint is at `/health`.

The legacy `watchlist.txt` is no longer used by production. If it contains real URLs, import them once after migration with `python -m monitor_app.import_watchlist watchlist.txt`. The current file contains only comments/examples.

## Tests

Run `python -m pip install pytest` then `python -m pytest -q`. Tests use local fixtures and mocks; they do not poll retailers.

## Guides

- [Deployment](DEPLOYMENT.md)
- [Operations](OPERATIONS.md)
- [Adding retailers](ADDING_RETAILERS.md)
- [Handoff](HANDOFF.md)
- [Implementation audit](IMPLEMENTATION_PLAN.md)
