# Operations

Sign in at the Railway public domain with the admin password. The dashboard is private; `/health` is public and exposes no secret.

- **Add a product:** Copy a direct product page URL, give it a friendly name, and leave retailer on auto-detect. The first confirmed check establishes a baseline and does not alert.
- **Pause or resume:** Use the product's Pause/Resume button. Resume schedules a fresh check. The last known status stays in the database.
- **Remove:** Use Remove. Products without purchase history are deleted with their status history. Products with purchase history are paused and retained for audit.
- **Test Discord:** Use Send test notification. The result appears at the top and in notification attempts. A configured webhook is required.
- **Read status:** `IN_STOCK`, `PREORDER`, `OUT_OF_STOCK`, `COMING_SOON`, and `UNAVAILABLE` are observations. `UNKNOWN` means the page did not provide a trustworthy signal; `ERROR` means a request or internal failure. Neither means out of stock. Price is last known when a new price is unavailable; purchase rules require a price confirmed by the current successful check.
- **Read health:** `/health` shows database, worker heartbeat, last completed cycle, enabled products, errors/unknown, and whether Discord is configured. Worker stale or database error returns HTTP 503.

The worker checks due products approximately every 15 seconds; each product's actual interval is at least five minutes, normally 15 to 20 minutes for built-in retailers, with jitter. Errors back off exponentially; HTTP 429 honors `Retry-After` or waits at least 30 minutes. No browser, CAPTCHA, account login, or proxy is used.

## Discovery and sandbox orders

- Add a Target or Best Buy public listing URL under Discovery. The first successful scan is a **silent baseline**. If no recognizable product cards appear, the baseline remains pending and the source shows an error. Later unseen listings appear in Recent discoveries. Recognized sealed products join Products and receive an ordinary stock check. Other merchandise remains recorded but is not auto-enrolled.
- Source scans default to every 30 minutes. Source failures back off for 30 minutes and do not stop other sources. A listing or product check marked `UNKNOWN` is not treated as in stock.
- Create a rule with retailer, type, title, price, quantity, direct-seller, daily spend, and optional lifetime SKU limits. It starts disabled. `MONITOR` never creates an order. `APPROVAL` creates a candidate for dashboard approval. `AUTO` is still sandbox only and requires the separate sandbox switch. Missing or ambiguous price, seller, identity, or availability blocks a match.
- Approve or reject a pending candidate in the authenticated dashboard. Approval rechecks the product page and rule. A changed or unconfirmed offer is blocked. Submitting records a Zinc idempotency key and hard all-in order cap. Pending or submitted candidates reserve their full order cap against the daily ceiling.
- If a submission says **SUBMISSION UNKNOWN**, check Zinc's sandbox orders using the stored idempotency key and resolve it with developer help. The app does not retry an uncertain submission. The emergency purchase-off button stops future submissions; it cannot cancel an order already sent to Zinc.
- Sandbox order status is polled after about seven minutes, then every five minutes until terminal. `PLACED` means Zinc's test-mode order status, not a live purchase. Purchase attempts and status changes remain in the dashboard audit history.

For repeated `UNKNOWN` or `ERROR`, inspect the product page manually and the Railway logs. A retailer may have changed its page or restricted access. Correct an incorrect URL; if the page requires login/challenge, pause that product. For a failed Discord test, check the webhook variable and Discord channel permissions. Do not paste the webhook into support messages.

History and alert attempts older than `HISTORY_RETENTION_DAYS` (default 90, minimum 7) are deleted during worker cycles. Back up PostgreSQL separately if longer records are needed.
