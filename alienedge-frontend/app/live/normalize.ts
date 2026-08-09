import type { AxiosResponse } from "axios";
import type {
  LiveAggregatorReport,
  LiveDangerReport,
  LiveDashboardResult,
  LiveIncomingPick,
  LivePrematchPick,
} from "@/lib/api";

/**
 * Live engines sometimes return dict[fixture_id → picks] instead of arrays.
 * Normalize to the array shapes `lib/api.ts` documents so the UI never blanks.
 */

function asArray<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  return [];
}

export function normalizeIncoming(
  res: AxiosResponse<LiveIncomingPick[] | Record<string, unknown>>
): AxiosResponse<LiveIncomingPick[]> {
  const raw = res.data;
  if (Array.isArray(raw)) return { ...res, data: raw };

  const rows: LiveIncomingPick[] = Object.entries(raw ?? {}).map(
    ([fixture_id, value]) => {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        const obj = value as Record<string, unknown>;
        const picks = Array.isArray(obj.picks) ? obj.picks : [];
        return {
          fixture_id: String(obj.fixture_id ?? fixture_id),
          fixture: String(obj.fixture ?? fixture_id),
          picks: picks as LiveIncomingPick["picks"],
        };
      }
      return {
        fixture_id,
        fixture: fixture_id,
        picks: (Array.isArray(value) ? value : []) as LiveIncomingPick["picks"],
      };
    }
  );
  return { ...res, data: rows };
}

export function normalizePrematch(
  res: AxiosResponse<LivePrematchPick[] | Record<string, unknown>>
): AxiosResponse<LivePrematchPick[]> {
  const raw = res.data;
  if (Array.isArray(raw)) return { ...res, data: raw };

  const rows: LivePrematchPick[] = Object.entries(raw ?? {}).map(
    ([fixture_id, value]) => ({
      fixture_id,
      picks: (Array.isArray(value)
        ? value
        : Array.isArray((value as { picks?: unknown })?.picks)
          ? (value as { picks: LivePrematchPick["picks"] }).picks
          : []) as LivePrematchPick["picks"],
    })
  );
  return { ...res, data: rows };
}

export function normalizeDashboard(
  res: AxiosResponse<LiveDashboardResult[] | Record<string, unknown>>
): AxiosResponse<LiveDashboardResult[]> {
  return { ...res, data: asArray<LiveDashboardResult>(res.data) };
}

export function normalizeDanger(
  res: AxiosResponse<LiveDangerReport[] | Record<string, unknown>>
): AxiosResponse<LiveDangerReport[]> {
  return { ...res, data: asArray<LiveDangerReport>(res.data) };
}

export function normalizeAggregator(
  res: AxiosResponse<LiveAggregatorReport[] | Record<string, unknown>>
): AxiosResponse<LiveAggregatorReport[]> {
  const raw = res.data;
  if (raw && typeof raw === "object" && !Array.isArray(raw) && "error" in raw) {
    return { ...res, data: [] };
  }
  return { ...res, data: asArray<LiveAggregatorReport>(raw) };
}
