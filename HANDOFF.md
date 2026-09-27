# Handoff checklist

For the person taking over:

1. Obtain ownership or maintainer access to this GitHub fork, the Railway project, PostgreSQL service, and the intended Discord server/channel.
2. In Railway, confirm `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD`, `DISCORD_WEBHOOK_URL`, and `SESSION_COOKIE_SECURE=true`. Keep secrets in Railway Variables. Rotate the admin password and webhook when ownership changes. Zinc test mode additionally needs a `zn_test_` API key and `ZINC_SHIPPING_*` variables; do not give the app a live key.
3. Enable and verify PostgreSQL backups. Review Railway billing and usage limits.
4. Open the Railway domain, sign in, confirm healthy database and worker, and send a Discord test. No terminal or code edit is required for daily product management.
5. Add one real product per desired retailer. Compare the first result with the live page. Target remains unsupported. Best Buy requires a developer Products API key and Railway validation; see `BEST_BUY_API.md` and `RETAILER_SUPPORT.md`.
6. Bookmark `OPERATIONS.md`. If health goes stale or errors persist, inspect Railway logs or contact a developer.

The app monitors and notifies, and can submit **Zinc test-mode orders only** when a rule and the separate sandbox switch permit it. Live purchasing is unavailable. The first discovery scan is silent; first stock observations do not send restock alerts. Alerts begin on an observed out-of-stock or coming-soon to in-stock or preorder transition.

Still requiring account access: connecting GitHub to Railway, provisioning PostgreSQL, setting secrets, generating the public domain, creating the Discord webhook, and verifying actual delivery to the chosen channel. These actions were not done in development.
