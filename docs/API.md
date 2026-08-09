# AlienEdge REST API

**Source of truth:** `api/main.py`  
**Frontend client:** `alienedge-frontend/lib/api.ts` (must match this file exactly)

Base URL: `http://localhost:8000`

## Health

| Method | Path | Notes |
|--------|------|-------|
| GET | `/` | Health |
| GET | `/health` | `{ status, service, version }` |

## Foundation

| Method | Path | Engine |
|--------|------|--------|
| GET | `/api/dna/{date}` | `run_dna_profiler` |
| GET | `/api/underdog/{date}` | `run_underdog_engine` |
| GET | `/api/underdog/audit/{date}` | `run_underdog_master_engine` |
| GET | `/api/underdog/apex/{date}` | `run_apex_underdog_aggregator` |
| GET | `/api/calibration/{date}` | `run_total_visibility_merger` |

### DNA v2 (additive — separate from `/api/dna`, never overwrites v1 data)

| Method | Path | Engine | Notes |
|--------|------|--------|-------|
| GET | `/api/dna/v2/{date}` | `run_dna_engine_v2` + `build_market_factor_counts` | Runs live, writes `data/team_dna_v2_profiles.json`, `data/fixture_style_clashes_v2.json`, `data/dna_v2_market_factors.json`. Returns `{ dna_profiles, fixture_clashes, market_factors }`. |
| GET | `/api/dna/v2/latest` | disk read only | Fast, no recompute — reads the three files above straight off disk. Used by the frontend for instant fixture-list DNA counts and instant DNA Analysis page opens. |

`market_factors` is keyed by `fixture_id` and contains a per-market (`win`, `gg`, `over25`, `over15`, `unders`, `draw`, `corners`) breakdown of `{ home_count, away_count, factors: [{ name, home_value, away_value, winner }] }` — this is the source of the fixture-list "DNA count" column (e.g. `9 : 3`). First Half / Second Half markets are intentionally excluded: the engine only aggregates full-match statistics, so there is no genuine half-specific signal to compare.

## Win

| Method | Path | Engine |
|--------|------|--------|
| GET | `/api/win/forecast/{date}` | `run_win_forecast_engine` |
| GET | `/api/win/psychology/{date}` | `run_win_psychology_engine` |
| GET | `/api/win/apex/{date}` | `run_win_apex_aggregator` |
| GET | `/api/win/raw/{date}` | `run_win_raw_engine` |
| GET | `/api/win/u2s/{date}` | `run_u2s_psychology_engine` |

## GG / BTTS

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/gg/precision/{date}` | `{ gg, o15 }` |
| GET | `/api/gg/forensics/{date}` | array |
| GET | `/api/gg/psychology/{date}` | array |
| GET | `/api/gg/supreme/{date}` | array |
| GET | `/api/gg/cross-verify` | array (no date) |

## Over 2.5

| Method | Path |
|--------|------|
| GET | `/api/over25/stage1/{date}` |
| GET | `/api/over25/stage2/{date}` |
| GET | `/api/over25/stage3/{date}` |
| GET | `/api/over25/psychology/{date}` |
| GET | `/api/over25/gold/{date}` |
| GET | `/api/over25/apex/{date}` |
| GET | `/api/over25/forecast/{date}` |

## Over 1.5

| Method | Path |
|--------|------|
| GET | `/api/over15/stage3/{date}` |
| GET | `/api/over15/psychology/{date}` |
| GET | `/api/over15/apex/{date}` |

## Unders & Draw

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/unders/{date}` | `{ u25, u35 }` |
| GET | `/api/draw/{date}` | `{ draws, parity_list, amateurs_list }` |

## Corners

| Method | Path |
|--------|------|
| GET | `/api/corners/stage1/{date}` |
| GET | `/api/corners/stage2/{date}` |
| GET | `/api/corners/psychology/{date}` |
| GET | `/api/corners/catalyst/{date}` |
| GET | `/api/corners/aggregator/{date}` |

## Specials / SH

| Method | Path |
|--------|------|
| GET | `/api/sot/{date}` |
| GET | `/api/fhvi/{date}` |
| GET | `/api/shvi/{date}` |
| GET | `/api/sh-gg-winner/{date}` |
| GET | `/api/sh-master/{date}` |
| GET | `/api/sh-8goal/{date}` |

## Live (exposed in api/main.py)

| Method | Path | Engine |
|--------|------|--------|
| GET | `/api/live/prematch` | stage 1 strategic audit board (`live_prematch_audit.json`) |
| GET | `/api/live/validation` | stage 2 VALIDATION BOARD + VALIDATED_ALERTS (`validation_board.json`) |
| GET | `/api/live/incoming` | stage 3 incoming |
| GET | `/api/live/danger` | stage 4 danger |
| GET | `/api/live/aggregator` | stage 5 aggregator |
| GET | `/api/live/orchestrator` | stage 6 VIP + LIVE cycle board (`orchestrator_board.json`) |
| GET | `/api/live/alerts` | stage 6 fire_alert rows (`ready_to_push` / session logs) |
| GET | `/api/live/dashboard` | stage 7 supreme dashboard |

> Stage 2 validates stage 1’s `live_predictions.json` in-play. Stage 6 is the VIP + free LIVE alert orchestrator (frontend `/alerts`). Infinite scanner loops stay CLI-only; REST reads their persisted snapshots.

## Weekly filters

| Method | Path |
|--------|------|
| GET | `/api/filter/gg/{date}` |
| GET | `/api/filter/gg/weekly` |
| GET | `/api/filter/win/{date}` |
| GET | `/api/filter/win/weekly` |
| GET | `/api/filter/over25/{date}` |
| GET | `/api/filter/over25/weekly` |
| GET | `/api/filter/win/precision/{date}` |
| GET | `/api/filter/win/precision/weekly` |

Query params: see function signatures in `api/main.py`.

## Pipeline

| Method | Path | Query |
|--------|------|-------|
| GET | `/api/pipeline/{date}` | `?phases=foundation,win,gg,...` |

## Not in api/main.py (do not add to lib/api.ts)

- `/api/performance/{date}`
- `/api/live/stage1/prematch` (use `/api/live/prematch`)
- `/api/live/stage2/validator` (use `/api/live/validation`)
- `/api/live/stage3/incoming` (use `/api/live/incoming`)
- `/api/live/stage4/danger` (use `/api/live/danger`)
- `/api/live/stage5/aggregator` (use `/api/live/aggregator`)
- `/api/live/stage6/alerts` (use `/api/live/alerts`)
- `/api/live/stage7/dashboard` (use `/api/live/dashboard`)
- `/api/underdog/base/{date}` (use `/api/underdog/{date}`)
- `/api/underdog/master/{date}` (use `/api/underdog/audit/{date}`)
- `/api/underdog/handshake/{date}` (use `/api/calibration/{date}`)
- `/api/over25/killswitch/{date}` (use `/api/over25/stage3/{date}`)
- `/api/filter/gg/daily/{date}` (use `/api/filter/gg/{date}`)
