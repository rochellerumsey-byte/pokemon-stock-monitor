# Deploy on Railway

The deployed app uses one Railway web service and one PostgreSQL service. It does not depend on a personal computer. Validate the draft PR branch before merging.

1. In Railway, create a project and add PostgreSQL.
2. Add one web service from `rochellerumsey-byte/pokemon-stock-monitor`, selecting the `codex/reliable-monitor` branch for validation. Set **one replica**. Railway detects the root `Dockerfile`; leave the Start Command blank so its `CMD` runs.
3. In web service Variables, set `DATABASE_URL` to a reference to PostgreSQL's `DATABASE_URL` (for example, `${{Postgres.DATABASE_URL}}` if the service is named Postgres). The startup script refuses a missing or non-PostgreSQL URL.
4. Set `ADMIN_PASSWORD` to a unique password of at least 16 characters and `SECRET_KEY` to a random secret of at least 32 characters. `SESSION_COOKIE_SECURE` defaults to `true`; keep it true for the public HTTPS domain.
   Optionally set `DISCOVERY_INTERVAL_SECONDS` (default 1800, minimum 300). This controls source-page scans separately from `CHECK_INTERVAL_SECONDS`, which controls individual product checks.
5. For a new Railway service, set **Healthcheck Path** to `/health`, timeout to **180 seconds**, and **Restart Policy** to **On Failure** in service settings. The checked-in `railway.json` has valid legacy values, but Railway no longer applies Config as Code to new services. Do not rely on that file for this setup.
6. Create a Discord webhook in the intended channel, then set `DISCORD_WEBHOOK_URL` in Railway Variables. Do not put it in Git or messages.
7. Generate a public domain. Open `/health`; healthy startup reports database connected and worker running. Sign in and send a test Discord notification. Review the Railway logs for migration, worker, and Gunicorn startup.
8. Add a real product URL, compare its first check with the public product page, then restart the web service. Confirm the product and status persist and `/health` returns healthy again.

## Optional Zinc test mode

Phase 2 cannot place live purchases. For sandbox validation, obtain a Zinc **test-mode** API key starting `zn_test_`, then set `ZINC_API_KEY` and the `ZINC_SHIPPING_*` variables listed in `.env.example` in Railway Variables. Do not commit the key or an address. The address goes directly to Zinc on test-mode submission and is not stored in the application's tables. A live `zn_live_` key fails startup validation and is rejected by the provider. In the dashboard, create a disabled rule, review and enable it, then use **Enable sandbox submissions**. This switch defaults OFF and has an emergency OFF button. Use a Zinc rehearsal product and verify the sandbox order record, status reconciliation, and Discord attempts before trusting the flow. Zinc's [current order API](https://github.com/zincio/skills/blob/master/skills/universal-checkout/SKILL.md) specifies the idempotency key and total `max_price`; [Zinc describes test mode](https://www.zinc.com/) as isolated and non-purchasing.

Real retailer discovery, Zinc sandbox delivery, Discord delivery, and PostgreSQL operation still require deployment validation. Fixture tests and CI do not establish them.

## Optional Best Buy Products API

Best Buy discovery and numeric-SKU monitoring require `BEST_BUY_API_KEY` in Railway Variables. Obtain it through the [Best Buy Developer Portal](https://developer.bestbuy.com/) and review [BEST_BUY_API.md](BEST_BUY_API.md), including the API content-retention terms, before configuring it. No key is included in CI. Without a key, Best Buy checks remain `UNKNOWN` and source scans keep their baseline pending. An API success in CI is mocked; verify a full scan and known product from Railway after configuring the key. Seller remains unknown and purchase rules stay blocked for Best Buy.

The startup script validates required settings, runs `alembic upgrade head`, starts one polling process, and runs Gunicorn on Railway's `PORT`. It stops the container if either process exits unexpectedly so Railway can restart it. PostgreSQL advisory locking prevents duplicate polling during restarts. Railway's health check gates deployment; Railway does not poll it continuously afterward, so the dashboard and logs remain important.

The web service must use PostgreSQL. A SQLite URL is for local development with the separate commands in the README, not `start.sh`. Enable database backups before handoff. A database connection failure at startup may need a redeploy after PostgreSQL becomes available.

Current Railway setup is described in [Railway's service documentation](https://docs.railway.com/services), [PostgreSQL documentation](https://docs.railway.com/databases/postgresql), [health check documentation](https://docs.railway.com/deployments/healthchecks), and [Config as Code deprecation notice](https://docs.railway.com/config-as-code).
