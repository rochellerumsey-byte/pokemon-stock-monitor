# Deploy on Railway

The deployed app uses one Railway web service and one PostgreSQL service. It does not depend on a personal computer.

1. Push this repository to GitHub. In Railway, create a project and add PostgreSQL.
2. Add a service from this GitHub repository. Railway detects the root `Dockerfile`.
3. In the web service Variables, set `DATABASE_URL` to a reference to PostgreSQL's `DATABASE_URL` (for example, `${{Postgres.DATABASE_URL}}` if the service is named Postgres).
4. Set `ADMIN_PASSWORD` to a unique password of at least 16 characters and `SECRET_KEY` to a random secret of at least 32 characters. Set `SESSION_COOKIE_SECURE=true`.
5. Create a Discord webhook in the intended channel, then set `DISCORD_WEBHOOK_URL` in Railway Variables. Do not put it in Git or messages.
6. Generate a public domain for the web service. Open `/health`. On a healthy startup it reports database connected and worker running. Then sign in and send a test Discord notification.
7. Add one real product URL for each retailer you intend to use. Watch its first check and compare the status and price with the public product page before relying on alerts.

The startup script runs `alembic upgrade head`, starts one polling process, and runs Gunicorn. PostgreSQL advisory locking prevents two polling processes from checking the same products if multiple web replicas start. Keep the web service running continuously. Railway health checks use `/health` and return 503 if the worker heartbeat is stale.

The web service must use PostgreSQL in production. A SQLite URL is for local development only. Enable database backups in Railway before handoff. A database connection failure at startup may need a redeploy after PostgreSQL becomes available.

Current Railway setup is described in [Railway's service documentation](https://docs.railway.com/services) and [PostgreSQL documentation](https://docs.railway.com/databases/postgresql).
