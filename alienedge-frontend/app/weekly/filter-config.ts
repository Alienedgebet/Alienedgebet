export interface FilterFieldDef {
  key: string;
  label: string;
  type: "select" | "number" | "text" | "checkbox";
  options?: { value: string; label: string }[];
  placeholder?: string;
  step?: number;
  defaultValue?: any;
}

export interface MarketFilterConfig {
  key: string;
  label: string;
  description: string;
  oddsBands: string[];
  riskOptions: { key: string; label: string; icon: string }[];
  fields: FilterFieldDef[];
  priorityKeys: string[];
}

export const GG_FILTER_CONFIG: MarketFilterConfig = {
  key: "gg",
  label: "GG / BTTS Precision Filter",
  description: "7-day cross-verification engine with total parity (<= 4), table distance, and short-term form gating.",
  oddsBands: ["1.40-1.75", "1.50-1.85", "1.80-2.20"],
  riskOptions: [
    { key: "banker", label: "Banker (Parity ≤ 4)", icon: "shield" },
    { key: "balanced", label: "Balanced", icon: "sparkles" },
    { key: "aggressive", label: "Aggressive", icon: "flame" },
  ],
  fields: [
    { key: "min_prob", label: "Min Probability %", type: "number", defaultValue: 60 },
    { key: "max_parity", label: "Max Total Parity (H2H + Concede)", type: "number", defaultValue: 4 },
    { key: "min_home_gg5", label: "Min Home GG (Last 5)", type: "number", defaultValue: 3 },
    { key: "min_away_gg5", label: "Min Away GG (Last 5)", type: "number", defaultValue: 3 },
    { key: "min_h2h_gg", label: "Min H2H GG Count", type: "number", defaultValue: 3 },
    { key: "pos_diff_max", label: "Max Table Distance", type: "number", defaultValue: 10 },
    { key: "min_gg_odds", label: "Min GG Odds", type: "number", step: 0.01, defaultValue: 1.50 },
    { key: "max_gg_odds", label: "Max GG Odds", type: "number", step: 0.01, defaultValue: 2.20 },
    { key: "strict_mode", label: "Strict Parity Lock", type: "checkbox", defaultValue: true },
  ],
  priorityKeys: [
    "match_date", "home_team", "away_team", "gg_prob_pct", "gg_odds",
    "table_distance", "tier", "verification_days", "total_parity"
  ],
};

export const OVER25_FILTER_CONFIG: MarketFilterConfig = {
  key: "over25",
  label: "Over 2.5 Goals Stage 3 Filter",
  description: "Poisson probability aggregator with AI council votes, table gap gates, and kill-switch filters.",
  oddsBands: ["1.30-1.60", "1.50-1.85", "1.80-2.20"],
  riskOptions: [
    { key: "banker", label: "Banker (Votes ≥ 7 + Gap ≤ 6)", icon: "shield" },
    { key: "balanced", label: "Balanced (Votes ≥ 6)", icon: "sparkles" },
    { key: "aggressive", label: "Aggressive Firepower", icon: "flame" },
  ],
  fields: [
    { key: "min_poisson", label: "Min Poisson Probability %", type: "number", defaultValue: 65 },
    { key: "min_votes", label: "Min Council Votes (/10)", type: "number", defaultValue: 6 },
    { key: "max_pos_gap", label: "Max Table Position Gap", type: "number", defaultValue: 6 },
    { key: "min_h2h_overs", label: "Min H2H Over 2.5 Matches", type: "number", defaultValue: 3 },
    { key: "min_odds", label: "Min Odds", type: "number", step: 0.01, defaultValue: 1.50 },
    { key: "max_odds", label: "Max Odds", type: "number", step: 0.01, defaultValue: 1.85 },
  ],
  priorityKeys: [
    "match_date", "fixture", "poisson_over_prob_num", "o25_odds",
    "council_votes", "kill_switch_pass", "pos_gap", "h2h_overs_last_5"
  ],
};

export const WIN_FILTER_CONFIG: MarketFilterConfig = {
  key: "win",
  label: "Win Poisson Precision Filter",
  description: "Cross-checks home/away venue dominance, parity score gating (Safe >= 15), and draw kill-switches.",
  oddsBands: ["1.30-1.60", "1.40-1.90", "1.80-2.40"],
  riskOptions: [
    { key: "safe", label: "Safe (Parity ≥ 15 + Form ≥ 4)", icon: "shield" },
    { key: "balanced", label: "Balanced (Parity ≥ 10)", icon: "sparkles" },
    { key: "aggressive", label: "Aggressive (Parity ≥ 5)", icon: "flame" },
  ],
  fields: [
    { key: "min_form_wins", label: "Min Form Wins (Last 5 Overall)", type: "number", defaultValue: 3 },
    { key: "min_venue_wins", label: "Min Venue Wins (Last 5 at Venue)", type: "number", defaultValue: 0 },
    { key: "min_h2h_wins", label: "Min H2H Wins", type: "number", defaultValue: 2 },
    { key: "min_opp_conceded", label: "Min Opponent Conceded (Last 5)", type: "number", defaultValue: 5 },
    { key: "min_opp_losses", label: "Min Opponent Losses", type: "number", defaultValue: 0 },
    { key: "min_parity_gap", label: "Min Parity Score", type: "number", defaultValue: 10 },
    { key: "min_odds", label: "Min Win Odds", type: "number", step: 0.01, defaultValue: 1.40 },
    { key: "max_odds", label: "Max Win Odds", type: "number", step: 0.01, defaultValue: 2.00 },
    { key: "require_no_draw", label: "Require No Draw Streak (Last 3)", type: "checkbox", defaultValue: false },
    { key: "strict_mode", label: "Strict Mode (Uncheck for Diamond-in-Rough soft mode)", type: "checkbox", defaultValue: true },
  ],
  priorityKeys: [
    "match_date", "fixture", "side", "team_name", "poisson_win_prob",
    "win_odds", "parity_score", "last_5_wins_overall", "last_5_wins_at_venue",
    "opp_last_5_conceded_raw", "opp_last_5_losses", "h2h_wins_last_5", "last_3_no_draw_BOTH"
  ],
};

export const MOCK_WEEKLY_RESULTS: Record<string, Record<string, any>[]> = {
  gg: [
    {
      fixture_id: "fx_101",
      home_team: "Napoli",
      away_team: "AS Roma",
      tier: "🔥 DIAMOND",
      gg_prob_pct: 88.4,
      gg_odds: 1.68,
      table_distance: 2,
      home_gg_last3: 3,
      away_gg_last3: 2,
      h2h_gg_count: 4,
      verification_days: 7,
      total_parity: 3,
      risk: "banker",
    },
    {
      fixture_id: "fx_102",
      home_team: "Newcastle",
      away_team: "Aston Villa",
      tier: "💎 ELITE",
      gg_prob_pct: 81.2,
      gg_odds: 1.62,
      table_distance: 3,
      home_gg_last3: 2,
      away_gg_last3: 3,
      h2h_gg_count: 3,
      verification_days: 6,
      total_parity: 4,
      risk: "balanced",
    },
    {
      fixture_id: "fx_103",
      home_team: "Marseille",
      away_team: "Lyon",
      tier: "⚡ HIGH VALUE",
      gg_prob_pct: 77.5,
      gg_odds: 1.74,
      table_distance: 4,
      home_gg_last3: 3,
      away_gg_last3: 3,
      h2h_gg_count: 5,
      verification_days: 5,
      total_parity: 2,
      risk: "aggressive",
    },
  ],
  over25: [
    {
      fixture: "Bayern Munich vs RB Leipzig",
      poisson_over_prob_num: 84.5,
      o25_odds: 1.55,
      council_votes: "9/10",
      kill_switch_pass: true,
      pos_gap: 3,
      h2h_overs_last_5: 4,
      tier: "🔥 BANKER",
      risk: "banker",
    },
    {
      fixture: "Man City vs Arsenal",
      poisson_over_prob_num: 76.8,
      o25_odds: 1.65,
      council_votes: "8/10",
      kill_switch_pass: true,
      pos_gap: 1,
      h2h_overs_last_5: 3,
      tier: "💎 BALANCED",
      risk: "balanced",
    },
    {
      fixture: "Bayer Leverkusen vs Frankfurt",
      poisson_over_prob_num: 71.0,
      o25_odds: 1.72,
      council_votes: "7/10",
      kill_switch_pass: true,
      pos_gap: 5,
      h2h_overs_last_5: 4,
      tier: "⚡ AGGRESSIVE",
      risk: "aggressive",
    },
  ],
  win: [
    {
      fixture: "Real Madrid vs Alaves",
      side: "Home",
      team_name: "Real Madrid",
      poisson_win_prob: "86.4%",
      win_odds: 1.35,
      parity_score: 18.5,
      last_5_wins_overall: 5,
      last_5_wins_at_venue: 5,
      opp_last_5_conceded_raw: 9,
      opp_last_5_losses: 4,
      h2h_wins_last_5: 4,
      last_3_no_draw_BOTH: true,
      tier: "🔥 SAFE LOCK",
      risk: "safe",
    },
    {
      fixture: "Inter Milan vs Torino",
      side: "Home",
      team_name: "Inter Milan",
      poisson_win_prob: "78.2%",
      win_odds: 1.48,
      parity_score: 12.0,
      last_5_wins_overall: 4,
      last_5_wins_at_venue: 4,
      opp_last_5_conceded_raw: 7,
      opp_last_5_losses: 3,
      h2h_wins_last_5: 3,
      last_3_no_draw_BOTH: true,
      tier: "💎 BALANCED",
      risk: "balanced",
    },
    {
      fixture: "Aston Villa vs Wolves",
      side: "Home",
      team_name: "Aston Villa",
      poisson_win_prob: "72.0%",
      win_odds: 1.82,
      parity_score: 6.5,
      last_5_wins_overall: 3,
      last_5_wins_at_venue: 3,
      opp_last_5_conceded_raw: 8,
      opp_last_5_losses: 2,
      h2h_wins_last_5: 2,
      last_3_no_draw_BOTH: false,
      tier: "⚡ AGGRESSIVE VALUE",
      risk: "aggressive",
    },
  ],
};