# Frontend Build Phases

One task per session. One PR-sized diff. Verify before advancing.

## Agent rules

1. **Backend contract first** — read `api/main.py` before editing `lib/api.ts`
2. **No progress fiction** — use `scaffolded` / `verified` / `not started`, never stale ✅
3. **Don't rebuild assets** — keep `tailwind.config.ts`, `globals.css`, `components/ui/*`
4. **Verify each phase** — run frontend, hit `/health`, confirm 200 before next layer
5. **Explicit out of scope** — end every session prompt with what not to build

## Phase 0 — Foundation (current)

| Item | Status |
|------|--------|
| `tailwind.config.ts` | scaffolded (keep) |
| `app/globals.css` | scaffolded (keep) |
| `lib/api.ts` | verified against `api/main.py` |
| `app/layout.tsx` | scaffolded — root shell |
| `app/page.tsx` | scaffolded — Phase 0 landing + health ping |
| `docs/*` | scaffolded |

**Out of scope:** AppShell, dashboard, market pages, engines, social features.

## Phase 1 — Layout shell (complete)

Read `docs/BLUEPRINT.md` layout section only.

| Item | Status |
|------|--------|
| `components/layout/Sidebar.tsx` | verified |
| `components/layout/TopBar.tsx` | verified |
| `components/layout/RightPanel.tsx` | verified — mock data, Phase 13 will wire social backend |
| `components/layout/AppShell.tsx` | verified |
| Wire `app/layout.tsx` → AppShell | verified |

## Phase 2 — Shared building blocks (complete)

| Item | Status |
|------|--------|
| `components/predictions/TierBadge.tsx` | verified |
| `components/predictions/ScoreBar.tsx` | verified |
| `components/predictions/ProbValue.tsx` / `ProbCell.tsx` | verified |
| `components/predictions/PredictionTable.tsx` / `PredictionCard.tsx` | verified |
| `components/predictions/ChainSection.tsx` (accordion) | verified |
| `components/layout/DateSelector.tsx` | verified |
| `lib/use-api.ts` | verified |

## Phase 3+ — One page per session

Build in blueprint order (see `BLUEPRINT.md` FRONTEND BUILD ORDER):

| Item | Status |
|------|--------|
| Layer 3: `app/dashboard/page.tsx` | verified — hero carousel, elite rank list, engine status, AI market assessment |
| Layer 4: one market page per session (`win`, `gg`, `over25`, `over15`, `draw`, `unders`, `corners`, `sot`, `fhvi`, `shvi`, `underdog`) | `win` + `gg` verified — full backend column sets. Remaining markets: column audit pending |
| Layer 5: `app/weekly/page.tsx` (Weekly Forecast Filter) | in progress — renamed; result columns locked to GG/Win/O25/Precision engine `display_cols` printouts; pick-page column audits next |
| Layer 6: `app/live/page.tsx` | verified (Phase B) — all 5 `liveApi` heads via `ChainStage`; deeper UX = Phase C |
| Layers 7–10: shared components as needed per page | not started |
| Phase 13: social backend (auth, war_room_messages, match_comments, leaderboard endpoints) + wiring `RightPanel.tsx` off mock data | not started — zero `/api/social/*` routes exist yet |
| Phase B — Entry & nav | verified — `/` redirects to `/dashboard`; `/live` no longer 404s |

**Out of scope right now:** Phase C live UX polish, weekly filter typing, social widgets.
