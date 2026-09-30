"""
Over 1.5 Apex Aggregator — DELEGATING SHIM.

WHY THIS FILE EXISTS (and why it no longer contains an engine)
----------------------------------------------------------------
This module previously held a 506-line copy of the Over 1.5 rules engine.
It was byte-identical to PSYCHOLOGY/over15_psychology.py except for the
function name — `diff` returned exactly one differing line.

Both were registered in the pipeline (main.py L697 psychology, L698 apex)
and BOTH wrote to the same file:

    output/ALIENEDGE_O15_PREDICTIONS_{date}.csv     (line 504 in each)

Because apex ran second, it silently overwrote psychology's output on
every run. The frontend showed "Over 1.5 Intelligence" and "Over 1.5 Apex"
as two independent engines, but the second was displaying the first's work
with its own name on it. Every O1.5 API call was also paid twice.

WHAT THIS SHIM DOES
-------------------
It preserves the public name `run_o15_apex_engine` and the /api/over15/apex/
endpoint, but delegates to the single canonical implementation. One engine,
one set of API calls, one output file. The endpoint keeps working; the
duplicate identity does not.

If you ever want the two to diverge again, FORK DELIBERATELY: copy the
psychology engine, give it a distinct rule set, and give it its own
OUTPUT_CSV. Do not let that happen by accident.
"""

from PSYCHOLOGY.over15_psychology import run_o15_psychology_engine


def run_o15_apex_engine(target_date=None):
    """
    Delegates to the canonical Over 1.5 engine.

    Returns exactly what the psychology engine returns, so the persisted
    `over15_apex` cache entry and the /api/over15/apex/{date} response stay
    populated and the frontend needs no change.
    """
    print(
        "\n>> [O1.5 Apex] This is a shim: the real Over 1.5 engine now lives in\n"
        "   PSYCHOLOGY/over15_psychology.py. Delegating to it so there is ONE\n"
        "   engine, ONE set of API calls, and ONE output file."
    )
    return run_o15_psychology_engine(target_date)
