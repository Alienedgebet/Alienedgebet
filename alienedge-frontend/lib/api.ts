import axios, { AxiosInstance, AxiosResponse } from "axios";

// ============================================================
// ALIENEDGE API CLIENT
// Synced to api/main.py — backend is source of truth
// ============================================================

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  // 800ms — fail fast when API is off so market pages paint mocks quickly
  // instead of stacking multi-second waits across 5–7 parallel stage calls.
  timeout: 800,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    console.error("[AlienEdge API]", err?.response?.data || err.message);
    return Promise.reject(err);
  }
);

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
  Market_Power_Scores: {
    Corner_Power: number;
    Goal_Intent: number;
    BTTS_Friction: number;
    Win_Dominance: number;
    Box_Dominance: number;
  };
  Tactical_DNA: {
    Tempo: number;
    Line_Height: string;
    Risk_Appetite: string;
    Verticality: string;
    Shot_Quality: string;
    Transition_Style: string;
    Transition_Score: number;
  };
  Raw_Audit_Metrics: {
    Avg_Corners: number;
    Estimated_Crosses: number;
    Estimated_Blocks: number;
    Dangerous_Attacks: number;
    Passing_Control: number;
    Big_Chances_Created: number;
    Shots_Insidebox: number;
    Shots_Outsidebox: number;
    Inside_Shot_Ratio_Pct: number;
    Tackles_Avg: number;
    Interceptions_Avg: number;
    Own_Pass_Quality_Pct: number;
    Opp_Pass_Acc_Allowed: number;
    Opp_Dangerous_Attacks: number;
    Resistance_Score: number;
  };
}

export interface DnaV2PillarClash {
  home_score: number;
  away_score: number;
  difference: number;
  edge: string;
  margin: "Clear" | "Tight";
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
  combined_box_dominance: number;
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
  home_value: number;
  away_value: number;
  winner: "home" | "away" | "neutral";
}

export interface DnaV2MarketCount {
  home_count: number;
  away_count: number;
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

export interface UnderdogBasePick {
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

export interface UnderdogMasterPick {
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

export interface UnderdogApexPick {
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
export interface GGPrecisionPick {
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
  home_gk_cpg: number;
  away_gk_cpg: number;
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
export interface GGO15Pick {
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

export interface GGForensicPick {
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

export interface GGPsychologyPick {
  Fixture: string;
  MC_Rank: string;
  MC_Prob: string;
  Psych_Score: number;
  Spears: string;
  Tier: string;
  Psych_Triggers: string;
}

export interface GGSupremePick {
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

export interface GGCrossVerifyPick {
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
export interface WinForecastPick {
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

export interface WinU2SPick {
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

export interface WinPsychologyPick {
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

export interface WinApexPick {
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

export interface WinRawPick {
  fixture_id: string;
  fixture: string;
  side: string;
  team_name: string;
  win_odds: number;
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
export interface Over25Stage1Pick {
  id: string;
  fixture: string;
  Time: string;
  Odds: number;
  Confidence: string;
  Algorithm: string;
}

export interface Over25Stage2Pick {
  id: string;
  fixture: string;
  Time: string;
  Votes: number;
  Odds: number;
  Algorithm: string;
  Reasons: string;
}

export interface Over25Stage3Pick {
  Match: string;
  Odds: number;
  "Poisson%": number;
  Grade: string;
  GradeNum: number;
  H2H_Record: string;
  PickedBy: string;
  Failures: string;
}

export interface Over25PsychologyPick {
  Fixture: string;
  Base_Poisson: string;
  Base_Grade: string;
  Score: number;
  Tier: string;
  Reasons: string;
}

export interface Over25GoldPick {
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

export interface Over25ApexPick {
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

export interface Over25ForecastPick {
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
export interface Over15Stage3Pick {
  Match: string;
  Odds: number;
  "Poisson%": number;
  Grade: string;
  GradeNum: number;
  H2H_Record: string;
  PickedBy: string;
  Failures: string;
}

export interface Over15PsychologyPick {
  Fixture: string;
  Base_Poisson: string;
  Base_Grade: string;
  Score: number;
  Tier: string;
  Reasons: string;
}

export interface Over15ApexPick {
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
export interface CornerStage1Pick {
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
}

export interface CornerStage2Pick {
  fixture_id: string;
  fixture: string;
  stage1_predicted_corners: number;
  stage2_predicted_corners: number;
  expected_total_corners: number;
  corner_tier: string;
  style_alignment: string;
  expected_difference: number;
  avg_confidence: number;
  home_is_persistent_venue: boolean;
  away_is_persistent_venue: boolean;
  home_is_persistent_overall: boolean;
  away_is_persistent_overall: boolean;
}

export interface CornerPsychologyPick {
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
}

export interface CornerCatalystPick {
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
}

export interface CornerAggregatorPick {
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
}

// ============================================================
// SPECIALS TYPES
// ============================================================
export interface DrawPick {
  fixture_id: string;
  fixture: string;
  home_team: string;
  away_team: string;
  tier: string;
  section: string;
  composite_draw_score: number;
  mc_draw_prob: number;
  poisson_draw_prob: number;
  dmi: number;
  parity: number;
  draw_odds: number;
  value_edge: number;
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

export interface UndersPick {
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
  home_gk_cpg: number;
  away_gk_cpg: number;
  home_gk_note: string;
  away_gk_note: string;
  fatigue_home: number;
  fatigue_away: number;
}

export interface UndersResponse {
  u25: UndersPick[];
  u35: UndersPick[];
}

export interface SOTPick {
  Fixture: string;
  Verdict: string;
  Proj_SOT: number;
  "Poisson_Over_8.5": string;
  Consistency: string;
  Game_Script: string;
  Momentum: string;
  "1x2_Home_Odd": number | string;
}

export interface FHVIPick {
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

export interface SHVIPick {
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

export interface SHMasterPick {
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

export interface SH8GoalPick {
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
  home: LivePrematchTeamAudit;
  away: LivePrematchTeamAudit;
  picks: Array<string | { type: string; target_loc?: string }>;
  killer_rules: string[];
  combined_miss: number;
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

/** Stage 2 VALIDATION BOARD match — mirrors print_cycle_board cycle_log entry. */
export interface LiveValidationMatch {
  name: string;
  minute: number;
  id: string;
  score: string;
  lines: string[];
}

/** Stage 2 full board: tracks stage 1 picks through triple-phase audit. */
export interface LiveValidationBoard {
  cycle: number;
  total_live: number;
  total_tracked: number;
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
}

export interface LiveDangerReport {
  fixture: string;
  fixture_id: string;
  home_team: {
    team_name: string;
    id: number;
    breach: boolean;
    danger_level: string;
    vulnerability_pct: number;
    gk_leak: number;
    missing_details: Array<{ name: string; pos: string }>;
    formation: string;
    style: { label: string; score: number; da: number };
  };
  away_team: {
    team_name: string;
    id: number;
    breach: boolean;
    danger_level: string;
    vulnerability_pct: number;
    gk_leak: number;
    missing_details: Array<{ name: string; pos: string }>;
    formation: string;
    style: { label: string; score: number; da: number };
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
}

export interface LiveAggregatorReport {
  fixture: string;
  fixture_id: string;
  incoming_probabilities: Record<string, unknown>[];
  danger_report: {
    home: { status: string; sync: string; breach: boolean };
    away: { status: string; sync: string; breach: boolean };
  };
  match_chemistry_list: Record<string, string>;
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
  };
  away?: {
    live_xg?: number;
    sot?: number;
    da?: number;
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
  /** VALID_30 | SUPREME_45 | null */
  validation?: string | null;
  /** Settled markets e.g. ["GG","O2.5"] */
  settled?: string[];
}

export interface LiveOrchestratorBoard {
  session: string;
  cycle: number;
  total_live: number;
  total_db: number;
  matches: LiveOrchestratorMatch[];
}

// ============================================================
// USER-DEFINED LIVE ALERT RULES (Code 6 flexibility filter)
// ============================================================
export type PrematchFlagKey =
  | "both_2h_goal_100_percent"
  | "home_h2h_win_100"
  | "away_h2h_win_100"
  | "h2h_gg_100"
  | "h2h_o25_100";

export type PrematchRateMetric = "home_2h_rate" | "away_2h_rate";

export type UserRulePrematch =
  | { type: "none" }
  | { type: "flag"; flag: PrematchFlagKey }
  | { type: "rate"; metric: PrematchRateMetric; min_value: number };

export type UserRuleLive =
  | { type: "snapshot" }
  | { type: "pressure_share"; side: "home" | "away" | "any"; min_value: number }
  | { type: "chaos_index"; min_value: number };

export interface UserRuleDef {
  rule_id: string;
  user_id: string;
  label: string;
  prematch: UserRulePrematch;
  live: UserRuleLive;
  active: boolean;
  created_at?: string;
}

export type UserRuleCreate = Omit<UserRuleDef, "rule_id" | "created_at">;
export type UserRulePatch = Partial<Pick<UserRuleDef, "label" | "prematch" | "live" | "active">>;

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
  mode?: "public" | "tipster" | "odds_band";
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
  mode?: "public" | "tipster" | "odds_band";
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

export interface WinPrecisionWeeklyParams {
  start_date?: string;
  end_date?: string;
  anchor_date?: string;
}

export interface PipelineResponse {
  date: string;
  phases_run: string[];
  results: Record<string, unknown>;
  errors: Record<string, string>;
}

// ============================================================
// API ENDPOINT GROUPS — paths match api/main.py exactly
// ============================================================

export const healthApi = {
  check: (): Promise<AxiosResponse<HealthResponse>> => api.get("/health"),
};

export const foundationApi = {
  getDNA: (date: string): Promise<AxiosResponse<DnaProfile[]>> =>
    api.get(`/api/dna/${date}`),

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
    api.get(`/api/dna/v2/${date}`),

  // Disk-only fast read — no engine recompute. Preferred for fixture-list
  // DNA counts and for the DNA Analysis page so opening it feels instant.
  getLatest: (): Promise<AxiosResponse<DnaV2Response>> =>
    api.get(`/api/dna/v2/latest`),
};

export const underdogApi = {
  getBase: (date: string): Promise<AxiosResponse<UnderdogBasePick[]>> =>
    api.get(`/api/underdog/${date}`),

  getAudit: (date: string): Promise<AxiosResponse<UnderdogMasterPick[]>> =>
    api.get(`/api/underdog/audit/${date}`),

  getApex: (date: string): Promise<AxiosResponse<UnderdogApexPick[]>> =>
    api.get(`/api/underdog/apex/${date}`),
};

export const ggApi = {
  getPrecision: (date: string): Promise<AxiosResponse<GGPrecisionResponse>> =>
    api.get(`/api/gg/precision/${date}`),

  getForensics: (date: string): Promise<AxiosResponse<GGForensicPick[]>> =>
    api.get(`/api/gg/forensics/${date}`),

  getPsychology: (date: string): Promise<AxiosResponse<GGPsychologyPick[]>> =>
    api.get(`/api/gg/psychology/${date}`),

  getSupreme: (date: string): Promise<AxiosResponse<GGSupremePick[]>> =>
    api.get(`/api/gg/supreme/${date}`),

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
    api.get(`/api/win/apex/${date}`),

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
    api.get(`/api/over25/apex/${date}`),

  getForecast: (date: string): Promise<AxiosResponse<Over25ForecastPick[]>> =>
    api.get(`/api/over25/forecast/${date}`),
};

export const over15Api = {
  getStage3: (date: string): Promise<AxiosResponse<Over15Stage3Pick[]>> =>
    api.get(`/api/over15/stage3/${date}`),

  getPsychology: (date: string): Promise<AxiosResponse<Over15PsychologyPick[]>> =>
    api.get(`/api/over15/psychology/${date}`),

  getApex: (date: string): Promise<AxiosResponse<Over15ApexPick[]>> =>
    api.get(`/api/over15/apex/${date}`),
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
    api.get(`/api/corners/aggregator/${date}`),
};

export const specialsApi = {
  getUnders: (date: string): Promise<AxiosResponse<UndersResponse>> =>
    api.get(`/api/unders/${date}`),

  getDraw: (date: string): Promise<AxiosResponse<DrawResponse>> =>
    api.get(`/api/draw/${date}`),

  getSOT: (date: string): Promise<AxiosResponse<SOTPick[]>> =>
    api.get(`/api/sot/${date}`),

  getFHVI: (date: string): Promise<AxiosResponse<FHVIPick[]>> =>
    api.get(`/api/fhvi/${date}`),

  getSHVI: (date: string): Promise<AxiosResponse<SHVIPick[]>> =>
    api.get(`/api/shvi/${date}`),
};

export const shMasterApi = {
  getSHGGWinner: (date: string): Promise<AxiosResponse<SHGGWinnerPick[]>> =>
    api.get(`/api/sh-gg-winner/${date}`),

  getSHMaster: (date: string): Promise<AxiosResponse<SHMasterPick[]>> =>
    api.get(`/api/sh-master/${date}`),

  getSH8Goal: (date: string): Promise<AxiosResponse<SH8GoalPick[]>> =>
    api.get(`/api/sh-8goal/${date}`),
};

export const liveApi = {
  /** Stage 1 rich strategic audit board. */
  getPrematch: (): Promise<AxiosResponse<LivePrematchAudit[]>> =>
    api.get("/api/live/prematch"),

  /** Stage 2 — validates stage 1 prematch feed (validated_picks.json). */
  getValidation: (): Promise<AxiosResponse<LiveValidationBoard>> =>
    api.get("/api/live/validation"),

  getIncoming: (): Promise<AxiosResponse<LiveIncomingPick[]>> =>
    api.get("/api/live/incoming"),

  getDanger: (): Promise<AxiosResponse<LiveDangerReport[]>> =>
    api.get("/api/live/danger"),

  getAggregator: (): Promise<AxiosResponse<LiveAggregatorReport[]>> =>
    api.get("/api/live/aggregator"),

  /** Stage 6 — last VIP + LIVE orchestrator board. */
  getOrchestrator: (): Promise<AxiosResponse<LiveOrchestratorBoard>> =>
    api.get("/api/live/orchestrator"),

  /** Stage 6 — VIP + free LIVE alerts (ready_to_push / session logs). */
  getAlerts: (): Promise<AxiosResponse<LiveAlertPick[]>> =>
    api.get("/api/live/alerts"),

  getDashboard: (): Promise<AxiosResponse<LiveDashboardResult[]>> =>
    api.get("/api/live/dashboard"),
};

export const userRulesApi = {
  list: (userId: string): Promise<AxiosResponse<UserRuleDef[]>> =>
    api.get("/api/live/user-rules", { params: { user_id: userId } }),

  create: (rule: UserRuleCreate): Promise<AxiosResponse<UserRuleDef>> =>
    api.post("/api/live/user-rules", rule),

  update: (ruleId: string, patch: UserRulePatch): Promise<AxiosResponse<UserRuleDef>> =>
    api.patch(`/api/live/user-rules/${ruleId}`, patch),

  remove: (ruleId: string, userId: string): Promise<AxiosResponse<void>> =>
    api.delete(`/api/live/user-rules/${ruleId}`, { params: { user_id: userId } }),

  /** Alerts fired specifically from this user's own saved rules. */
  getMyAlerts: (userId: string): Promise<AxiosResponse<LiveAlertPick[]>> =>
    api.get("/api/live/alerts/mine", { params: { user_id: userId } }),
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

  getWinPrecision: (date: string) =>
    api.get(`/api/filter/win/precision/${date}`),

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