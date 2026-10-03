import axios, {
  AxiosInstance,
  AxiosResponse,
  AxiosRequestConfig,
} from "axios";

// ============================================================
// ALIENEDGE API CLIENT
// Synced to api/main.py — backend is source of truth
// ============================================================

const BASE_URL = process.env.NODE_ENV === "production" ? "" : (process.env.NEXT_PUBLIC_API_URL || "");

// ── Endpoint-aware timeouts ───────────────────────────────────────────
// A single aggressive timeout made large-but-legitimate analytics payloads
// (Corners Stage 1 is ~345 KB) look like failures and swap into demo data.
// Normal endpoints keep a sensible default; the known heavy analytics
// chains get a longer budget. `/api/filter/*` is in the heavy set because a
// non-baseline Weekly request (tipster sliders, a non-default odds corridor or
// any drawer threshold) runs the real FILTER engine over every date in the
// requested range inside the request — same work class as the other chains.
// Any per-request override (config.timeout, including 0 = no timeout) always
// wins.
const DEFAULT_TIMEOUT_MS = 10_000; // normal endpoints
const HEAVY_TIMEOUT_MS = 45_000; // corners stage 1/2, GG, Win, Over 1.5 / Over 2.5 chains
const HEAVY_ENDPOINT_PATTERN = /^\/api\/(corners|gg|win|over15|over25|sot|fhvi|shvi|underdog|draw|unders|alerts|weekly|filter)\//;

const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: DEFAULT_TIMEOUT_MS,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  // axios merges the instance-level `timeout` (DEFAULT_TIMEOUT_MS) into
  // `config` BEFORE request interceptors run, so `config.timeout` is never
  // null here — the previous `== null` guard made the HEAVY_TIMEOUT_MS branch
  // dead code and capped every pick page at the normal timeout. Detect "no
  // explicit per-request override" by checking for the default value instead,
  // so heavy analytics chains (corners/gg/win/over15/over25) actually get
  // HEAVY_TIMEOUT_MS while an explicit override (incl. 0 = no timeout) still wins.
  if (
    config.url &&
    (config.timeout == null || config.timeout === DEFAULT_TIMEOUT_MS)
  ) {
    config.timeout = HEAVY_ENDPOINT_PATTERN.test(config.url)
      ? HEAVY_TIMEOUT_MS
      : DEFAULT_TIMEOUT_MS;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    console.error("[AlienEdge API] request failed", err?.message || "Network error");
    return Promise.reject(err);
  }
);

// ── Shared raw-response snapshot cache ────────────────────────────────
// The dashboard and each market page fetch the same flagship endpoints
// (e.g. /api/win/apex/{date}) through different components. So that
// "same market + same date" always renders from ONE underlying response
// (and cannot independently flip between real/demo), raw responses are
// snapshotted here per URL for a short TTL, and concurrent in-flight
// requests for the same URL are deduplicated. Components still keep their
// own shaped useApi caches; this layer only guarantees the underlying
// data snapshot is identical across them.
const RAW_CACHE_TTL_MS = 3 * 60 * 1000; // matches useApi's cache TTL
const rawCache = new Map<string, { data: unknown; ts: number }>();
const inflight = new Map<string, Promise<AxiosResponse<unknown>>>();
let rawCacheGeneration = 0;

/**
 * Force the next explicit refresh to bypass the shared raw-response snapshot.
 * The generation guard prevents an older in-flight request from repopulating
 * the cache after a refresh has already started.
 */
export function clearRawCache(): void {
  rawCache.clear();
  inflight.clear();
  rawCacheGeneration += 1;
}

export function cachedGet<T>(
  url: string,
  config?: AxiosRequestConfig
): Promise<AxiosResponse<T>> {
  const generation = rawCacheGeneration;
  const hit = rawCache.get(url);
  if (hit && Date.now() - hit.ts < RAW_CACHE_TTL_MS) {
    return Promise.resolve({
      data: hit.data as T,
      status: 200,
      statusText: "OK",
      headers: {},
      config: {},
    } as AxiosResponse<T>);
  }
  const pending = inflight.get(url);
  if (pending) return pending as Promise<AxiosResponse<T>>;

  const request = api
    .get<T>(url, config)
    .then((res) => {
      if (generation === rawCacheGeneration) {
        rawCache.set(url, { data: res.data, ts: Date.now() });
      }
      return res;
    })
    .finally(() => {
      if (generation === rawCacheGeneration) inflight.delete(url);
    });
  inflight.set(url, request as Promise<AxiosResponse<unknown>>);
  return request;
}

// ============================================================
// HEALTH
// ============================================================
export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

// ============================================================
// FOUNDATION CHAIN TYPES
// ============================================================
export interface DnaProfile {
  team_id: string;
  team_name: string;
  Archetype: string;
  Market_Power_Scores: {
    Corner_Power: number;
    Goal_Intent: number;
    BTTS_Friction: number;
    Win_Dominance: number;
  };
  Tactical_DNA: {
    Tempo: number;
    Line_Height: string;
    Risk_Appetite: string;
    Verticality: string;
  };
  Raw_Audit_Metrics: {
    Avg_Corners: number;
    Estimated_Crosses: number;
    Estimated_Blocks: number;
    Dangerous_Attacks: number;
    Passing_Control: number;
  };
}

// ============================================================
// DNA ENGINE V2 — fully separate universal DNA provider.
// Never merge with DnaProfile above; v1 and v2 are independent.
// ============================================================
export interface DnaV2Profile {
  team_name: string;
  Archetype: string;
  /**
   * A pillar is `number` when it was measured and `null` when it could not
   * be. `null` is NOT zero: zero means "measured, and it is terrible".
   * Schema v3 introduced this distinction because collapsing the two let a
   * team with no provider data look like a genuinely 0-strength side.
   */
  Market_Power_Scores: {
    Corner_Power: number;
    Goal_Intent: number;
    BTTS_Friction: number;
    Win_Dominance: number | null;
    /** Schema v4: nullable — the pillar is unknown when its inputs were never
     *  reported, rather than scored as 0. */
    Box_Dominance: number | null;
  };
  Tactical_DNA: {
    /** Schema v4: nullable — was a fabricated 0.0 for a team with no stats. */
    Tempo: number | null;
    Line_Height: string;
    Risk_Appetite: string;
    Verticality: string;
    Shot_Quality: string;
    Transition_Style: string;
    /** Schema v4: nullable — was a fabricated 0.0 for a team with no stats. */
    Transition_Score: number | null;
  };
  Raw_Audit_Metrics: {
    Avg_Corners: number | null;
    Estimated_Crosses: number;
    Estimated_Blocks: number;
    Dangerous_Attacks: number | null;
    Passing_Control: number | null;
    Big_Chances_Created: number | null;
    Shots_Insidebox: number | null;
    Shots_Outsidebox: number | null;
    Inside_Shot_Ratio_Pct: number;
    Tackles_Avg: number | null;
    Interceptions_Avg: number | null;
    Own_Pass_Quality_Pct: number | null;
    Opp_Pass_Acc_Allowed: number | null;
    Opp_Dangerous_Attacks: number | null;
    /** null when the opponent was never measured — never a perfect 100. */
    Resistance_Score: number | null;
  };
  /**
   * DISPLAY ONLY — per-match recent results rendered by the SportyBet-style
   * form strip. Fed by no pillar, archetype or clash. Optional because
   * profiles cached before this field existed simply don't have it, and the
   * UI must degrade to "—" rather than crash on an older snapshot.
   */
  form_rows?: DnaV2FormRow[];
  /**
   * How much of this profile is actually measured. The engine used to compute
   * per-stat match counts and throw them away, so a one-match average rendered
   * exactly like an eight-match one. Present from schema v3 onward.
   */
  Data_Coverage?: {
    Stats_Matches: number;
    Stats_Sample: number;
    Stats_Coverage_Pct: number;
    Form_Rows_Matches: number;
    Form_Rows_Sample: number;
  };
  /**
   * True when too few matches carried provider statistics for these pillars to
   * mean anything. The UI must NOT present such a team as merely weak.
   */
  insufficient_data?: boolean;
}

/** One recent result. `venue` is "home" | "away" from THIS team's perspective. */
export interface DnaV2FormRow {
  date: string | null;
  fixture_id: number | string | null;
  opponent: string | null;
  opponent_id: number | string | null;
  venue: "home" | "away" | null;
  result: "W" | "D" | "L";
  goals_for: number;
  goals_against: number;
}

export interface DnaV2PillarClash {
  /** null when that side's pillar could not be measured (schema v3+). */
  home_score: number | null;
  away_score: number | null;
  /** null when either side is unmeasured — there is no gap to report. */
  difference: number | null;
  /** "Unknown" means unmeasured, which is NOT the same as "Neutral". */
  edge: string;
  margin: "Clear" | "Tight" | "Unknown";
}

export interface DnaV2Clash {
  fixture: string;
  home_team: string;
  away_team: string;
  fixture_id: string;
  fixture_date: string;
  pillar_clash: {
    Corner_Power: DnaV2PillarClash;
    Goal_Intent: DnaV2PillarClash;
    BTTS_Friction: DnaV2PillarClash;
    Win_Dominance: DnaV2PillarClash;
    Box_Dominance: DnaV2PillarClash;
  };
  home_pillar_edges: number;
  away_pillar_edges: number;
  overall_structural_edge: string;
  /** Schema v4: null when either side's Box Dominance was unmeasured. */
  combined_box_dominance: number | null;
  combined_goal_intent: number;
  market_signals: {
    Over_Under: string;
    GG_NoGG: string;
    Corners: string;
  };
}

export type DnaV2MarketKey =
  | "win"
  | "gg"
  | "over25"
  | "over15"
  | "unders"
  | "draw"
  | "corners";

export interface DnaV2Factor {
  name: string;
  /** null when the underlying stat was never measured for that team. */
  home_value: number | null;
  away_value: number | null;
  /**
   * Four outcomes, and only two of them are wins:
   *   "unknown"   — one side's value was unmeasured. Never weighed.
   *   "undecided" — both sides measured, but the gap is smaller than the
   *                 measurement noise of the two averages. This is NOT a tie
   *                 between two equal numbers; it is "too close to call". It
   *                 awards no point and is excluded from the denominator.
   *   "neutral"   — the two values are exactly equal.
   *   "home"/"away" — the gap exceeds the noise floor. These are the only wins.
   */
  winner: "home" | "away" | "neutral" | "unknown" | "undecided";
  /** Size of the gap. null when unmeasured. */
  difference?: number | null;
  /** The 95% noise floor this factor had to clear. */
  min_margin?: number | null;
  /** Why the factor landed where it did. */
  reason?: "decided" | "within_noise" | "unmeasured";
}

export interface DnaV2MarketCount {
  home_count: number;
  away_count: number;
  /** Factors neither team could be measured on (schema v3+). */
  unknown_count?: number;
  /** Measured on both sides but inside the noise floor — no point awarded. */
  undecided_count?: number;
  /** Factors that produced a verdict for either side (home + away). */
  decided_count?: number;
  /** Factors actually weighed — total minus unknown. */
  comparable_count?: number;
  factors: DnaV2Factor[];
}

export interface DnaV2FixtureFactors {
  fixture_id: string;
  fixture: string;
  home_team: string;
  away_team: string;
  markets: Record<DnaV2MarketKey, DnaV2MarketCount>;
}

export interface DnaV2Response {
  dna_profiles: Record<string, DnaV2Profile>;
  fixture_clashes: DnaV2Clash[];
  market_factors: Record<string, DnaV2FixtureFactors>;
}

/**
 * Per-fixture metadata for the SportyBet-style match header, joined on the
 * backend from cache files the same pipeline run already wrote.
 *
 * Every field is nullable BY DESIGN: the backend returns null rather than
 * guessing, so the UI can render an honest em-dash. In particular
 * `home_position` / `away_position` are null for friendlies and cups, where
 * there is no league table at all — the engines store 99 as an UNRANKED
 * sentinel and the backend normalises it away, because showing "99" would
 * claim a team is 99th.
 */
export interface DnaV2MatchMeta {
  fixture_id: string;
  league_name: string | null;
  league_id: number | string | null;
  competition: string | null;
  classification: string | null;
  is_friendly: boolean | null;
  is_cup: boolean | null;
  season_name: string | null;
  stage_id: number | string | null;
  venue_id: number | string | null;
  home_team: string | null;
  away_team: string | null;
  home_position: number | null;
  away_position: number | null;
  /** True when the fixture has no league table (friendly/cup). */
  is_unranked: boolean;
}

export interface DnaV2MatchMetaResponse {
  date: string;
  fixtures: Record<string, DnaV2MatchMeta>;
}

/**
 * ONE real past meeting between the two teams of a fixture.
 *
 * Every field is non-null on purpose. The backend OMITS any meeting whose
 * scoreline or team names it could not read, rather than emitting a 0-0, so
 * a row that exists at all is a row where every number was measured.
 * A genuine 0-0 IS present — that is a real result, not a data gap.
 */
export interface DnaV2H2HMeeting {
  date: string | null;
  fixture_id: number | string | null;
  home: string;
  away: string;
  home_goals: number;
  away_goals: number;
  home_id: string;
  away_id: string;
}

/**
 * Why the H2H block has nothing to show.
 *
 * These are deliberately distinct. "These two have never met" and "we could
 * not ask the provider" are completely different facts, and collapsing them
 * into one empty panel is how a missing feed gets mistaken for a missing
 * rivalry.
 *
 *  - null                 — the lookup succeeded; `meetings` is authoritative
 *                          (possibly empty, which really means never met)
 *  - "no_data"            — no DNA data for this fixture/date
 *  - "unresolved_teams"   — a team name did not map to exactly one team id
 *  - "ambiguous_team_name"— two teams share a display name; refused, not guessed
 *  - "no_provider_key"    — server has no provider credentials configured
 *  - "rate_limited"       — provider throttled us; NOT a claim of no history
 *  - "provider_http_*"    — provider returned an unexpected status
 *  - "provider_unreachable" — network failure
 */
export type DnaV2H2HError =
  | "no_data"
  | "unresolved_teams"
  | "ambiguous_team_name"
  | "no_provider_key"
  | "rate_limited"
  | "provider_unreachable"
  | `provider_http_${number}`
  | null;

export interface DnaV2H2HResponse {
  date: string;
  fixture_id: string;
  home_team: string | null;
  away_team: string | null;
  home_id: string | null;
  away_id: string | null;
  meetings: DnaV2H2HMeeting[];
  error: DnaV2H2HError;
}

export interface UnderdogBasePick extends FixtureRisk {
  fixture_id: string;
  fixture: string;
  league: string;
  underdog_team: string;
  dog_odds: number;
  dog_score_prob: string;
  parity_gap: number;
  dog_att_strength: number;
  fav_def_weakness: number;
  dog_is_hot: boolean;
  dog_due_goal: boolean;
  both_no_draw_3: boolean;
  fav_vulnerability_5: string;
  fav_cs_streak: number;
  h2h_dog_gs_last_5: number;
  dog_venue_wins: number;
}

export interface UnderdogMasterPick extends FixtureRisk {
  fixture_id: string;
  fixture: string;
  underdog_team: string;
  Audit_Real_Prob: string;
  Dog_Score_Prob: string;
  Fav_Spear_Power: string;
  Dominance_Gap: number;
  Audit_Verdict: string;
  parity_gap: number;
  dog_is_hot: boolean;
  dog_due_goal: boolean;
  fav_cs_streak: number;
}

export interface UnderdogHandshake {
  fixture: string;
  underdog_team: string;
  parity_gap: number;
  Dominance_Gap: number;
  Audit_Real_Prob: string;
  Verdict: string;
}

export interface UnderdogApexPick extends FixtureRisk {
  fixture_id: string;
  Fixture: string;
  Rank: string;
  Monte_UD_Prob: string;
  Engine: string;
  Handshake: string;
  DNA: string;
  Rule: string;
  Fav_Vuln: string;
  SH_GG_Label: string;
}

// ============================================================
// GG CHAIN TYPES
// ============================================================
export interface GGPrecisionPick extends FixtureRisk {
  date?: string;
  fixture_id: string;
  fixture: string;
  home_team: string;
  away_team: string;
  league_id: string;
  lambda_home: number;
  lambda_away: number;
  combined_lambda?: number;
  mc_btts_prob: number;
  mc_over15_prob?: number;
  mc_draw_prob?: number;
  venue_btts_home?: number;
  venue_btts_away?: number;
  venue_btts_combined: number;
  h2h_btts_rate: number;
  home_gk_liable: boolean;
  away_gk_liable: boolean;
  // null when the keeper has no reliable sample (engine reports "no grade"
  // rather than scoring missing data as an elite wall)
  home_gk_cpg: number | null;
  away_gk_cpg: number | null;
  home_gk_note: string;
  away_gk_note: string;
  fatigue_home: number;
  fatigue_away: number;
  league_weight: number;
  draw_odds?: number | null;
  home_odds?: number | null;
  away_odds?: number | null;
  gg_score: number;
  gg_signals_fired: number;
  gg_tier: string;
  sig1_mc_btts: number;
  sig2_venue_btts: number;
  sig3_gk_vuln: number;
  sig4_h2h_btts: number;
  sig5_directional: number;
  composite_draw_score?: number;
  dmi?: number;
  parity?: number;
}

// The o15 branch of /api/gg/precision/{date} — same run, second head
// (Engine/gg_precision_engine.py::o15_row). mc_over15_prob is a 0-1 fraction
// (Monte Carlo rate), not a pre-multiplied percentage.
export interface GGO15Pick extends FixtureRisk {
  date?: string;
  fixture_id: string;
  fixture: string;
  home_team: string;
  away_team: string;
  league_id: string;
  o15_tier: string;
  o15_score: number;
  combined_lambda: number;
  mc_over15_prob: number;
  sig1_combined_lambda: number;
  sig2_mc_over15: number;
  sig3_venue_goals_avg: number;
  sig4_league_weight: number;
  sig5_fatigue_penalty: number;
  combined_venue_goals_avg: number;
  venue_goals_avg_home: number;
  venue_goals_avg_away: number;
  fatigue_home: number;
  fatigue_away: number;
  league_weight?: number;
  composite_draw_score?: number;
}

export interface GGPrecisionResponse {
  gg: GGPrecisionPick[];
  o15: GGO15Pick[];
}

export interface GGForensicPick extends FixtureRisk {
  fixture_id: string;
  league_id: string;
  Fixture: string;
  Score: string;
  DNA_Intelligence: string;
  "Poisson%": number;
  H2H_GG: string;
  DNA_Insight: string;
  Ranks: string;
  Forensic_Audit: string;
}

export interface GGPsychologyPick extends FixtureRisk {
  Fixture: string;
  MC_Rank: string;
  MC_Prob: string;
  Psych_Score: number;
  Spears: string;
  Tier: string;
  Psych_Triggers: string;
}

export interface GGSupremePick extends FixtureRisk {
  fixture_id: string;
  Fixture: string;
  Category: string;
  Cat_Priority: number;
  Monte_GG_Prob: number;
  NGG_Risk: number;
  Base_Marks: string;
  DNA_Status: string;
  Psych_Score: string | number;
  Psych_Triggers: string;
  VIP_Status: string;
  Veto_Status: string;
  Spears: string;
}

export interface GGCrossVerifyPick extends FixtureRisk {
  fixture_id: string;
  home_team: string;
  away_team: string;
  league_id: string;
  gg_prob_pct: number;
  tier: string;
  verification_days: number;
  table_distance: number;
  audit_timestamp?: string;
}

// ============================================================
// WIN CHAIN TYPES
// ============================================================
export interface WinForecastPick extends FixtureRisk {
  fixture_id: string;
  fixture: string;
  side: string;
  team_name: string;
  win_odds: number;
  poisson_win_prob: string;
  poisson_draw_prob: string;
  last_5_wins_overall: number;
  last_5_wins_at_venue: number;
  last_5_goals_scored: number;
  opp_last_5_goals_scored: number;
  opp_last_5_losses: number;
  opp_last_5_conceded_raw: number;
  opp_no_clean_sheet_count: number;
  h2h_wins_last_5: number;
  last_3_no_draw_BOTH: boolean;
  parity_score: number;
  parity_even_count: number;
}

export interface WinU2SPick extends FixtureRisk {
  Fixture: string;
  Underdog: string;
  Audit_Verdict: string;
  Spear_Matchup: string;
  Dog_Venue_SOT: number;
  Fav_Venue_SOT: number;
  Dog_H2H_SOT: number | string;
  Fav_H2H_SOT: number | string;
  Dog_Opp_Avg_Conceded: number | string;
  Fav_Opp_Avg_Conceded: number | string;
  Dog_Scoring_Consistency: string;
  Psych_Score: number | string;
  Tier: string;
  Triggers: string;
}

export interface WinPsychologyPick extends FixtureRisk {
  Fixture: string;
  Master_Pick: string;
  Master_Prob: string;
  Audit_Score: number;
  H_Base: number;
  A_Base: number;
  Tier: string;
  Spears: string;
  H_Quality: string;
  A_Quality: string;
  Home_Logic: string;
  Away_Logic: string;
}

export interface WinApexPick extends FixtureRisk {
  fixture_id: string;
  Fixture: string;
  Target: string;
  Category: string;
  Cat_Priority: number;
  Monte_Win_Prob: number;
  Monte_Draw_Prob: number;
  Lambda_Detail: string;
  Underdog_Risk: string;
  Psych_Score: string | number;
  Psych_Logic: string;
  Chokehold_Status: string;
  Veto_Reason: string;
}

export interface WinRawPick extends FixtureRisk {
  fixture_id: string;
  fixture: string;
  side: string;
  team_name: string;
  win_odds: number;
  /**
   * Present in the payload and used by the Smart-rank ordering, but missing
   * from this interface until now. Declared optional because roughly 2% of rows
   * carry no price at all; the ordering treats a missing value as unknown, not
   * as a short price.
   */
  poisson_win_prob?: string | number;
  last_5_wins_overall: number;
  last_5_wins_at_venue: number;
  last_5_goals_scored: number;
  opp_last_5_goals_scored: number;
  opp_last_5_losses: number;
  opp_last_5_conceded_raw: number;
  opp_no_clean_sheet_count: number;
  h2h_wins_last_5: number;
  last_3_no_draw_BOTH: boolean;
  parity_score: number;
  parity_even_count: number;
}

// ============================================================
// OVER 2.5 CHAIN TYPES
// ============================================================
export interface Over25Stage1Pick extends FixtureRisk {
  id: string;
  fixture: string;
  Time: string;
  Odds: number;
  Confidence: string;
  Algorithm: string;
}

export interface Over25Stage2Pick extends FixtureRisk {
  id: string;
  fixture: string;
  Time: string;
  Votes: number;
  Odds: number;
  Algorithm: string;
  Reasons: string;
}

export interface Over25Stage3Pick extends FixtureRisk {
  Match: string;
  Odds: number;
  "Poisson%": number;
  Grade: string;
  GradeNum: number;
  H2H_Record: string;
  PickedBy: string;
  Failures: string;
}

export interface Over25PsychologyPick extends FixtureRisk {
  Fixture: string;
  Base_Poisson: string;
  Base_Grade: string;
  Score: number;
  Tier: string;
  Reasons: string;
}

export interface Over25GoldPick extends FixtureRisk {
  fixture_id: string;
  league: string;
  kickoff_datetime: string;
  teams: {
    home: { id: string; name: string };
    away: { id: string; name: string };
  };
  flags: {
    both_teams_high_attack: boolean;
    h2h_o15_100_percent: boolean;
    both_2h_goal_100_percent: boolean;
    home_h2h_win_100: boolean;
    away_h2h_win_100: boolean;
    h2h_gg_100: boolean;
    h2h_o25_100: boolean;
  };
  metrics: {
    home_goals_last_5: number;
    away_goals_last_5: number;
    h2h_matches_analyzed: number;
  };
}

export interface Over25ApexPick extends FixtureRisk {
  fixture_id: string;
  Fixture: string;
  Category: string;
  Cat_Priority: number;
  Super_Monte_Prob: number;
  U25_Risk: number;
  Base_Grade: string;
  DNA_Status: string;
  Psych_Score: string | number;
  Psych_Triggers: string;
  VIP_Status: string;
  Veto_Status: string;
}

export interface Over25ForecastPick extends FixtureRisk {
  fixture_id: string;
  league: string;
  fixture: string;
  o25_odds: number;
  kill_switch_pass: boolean;
  poisson_over_prob_num: number;
  council_votes: string;
  pos_gap: number;
  parity_diff: number;
  h2h_overs_last_5: number;
  combined_gs_last_5: number;
}

// ============================================================
// OVER 1.5 CHAIN TYPES
// ============================================================
export interface Over15Stage3Pick extends FixtureRisk {
  Match: string;
  Odds: number;
  "Poisson%": number;
  Grade: string;
  GradeNum: number;
  H2H_Record: string;
  PickedBy: string;
  Failures: string;
}

export interface Over15PsychologyPick extends FixtureRisk {
  Fixture: string;
  Base_Poisson: string;
  Base_Grade: string;
  Score: number;
  Tier: string;
  Reasons: string;
}

/**
 * A frozen PRE-FIX Over 1.5 verdict.
 *
 * Identical row shape to Over15PsychologyPick on purpose — the two tables are
 * meant to be read side by side — plus the provenance of the snapshot so the
 * UI can say WHERE this came from rather than letting a stale verdict look
 * like a live one.
 */
export interface Over15LegacyPick extends Over15PsychologyPick {
  _legacy_note?: string;
  _legacy_generated_at?: string | null;
}

export interface Over15ApexPick extends FixtureRisk {
  Fixture: string;
  Base_Poisson: string;
  Base_Grade: string;
  Score: number;
  Tier: string;
  Reasons: string;
}

// ============================================================
// CORNER CHAIN TYPES
// ============================================================
export interface CornerStage1Pick extends FixtureRisk {
  fixture_id: string;
  fixture: string;
  expected_total_corners: number;
  corner_tier: string;
  expected_difference: number;
  team_more_corners: string;
  team_more_corners_probability_like: number;
  avg_confidence: number;
  home_win_odds: number;
  over_2_5_odds: number;
  tier_1_priority: boolean;
  verification?: {
    status: "SCHEDULED" | "LIVE" | "FINISHED";
    score?: string;
    minute?: number | string | null;
    verdict: "PENDING" | "IN_PLAY" | "WON" | "LOST";
    badge_text: string;
    note?: string;
    h_corners?: number;
    a_corners?: number;
    total_corners?: number;
  };
}

  /** One team flagged as corner-consistent, with the evidence behind the flag. */
export interface CornerConsistencyKing {
  fixture: string;
  /** 2 = both teams persistent, 1 = one side. */
  score: number;
  total: number;
  h_count: number;
  a_count: number;
  /** The ACTUAL last-N corner list, so the claim is checkable. */
  h_list: number[];
  a_list: number[];
}

/** A fixture that qualified on consistency alone (tier/confidence would not). */
export interface CornerConsistencyOnly {
  fixture: string;
  tier: string;
  avg_confidence: number;
  home_persistent: boolean;
  away_persistent: boolean;
  home_over4: number;
  away_over4: number;
  home_lastN: number[];
  away_lastN: number[];
}

/** GET /api/corners/consistency */
export interface CornerConsistencyReport {
  available: boolean;
  date: string | null;
  generated_at: string | null;
  /** Plain-English statement of what "persistent" means. */
  rule: string | null;
  count: number;
  kings: CornerConsistencyKing[];
  qualified_via_consistency_only: CornerConsistencyOnly[];
  reason?: string;
}

export interface CornerStage2Pick extends FixtureRisk {
  fixture_id: string;
  fixture_name: string;
  stage1_predicted_corners: number;
  stage2_predicted_corners: number;
  predicted_corners: number;
  corner_tier: string;
  style_alignment: string;
  diff: number;
  avg_confidence: number;
  home_is_persistent_venue: boolean;
  away_is_persistent_venue: boolean;
  home_is_persistent_overall: boolean;
  away_is_persistent_overall: boolean;
  /**
   * Corner consistency, added 2026-09-28. The miner always computed this
   * ("more than 4 corners in at least 4 of the last 5") and then filtered it
   * out of existence, so it was never visible on this screen even though the
   * engine was printing it to the log every run.
   */
  home_is_persistent_over_4?: boolean;
  away_is_persistent_over_4?: boolean;
  home_over_4_corners_count?: number;
  away_over_4_corners_count?: number;
  verification?: {
    status: "SCHEDULED" | "LIVE" | "FINISHED";
    score?: string;
    minute?: number | string | null;
    verdict: "PENDING" | "IN_PLAY" | "WON" | "LOST";
    badge_text: string;
    note?: string;
    h_corners?: number;
    a_corners?: number;
    total_corners?: number;
  };
}

export interface CornerPsychologyPick extends FixtureRisk {
  fixture_name: string;
  home_position: number;
  away_position: number;
  friction_grade: string;
  standings_gap: number;
  tactical_intelligence_grade: string;
  tactical_note: string;
  is_wounded_beast: boolean;
  wounded_reason: string;
  wounded_team_name: string;
  verification?: {
    status: "SCHEDULED" | "LIVE" | "FINISHED";
    score?: string;
    minute?: number | string | null;
    verdict: "PENDING" | "IN_PLAY" | "WON" | "LOST";
    badge_text: string;
    note?: string;
    h_corners?: number;
    a_corners?: number;
    total_corners?: number;
  };
}

export interface CornerCatalystPick extends FixtureRisk {
  fixture_name: string;
  predicted_corners: number;
  corner_tier: string;
  home_position: number;
  away_position: number;
  friction_grade: string;
  home_is_wounded_beast: boolean;
  home_wounded_intensity: string;
  away_is_wounded_beast: boolean;
  away_wounded_intensity: string;
  verification?: {
    status: "SCHEDULED" | "LIVE" | "FINISHED";
    score?: string;
    minute?: number | string | null;
    verdict: "PENDING" | "IN_PLAY" | "WON" | "LOST";
    badge_text: string;
    note?: string;
    h_corners?: number;
    a_corners?: number;
    total_corners?: number;
  };
}

export interface CornerAggregatorPick extends FixtureRisk {
  /**
   * Corner-consistency badge per side, emitted by the aggregator as an icon:
   * 👑 consistent at this venue, ⭐ consistent overall, ❌ no consistency.
   *
   * Present in the payload since long before this column existed — the
   * aggregator has been writing H_King/A_King on every run while the corners
   * page never referenced them, so a home team with a 👑 was invisible.
   *
   * Icon only, by decision: the 4/5 count is available on the stage-2 table,
   * and the aggregator CSV does not carry it.
   */
  H_King?: string;
  A_King?: string;
  Fixture: string;
  Master_Score: number;
  Chaos_Rating: number;
  Tier: string;
  True_Corner_Fav: string;
  Match_Flow: string;
  "U2.5%": string;
  UD_Prob: string;
  NB_Prob: string;
  Total_Exp: number;
  Home_Pos: number;
  Away_Pos: number;
  Friction: string;
  Home_Wounded: string;
  Home_Wound_Int: string;
  Away_Wounded: string;
  Away_Wound_Int: string;
  Home_Team: string;
  Away_Team: string;
  Home_Score: number;
  Away_Score: number;
  Home_Label: string;
  Away_Label: string;
  Home_DNA: string;
  Away_DNA: string;
  Home_SH_Ratio: number;
  Away_SH_Ratio: number;
  verification?: {
    status: "SCHEDULED" | "LIVE" | "FINISHED";
    score?: string;
    minute?: number | string | null;
    verdict: "PENDING" | "IN_PLAY" | "WON" | "LOST";
    badge_text: string;
    note?: string;
    h_corners?: number;
    a_corners?: number;
    total_corners?: number;
  };
}

// ============================================================
// SPECIALS TYPES
// ============================================================
export interface DrawPick extends FixtureRisk {
  fixture_id: string;
  fixture: string;
  home_team: string;
  away_team: string;
  tier: string;
  section: string;
  // These four are null when the fixture had too little usable history for the
  // engine to estimate a probability at all (Engine/draw_engine.py
  // MIN_HISTORY_SAMPLE). The API preserves that null on purpose — see
  // NULLABLE_FIELDS in api/main.py — so renderers must handle it. Note that
  // `null * 100` is 0 in JS, so these must be null-checked, never multiplied
  // blindly, or "no data" displays as a confident 0.0%.
  composite_draw_score: number | null;
  mc_draw_prob: number | null;
  poisson_draw_prob: number | null;
  dmi: number;
  parity: number;
  draw_odds: number;
  value_edge: number | null;
  mc_spread: number;
  mc_stability: string;
  most_likely_draw_score: string;
  most_likely_draw_pct: number;
  home_draws: number;
  away_draws: number;
  h2h_draws: number;
  total_draws: number;
  fatigue_score: number;
  home_position: number;
  away_position: number;
}

// parity_list and amateurs_list are just filtered subsets of the same ranked
// DataFrame as `draws` (Engine/draw_engine.py::run_draw_engine) — parity >= 0.9
// and total_draws > 5 respectively — so they share the DrawPick shape exactly.
export interface DrawResponse {
  draws: DrawPick[];
  parity_list: DrawPick[];
  amateurs_list: DrawPick[];
}

export interface UndersPick extends FixtureRisk {
  fixture_id: string;
  fixture: string;
  home_team: string;
  away_team: string;
  combined_lambda: number;
  mc_u25_prob?: number;
  mc_u35_prob?: number;
  u25_score?: number;
  u25_tier?: string;
  u25_signals_fired?: number;
  u35_score?: number;
  u35_tier?: string;
  // null when the keeper has no reliable sample (engine reports "no grade"
  // rather than scoring missing data as an elite wall)
  home_gk_cpg: number | null;
  away_gk_cpg: number | null;
  home_gk_note: string;
  away_gk_note: string;
  fatigue_home: number;
  fatigue_away: number;
  // Hard tier gates: a fixture must clear all three to earn any tier.
  gates_passed?: boolean;
  gate_reasons?: string;
  gate_home_scored?: number;
  gate_away_scored?: number;
  gate_home_conceded?: number;
  gate_away_conceded?: number;
  gate_h2h?: string;
}

export interface UndersResponse {
  u25: UndersPick[];
  u35: UndersPick[];
}

export interface SOTPick extends FixtureRisk {
  Fixture: string;
  Verdict: string;
  Proj_SOT: number;
  "Poisson_Over_8.5": string;
  Consistency: string;
  Game_Script: string;
  Momentum: string;
  "1x2_Home_Odd": number | string;
}

export interface FHVIPick extends FixtureRisk {
  fixture: string;
  ht_score: string;
  ft_score: string;
  fhvi_score: number;
  fhvi_label: string;
  fh_pressure: number;
  country: string;
  comb_fh_r: number;
  avg_sh_goals: number;
  h_fh_r_disp: number;
  a_fh_r_disp: number;
  h_fh_c_r_disp: number;
  a_fh_c_r_disp: number;
  Category: string;
}

export interface SHVIPick extends FixtureRisk {
  fixture: string;
  ht_score: string;
  ft_score: string;
  shvi_score: number;
  shvi_label: string;
  sh_pressure: number;
  country: string;
  comb_sh_r: number;
  avg_fh_goals: number;
  h_sh_r_disp: number;
  a_sh_r_disp: number;
  h_sh_c_r_disp: number;
  a_sh_c_r_disp: number;
  Category: string;
}

// ============================================================
// SH MASTER CHAIN TYPES
// ============================================================
export interface SHGGWinnerPick {
  fixture_id: string;
  league: string;
  kickoff_datetime: string;
  teams: {
    home: { id: string; name: string };
    away: { id: string; name: string };
  };
  pick_labels: string[];
  flags: {
    both_2h_goal_100_percent: boolean;
    home_h2h_win_100: boolean;
    away_h2h_win_100: boolean;
    h2h_gg_100: boolean;
    h2h_o25_100: boolean;
  };
  metrics: {
    home_2h_rate: number;
    away_2h_rate: number;
    h2h_matches_analyzed: number;
  };
}

export interface SHMasterPick extends FixtureRisk {
  fixture: string;
  league: string;
  shvi_score: number;
  sh_pressure: number;
  ht: string;
  ft: string;
  sh_scoring_rate: string;
  avg_fh_goals: number;
  late_threat: string;
}

export interface SH8GoalPick extends FixtureRisk {
  Fixture_ID: string;
  League: string;
  Time: string;
  Fixture: string;
  H_Goals_L5: number;
  A_Goals_L5: number;
  Labels: string;
  Status: string;
}

// ============================================================
// LIVE TYPES (api/main.py live endpoints)
// Stage 1 rich audit → Stage 2 validates that feed in-play.
// Stage 6 orchestrator = VIP DB + free LIVE scanner (/alerts).
// ============================================================

export interface LivePrematchPlayerRow {
  name: string;
  pos: string;
  apps: number;
  mins: number;
  rating: number;
  status: string;
}

export interface LivePrematchTeamAudit {
  team_id: string;
  team_name: string;
  loc: string;
  miss: number;
  kmv: number;
  rv: number;
  gk_out: boolean;
  gk_status: string;
  def_miss: number;
  mid_miss: number;
  att_miss: number;
  l_wing_miss: boolean;
  r_wing_miss: boolean;
  players: LivePrematchPlayerRow[];
}

/** Stage 1 strategic audit fixture — mirrors console print board. */
export interface LivePrematchAudit {
  fixture_id: string;
  fixture: string;
  kickoff_utc: string;
  status_text: string;
  odds_home_win: number | null;
  odds_away_win: number | null;
  odds_o25: number | null;
  /**
   * Seconds since the scanner last rewrote this board (2026-09-29).
   *
   * The page polled every 20s while the scanner wrote every ~72s, so most
   * polls returned identical bytes. The age lets the UI state the real
   * freshness instead of implying a live refresh it never had.
   */
  data_age_seconds?: number | null;
  /**
   * Optional live-odds mirror of the three pre-match markets above. No live
   * odds feed is produced by the engines today, so these are normally
   * undefined and the UI shows an explicit "not available" state. They are
   * declared so a future live feed renders without a frontend change.
   */
  live_odds_home_win?: number | null;
  live_odds_away_win?: number | null;
  live_odds_o25?: number | null;
  live_odds_updated_at?: string | null;
  home: LivePrematchTeamAudit;
  away: LivePrematchTeamAudit;
  picks: Array<string | { type: string; target_loc?: string }>;
  killer_rules: string[];
  combined_miss: number;
  /**
   * Explicit lifecycle flags written by Stage 1 via the shared state classifier
   * (live_state_classifier.py). Present so the UI never has to re-derive a
   * fixture's status from `status_text` — which is what previously let a
   * finished match stay on the Code 1 board, because `isFinished` only tinted a
   * badge while every row was still rendered.
   */
  state?: "LIVE" | "FINISHED" | "NOT_STARTED" | string;
  is_live?: boolean;
  is_finished?: boolean;
  is_upcoming?: boolean;
  has_lineup?: boolean;
  has_formation?: boolean;
  /** {team_id: formation} for both sides, present when has_formation is true. */
  formations?: Record<string, string>;
  admit_reason?: string;
}

/** @deprecated thin feed shape — prefer LivePrematchAudit */
export interface LivePrematchPick {
  fixture_id: string;
  picks: Array<{
    type: string;
    target_loc?: string;
    target_name?: string;
    reason?: string;
  }>;
}

/** Stage 2 VALIDATED_ALERTS row — validates stage 1 prematch picks live. */
export interface LiveValidationPick {
  fixture_id: string;
  match_name: string;
  prediction_type: string;
  target: string;
  forensic_note: string;
  stats_note: string;
  minute_triggered: number;
  scores: string;
  timestamp: string;
}

/** Code 2 validator verdict for one dimension of the gate. */
export type LiveValidationState =
  | "SUPPORTED"
  | "CONTRADICTED"
  | "NEUTRAL"
  | "INSUFFICIENT_DATA"
  | "SETTLED";

/** Where a prediction currently sits in its live lifecycle. */
export type LivePredictionStage =
  | "MONITORING"
  | "SUPPORTED"
  | "UNLIKELY"
  | "VOID"
  | "TRIGGERED"
  | "SETTLED";

/**
 * The 45' locked verdict written by Code 2. "REJECTED" is intentionally absent:
 * a 45' reading is a probability, not a refutation. VOID is the arithmetic case
 * (3+ goals already scored) and is separate from UNLIKELY, which still allows
 * the pick to come in.
 */
export type LivePredictionVerdict =
  | "LIKELY"
  | "UNLIKELY"
  | "VOID"
  | "UNCLEAR"
  // The 30' checkpoint is an OBSERVATION, not a verdict.
  | "SUPPORTING"
  | "AGAINST"
  | "FINAL_APPROVED"
  | "FINAL_REJECTED"
  | "PRE_APPROVED"
  | "PRE_REJECTED"
  | "APPROVED_WATCH"
  | "TRIGGERED"
  | "WON"
  | "LOST";

/** One canonical prediction tracked through its live lifecycle by Code 2. */
export interface LiveValidationPrediction {
  key: string;
  label: string;
  type: string;
  target: string;
  status:
    | "WAITING"
    | "QUEUED"
    | "MONITORING"
    | "TRIGGERED"
    | "STRIKE_WINDOW"
    | "SETTLED";
  stage?: LivePredictionStage;
  stage_note?: string;
  /** The locked 45' verdict: LIKELY / UNLIKELY / VOID / UNCLEAR. */
  verdict?: LivePredictionVerdict;
  verdict_note?: string;
  /** The 60' FINAL validation. Supersedes verdict for non-45'-locked markets. */
  verdict_60?: LivePredictionVerdict;
  verdict_30?: LivePredictionVerdict;
  verdict_45?: LivePredictionVerdict;
  /** The minute the authoritative verdict was actually recorded (60' if the
   *  final validation exists, otherwise 45', otherwise 30'). */
  verdict_minute?: number;
  /** The 30' -> 45' comparison: how the match moved between checkpoints. */
  comparison_30_45?: "STRENGTHENED" | "HELD" | "WEAKENED" | "COLLAPSED" | "NO_BASELINE";
  comparison_note?: string;
  /** The 45'/60' window was missed and the verdict was recorded late. */
  late_45?: boolean;
  late_60?: boolean;
  /** Recorded after the window closed — flagged, never a live read. */
  backfilled?: boolean;
  /** Past 60' with a final validation: this market may only TRIGGER now. */
  trigger_only?: boolean;
  signal?: LiveValidationState;
  forensic?: LiveValidationState;
  statistics?: LiveValidationState;
  stats_label?: string;
  /** The three judges' individual readings and reasoning, verbatim from the
   *  statistical judge. Present so the UI can show WHICH judge dissented and
   *  why instead of an opaque "STATS_1/3" tally. */
  engine_detail?: string;
  /** Forensic dimension: "MAINTAINED (No structural fracture — not evidence)". */
  forensic_note?: string;
  /** Suppressed: a contradictory market on an UNDER fixture, or an orphan kept
   *  alive after its feed row vanished. Visible with a reason, never alertable. */
  suppressed?: boolean;
  suppressed_reason?: string | null;
  /** Its feed row disappeared; carried forward so it can still settle. */
  orphaned?: boolean;
  triggered?: boolean;
  minute?: number;
  trigger_minute?: number | null;
  score_at_trigger?: string | null;
  final_score?: string | null;
  settlement?: string | null;
}

export interface LiveValidationSideStats {
  possession: number;
  shots_on_target: number;
  dangerous_attacks: number;
  corners: number;
  /**
   * Shots from INSIDE the penalty box. This replaces the old `box_entries`
   * row: the in-play feed carries no box-touch statistic at all (verified
   * across 22 live team rows — the key is simply absent), so the previous row
   * could only ever render "no data". These are NOT the same metric and are
   * not presented as one; box entries exist only in the pre-match squad data.
   */
  shots_inside_box: number;
  /** Total attacks made. */
  attacks: number;
}

/** Stage 2 VALIDATION BOARD match — mirrors print_cycle_board cycle_log entry. */
export interface LiveValidationMatch {
  name: string;
  minute: number;
  id: string;
  score: string;
  lines: string[];
  status?: "SCHEDULED" | "LIVE" | "FINISHED";
  is_finished?: boolean;
  retained_finished?: boolean;
  /** Structured contract (Code 2). The fields below are all optional so a
   *  board written before the contract change still renders. */
  fixture_id?: string;
  score_parts?: { home: number; away: number; display: string };
  period?: string;
  updated_at?: string;
  statistics?: { home: LiveValidationSideStats; away: LiveValidationSideStats };
  predictions?: LiveValidationPrediction[];
  /**
   * PHASE 2 — a live-only read for a match Code 1 did NOT pick. It is an
   * OBSERVATION from the live statistics, never a bet, and it never carries a
   * verdict. Deliberately a separate field so it can never be rendered as if
   * it were a validated Code 1 prediction.
   */
  live_read?: LiveOnlyRead;
}

/** The live-only read's own vocabulary. Never LIKELY/UNLIKELY. */
export type LiveReadState = "ON_TRACK" | "AT_RISK" | "DEAD" | "UNCLEAR";

export interface LiveOnlyRead {
  key: string;
  label: string;
  type: string;
  target: string;
  status: "READ";
  stage: "READ";
  stage_note: string;
  read: LiveReadState;
  read_label: string;
  /** Always false — this is what separates a read from a Code 1 pick. */
  prematch_pick: false;
  signal?: LiveValidationState;
  /** Always null — a read never produces a verdict. */
  verdict?: null;
  stats_label?: string;
  minute?: number;
  triggered?: boolean;
}

/** Stage 2 full board: tracks stage 1 picks through triple-phase audit. */
export interface LiveValidationBoard {
  cycle: number;
  total_live: number;
  total_tracked: number;
  retained_finished?: number;
  errors?: Array<{ fixture_id: string; error: string; timestamp?: string }>;
  matches: LiveValidationMatch[];
  alerts: LiveValidationPick[];
}

export interface LiveIncomingPick {
  fixture_id: string;
  fixture: string;
  picks: Array<{
    type: string;
    target_loc?: string;
    target_name?: string;
    reason: string;
  }>;
  live?: {
    score: string;
    minute: number;
    state: string;
    is_finished: boolean;
  };
}

/** One side of a fixture, as the Live Match page reports it (Code 1). */
export interface LiveIncomingTeamView {
  gk_ok: boolean;
  /** e.g. "Solid Form (0.8 per 90)" — the Edge's own wording. */
  gk_status: string;
  /** Count of absent key players, and the Edge's risk band for it. */
  miss: number;
  risk: "FULL STRENGTH" | "CLEAR" | "ELEVATED" | "HEAVY" | string;
  /** Key Missing Vulnerability, as a percentage. */
  kmv: number | null;
  /** Replacement Vulnerability, as a percentage. */
  rv: number | null;
  missing_names: string[];
  players: LivePrematchPlayerRow[];
  raw?: LivePrematchTeamAudit;
}

/** Code 4's signed opinion about one side. Secondary, never authoritative. */
export interface LiveIncomingSignedRead {
  signed_verdict?: "DANGER" | "ROTATION" | "BLESSING" | "UNKNOWN";
  signed_reason?: string;
  /** Positive = quality lost, negative = the XI was upgraded. */
  net_impact?: number | null;
  /** 0-1. Below 0.45 the evidence is too thin to call. */
  impact_confidence?: number | null;
  rotation_uplift?: number;
  gk_note?: string;
}

/**
 * One fixture's full incoming-prediction drill-down, from
 * GET /api/live/incoming/{fixtureId}. A pure join across the four local
 * artifacts, so the page can show the entire chain behind a pick without the
 * engines making another provider call.
 */
export interface LiveIncomingDetail {
  fixture_id: string;
  fixture: string;
  live?: {
    score: string;
    minute: number;
    state: string;
    is_finished: boolean;
  };
  picks: LiveIncomingPick["picks"];

  /**
   * One side, as the Live Match (Edge) page reports it.
   *
   * Code 1 is the single source of truth here (2026-09-28). The endpoint
   * previously served Code 1's player table beside Code 4's own "absent" list,
   * and the two disagreed about who was missing — the Edge said Ignasi Miquel
   * was out while the danger card named a different goalkeeper entirely, so
   * one screen read "GK OK" and the other "GK UNKNOWN" for the same match.
   */
  teams: Partial<Record<"home" | "away", LiveIncomingTeamView>>;
  table_available: boolean;

  /**
   * Code 4's signed read, kept strictly as a SECONDARY opinion. It may add
   * insight; it may never contradict the table it sits under.
   */
  danger: Partial<Record<"home" | "away", LiveIncomingSignedRead>>;
  danger_available: boolean;

  /** Code 5's market grades, post-coherence. */
  chemistry: Record<string, string>;
  chemistry_available: boolean;

  /** Code 3 vs Code 5 reconciliation. */
  handshake?: {
    status: "CONFLICT" | "CORROBORATED" | "NO_OVERLAP";
    agreements: number;
    conflicts: number;
    summary: string;
    detail: Array<{
      type: string;
      target_name?: string;
      target_loc?: string;
      reason?: string;
      market: string;
      market_grade: string;
      verdict: "AGREES" | "CONFLICTS" | "NEUTRAL";
    }>;
    coherence_notes: string[];
  } | null;

  /**
   * Which inputs actually landed. Drives an explicit "not available" state
   * rather than a blank panel, so the user can tell missing evidence from a
   * missing page.
   */
  availability: {
    picks: boolean;
    table: boolean;
    danger: boolean;
    chemistry: boolean;
  };
  partial: boolean;
}

export interface LiveDangerReport {
  fixture: string;
  fixture_id: string;
  home_team: {
    team_name: string;
    id: number;
    breach: boolean | null;
    danger_level: string;
    data_available?: boolean;
    vulnerability_pct: number | null;
    gk_leak: number | null;
    gk_leak_available?: boolean;
    missing_details: Array<{
      name: string;
      pos: string;
      /** Present since 2026-09-28 — the quality evidence behind the absence. */
      rating?: number | null;
      apps?: number | null;
      mins?: number | null;
      worth?: number | null;
    }>;
    formation: string;
    style: { label: string; score: number | null; da: number | null; available?: boolean };

    // ── SIGNED IMPACT (2026-09-28) ──────────────────────────────────────
    // The verdict now carries the SIGN of a rotation rather than a count of
    // absences. `vulnerability_pct` above is retained for compatibility but
    // no longer decides the badge — `net_impact` does.
    verdict?: "DANGER" | "ROTATION" | "BLESSING" | "UNKNOWN";
    verdict_reason?: string;
    net_impact?: number;
    impact_confidence?: number;
    regime?: "STRONG_FAVOURITE" | "MID_FIELD" | "BIG_DOG";
    quality_lost?: number;
    replacement_credit?: number;
    rotation_uplift?: number;
    gk_verdict?: string;
    gk_note?: string;
  };
  away_team: {
    team_name: string;
    id: number;
    breach: boolean | null;
    danger_level: string;
    data_available?: boolean;
    vulnerability_pct: number | null;
    gk_leak: number | null;
    gk_leak_available?: boolean;
    missing_details: Array<{
      name: string;
      pos: string;
      /** Present since 2026-09-28 — the quality evidence behind the absence. */
      rating?: number | null;
      apps?: number | null;
      mins?: number | null;
      worth?: number | null;
    }>;
    formation: string;
    style: { label: string; score: number | null; da: number | null; available?: boolean };

    // ── SIGNED IMPACT (2026-09-28) ──────────────────────────────────────
    // The verdict now carries the SIGN of a rotation rather than a count of
    // absences. `vulnerability_pct` above is retained for compatibility but
    // no longer decides the badge — `net_impact` does.
    verdict?: "DANGER" | "ROTATION" | "BLESSING" | "UNKNOWN";
    verdict_reason?: string;
    net_impact?: number;
    impact_confidence?: number;
    regime?: "STRONG_FAVOURITE" | "MID_FIELD" | "BIG_DOG";
    quality_lost?: number;
    replacement_credit?: number;
    rotation_uplift?: number;
    gk_verdict?: string;
    gk_note?: string;
  };
  style_alignment: string;
  match_chemistry_list: {
    Gg: string;
    Corner: string;
    "Home Win": string;
    "Away Win": string;
    "Over2.5": string;
    "Under3.5": string;
    "Over1.5": string;
  };
  live?: {
    score: string;
    minute: number;
    state: string;
    is_finished: boolean;
  };
}

export interface LiveAggregatorReport {
  fixture: string;
  fixture_id: string;
  incoming_probabilities: Record<string, unknown>[];
  danger_report: {
    home: { id?: number | string; team_name?: string; status: string; data_available?: boolean; sync: string; breach: boolean | null };
    away: { id?: number | string; team_name?: string; status: string; data_available?: boolean; sync: string; breach: boolean | null };
  };
  match_chemistry_list: Record<string, string>;
  live?: {
    score: string;
    minute: number;
    state: string;
    is_finished: boolean;
  };
}

export interface LiveDashboardResult {
  fixture: string;
  fixture_id: string;
  Win?: {
    base: number;
    adj: number;
    pick: string;
    light: string;
    reason: string;
  };
  GG?: {
    base: number;
    adj: number;
    light: string;
    reason: string;
  };
  O25?: {
    base: number;
    adj: number;
    light: string;
    reason: string;
  };
  Corner?: {
    base: number;
    adj: number;
    light: string;
    reason: string;
  };
  SH_GG?: {
    base: number;
    adj: number;
    light: string;
    reason: string;
  };
}

/** Stage 6 nested intel — Brain.analyze_match_state() shape. */
export interface LiveStage6Intel {
  home?: {
    live_xg?: number;
    sot?: number;
    da?: number;
    corn?: number;
  };
  away?: {
    live_xg?: number;
    sot?: number;
    da?: number;
    corn?: number;
  };
  match?: {
    confidence_score?: number;
    chaos_index?: number;
    h_pressure_share?: number;
    a_pressure_share?: number;
  };
}

/** Stage 6 StructuralDetective.investigate() fields. */
export interface LiveStage6Forensics {
  status?: string;
  h_doom?: number;
  a_doom?: number;
  h_red?: boolean;
  a_red?: boolean;
  h_gk?: boolean;
  a_gk?: boolean;
  h_triple?: boolean;
  a_triple?: boolean;
}

/** Stage 6 live key-player-lost tracker (real, in-play, distinct from Stage 1's prematch missing count). */
export interface LiveKeyLoss {
  h_lost: number;
  a_lost: number;
}

/** Stage 6 fire_alert record — VIP + free LIVE orchestrator. */
export interface LiveAlertPick {
  f_id: string;
  fixture: string;
  time: string;
  minute: number;
  level: string;
  confidence: number;
  msg: string;
  session: string;
  /** Present only on alerts fired by a user's own saved rule; null/absent = system alert. */
  user_id?: string | null;
  rule_id?: string | null;
  rule_label?: string | null;
  /** Which storm gate fired: developing (30-45') | sustained (45-60') | peaking (60-75'). */
  storm_stage?: "developing" | "sustained" | "peaking" | null;
  /** Scoreline at the exact instant the alert fired. null = not captured. */
  score_at_trigger?: string | null;
  score_home_trigger?: number | null;
  score_away_trigger?: number | null;
  /** Full-time scoreline, written once the fixture reaches FT. */
  final_score?: string | null;
  /** Goals scored AFTER the trigger minute. null when unverifiable. */
  goals_after?: number | null;
  /**
   * Descriptive outcome, never an accuracy claim:
   *   pending        — match still running
   *   goal_followed  — at least one goal was scored after the alert
   *   no_further_goal— none followed
   *   unverifiable   — no trigger scoreline was captured for this record
   */
  outcome?: "pending" | "goal_followed" | "no_further_goal" | "unverifiable" | null;
  resolved_at?: string | null;
}

/** Stage 6 cycle_matches orchestrator board row. */
export interface LiveOrchestratorMatch {
  name: string;
  id: string;
  minute: number;
  conf: number;
  h_pressure: number;
  a_pressure: number;
  chaos: number;
  h_xg: number;
  a_xg: number;
  h_sot: number;
  a_sot: number;
  structural: string;
  alerts: Array<{ id?: string; msg: string; tier: string; conf: number }>;
  in_db: boolean;
  /** Nested Code 6 intel (optional — older boards may omit). */
  intel?: LiveStage6Intel;
  /** Nested structural forensics (optional). */
  forensics?: LiveStage6Forensics;
  /** Live key-player-lost counts (optional — older boards may omit). */
  key_loss?: LiveKeyLoss;
  /** VALID_30 | SUPREME_45 | null */
  validation?: string | null;
  /** Settled markets e.g. ["GG","O2.5"] */
  settled?: string[];
  /**
   * Raw live team statistics for this fixture, published by Code 6 from the
   * same payload it already analyses. This replaced the Code 2 validation
   * board as the live page's source for team statistics, at no extra provider
   * cost. Keys are the provider's own stat names (e.g. "shots-on-target").
   */
  statistics?: Record<string, Record<string, number>>;
  /** Storm progression (read-only, never alertable on its own). */
  storm?: {
    stage?: "developing" | "sustained" | "peaking" | null;
    first_seen?: number;
    last_seen?: number;
    confidence?: number;
    chaos?: number;
  } | null;
  /**
   * Whether the structural bar could be tested at all.
   *   evaluated     — a squad was built for both sides, so a storm alert was
   *                   possible (or genuinely not warranted)
   *   not_evaluated — no squad could be built, so no alert was possible.
   *                   Silence here means BLIND, not QUIET.
   */
  evaluation?: "evaluated" | "not_evaluated" | null;
  evaluation_note?: string | null;
}

/**
 * How much of the live feed Code 6 was actually able to judge.
 *
 * Published so a blank alerts page is never ambiguous: "no storms today" and
 * "the engine could not look at most of today's matches" look identical
 * otherwise.
 */
export interface LiveCoverage {
  evaluated: number;
  unevaluated: number;
  total: number;
  pct: number;
  /**
   * True while squad fetches are still in flight. The counts are then
   * PROVISIONAL: the vault is cold (e.g. straight after a restart) and the
   * figure is not the real coverage yet. A 0% shown during warm-up would read
   * as "the engine is blind" when it is really "it has not finished looking".
   */
  warming_up?: boolean;
  pending_fetches?: number;
  provisional?: boolean;
  reason: string;
}

export interface LiveOrchestratorBoard {
  session: string;
  cycle: number;
  total_live: number;
  total_db: number;
  matches: LiveOrchestratorMatch[];
  coverage?: LiveCoverage;
}

// ============================================================
// USER-DEFINED LIVE ALERT RULES (Code 6 flexibility filter)
// Every type below mirrors LIVE_SCANNER/user_rules_store.py exactly —
// three real prematch sources (SH-GG Winner flags/rates, Stage 1 team
// audit, Aggregator chemistry/breach) and eight real live conditions
// (snapshot, pressure, chaos, xG, SOT, corners, DA, key player lost),
// plus an optional minute window.
// ============================================================
export type PrematchFlagKey =
  | "both_2h_goal_100_percent"
  | "home_h2h_win_100"
  | "away_h2h_win_100"
  | "h2h_gg_100"
  | "h2h_o25_100";

export type PrematchRateMetric = "home_2h_rate" | "away_2h_rate";

export type ChemistryMarket =
  | "Gg"
  | "Corner"
  | "Home Win"
  | "Away Win"
  | "Over2.5"
  | "Under3.5"
  | "Over1.5";

export type ChemistryLevel =
  | "excellent"
  | "elite"
  | "very strong"
  | "strong"
  | "weak"
  | "very weak"
  | "unavailable";

export type RuleSide = "home" | "away" | "any";

export type UserRulePrematch =
  | { type: "none" }
  | { type: "flag"; flag: PrematchFlagKey }
  | { type: "rate"; metric: PrematchRateMetric; min_value: number }
  | { type: "gk_liability"; side: RuleSide }
  | { type: "key_missing"; side: RuleSide; min_count: number }
  | { type: "aggregator_chemistry"; market: ChemistryMarket; level: ChemistryLevel }
  | { type: "aggregator_breach"; side: RuleSide };

export type LiveConditionType =
  | "snapshot"
  | "pressure_share"
  | "chaos_index"
  | "xg"
  | "sot"
  | "corners"
  | "da"
  | "key_player_lost"
  | "goals";

/**
 * The scoreline gate. Mirrors LIVE_SCANNER/user_rules_store.py
 * VALID_GOAL_DIRECTIONS exactly — a value outside this set is rejected with a
 * 422 by the server.
 *
 *   under 2.5 -> fires while the total is still <= 2 (the trade is still live)
 *   over  2.5 -> fires once the total has reached 3      (the line is beaten)
 *   exact 3   -> fires only at exactly 3 goals
 *
 * The asymmetry is deliberate: an UNDER alert is useful BEFORE the line is
 * crossed, an OVER alert only AFTER. Treating them the same would fire the
 * under gate when the market is already dead.
 */
export type RuleGoalDirection = "under" | "over" | "exact";

export type UserRuleLive =
  | { type: "snapshot" }
  | { type: "pressure_share"; side: RuleSide; min_value: number }
  | { type: "chaos_index"; min_value: number }
  | { type: "xg"; side: RuleSide; min_value: number }
  | { type: "sot"; side: RuleSide; min_value: number }
  | { type: "corners"; side: RuleSide; min_value: number }
  | { type: "da"; side: RuleSide; min_value: number }
  | { type: "key_player_lost"; side: RuleSide; min_count: number }
  | { type: "goals"; direction: RuleGoalDirection; line: number };

/**
 * A CONDITION GROUP: any number of live conditions plus how many must hold.
 *
 *   mode="all"      every condition must hold
 *   mode="at_least" `threshold` of them must hold — any N of the K chosen
 *
 * Prematch is deliberately NOT a group: exactly one prematch signal, so the
 * match board is never silently widened behind the user's back.
 */
export interface UserRuleLiveGroup {
  conditions: UserRuleLive[];
  mode: "all" | "at_least";
  threshold: number;
}

/**
 * The live half of a rule. A bare single condition is still accepted and
 * normalised to a one-condition group, so alerts saved before multi-select
 * keep working.
 */
export type UserRuleLiveAny = UserRuleLive | UserRuleLiveGroup;

export type RuleConditionMode = "all" | "at_least";

/** Where a saved alert stands right now. */
export type RuleAlertStatus = "waiting" | "live" | "fired" | "paused";

/** A live fixture currently satisfying this rule. */
export interface RuleLiveMatch {
  fixture_id: string;
  name: string;
  minute?: number | null;
  score?: string | null;
  gate?: string | null;
  note?: string | null;
}

/** The last alert this rule actually fired, as recorded in the alert log. */
export interface RuleLastFired {
  fixture_id?: string | null;
  fixture?: string | null;
  minute?: number | null;
  score?: string | null;
  time?: string | null;
  outcome?: string | null;
}

/**
 * Per-rule status, assembled by the API from the live board AND the fire
 * history. Neither alone can answer the question that matters: a rule that has
 * never fired looks identical whether it is about to fire or can never fire.
 */
export interface RuleStatus {
  rule_id: string;
  label: string;
  active: boolean;
  status: RuleAlertStatus;
  status_label: string;
  live_count: number;
  live_matches: RuleLiveMatch[];
  fired_count: number;
  last_fired: RuleLastFired | null;
  /** Qualifying right now, but this device could not receive it. */
  needs_push: boolean;
  /** null when the notification store could not be read — say nothing rather
   * than guess. */
  push_ready: boolean | null;
  board_age?: string | null;
  /** The live board is older than expected, so "nothing qualifying" is not
   * trustworthy and must not be presented as fact. */
  board_stale: boolean;
}

export interface UserRuleMinuteWindow {
  start: number;
  end: number;
}

export interface UserRuleDef {
  rule_id: string;
  user_id: string;
  label: string;
  prematch: UserRulePrematch;
  live: UserRuleLiveAny;
  minute_window?: UserRuleMinuteWindow;
  /**
   * Fixture ids the user accepted in the setup board. SOFT by design: the
   * evaluator never tests membership, so a rule still fires on any qualifying
   * match. These are the matches that get marked and ranked first.
   */
  watchlist?: string[];
  active: boolean;
  created_at?: string;
}

export type UserRuleCreate = Omit<UserRuleDef, "rule_id" | "created_at" | "user_id">;
export type UserRulePatch = Partial<
  Pick<UserRuleDef, "label" | "prematch" | "live" | "minute_window" | "active" | "watchlist">
>;

/** The real, already-on-disk facts shown on a candidate card. */
export interface RuleCandidateEvidence {
  has_lineup?: boolean;
  has_formation?: boolean;
  formations?: Record<string, string>;
  home_missing?: number | null;
  away_missing?: number | null;
  home_gk_out?: boolean;
  away_gk_out?: boolean;
  home_breach?: boolean;
  away_breach?: boolean;
  home_danger_status?: string | null;
  away_danger_status?: string | null;
  home_formation?: string | null;
  away_formation?: string | null;
  chemistry?: Record<string, string> | null;
  flags?: Record<string, boolean> | null;
  metrics?: Record<string, number> | null;
  picks?: { type?: string; target_loc?: string }[];
  kickoff_utc?: string | null;
  status_text?: string | null;
  state?: string | null;
}

/**
 * One row of the setup board: a known fixture scored against the user's chosen
 * prematch condition by the SAME predicate the live cycle will use.
 *
 * `met` is a boolean, never a guess, and `reason` is the predicate's own
 * wording. `live_score` is null when the fixture is not live — which the UI
 * must render as unknown, never as 0-0.
 */
export interface RuleCandidateMatch {
  fixture_id: string;
  name: string;
  home_name?: string | null;
  away_name?: string | null;
  met: boolean;
  reason: string;
  evidence: RuleCandidateEvidence;
  live_score: [number, number] | null;
  kickoff_utc?: string | null;
  state?: string | null;
}


/** Must match LIVE_SCANNER/user_rules_store.py VALID_PREMATCH_FLAGS exactly. */
export const PREMATCH_FLAG_OPTIONS: { value: PrematchFlagKey; label: string }[] = [
  { value: "both_2h_goal_100_percent", label: "Both 2H Goal (100%)" },
  { value: "home_h2h_win_100", label: "Home H2H Win (100%)" },
  { value: "away_h2h_win_100", label: "Away H2H Win (100%)" },
  { value: "h2h_gg_100", label: "H2H GG (100%)" },
  { value: "h2h_o25_100", label: "H2H Over 2.5 (100%)" },
];

/** Must match LIVE_SCANNER/user_rules_store.py VALID_PREMATCH_RATE_METRICS exactly. */
export const PREMATCH_RATE_OPTIONS: { value: PrematchRateMetric; label: string }[] = [
  { value: "home_2h_rate", label: "Home 2H Scoring Rate" },
  { value: "away_2h_rate", label: "Away 2H Scoring Rate" },
];

/** Must match LIVE_SCANNER/user_rules_store.py VALID_CHEMISTRY_MARKETS exactly. */
export const CHEMISTRY_MARKET_OPTIONS: { value: ChemistryMarket; label: string }[] = [
  { value: "Gg", label: "GG / BTTS" },
  { value: "Corner", label: "Corners" },
  { value: "Home Win", label: "Home Win" },
  { value: "Away Win", label: "Away Win" },
  { value: "Over2.5", label: "Over 2.5" },
  { value: "Under3.5", label: "Under 3.5" },
  { value: "Over1.5", label: "Over 1.5" },
];

/** Must match LIVE_SCANNER/user_rules_store.py VALID_CHEMISTRY_LEVELS exactly. */
export const CHEMISTRY_LEVEL_OPTIONS: { value: ChemistryLevel; label: string }[] = [
  { value: "excellent", label: "Excellent" },
  { value: "elite", label: "Elite" },
  { value: "very strong", label: "Very Strong" },
  { value: "strong", label: "Strong" },
  { value: "weak", label: "Weak" },
  { value: "very weak", label: "Very Weak" },
  { value: "unavailable", label: "Unavailable" },
];

/** Live condition types offering a per-side selector (home/away/any). */
export const LIVE_SIDED_TYPES: LiveConditionType[] = [
  "pressure_share",
  "xg",
  "sot",
  "corners",
  "da",
  "key_player_lost",
];

// ============================================================
// FIXTURE RISK (cup / friendly) — stamped by the API onto EVERY picks row
// (api/main.py read()/read_range() via fixture_classification). Additive:
// a row that was never classified keeps `classification: "unknown"`, which is
// deliberately NOT treated as "safe" anywhere in the UI.
// ============================================================
export interface FixtureRisk {
  classification?: "league" | "cup" | "friendly" | "unknown";
  is_cup?: boolean;
  is_friendly?: boolean;
  is_risk_fixture?: boolean;
  risk_level?: "high" | "elevated" | "normal" | "unknown";
  risk_label?: string;
  competition?: string | null;
  league_name?: string | null;
}

// ============================================================
// FILTER & PIPELINE TYPES
// ============================================================
export interface GGFilterParams {
  mode?: "public" | "tipster" | "odds_band" | "advanced";
  risk_level?: string;
  odds_band?: string;
  min_prob?: number;
  min_home_gg5?: number;
  min_away_gg5?: number;
  min_home_gg3?: number;
  min_away_gg3?: number;
  min_h2h_gg?: number;
  max_parity?: number;
  min_dominance?: number;
  max_home_missing?: number;
  max_away_missing?: number;
  min_gg_odds?: number;
  max_gg_odds?: number;
  strict_mode?: boolean;
  start_date?: string;
  end_date?: string;
  anchor_date?: string;
}

export interface WinFilterParams {
  mode?: "public" | "tipster" | "odds_band" | "advanced";
  risk_level?: string;
  odds_band?: string;
  min_form_wins?: number;
  min_opp_conceded?: number;
  min_h2h?: number;
  require_no_draw?: boolean;
  min_odds?: number;
  max_odds?: number;
  min_overall_wins?: number;
  min_venue_wins?: number;
  min_h2h_wins?: number;
  min_opp_losses?: number;
  min_parity_gap?: number;
  min_even_count?: number;
  strict_mode?: boolean;
  min_parity?: number;
  start_date?: string;
  end_date?: string;
  anchor_date?: string;
}

export interface Over25FilterParams {
  mode?: "public" | "tipster" | "odds_band" | "advanced";
  risk_level?: string;
  odds_band?: string;
  min_poisson?: number;
  min_votes?: number;
  max_pos_gap?: number;
  min_h2h_overs?: number;
  min_odds?: number;
  max_odds?: number;
  start_date?: string;
  end_date?: string;
  anchor_date?: string;
}

// Win Cross-Check uses the SAME drawer as /weekly/win (its default risk preset
// is `safe`, which is the snapshot it has always read), so it accepts the whole
// control set instead of dates only.
export type WinPrecisionWeeklyParams = WinFilterParams;

export interface PipelineResponse {
  date: string;
  phases_run: string[];
  results: Record<string, unknown>;
  errors: Record<string, string>;
}

// ============================================================
// TEAM INTELLIGENCE — /api/team/{team_name}/intelligence/{date}
// (INTELLIGENT_PASS/pass_count.py::get_team_intelligence)
// Read-only second-level audit feed: the team's per-check intelligence
// across every market for the date. Rendered by app/team/[teamName]/page.tsx.
// ============================================================

/** One intelligence check — mirrors pass_count.py's check dicts. */
export interface IntelligenceCheck {
  name: string;
  result: "PASS" | "FAIL" | "NOT_AVAILABLE";
  value?: unknown;
  threshold?: string;
}

/** One market's audit: {passed, total, checks[]} — total is DYNAMIC
 * (only applicable checks count; NOT_AVAILABLE never enters the denominator). */
export interface MarketIntelligence {
  passed: number;
  total: number;
  checks: IntelligenceCheck[];
}

export interface TeamIntelligencePage {
  team: string;
  date: string;
  fixture: string;
  fixture_id: string | number;
  opponent: string;
  fixture_found: boolean;
  /** Keyed by market: win, win_psychology, gg, gg_precision, over25, over15,
   * corners, draw, unders, u2s, fhvi, shvi. Empty for an unknown team. */
  markets: Record<string, MarketIntelligence>;
  /** Raw EXISTING engine values behind the checks — passthrough, missing → None. */
  context?: Record<string, unknown>;
}

/** Stable market ordering for the page (sections outside this list render after). */
export const TEAM_INTELLIGENCE_MARKET_ORDER = [
  "win",
  "win_psychology",
  "gg",
  "gg_precision",
  "over25",
  "over15",
  "corners",
  "draw",
  "unders",
  "u2s",
  "fhvi",
  "shvi",
  "sot",
  "gg_o15",
] as const;

/** Canonical report markets — mirrors INTELLIGENT_PASS/pass_count.py
 * TEAM_INTELLIGENCE_MARKETS (the pick/market is the primary object). */
export const TEAM_INTELLIGENCE_MARKET_LABELS: Record<string, string> = {
  win: "Win",
  win_psychology: "Win Psychology",
  gg: "GG / BTTS Supreme",
  gg_precision: "GG Precision",
  gg_o15: "GG / Over 1.5 Composite",
  over25: "Over 2.5",
  over15: "Over 1.5",
  corners: "Corners",
  draw: "Draw",
  unders: "Under 2.5",
  u2s: "Underdog-to-Score",
  fhvi: "FHVI",
  shvi: "SHVI",
  sot: "SOT",
};

/** Market → the sidebar page that market's table lives on. Used ONLY as the
 * Back-navigation fallback when the origin page was not carried in the URL. */
export const MARKET_SOURCE_PAGE: Record<string, string> = {
  win: "/win",
  win_psychology: "/win",
  gg: "/gg",
  gg_precision: "/gg",
  gg_o15: "/gg",
  over25: "/over25",
  over15: "/over15",
  corners: "/corners",
  draw: "/draw",
  unders: "/unders",
  u2s: "/underdog",
  fhvi: "/fhvi",
  shvi: "/shvi",
  sot: "/sot",
};

/** SINGLE-MARKET report payload (team+date+market identity). Carries
 * `score`+`checks` for THE requested pick only — never a markets map. */
export interface MarketIntelligenceReport {
  team: string;
  date: string;
  market: string;
  market_label: string;
  fixture: string;
  fixture_id: string | number;
  opponent: string;
  fixture_found: boolean;
  /** The audited pick (e.g. "Toluca" for a WIN pick); null for fixture-level markets. */
  prediction: string | null;
  score: { passed: number; total: number } | null;
  checks: IntelligenceCheck[];
}

export const teamIntelligenceApi = {
  get: (
    teamName: string,
    date: string,
    market?: string
  ): Promise<AxiosResponse<TeamIntelligencePage | MarketIntelligenceReport>> =>
    api.get(
      `/api/team/${encodeURIComponent(teamName)}/intelligence/${encodeURIComponent(date)}`,
      market ? { params: { market } } : undefined
    ),
};

// ============================================================
// API ENDPOINT GROUPS — paths match api/main.py exactly
// ============================================================

export const healthApi = {
  check: (): Promise<AxiosResponse<HealthResponse>> => api.get("/api/health"),
};

export const foundationApi = {
  // DNA v1 is persisted on disk as a {team_id: profile} object, but the Win
  // "Team DNA — Goal Intent Board" consumes a flat DnaProfile[] array
  // (ChainStage drops non-array payloads). Normalize the object shape here so
  // real profiles render regardless of whether the API has hoisted them yet —
  // an array response is passed through untouched.
  getDNA: (date: string): Promise<AxiosResponse<DnaProfile[]>> =>
    api.get(`/api/dna/${date}`).then((res) => {
      const raw = res.data as unknown;
      if (Array.isArray(raw)) return res;
      if (raw && typeof raw === "object") {
        const rows = Object.entries(raw as Record<string, unknown>)
          .map(([team_id, profile]) => ({
            team_id,
            ...(profile as Record<string, unknown>),
          }))
          .filter(
            (row) => typeof (row as { team_name?: unknown }).team_name === "string"
          );
        return { ...res, data: rows as DnaProfile[] };
      }
      return { ...res, data: [] as DnaProfile[] };
    }),

  getCalibration: (date: string): Promise<AxiosResponse<UnderdogHandshake[]>> =>
    api.get(`/api/calibration/${date}`),

  // win_forecast is a Phase A Foundation engine — lives here per architecture rule
  getWinForecast: (date: string): Promise<AxiosResponse<WinForecastPick[]>> =>
    api.get(`/api/win/forecast/${date}`),
};

// DNA Engine V2 — fully separate from foundationApi.getDNA (v1). All DNA
// comparison math (factor counts, style clashes) is computed server-side;
// this client only fetches and the UI only renders.
export const dnaV2Api = {
  get: (date: string): Promise<AxiosResponse<DnaV2Response>> =>
    cachedGet(`/api/dna/v2/${date}`),

  // Disk-only fast read — no engine recompute. Preferred for fixture-list
  // DNA counts and for the DNA Analysis page so opening it feels instant.
  getLatest: (): Promise<AxiosResponse<DnaV2Response>> =>
    cachedGet(`/api/dna/v2/latest`),

  // Read-only fixture metadata (league, competition, table position) for the
  // SportyBet-style match header. Also disk-only: the backend joins cache files
  // this same pipeline run already wrote, so this costs no engine run and no
  // provider call.
  getMatchMeta: (date: string): Promise<AxiosResponse<DnaV2MatchMetaResponse>> =>
    cachedGet(`/api/dna/v2/${date}/match-meta`),

  // Real past meetings between the two teams of ONE fixture.
  //
  // This is the only call on the DNA page that spends provider quota, and it
  // is per-fixture precisely so it spends exactly one: a per-date version
  // would ask the provider about every fixture on the slate (53 on a real
  // day) just to render the one page in front of the user.
  //
  // `cachedGet` is deliberately NOT used. That helper memoises by URL for the
  // life of the session, which would freeze the very first (possibly
  // rate-limited) answer forever and hide the block permanently after one bad
  // response. The server already caches per team-pair, so a reload is cheap
  // and always reflects the latest provider state.
  getH2H: (date: string, fixtureId: string): Promise<AxiosResponse<DnaV2H2HResponse>> =>
    api.get(`/api/dna/v2/h2h/${date}/${fixtureId}`),
};

export const underdogApi = {
  getBase: (date: string): Promise<AxiosResponse<UnderdogBasePick[]>> =>
    api.get(`/api/underdog/${date}`),

  getAudit: (date: string): Promise<AxiosResponse<UnderdogMasterPick[]>> =>
    api.get(`/api/underdog/audit/${date}`),

  getApex: (date: string): Promise<AxiosResponse<UnderdogApexPick[]>> =>
    cachedGet(`/api/underdog/apex/${date}`),
};

export const ggApi = {
  getPrecision: (date: string): Promise<AxiosResponse<GGPrecisionResponse>> =>
    api.get(`/api/gg/precision/${date}`),

  getForensics: (date: string): Promise<AxiosResponse<GGForensicPick[]>> =>
    api.get(`/api/gg/forensics/${date}`),

  getPsychology: (date: string): Promise<AxiosResponse<GGPsychologyPick[]>> =>
    api.get(`/api/gg/psychology/${date}`),

  getSupreme: (date: string): Promise<AxiosResponse<GGSupremePick[]>> =>
    cachedGet(`/api/gg/supreme/${date}`),

  getCrossVerify: (): Promise<AxiosResponse<GGCrossVerifyPick[]>> =>
    api.get("/api/gg/cross-verify"),
};

export const winApi = {
  // getForecast moved to foundationApi.getWinForecast (Phase A engine)
  getU2S: (date: string): Promise<AxiosResponse<WinU2SPick[]>> =>
    api.get(`/api/win/u2s/${date}`),

  getPsychology: (date: string): Promise<AxiosResponse<WinPsychologyPick[]>> =>
    api.get(`/api/win/psychology/${date}`),

  getApex: (date: string): Promise<AxiosResponse<WinApexPick[]>> =>
    cachedGet(`/api/win/apex/${date}`),

  getRaw: (date: string): Promise<AxiosResponse<WinRawPick[]>> =>
    api.get(`/api/win/raw/${date}`),
};

export const over25Api = {
  getStage1: (date: string): Promise<AxiosResponse<Over25Stage1Pick[]>> =>
    api.get(`/api/over25/stage1/${date}`),

  getStage2: (date: string): Promise<AxiosResponse<Over25Stage2Pick[]>> =>
    api.get(`/api/over25/stage2/${date}`),

  getStage3: (date: string): Promise<AxiosResponse<Over25Stage3Pick[]>> =>
    api.get(`/api/over25/stage3/${date}`),

  getPsychology: (date: string): Promise<AxiosResponse<Over25PsychologyPick[]>> =>
    api.get(`/api/over25/psychology/${date}`),

  getGold: (date: string): Promise<AxiosResponse<Over25GoldPick[]>> =>
    api.get(`/api/over25/gold/${date}`),

  getApex: (date: string): Promise<AxiosResponse<Over25ApexPick[]>> =>
    cachedGet(`/api/over25/apex/${date}`),

  getForecast: (date: string): Promise<AxiosResponse<Over25ForecastPick[]>> =>
    api.get(`/api/over25/forecast/${date}`),
};

export const over15Api = {
  getStage3: (date: string): Promise<AxiosResponse<Over15Stage3Pick[]>> =>
    api.get(`/api/over15/stage3/${date}`),

  getPsychology: (date: string): Promise<AxiosResponse<Over15PsychologyPick[]>> =>
    api.get(`/api/over15/psychology/${date}`),

  getApex: (date: string): Promise<AxiosResponse<Over15ApexPick[]>> =>
    cachedGet(`/api/over15/apex/${date}`),

  // The FROZEN PRE-FIX verdict for this date. Same row shape as the psychology
  // engine, so the two tables can be read against each other directly. Never
  // regenerated — see tools/snapshot_o15_prefix.py.
  getLegacy: (date: string): Promise<AxiosResponse<Over15LegacyPick[]>> =>
    cachedGet(`/api/over15/legacy/${date}`),
};

/**
 * DANGER DERIVATION — why one team's number is what it is.
 *
 * The board shows `vulnerability_pct` beside a verdict, and the two are
 * computed from different things, so a BLESSING can appear next to 87.1% and
 * read as a contradiction. This page exists so neither number has to be
 * believed on faith.
 *
 * It shows, in order:
 *   1. what the percentage actually measures,
 *   2. the arithmetic — numerator, denominator, per-position breakdown,
 *   3. every absent player with the rating/apps behind the weight,
 *   4. the signed verdict and its evidence, and
 *   5. the goalkeeper decision and why.
 *
 * Nothing here is computed client-side: the figures come from
 * /api/live/danger/{fixture_id}, which recomputes the breakdown from the
 * published record using the engine's own weights.
 */
export interface DangerAbsentPlayer {
  name: string;
  pos: string;
  rating: number | null;
  apps: number | null;
  mins: number | null;
  worth: number | null;
  weight: number;
}

export interface DangerSideDetail {
  team_name: string;
  team_id: number;
  verdict: string | null;
  verdict_reason: string | null;
  net_impact: number | null;
  impact_confidence: number | null;
  regime: string | null;
  quality_lost: number | null;
  replacement_credit: number | null;
  rotation_uplift: number | null;
  formation: string | null;
  vulnerability: {
    pct: number | null;
    missing_weight: number;
    total_weight: number | null;
    absent_by_position: { pos: string; count: number; weight: number }[];
    goalkeeper_share_of_scale: number | null;
    what_it_measures: string;
    why_it_is_not_the_verdict: string;
  };
  goalkeeper: {
    verdict: string | null;
    note: string | null;
    leak_per_90: number | null;
    available: boolean | null;
  };
  absent_players: DangerAbsentPlayer[];
  style: { label?: string; score?: number; da?: number } | null;
  attack_index: number | null;
}

export interface LiveDangerDetail {
  fixture: string;
  fixture_id: number | string;
  style_alignment: string | null;
  openness_score: number | null;
  match_chemistry: Record<string, string> | null;
  home: DangerSideDetail | null;
  away: DangerSideDetail | null;
  error?: string;
}

export const liveDangerApi = {
  getDetail: (fixtureId: string | number): Promise<AxiosResponse<LiveDangerDetail>> =>
    api.get(`/api/live/danger/${fixtureId}`),
};

export const cornersApi = {
  getStage1: (date: string): Promise<AxiosResponse<CornerStage1Pick[]>> =>
    api.get(`/api/corners/stage1/${date}`),

  getStage2: (date: string): Promise<AxiosResponse<CornerStage2Pick[]>> =>
    api.get(`/api/corners/stage2/${date}`),

  getPsychology: (date: string): Promise<AxiosResponse<CornerPsychologyPick[]>> =>
    api.get(`/api/corners/psychology/${date}`),

  getCatalyst: (date: string): Promise<AxiosResponse<CornerCatalystPick[]>> =>
    api.get(`/api/corners/catalyst/${date}`),

  getAggregator: (date: string): Promise<AxiosResponse<CornerAggregatorPick[]>> =>
    cachedGet(`/api/corners/aggregator/${date}`),

  /**
   * The PERSISTENT CORNER KINGS table, now actually served.
   *
   * Until 2026-09-28 this existed only as a console print in the miner, which
   * built the ranking, displayed it, and then filtered it out of the results.
   * Not date-scoped on purpose: the payload carries its own `date` and
   * `generated_at` so the page can state which run it is showing.
   */
  getConsistency: (): Promise<AxiosResponse<CornerConsistencyReport>> =>
    api.get("/api/corners/consistency"),
};

export const specialsApi = {
  getUnders: (date: string): Promise<AxiosResponse<UndersResponse>> =>
    cachedGet(`/api/unders/${date}`),

  getDraw: (date: string): Promise<AxiosResponse<DrawResponse>> =>
    cachedGet(`/api/draw/${date}`),

  getSOT: (date: string): Promise<AxiosResponse<SOTPick[]>> =>
    cachedGet(`/api/sot/${date}`),

  getFHVI: (date: string): Promise<AxiosResponse<FHVIPick[]>> =>
    cachedGet(`/api/fhvi/${date}`),

  getSHVI: (date: string): Promise<AxiosResponse<SHVIPick[]>> =>
    cachedGet(`/api/shvi/${date}`),
};

export const shMasterApi = {
  getSHGGWinner: (date: string): Promise<AxiosResponse<SHGGWinnerPick[]>> =>
    api.get(`/api/sh-gg-winner/${date}`),

  getSHMaster: (date: string): Promise<AxiosResponse<SHMasterPick[]>> =>
    api.get(`/api/sh-master/${date}`),

  getSH8Goal: (date: string): Promise<AxiosResponse<SH8GoalPick[]>> =>
    api.get(`/api/sh-8goal/${date}`),
};

export interface LivePredictionQuestion {
  id: string;
  question: string;
  source: string;
  answer: string;
  direction: "neutral" | "for_home" | "for_away" | "against_home";
  available: boolean;
}

export interface LivePredictionJudge {
  judge: string;
  verdict: "PASS" | "WARN" | "BLOCK";
  reason: string;
  detail: Record<string, unknown>;
}

export interface LivePrediction {
  fixture_id: string;
  fixture?: string | null;
  minute?: number | null;
  score?: string | null;
  home_team?: string | null;
  away_team?: string | null;
  /** FULL = pre-match audit available; LIVE_ONLY = live state only. */
  mode: "FULL" | "LIVE_ONLY";
  status: "OK" | "INSUFFICIENT" | "NOT_LIVE" | "ERROR";
  error?: string | null;
  /** null whenever the engine refused to answer. */
  predictions: {
    home_win: number;
    draw: number;
    away_win: number;
    home_to_score: { team: string; pct: number };
    away_to_score: { team: string; pct: number };
    over_2_5: number;
    under_3_5: number;
    exactly_3_goals: number;
  } | null;
  trace: LivePredictionQuestion[];
  judges: LivePredictionJudge[] | null;
  verdict: "PASS" | "WARN" | "BLOCK" | null;
  model?: {
    anchor: "market_price" | "live_observation";
    anchor_total_goals: number;
    minutes_remaining: number;
    [k: string]: unknown;
  } | null;
}

export interface LivePredictionSearch {
  query: string;
  matches: { fixture_id: string; name: string; minute?: number | null }[];
  prediction: LivePrediction | null;
}

export const liveApi = {
  /**
   * Stage 8 — instant live prediction from typed team names.
   *
   * Returns the matching live fixtures plus the judged prediction for the best
   * match. `verdict` is PASS, WARN or BLOCK; a BLOCK carries `predictions: null`
   * because the engine refuses rather than guessing.
   */
  searchPrediction: (
    q: string
  ): Promise<AxiosResponse<LivePredictionSearch>> =>
    api.get("/api/live/predict", { params: { q } }),

  /** Stage 8 — prediction for one known fixture. */
  getPrediction: (
    fixtureId: string | number
  ): Promise<AxiosResponse<LivePrediction>> =>
    api.get(`/api/live/predict/${fixtureId}`),

  /** Stage 1 rich strategic audit board. */
  getPrematch: (): Promise<AxiosResponse<LivePrematchAudit[]>> =>
    api.get("/api/live/prematch"),

  /** Stage 2 — validates stage 1 prematch feed (validated_picks.json). */
  getValidation: (): Promise<AxiosResponse<LiveValidationBoard>> =>
    api.get("/api/live/validation"),

  getIncoming: (): Promise<AxiosResponse<LiveIncomingPick[]>> =>
    api.get("/api/live/incoming"),

  /**
   * Full drill-down for one incoming fixture: the key-11 table, the keeper
   * assessment, the signed impact, the market chemistry and the Code 3 / Code 5
   * reconciliation. Served as a local-file join, so it costs no provider quota.
   */
  getIncomingDetail: (
    fixtureId: string | number
  ): Promise<AxiosResponse<LiveIncomingDetail>> =>
    api.get(`/api/live/incoming/${fixtureId}`),

  getDanger: (): Promise<AxiosResponse<LiveDangerReport[]>> =>
    api.get("/api/live/danger"),

  getAggregator: (): Promise<AxiosResponse<LiveAggregatorReport[]>> =>
    api.get("/api/live/aggregator"),

  /** Stage 6 — last VIP + LIVE orchestrator board. */
  getOrchestrator: (): Promise<AxiosResponse<LiveOrchestratorBoard>> =>
    api.get("/api/live/orchestrator"),

  /** Stage 6 — VIP + free LIVE alerts (ready_to_push / session logs). */
  getAlerts: (date?: string): Promise<AxiosResponse<LiveAlertPick[]>> =>
    api.get("/api/live/alerts", date ? { params: { date } } : undefined),

  getDashboard: (): Promise<AxiosResponse<LiveDashboardResult[]>> =>
    api.get("/api/live/dashboard"),
};

export const userRulesApi = {
  list: (): Promise<AxiosResponse<UserRuleDef[]>> =>
    api.get("/api/live/user-rules"),

  create: (rule: UserRuleCreate): Promise<AxiosResponse<UserRuleDef>> =>
    api.post("/api/live/user-rules", rule),

  /**
   * Every known fixture scored against the chosen prematch condition, by the
   * same predicate the live cycle uses. Read-only; nothing is persisted.
   */
  getCandidates: (
    prematch: UserRulePrematch
  ): Promise<AxiosResponse<RuleCandidateMatch[]>> =>
    api.post("/api/live/user-rules/candidates", { prematch }),

  /** Per-rule status: waiting, qualifying now, or already alerted. */
  getStatus: (): Promise<AxiosResponse<RuleStatus[]>> =>
    api.get("/api/live/user-rules/status"),

  update: (ruleId: string, patch: UserRulePatch): Promise<AxiosResponse<UserRuleDef>> =>
    api.patch(`/api/live/user-rules/${ruleId}`, patch),

  remove: (ruleId: string): Promise<AxiosResponse<void>> =>
    api.delete(`/api/live/user-rules/${ruleId}`),

  /** Alerts fired specifically from this user's own saved rules. */
  getMyAlerts: (): Promise<AxiosResponse<LiveAlertPick[]>> =>
    api.get("/api/live/alerts/mine"),
};

export const filterApi = {
  getGGFilter: (date: string, params?: GGFilterParams) =>
    api.get(`/api/filter/gg/${date}`, { params }),

  getGGWeekly: (params?: GGFilterParams) =>
    api.get("/api/filter/gg/weekly", { params }),

  getWinFilter: (date: string, params?: WinFilterParams) =>
    api.get(`/api/filter/win/${date}`, { params }),

  getWinWeekly: (params?: WinFilterParams) =>
    api.get("/api/filter/win/weekly", { params }),

  getOver25Filter: (date: string, params?: Over25FilterParams) =>
    api.get(`/api/filter/over25/${date}`, { params }),

  getOver25Weekly: (params?: Over25FilterParams) =>
    api.get("/api/filter/over25/weekly", { params }),

  getWinPrecision: (date: string, params?: WinFilterParams) =>
    api.get(`/api/filter/win/precision/${date}`, { params }),

  getWinPrecisionWeekly: (params?: WinPrecisionWeeklyParams) =>
    api.get("/api/filter/win/precision/weekly", { params }),
};

export const pipelineApi = {
  run: (
    date: string,
    phases?: string[]
  ): Promise<AxiosResponse<PipelineResponse>> =>
    api.get(`/api/pipeline/${date}`, {
      params: phases?.length ? { phases: phases.join(",") } : {},
    }),
};

// ============================================================
// UTILITY HELPERS
// ============================================================
// Date helpers live in date-utils.ts so layout/shell can import them
// without pulling this entire axios client into the first compile graph.
export { getTodayDate, formatDate, shiftDate } from "./date-utils";

/**
 * Canonical in-memory cache key for one market + one date, independent of
 * which component fetches it. Same market + same date → same key (and, via
 * `cachedGet`, the same underlying raw snapshot), instead of per-component
 * display names like "dashboard-win:..." vs "Win Apex — Final Aggregator:...".
 */
export const marketCacheKey = (market: string, date: string): string =>
  `market:${market}:${date}`;

/**
 * Single numeric normalization boundary for every value that reaches
 * `.toFixed()` or numeric comparison in the UI.
 *
 *  - finite number            → itself
 *  - numeric string ("65")    → 65
 *  - percentage string ("65%")→ 65  (only when `percentage: true` is passed,
 *    i.e. when the field's schema explicitly says it is a percentage)
 *  - null / undefined / NaN / ±Infinity / anything else → null
 *
 * Callers apply their existing UI fallback for null (skip the row, render
 * "–"), so invalid values are never silently converted into misleading
 * scores and can never crash `.toFixed()`.
 */
export function toFiniteNumber(
  val: unknown,
  opts?: { percentage?: boolean }
): number | null {
  if (val == null) return null;
  if (typeof val === "number") return Number.isFinite(val) ? val : null;
  if (typeof val === "string") {
    const s = val.trim();
    if (s === "" || s === "-" || s === "--") return null;
    const source = opts?.percentage ? s.replace(/%$/, "") : s;
    if (source !== s && opts?.percentage) {
      // "65%" — strip the trailing % only in percentage-schema fields.
      const n = Number(source);
      return Number.isFinite(n) ? n : null;
    }
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export const getTierClass = (tier: string): string => {
  const t = tier.toLowerCase();
  if (
    t.includes("diamond") ||
    t.includes("tier 1") ||
    t.includes("lock") ||
    t.includes("category 1") ||
    t.includes("holy grail") ||
    t.includes("greenlight")
  )
    return "tier-diamond";
  if (
    t.includes("fire") ||
    t.includes("solid") ||
    t.includes("tier 2") ||
    t.includes("category 2") ||
    t.includes("supreme") ||
    t.includes("premium")
  )
    return "tier-fire";
  if (
    t.includes("playable") ||
    t.includes("tier 3") ||
    t.includes("category 3") ||
    t.includes("lean") ||
    t.includes("monitor") ||
    t.includes("standard")
  )
    return "tier-solid";
  if (
    t.includes("avoid") ||
    t.includes("veto") ||
    t.includes("trap") ||
    t.includes("under") ||
    t.includes("redlight")
  )
    return "tier-avoid";
  if (t.includes("caution") || t.includes("risky") || t.includes("category 4"))
    return "tier-monitor";
  return "tier-monitor";
};

export const getTierEmoji = (tier: string): string => {
  const t = tier.toLowerCase();
  if (t.includes("diamond") || t.includes("lock") || t.includes("holy grail"))
    return "💎";
  if (t.includes("fire") || t.includes("solid") || t.includes("supreme"))
    return "🔥";
  if (t.includes("playable") || t.includes("lean")) return "📊";
  if (t.includes("avoid") || t.includes("veto") || t.includes("trap"))
    return "🛑";
  if (t.includes("monitor") || t.includes("caution")) return "👁️";
  if (t.includes("category 1") || t.includes("convergence")) return "🌌";
  return "📊";
};

export const getProbColor = (prob: number): string => {
  if (prob >= 75) return "text-accent-green";
  if (prob >= 60) return "text-accent-cyan";
  if (prob >= 45) return "text-accent-amber";
  return "text-accent-red";
};

export const getScoreBarVariant = (score: number, max = 100): string => {
  const pct = (score / max) * 100;
  if (pct >= 70) return "score-fill-green";
  if (pct >= 45) return "score-fill-indigo";
  return "score-fill-amber";
};

/** Solid dot color for a probability value — same thresholds as getProbColor. */
export const getTrafficLightDot = (prob: number): string => {
  if (prob >= 75) return "bg-accent-green";
  if (prob >= 60) return "bg-accent-cyan";
  if (prob >= 45) return "bg-accent-amber";
  return "bg-accent-red";
};

/** Ambient glow shadow matching a tier's semantic color, for hover/emphasis states. */
export const getTierGlow = (tier: string): string => {
  switch (getTierClass(tier)) {
    case "tier-diamond":
      return "shadow-glow";
    case "tier-fire":
      return "shadow-glow-amber";
    case "tier-solid":
      return "shadow-glow-green";
    case "tier-avoid":
      return "shadow-glow-red";
    default:
      return "";
  }
};

/** Solid dot color matching a tier's semantic color. */
export const getTierDotColor = (tier: string): string => {
  switch (getTierClass(tier)) {
    case "tier-diamond":
      return "bg-accent-indigo";
    case "tier-fire":
      return "bg-accent-amber";
    case "tier-solid":
      return "bg-accent-green";
    case "tier-avoid":
      return "bg-accent-red";
    default:
      return "bg-text-muted";
  }
};

export const getChemistryColor = (chemistry: string): string => {
  const c = chemistry.toLowerCase();
  if (c.includes("unavailable")) return "text-text-dim";
  if (c.includes("excellent") || c.includes("elite")) return "text-accent-green";
  if (c.includes("very strong") || c.includes("strong"))
    return "text-accent-cyan";
  if (c.includes("weak") || c.includes("very weak")) return "text-accent-red";
  return "text-accent-amber";
};

export const parseProbability = (val: string | number): number => {
  if (typeof val === "number") return val;
  return parseFloat(String(val).replace("%", "")) || 0;
};

export default api;
