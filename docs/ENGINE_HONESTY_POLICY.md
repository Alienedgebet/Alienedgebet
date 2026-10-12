# AlienEdge Engine Honesty Policy

*Adopted 2026-10-12. The rule every engine — existing and future — is
measured against.*

## Why this exists

The platform's credibility rests on users being able to tell, at a glance,
what a number IS. The Win Forecast v2 engine (Engine/win_forecast_v2.py)
proved the standard works: an HONESTY LEDGER in the file, version stamps in
every output row, and an EXPERIMENTAL badge that travels with the data.
This document makes that standard binding for everything else.

## The five rules

1. **Never publish a number you cannot qualify.** Every engine output row
   carries `model_version` (and `calibration_version` where calibration
   exists). If a probability is uncalibrated, say so — in the file, in the
   data, in the UI.

2. **No silent fabrication.** Missing inputs are missing: THIN_SAMPLE,
   PENDING, empty board. An engine may never invent a plausible-looking
   value to fill a gap. (This is already the platform's settled rule for
   settlement — PENDING, never a fabricated verdict — and it extends to
   model outputs.)

3. **Experimental means labelled, end-to-end.** A new or unvalidated model
   runs alongside production, not on top of it: separate save keys, separate
   API routes, separate frontend stages with a visible EXPERIMENTAL badge,
   and never a dependency of a production chain.

4. **Document limitations where the code lives.** A HONESTY LEDGER (or
   equivalent block comment) at the top of every engine file states what is
   real, what is stubbed, what threshold is unvalidated, and what scope
   limit applies. Reviewers should learn the weaknesses without reading the
   maths.

5. **Validation before promotion.** An experimental engine earns removal of
   its badge only by: settled-fixture history → chronological
   train/calibrate/test splits → a real calibration (isotonic/Platt) →
   backtested thresholds → an ROI/edge audit vs market prices. Until all
   five exist, 'VALUE CONFIRMED' is a label, not a claim.

## Current standing

| Engine family | Calibration status | UI marking |
|---|---|---|
| Win Forecast v1 chain (forecast → psychology → apex) | Apex blend coefficients fitted on 1,097 settled rows (2026-10-02 fit, documented in AGGREGATOR/win_apex_aggregator.py) | Production |
| Win Forecast v2 | **None (identity)** — calibration_version `none-identity-v0` | EXPERIMENTAL badge, unvalidated thresholds |
| All other production engines | Deterministic rules/weights — no probabilistic calibration claimed | Production; per-row confidence/quality fields where they exist |

## Consequence

Anything added after this document is written follows the five rules from
day one. An engine that cannot honestly state what it is gets to ship as
experimental — or not ship.
