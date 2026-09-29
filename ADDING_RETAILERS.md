# Adding retailers

## Simple dashboard configuration

An admin can add a public domain, an example product URL, a CSS selector for the product's purchase area, line-separated in-stock and out-of-stock text, and an optional price selector. The configured domain must resolve publicly. The purchase selector should cover only the primary product, not recommendations or site navigation. Both positive and negative indicators appearing together produce `UNKNOWN`. If the selector is missing, the result is `UNKNOWN`. Test several real in-stock and out-of-stock pages before relying on it. Disable a rule when it becomes unreliable.

Generic rules cannot handle JavaScript-only availability, location-specific inventory, retailer logins, or complex APIs. Such a site needs a custom adapter.

## Custom adapter

Add a small class in `monitor_app/adapters.py` implementing `parse(html) -> Result`. Register it in `ADAPTERS` and its trusted domain in `BUILTINS`. Product fetching, timeouts, rate-limit handling, backoff, state transitions, and Discord stay in the shared services. Prefer explicit structured product offers; use product-specific controls when necessary. Return `UNKNOWN` for ambiguous pages and `ERROR` for actual errors. Never turn a blocked page into `OUT_OF_STOCK`.

Add sanitized fixture tests for at least confirmed in-stock, out-of-stock, ambiguous, and price cases. Validate the adapter against current public pages and update `RETAILER_SUPPORT.md` with the date and observed result. Do not add checkout, CAPTCHA, proxy rotation, or access-control bypass logic.
