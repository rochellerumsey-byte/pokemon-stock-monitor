# Retailer support and validation

Validation date: 2026-09-27. **No retailer has been verified for live monitoring.** Status labels describe this runtime's live validation, not the existence of adapter code. Local fixture tests passed, but fixtures are examples and do not confirm current retailer behavior. Run checks from the deployed Railway environment before relying on alerts.

| Retailer | Validation | Direct public page check | Current limitation |
| --- | --- | --- | --- |
| Target | PARTIALLY VERIFIED | [Scarlet & Violet Booster Bundle](https://www.target.com/p/-/A-88275197) returned HTTP 200, a product title, and a disabled Add to cart button. No product JSON-LD availability was present. | The conservative adapter reports `UNKNOWN` rather than inferring stock solely from a disabled button. Need an unambiguous live in-stock and out-of-stock signal. |
| Best Buy | UNVERIFIED | [Prismatic Evolutions Booster Bundle](https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-prismatic-evolutions-booster-bundle/6608206) failed with a connection error from this runtime. | Fixture parser works; live availability and price were not established. |
| Pokémon Center | BLOCKED/UNSUPPORTED in this runtime | [Cyrus Premium Tournament Collection](https://www.pokemoncenter.com/product/699-85363/) returned HTTP 403. | No bypass is implemented. Monitor reports `ERROR`. |
| GameStop | BLOCKED/UNSUPPORTED in this runtime | [Mega Evolution Booster Box](https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-mega-evolution-booster-box/20027793.html) returned HTTP 403. | No bypass is implemented. Monitor reports `ERROR`. |
| Amazon | BLOCKED/UNSUPPORTED | Public product pages are not treated as a reliable monitoring source. | Adapter always reports `UNAVAILABLE`; it does not evade access controls. |

The tests use sanitized local HTML examples; they do not prove the current live sites expose those signals. An `UNKNOWN`, `ERROR`, or `UNAVAILABLE` observation never triggers a restock notification. A retailer should be called VERIFIED only after a current live public product page yields a correct stock and price result and the same behavior is confirmed on both sides of a stock transition.

## Phase 2 discovery validation

Target and Best Buy listing discovery is **FIXTURE TESTED ONLY**. Local fixture cards verify parsing, canonical retailer IDs, classification, silent baseline, deduplication, and enrollment. No live retailer listing page has been verified as parseable from Railway. Source-page selectors, seller signals, and product IDs need live validation before discovery or purchase candidates are relied upon. Pokémon Center, GameStop, Amazon, and generic retailers have **no discovery adapter** in this phase. Zinc sandbox order tests are mocked; no real Zinc sandbox submission or Discord delivery has been confirmed.

The discovery adapter registry supports retailer-specific URL identities and card selectors. Both documented Best Buy `/product/.../<sku>` and `/site/.../<sku>.p` URL shapes are covered by local tests; this does not verify current Best Buy pages. Ambiguous prices and multiple structured offers remain unconfirmed, which blocks AUTO rules. Seller identity from a single structured offer is retained for rule evaluation. Retailer-direct fulfillment at Zinc checkout has not been independently verified and must be validated before any future live purchasing phase.
