# Operations

Sign in at the Railway public domain with the admin password. The dashboard is private; `/health` is public and exposes no secret.

- **Add a product:** Copy a direct product page URL, give it a friendly name, and leave retailer on auto-detect. The first confirmed check establishes a baseline and does not alert.
- **Pause or resume:** Use the product's Pause/Resume button. Resume schedules a fresh check. The last known status stays in the database.
- **Remove:** Use Remove. This permanently deletes the product's status and alert history.
- **Test Discord:** Use Send test notification. The result appears at the top and in notification attempts. A configured webhook is required.
- **Read status:** `IN_STOCK`, `PREORDER`, `OUT_OF_STOCK`, `COMING_SOON`, and `UNAVAILABLE` are observations. `UNKNOWN` means the page did not provide a trustworthy signal; `ERROR` means a request or internal failure. Neither means out of stock. Price is last known when a new price is unavailable.
- **Read health:** `/health` shows database, worker heartbeat, last completed cycle, enabled products, errors/unknown, and whether Discord is configured. Worker stale or database error returns HTTP 503.

The worker checks due products approximately every 15 seconds; each product's actual interval is at least five minutes, normally 15 to 20 minutes for built-in retailers, with jitter. Errors back off exponentially; HTTP 429 honors `Retry-After` or waits at least 30 minutes. No browser, CAPTCHA, account login, or proxy is used.

For repeated `UNKNOWN` or `ERROR`, inspect the product page manually and the Railway logs. A retailer may have changed its page or restricted access. Correct an incorrect URL; if the page requires login/challenge, pause that product. For a failed Discord test, check the webhook variable and Discord channel permissions. Do not paste the webhook into support messages.

History and alert attempts older than `HISTORY_RETENTION_DAYS` (default 90, minimum 7) are deleted during worker cycles. Back up PostgreSQL separately if longer records are needed.
