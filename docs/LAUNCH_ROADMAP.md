# AlienEdge Launch Roadmap

*Decisions of 2026-10-12, set while preparing the first public sendout.*

## The decision: 100 users first, monetize later

**Monetization is PAUSED — deliberately, not forgotten.**

| Decision | Status | Why |
|---|---|---|
| Ship to first 100 users | ✅ NOW | Real users on real devices produce the feedback that matters |
| Monetization (pricing, billing) | ⏸ **PAUSED** | Their feedback defines the package — building a pricing model before anyone uses the product guesses at demand |
| Signup | 🌍 **OPEN TO THE WORLD** | The auth system is production-grade (scrypt, sessions, rate limits, password reset); growth is not the bottleneck — evidence is |
| Engine honesty policy | ✅ ADOPTED | `docs/ENGINE_HONESTY_POLICY.md` — the standard for every engine, present and future |
| Support channel | ✅ CONTACT + FAQ (no AI chat) | An LLM-backed live chat needs an API key and a knowledge base we don't have yet. Delivered instead: `/support` with email + WhatsApp + a 7-question FAQ covering function and usage |
| Mobile | ✅ PASSED | Automated pass complete (`docs/MOBILE_CHECKLIST.md`); run the 10-step manual device checklist before sendout |

## Support channels (published on /support, footer of every public page)

- **Email:** Alienedgebet@gmail.com
- **WhatsApp:** +234 916 804 1864 ([wa.me link](https://wa.me/2349168041864))
- FAQ on `/support` answers the "how does this app work" questions an AI
  chat would have answered

## What happens AFTER the first 100 users (in order)

1. **Collect feedback for ~4 weeks** — feature requests, confusion points,
   what they'd pay for. Use the WhatsApp/email channels + in-app reports.
2. **Decide the monetization package from that evidence** — tier structure,
   which engines sit behind which paywall, price point for the market.
3. **Build billing only after step 2** — provider (Paystack/Flutterwave /
   Stripe by region), subscription lifecycle, entitlement enforcement in the
   auth middleware.
4. **Replace the FAQ part of /support with AI live chat** when justified:
   needs (a) an LLM API key, (b) a curated knowledge base built from the
   feedback of steps 1–2, (c) rate limiting + cost caps. Until then the
   human channels are the honest answer.

## In-flight technical work (2026-10-12)

See `docs/OPS_RUNBOOK.md` for the completed infrastructure: nightly backup
with tested restore, 15-minute healthcheck + alerting, retention cleanup,
midnight pipeline schedule, quota budget, load-tested capacity (sized for
100+ concurrent readers).
