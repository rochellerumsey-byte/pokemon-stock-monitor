# Implementation plan and prototype audit

## Audit (2026-09-27)

The fork has two commits and a single monitoring script. `watchlist.txt` contains comments and example URLs, with no actual products to migrate. No project-specific `AGENTS.md` or `PROJECT_STATE.md` exists.

| Area | Finding | Action |
| --- | --- | --- |
| Retailer names and URL naming | Five retailers are named, but Amazon falls through to generic parsing. Detection uses substring matching and can be spoofed. | Retain the five names; detect by parsed hostname. |
| Product parsing | Button and price ideas are useful, but searching all HTML for phrases confuses related products, scripts, and navigation with the primary offer. No evidence becomes out of stock. | Isolate per-retailer adapters; prefer product-scoped structured data and explicit controls; return `UNKNOWN` on ambiguity. |
| Network requests | Random browser identities and cache-busting were added to evade detection; HTTP errors become false out-of-stock results. | Remove evasion; use one transparent user agent, timeouts, bounded retry, and backoff. |
| State and alerts | `previous_states` is lost on restart. Initial in-stock checks alert. Webhook failures are swallowed. | Persist products, transitions, attempts, and worker heartbeat; alert only on meaningful verified transitions. |
| Operation | File watchlist, macOS sound/browser actions, terminal only; no access control or health. | Server-rendered Flask dashboard with admin login, background worker and health endpoint. |
| Documentation | README asserts untested support and suggests proxies, CAPTCHA solving, and checkout automation. | Replace with verified support matrix and operational documentation. |

## Build plan

1. Add SQLAlchemy models, Alembic migration, application config, and persistent product services. Verify with SQLite tests and a PostgreSQL connection test when available.
2. Add a common adapter result/interface, five retailer modules, generic configured retailer parsing, and sanitized fixtures. Verify adapter tests; assess live pages separately.
3. Add one restart-safe polling worker, transition logic, retention, Discord webhook delivery and attempt history. Verify transitions, restart behavior, isolation, and payload tests.
4. Add authenticated Flask forms for products, generic retailers, Discord test, history, and health. Verify CRUD and access tests.
5. Add Railway container/startup configuration and complete README, deployment, operations, retailer, and handoff documents. Run full tests and security review.

## Deployment design

One Railway web service and a PostgreSQL service. A single container process starts database migrations, one monitoring worker, and the HTTP server. PostgreSQL advisory locking prevents a second worker from polling if an extra web replica starts. Database state and transitions survive restarts. The webhook, admin password, secret key, and database URL are Railway variables. Local development can use SQLite.

## Dependencies

Flask, SQLAlchemy, Alembic, psycopg, requests, Beautiful Soup, Gunicorn, pytest. No frontend build, queue, browser automation, or retailer credentials.
