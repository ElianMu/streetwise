# Provider access and permitted usage

No commercial provider has been newly connected by this change. Credential presence is not proof of working access, licensed fields, or permitted display. The audit records local bindings only; production must be checked via `/api/status` and a real request. Do not paste keys into chat, frontend files or source control.

| Provider | Existing adapter | Fields requested | Access / pricing / policy check before use |
|---|---|---|---|
| Google Places (New) | Text Search | rating, userRatingCount, priceLevel, hours, website and Maps link; formatted address for branch matching | Cloud project + enabled API + billing + field/SKU quota. Review current Maps/Places display, logo attribution and storage policies, including compatibility with this MapLibre UI. No current price quote or blanket display permission is asserted. |
| Yelp | Fusion search | per-provider rating, count, price indicator, source link | Developer agreement/plan and current access; attribution/link and permitted storage rules. Live access not verified. |
| Foursquare | Existing v3 search adapter | rating scale 10, count, price | Verify current API version, contracted endpoint/fields, plan and attribution before enabling. The legacy endpoint is not certified current by this audit. |
| Booking.com Demand | Contract-specific client not implemented | No room/rate/inventory data retrieved | Partner approval, credentials, property ID mapping, dated party-specific requests and permitted use are prerequisites. |
| Expedia Rapid | Contract-specific client not implemented | No room/rate/inventory data retrieved | Partner approval, signature/client integration and property mapping are prerequisites. |

Official starting points:
- https://developers.google.com/maps/documentation/places/web-service/get-api-key
- https://developers.google.com/maps/documentation/places/web-service/policies
- https://developers.google.com/maps/billing-and-pricing/overview
- https://docs.developer.yelp.com/
- https://docs.foursquare.com/
- https://developers.booking.com/demand
- https://developers.expediagroup.com/rapid

Current official policy pages could not all be read through the cloud egress policy. Therefore plan prices, exact usage limits and display licence compliance are pending verification, not inferred. Required Cloud domain additions were saved in the environment draft; saving does not publish or apply them.

## Configuration

Keep application keys in Render's backend Environment settings. The existing variable names are `GOOGLE_PLACES_API_KEY`, `YELP_API_KEY`, `FOURSQUARE_API_KEY`, `BOOKING_DEMAND_API_KEY`, `EXPEDIA_RAPID_API_KEY`. Do not configure providers merely to satisfy an empty status indicator; use only a provider with a valid agreement for the intended fields/display. For Google, enable Places API (New), restrict the key to that API, use backend-appropriate restrictions, and configure quotas/budget alerts (alerts alone do not stop billing). The GitHub Pages origin is not a valid website-referrer restriction for a server-side Render call.

Default business-response caching is disabled, and review text is neither requested nor stored. No cross-provider rating is calculated. Matching requires source name evidence, matching street address and nearby coordinates; insufficient address evidence returns no confident match instead of borrowing a nearby branch's reviews.

Hotel results without a working lodging client are static listings only. Bed counts, cancellation, dated prices, fees and availability never become verified merely because a key is set. Current clients return `blocked_by_provider_access` without credentials and `not_implemented` if credentials exist but a partner-specific implementation is absent.
