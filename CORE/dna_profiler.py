import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
V2_PATH  = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
V1_PATH  = os.path.join(DATA_DIR, "team_dna_profiles.json")

def run_dna_profiler(target_date):
    """Unified DNA v1 wrapper. Reads from disk. 0 API calls."""
    for path in [V2_PATH, V1_PATH]:
        if os.path.exists(path) and os.path.getsize(path) > 100:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"[⚡ DNA CACHE] Loaded {len(data)} profiles from disk. (0 API Calls)")
                return data
            except Exception:
                pass
    return {}

if __name__ == "__main__":
    run_dna_profiler("2026-09-06")
