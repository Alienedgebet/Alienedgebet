"""
SHADOW MODE — Stage 8 live prediction engine (proposed changes).

This module is deliberately incapable of changing a production prediction.

It imports the same `predict()` from `live_stage8_live_prediction.py` (which now
includes the proposed A1/A2/B2/C1/C2/D3 changes), runs it on the same live-board
inputs, and writes the result to a SEPARATE output file:

    data/stage8_live_prediction_shadow.json

It does NOT:
  * write to data/stage8_live_prediction.json (production output)
  * append to data/stage8_prediction_log.jsonl (production history)
  * make any SportMonks API calls
  * modify any production file or configuration

Use case: run the shadow engine side-by-side with the production engine each
cycle, then diff the two outputs to validate proposed changes before promoting.

Controlled by the STAGE8_SHADOW env var (set to "1" to enable). When disabled,
run_shadow_engine() returns immediately having changed nothing.
"""
import json
import os
import time

from .live_stage8_live_prediction import (
    predict, BOARD_FILE, DANGER_FILE, PREMATCH_FILE,
    DNA_PROFILES_FILE, STYLE_CLASHES_FILE, DATA_DIR,
)

SHADOW_FILE = os.path.join(DATA_DIR, "stage8_live_prediction_shadow.json")
ENABLED = os.environ.get("STAGE8_SHADOW", "0") == "1"


def _load(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _as_rows(val):
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return val.get("matches", [])
    return []


def run_shadow_engine():
    """
    Run the proposed engine on the live board and write to the shadow file.

    No production file is touched. Returns a summary dict.
    """
    if not ENABLED:
        return {"enabled": False, "note": "STAGE8_SHADOW != 1 — shadow disabled"}

    board_doc = _load(BOARD_FILE, {})
    rows = _as_rows(board_doc)
    danger_rows = _as_rows(_load(DANGER_FILE, []))
    pm_rows = _as_rows(_load(PREMATCH_FILE, []))
    dna_cache = _load(DNA_PROFILES_FILE, {})
    clash_cache = _as_rows(_load(STYLE_CLASHES_FILE, []))

    out = {}
    for m in rows:
        fid = m.get("id")
        if fid is None:
            continue
        try:
            rec = predict(
                fid,
                _board_cache=rows,
                _danger_cache=danger_rows,
                _prematch_cache=pm_rows,
                _dna_cache=dna_cache,
                _clash_cache=clash_cache,
            )
            out[str(fid)] = rec
        except Exception as exc:
            out[str(fid)] = {
                "fixture_id": str(fid),
                "status": "ERROR",
                "error": f"shadow prediction failed: {exc}",
                "predictions": None, "trace": [], "judges": None,
                "verdict": "BLOCK",
            }

    payload = {
        "generated_at": time.time(),
        "mode": "SHADOW — proposed Stage 8 engine, does not touch production",
        "engines": len(rows),
        "predictions": out,
    }
    tmp = SHADOW_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    os.replace(tmp, SHADOW_FILE)

    n_ok = sum(1 for v in out.values() if v.get("status") == "OK")
    return {
        "enabled": True,
        "fixtures_processed": len(rows),
        "ok": n_ok,
        "shadow_file": SHADOW_FILE,
    }


if __name__ == "__main__":
    print(json.dumps(run_shadow_engine(), indent=1))