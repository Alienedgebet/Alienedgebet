"""
AlienEdge API — Intelligent Pass endpoint.

GET /api/intelligent-pass/{team}?date=&market=&fixture_id=&label=

Evaluates the Intelligent Pass checks for ONE team + fixture + market and
returns PASS/FAIL/N/A per check plus the INTELLIGENT PASS COUNT.

Engine data files live under data/intelligent_pass_cache/<engine>/<date>.json
and are supplied separately (Option 1). When absent, checks report N/A.
"""
import sys
import os
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from INTELLIGENT_PASS.pass_count import evaluate, evaluate_all

app = FastAPI(title="AlienEdge Intelligent Pass API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static routes FIRST so they are not swallowed by the /{team} path route.


@app.get("/api/intelligent-pass/markets")
def list_markets():
    """List supported market keys (no date/market required)."""
    return JSONResponse(content={"markets": sorted({
        "WIN", "GG", "O2.5", "O1.5", "CORNERS", "DRAW", "UNDERS", "U2S",
        "FHVI", "SHVI",
    })})


@app.get("/api/intelligent-pass/{team}")
def intelligent_pass(
    team: str,
    date: str = Query(..., description="YYYY-MM-DD"),
    market: str = Query(
        ..., description="WIN | GG | O2.5 | O1.5 | Corners | Draw | Unders | U2S | FHVI | SHVI"
    ),
    fixture_id: Optional[str] = Query(
        None, description="Fixture id (id-bearing engines)"
    ),
    label: Optional[str] = Query(
        None, description="Fixture label / team match (id-less engines)"
    ),
):
    result = evaluate(team, date, market, fixture_id=fixture_id, label=label)
    return JSONResponse(content=result)


@app.get("/api/intelligent-pass/{team}/all")
def intelligent_pass_all(
    team: str,
    date: str = Query(..., description="YYYY-MM-DD"),
    fixture_id: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
):
    """Evaluate every supported market for one team + fixture."""
    results = evaluate_all(team, date, fixture_id=fixture_id, label=label)
    return JSONResponse(content=results)


@app.get("/api/health")
def health():
    return {"status": "ok"}
