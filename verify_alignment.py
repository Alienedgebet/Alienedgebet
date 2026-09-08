"""
Run this from your project root AFTER main.py has produced today's output:

    python verify_alignment.py [YYYY-MM-DD]

It does two things:
1. Lists every file actually sitting in output/ and master_aggregator/,
   grouped by which market they look like they belong to (by keyword).
2. Grep's your Engine/AGGREGATOR/PSYCHOLOGY source for the literal string
   that gets passed to `.to_csv(...)` / `open(..., 'w')` / `json.dump`,
   so you can see the REAL filename each function writes without
   guessing from output/ alone (useful if output/ is empty on a fresh
   checkout, e.g. before the first pipeline run).

Nothing here touches your engine math — read-only.
"""
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(ROOT, "output")
MASTER_AGG_DIR = os.path.join(ROOT, "master_aggregator")

date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")

KEYWORDS = {
    "win": ["win"],
    "gg": ["gg", "btts"],
    "over25": ["over25", "o25"],
    "over15": ["over15", "o15"],
    "corners": ["corner"],
    "draw": ["draw"],
    "unders": ["under"],
    "sot": ["sot", "cerberus"],
    "fhvi": ["fhvi"],
    "shvi": ["shvi"],
    "sh_master": ["sh_gg", "sh_8goal", "hvi_vortex", "shvi_vortex"],
    "underdog": ["underdog", "ud_score", "apex_ud"],
}


def scan_dir(label, path):
    print(f"\n── {label} ({path}) ──")
    if not os.path.isdir(path):
        print("  (directory does not exist)")
        return
    files = sorted(os.listdir(path))
    if not files:
        print("  (empty — run main.py for a date first)")
        return
    for f in files:
        tag = next((k for k, kws in KEYWORDS.items() if any(kw in f.lower() for kw in kws)), "?")
        print(f"  [{tag:10s}] {f}")


def grep_engine_writers():
    print("\n── Literal output filenames referenced in engine source ──")
    write_pattern = re.compile(
        r"""(?:to_csv|open|json\.dump)\s*\(\s*[a-zA-Z_.]*\(?["']?([^"',)]+\.(?:csv|json))""",
        re.IGNORECASE,
    )
    scan_roots = ["Engine", "AGGREGATOR", "PSYCHOLOGY", "CORE", "FILTER"]
    for folder in scan_roots:
        folder_path = os.path.join(ROOT, folder)
        if not os.path.isdir(folder_path):
            continue
        for dirpath, _, filenames in os.walk(folder_path):
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                except Exception:
                    continue
                hits = write_pattern.findall(content)
                if hits:
                    rel = os.path.relpath(fpath, ROOT)
                    print(f"  {rel}:")
                    for h in set(hits):
                        print(f"    -> {h}")


if __name__ == "__main__":
    print(f"Alignment check for date={date_str}")
    scan_dir("output/", OUTPUT_DIR)
    scan_dir("master_aggregator/", MASTER_AGG_DIR)
    grep_engine_writers()
    print(
        "\nCompare the tagged filenames above against the `paths = [...]` "
        "lists in api/main.py for the matching route. Any name api/main.py "
        "checks that never appears here is a dead/incorrect candidate — "
        "swap it for the real one shown above."
    )
