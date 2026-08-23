// ============================================================
// WEEKLY FILTER UI CONFIG
// Maps UI fields straight onto the ?query params each backend
// filter engine accepts (see api/main.py + lib/api.ts *FilterParams
// interfaces). All fields render regardless of `mode` — the
// backend only consumes the params relevant to whichever mode is
// selected, so there is no need to conditionally show/hide fields.
// ============================================================

export type FilterFieldType = "select" | "number" | "text" | "checkbox";

export interface FilterFieldDef {
  key: string;
  label: string;
  type: FilterFieldType;
  options?: { value: string; label: string }[];
  placeholder?: string;
  step?: number;
}

export interface MarketFilterConfig {
  key: string;
  label: string;
  fields: FilterFieldDef[];
  /** Columns DynamicTable should surface first, when present in the response. */
  priorityKeys: string[];
}

export const GG_FILTER_CONFIG: MarketFilterConfig = {
  key: "gg",
  label: "GG Filter",
  fields: [
    {
      key: "mode",
      label: "Mode",
      type: "select",
      options: [
        { value: "public", label: "Public" },
        { value: "tipster", label: "Tipster" },
        { value: "odds_band", label: "Odds Band" },
        { value: "advanced", label: "Advanced" },
      ],
    },
    { key: "risk_level", label: "Risk Level", type: "text", placeholder: "balanced / banker" },
    { key: "odds_band", label: "Odds Band", type: "text", placeholder: "e.g. 1.50-2.00" },
    { key: "min_prob", label: "Min Prob", type: "number" },
    { key: "min_home_gg5", label: "Min Home GG /5", type: "number" },
    { key: "min_away_gg5", label: "Min Away GG /5", type: "number" },
    { key: "min_home_gg3", label: "Min Home GG /3", type: "number" },
    { key: "min_away_gg3", label: "Min Away GG /3", type: "number" },
    { key: "min_h2h_gg", label: "Min H2H GG", type: "number" },
    { key: "max_parity", label: "Max Parity", type: "number" },
    { key: "min_dominance", label: "Min Dominance", type: "number" },
    { key: "max_home_missing", label: "Max Home Missing", type: "number" },
    { key: "max_away_missing", label: "Max Away Missing", type: "number" },
    { key: "min_gg_odds", label: "Min GG Odds", type: "number", step: 0.01 },
    { key: "max_gg_odds", label: "Max GG Odds", type: "number", step: 0.01 },
    { key: "strict_mode", label: "Strict Mode", type: "checkbox" },
  ],
  // Order matches Engine/gg_engine_weekly.py display_cols printout
  priorityKeys: [
    "match_date", "home_team", "away_team",
    "gg_prob_pct", "gg_odds", "dominance_score",
    "home_gg_count", "away_gg_count", "h2h_gg_count",
    "home_gg_last3", "away_gg_last3",
    "table_distance", "tier",
    "mc_btts_prob", "venue_btts_combined",
    "gg_new_score", "gg_signals_fired", "gg_new_tier",
    "home_gk_liable", "away_gk_liable",
    "home_gk_cpg", "away_gk_cpg",
    "o15_score", "o15_tier",
  ],
};

export const WIN_FILTER_CONFIG: MarketFilterConfig = {
  key: "win",
  label: "Win Filter",
  fields: [
    {
      key: "mode",
      label: "Mode",
      type: "select",
      options: [
        { value: "public", label: "Public" },
        { value: "tipster", label: "Tipster" },
        { value: "odds_band", label: "Odds Band" },
      ],
    },
    { key: "risk_level", label: "Risk Level", type: "text", placeholder: "balanced / safe" },
    { key: "odds_band", label: "Odds Band", type: "text", placeholder: "e.g. 1.50-2.00" },
    { key: "min_form_wins", label: "Min Form Wins", type: "number" },
    { key: "min_opp_conceded", label: "Min Opp Conceded", type: "number" },
    { key: "min_h2h", label: "Min H2H", type: "number" },
    { key: "require_no_draw", label: "Require No Draw", type: "checkbox" },
    { key: "min_odds", label: "Min Odds", type: "number", step: 0.01 },
    { key: "max_odds", label: "Max Odds", type: "number", step: 0.01 },
    { key: "min_overall_wins", label: "Min Overall Wins", type: "number" },
    { key: "min_venue_wins", label: "Min Venue Wins", type: "number" },
    { key: "min_h2h_wins", label: "Min H2H Wins", type: "number" },
    { key: "min_opp_losses", label: "Min Opp Losses", type: "number" },
    { key: "min_parity_gap", label: "Min Parity Gap", type: "number" },
    { key: "min_even_count", label: "Min Even Count", type: "number" },
    { key: "min_parity", label: "Min Parity", type: "number" },
    { key: "strict_mode", label: "Strict Mode", type: "checkbox" },
  ],
  // Order matches Engine/win_engine_weekly.py display_cols printout
  priorityKeys: [
    "match_date", "fixture", "side", "team_name", "win_odds",
    "last_5_wins_overall", "last_5_wins_at_venue",
    "h2h_wins_last_5", "parity_score",
    "last_3_no_draw_BOTH",
  ],
};

export const OVER25_FILTER_CONFIG: MarketFilterConfig = {
  key: "over25",
  label: "Over 2.5 Filter",
  fields: [
    {
      key: "mode",
      label: "Mode",
      type: "select",
      options: [
        { value: "public", label: "Public" },
        { value: "tipster", label: "Tipster" },
        { value: "odds_band", label: "Odds Band" },
      ],
    },
    { key: "risk_level", label: "Risk Level", type: "text", placeholder: "balanced / banker" },
    { key: "odds_band", label: "Odds Band", type: "text", placeholder: "e.g. 1.50-2.00" },
    { key: "min_poisson", label: "Min Poisson", type: "number" },
    { key: "min_votes", label: "Min Votes", type: "number" },
    { key: "max_pos_gap", label: "Max Pos Gap", type: "number" },
    { key: "min_h2h_overs", label: "Min H2H Overs", type: "number" },
    { key: "min_odds", label: "Min Odds", type: "number", step: 0.01 },
    { key: "max_odds", label: "Max Odds", type: "number", step: 0.01 },
  ],
  // Order matches Engine/over25_engine_weekly.py display_cols printout
  priorityKeys: [
    "match_date", "fixture", "poisson_over_prob_num",
    "o25_odds", "council_votes",
    "kill_switch_pass", "pos_gap", "h2h_overs_last_5",
  ],
};
