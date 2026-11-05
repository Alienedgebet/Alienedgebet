/**
 * AlienEdge API client — Intelligent Pass slice.
 *
 * Thin wrapper over the backend Intelligent Pass API (api/main.py).
 * Engine data is supplied separately; when no engine cache exists for the
 * requested date/market the backend returns checks with result "N/A".
 */
const BASE_URL = typeof window !== "undefined" ? "" : "";

export interface IntelligentPassCheck {
  name: string;
  result: "PASS" | "FAIL" | "N/A";
  value: number | string | null;
  threshold: number | string | null;
  source: string;
  field: string;
  mapping: string;
}

export interface IntelligentPassResult {
  team: string;
  date: string;
  market: string;
  fixture_id: string | null;
  label: string | null;
  checks: IntelligentPassCheck[];
  pass_count: number;
  total: number;
  source_date: string | null;
}

export async function getIntelligentPass(
  team: string,
  date: string,
  market: string,
  opts?: { fixture_id?: string | null; label?: string | null },
): Promise<IntelligentPassResult> {
  const params = new URLSearchParams({
    date,
    market,
  });
  if (opts?.fixture_id) params.set("fixture_id", opts.fixture_id);
  if (opts?.label) params.set("label", opts.label);

  const res = await fetch(
    `${BASE_URL}/api/intelligent-pass/${encodeURIComponent(team)}?${params}`,
    { headers: { Accept: "application/json" } },
  );
  if (!res.ok) {
    throw new Error(`Intelligent Pass API ${res.status} for ${team}/${market}`);
  }
  return (await res.json()) as IntelligentPassResult;
}

export async function getIntelligentPassMarkets(): Promise<string[]> {
  const res = await fetch(`${BASE_URL}/api/intelligent-pass/markets`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) return [];
  const data = (await res.json()) as { markets?: string[] };
  return data.markets ?? [];
}
