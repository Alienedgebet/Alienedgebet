# ALIENEDGE SUPER-MATRIX: MASTER PROJECT BLUEPRINT (v3)

> **Moved from `.cursorrules`.** Agent quick-rules live in `.cursorrules`.
> **REST paths:** `docs/API.md` and `api/main.py` override any endpoint tables below.

Architectural reference for AlienEdge — institutional-grade football intelligence.
Source code is always authoritative; this document is guidance.

---

# PART 1 — ARCHITECTURE

## ROLE

Before generating, modifying, refactoring, or deleting any code:
- Read `main.py`, `api/main.py`, `alienedge-frontend/lib/api.ts`, `tailwind.config.ts`, `app/globals.css`
- Never assume implementation details
- Preserve existing architecture unless explicitly instructed
- Prediction accuracy over speed

## PROJECT IDENTITY

AlienEdge is a mathematical decision-support platform — NOT a betting app, bookmaker, wallet,
or financial product. The frontend visualizes backend intelligence.

## DEVELOPMENT PRIORITY ORDER

1. Prediction accuracy → 2. Backend integrity → 3. Engine relationships → 4. API contracts →
5. Frontend visualization → 6. UX → 7. Social features

## CRITICAL ARCHITECTURE RULES

### Rule 1 — Unified GG + Over 1.5 Head Engine
`Engine/gg_precision_engine.py` (`run_gg_o15_engine`) generates BOTH GG and Over 1.5 picks.
Legacy `gg_stage1.py` / `gg_stage2.py` are inactive.

### Rule 2 — Unders Engine Handles Two Markets
`Engine/unders_engine.py` handles U2.5 AND U3.5 in one run.

### Rule 3 — Win Forecast in Foundation Phase
`win_forecast.py` runs in Phase A. Win chain (Phase H): u2s → win_psychology → win_apex →
sh_master_vortex → sh_8goal → win_raw.

### Rule 4 — Weekly Filters Are Separate
GG / Over 2.5 / Win filter engines are user-triggered, separate UI (`app/weekly`), never on
pick chain pages.

### Rule 5 — live_stage7_dashboard Is Standalone
Not in `main.py` pipeline; accessed via `/api/live/dashboard`.

### Rule 6 — DNA Engine V2 Is Additive, Never a Replacement
`CORE/dna_engine_v2.py` (`run_dna_engine_v2`) runs alongside the original `CORE/dna_profiler.py`
(`run_dna_profiler`) in Phase A — it does not replace it, and it writes to its own files
(`data/team_dna_v2_profiles.json`, `data/fixture_style_clashes_v2.json`). `CORE/dna_v2_market_factors.py`
derives per-market (win/gg/over25/over15/unders/draw/corners) DNA factor win-counts from the v2
output only — see `docs/API.md` → "DNA v2". This is the sole source for the frontend's universal
DNA count column and DNA Analysis page; the frontend never recomputes DNA logic itself.

## ACTIVE ENGINE MAP

See `main.py` for the live pipeline. Summary:

- **Phase A — Foundation:** dna, dna v2 (+ market factors), underdog, audit, calibration, apex UD, win forecast, sh-gg-winner
- **Phase C — Corners:** 5 stages (miner → refiner → psychology → catalyst → aggregator)
- **Phase D — GG:** precision head (GG+O1.5) → forensics → psychology → supreme → precision filter
- **Phase E — Over 2.5:** 7 stages through forecast
- **Phase F — Over 1.5:** 3 stages (reads GG head output)
- **Phase G — Specials:** unders, draw, sot, fhvi, shvi
- **Phase H — Win / SH:** u2s, win psych, win apex, sh-master, sh-8goal, win raw
- **Phase I — Live:** 7-code ecosystem (5 REST routes in `api/main.py` today)
- **Phase 4 — Filters:** gg/win/over25 weekly engines + win precision filter

---

# PART 2 — IMPLEMENTATION REFERENCE

## REST API

**Do not use endpoint tables in this file.** Read `docs/API.md` (generated from `api/main.py`).
Sync `alienedge-frontend/lib/api.ts` to match exactly.

## WEEKLY FILTER SYSTEM

Separate from pick chains. Dedicated page `app/weekly/page.tsx` with three tabs.
Endpoints: `/api/filter/gg/{date}`, `/api/filter/gg/weekly`, same pattern for win and over25,
plus `/api/filter/win/precision/{date}` and weekly variant.

## FRONTEND ARCHITECTURE

### Stack
Next.js 16 App Router · TypeScript strict · Tailwind · Shadcn UI · Framer Motion · Lucide ·
Recharts · Axios via `lib/api.ts`

### Design system
- Backgrounds: `bg-bg-primary` `#060912`, `bg-bg-card` `#0d1426`, `bg-bg-elevated` `#111d35`
- Accents: cyan `#06b6d4`, indigo `#6366f1`, amber, green, red
- UI: Inter · Metrics: JetBrains Mono
- Bloomberg-terminal aesthetic, glass panels, glow borders

### 3-column layout (v3)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOP BAR — match center stats, user menu                                       │
├──────────────────┬──────────────────────────────────┬────────────────────────┤
│ SIDEBAR (240px)  │ MAIN (flex-1)                    │ RIGHT PANEL (320px)    │
│ Intelligence nav │ Elite picks, live/incoming tables│ War Room + Leaderboard │
└──────────────────┴──────────────────────────────────┴────────────────────────┘
```

Right panel: **only** Global War Room and Leaderboard. Match Comments live under match cards.

### Multi-engine display rule
Every market page shows ALL chain stages together (collapsible, never hidden by default).
Weekly filters stay on `/weekly` only.

## FRONTEND BUILD ORDER

See `docs/PHASES.md` for phased delivery. File sequence:

| Layer | Files | Status |
|-------|-------|--------|
| 1 Foundation | globals.css, tailwind.config.ts, lib/api.ts, layout.tsx, page.tsx | Phase 0 scaffolded |
| 2 Layout shell | Sidebar, TopBar, RightPanel, AppShell | Phase 1 — not started |
| 3 Dashboard | dashboard/page.tsx | not started |
| 4 Market pages | gg, win, over25, over15, corners, draw, unders, sh-master | not started |
| 5 Weekly filters | weekly/page.tsx | not started |
| 6 Live | live/page.tsx | not started |
| 7–10 | predictions, charts, live, social components | not started |

## API CLIENT RULES

- All HTTP through `lib/api.ts`
- Typed returns matching `api/main.py` responses
- Base URL: `http://localhost:8000`
- Mock data typed to interfaces when backend unavailable

---

# PART 3 — SOCIAL DATA INFRASTRUCTURE

Minimal schema: `users`, `war_room_messages`, `match_comments`.
War Room needs SSE/WebSocket (one global channel). Comments and Leaderboard are pull-based.
Rate limits and War Room gate (`prediction_accuracy > 55%`) enforced server-side.

---

# PART 4 — SOCIAL INTELLIGENCE (v3 — three features only)

1. **Global War Room** — one gated room, read-all / post if accuracy > 55%
2. **Match Comments** — flat thread under prediction cards, open to all members
3. **Leaderboard** — sort by `prediction_accuracy`, min sample size threshold

Explicitly NOT in v3: per-fixture rooms, feeds, syndicates, notebooks, Kelly, Paroli, VIP tiers.

---

# PART 5 — DEVELOPMENT RULES

Always: read before write, strict TS, Tailwind tokens, lucide icons, framer-motion transitions.
Never: invent engine math, use legacy gg stages, mix weekly filters into chain pages, use `any`,
add financial/wallet features, build out-of-scope social features.

**Final rule:** `api/main.py` and `main.py` beat this document on backend matters.
