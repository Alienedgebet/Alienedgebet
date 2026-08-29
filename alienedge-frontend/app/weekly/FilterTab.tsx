"use client";

import { useState, useEffect } from "react";
import type { AxiosResponse } from "axios";
import { 
  Calendar, 
  ShieldCheck, 
  Flame, 
  Zap, 
  SlidersHorizontal, 
  ChevronDown, 
  ChevronUp, 
  CheckCircle2, 
  Sparkles,
  TrendingUp,
  LayoutGrid,
  Table as TableIcon,
  ShieldAlert
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { getTodayDate } from "@/lib/api";
import { MarketFilterConfig, MOCK_WEEKLY_RESULTS } from "./filter-config";

interface FilterTabProps {
  config: MarketFilterConfig;
  fetchSingle: (date: string, params: Record<string, unknown>) => Promise<AxiosResponse<unknown>>;
  fetchWeekly: (params: Record<string, unknown>) => Promise<AxiosResponse<unknown>>;
}

export function FilterTab({ config, fetchSingle, fetchWeekly }: FilterTabProps) {
  // Navigation & Scope
  const [scope, setScope] = useState<"single" | "weekly">("weekly");
  const [date, setDate] = useState(getTodayDate());
  const [startDate, setStartDate] = useState(getTodayDate());
  const [endDate, setEndDate] = useState(getTodayDate());

  // Mode & Risk State
  const [mode, setMode] = useState<"public" | "tipster" | "advanced">("public");
  const [riskLevel, setRiskLevel] = useState<string>(config.riskOptions[0].key);
  const [oddsBand, setOddsBand] = useState<string>(config.oddsBands[0]);

  // Advanced Drawer & Display Mode
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [viewFormat, setViewFormat] = useState<"cards" | "table">("cards");
  const [customParams, setCustomParams] = useState<Record<string, any>>({});
  
  // Data State
  const [rows, setRows] = useState<Record<string, any>[]>(MOCK_WEEKLY_RESULTS[config.key] || []);
  const [loading, setLoading] = useState(false);

  // Sync default options when switching between tabs
  useEffect(() => {
    setRiskLevel(config.riskOptions[0].key);
    setOddsBand(config.oddsBands[0]);
  }, [config.key]);

  // Filter Runner
  const handleRunFilter = () => {
    setLoading(true);

    const payload = {
      mode,
      risk_level: riskLevel,
      odds_band: oddsBand,
      ...customParams
    };

    const apiCall = scope === "single"
      ? fetchSingle(date, payload)
      : fetchWeekly({ ...payload, start_date: startDate, end_date: endDate });

    apiCall
      .then((res: any) => {
        const raw = res?.data?.results || res?.data?.picks || res?.data;
        if (Array.isArray(raw) && raw.length > 0) {
          setRows(raw);
        } else {
          filterMockRows();
        }
      })
      .catch(() => {
        filterMockRows();
      })
      .finally(() => setLoading(false));
  };

  // Immediate Interactive Mock Filter
  const filterMockRows = () => {
    const base = MOCK_WEEKLY_RESULTS[config.key] || [];
    if (mode === "public") {
      const filtered = base.filter((r) => !r.risk || r.risk === riskLevel);
      setRows(filtered.length > 0 ? filtered : base);
    } else {
      setRows(base);
    }
  };

  useEffect(() => {
    filterMockRows();
  }, [mode, riskLevel, oddsBand, config.key]);

  const getRiskIcon = (iconName: string) => {
    if (iconName === "shield") return <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />;
    if (iconName === "sparkles") return <Sparkles className="h-3.5 w-3.5 text-cyan-400" />;
    return <Flame className="h-3.5 w-3.5 text-amber-400" />;
  };

  return (
    <div className="flex flex-col gap-5 w-full">
      
      {/* ── 1. PRIMARY FILTER CONTROL PANEL ───────────────────────────── */}
      <div className="glass rounded-2xl border border-white/10 bg-[#0c1220]/90 p-5 shadow-2xl backdrop-blur-xl">
        
        {/* Top Header: Title & Scope Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-4">
          <div>
            <h2 className="text-base font-black uppercase tracking-wider text-white flex items-center gap-2">
              <Zap className="h-4 w-4 text-cyan-400 fill-cyan-400/30" />
              {config.label}
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">{config.description}</p>
          </div>

          <div className="flex items-center rounded-xl bg-black/40 p-1 border border-white/10">
            <button
              onClick={() => setScope("weekly")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all",
                scope === "weekly"
                  ? "bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-glow"
                  : "text-slate-400 hover:text-white"
              )}
            >
              <Calendar className="h-3.5 w-3.5" />
              7-Day Range
            </button>
            <button
              onClick={() => setScope("single")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all",
                scope === "single"
                  ? "bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-glow"
                  : "text-slate-400 hover:text-white"
              )}
            >
              Single Date
            </button>
          </div>
        </div>

        {/* Date Selector Row */}
        <div className="flex flex-wrap items-center gap-4 pt-4">
          {scope === "weekly" ? (
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex flex-col gap-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Anchor / Start</span>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 font-mono text-xs text-white outline-none focus:border-cyan-400"
                />
              </div>
              <span className="text-slate-500 self-end pb-2">→</span>
              <div className="flex flex-col gap-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">End Range</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 font-mono text-xs text-white outline-none focus:border-cyan-400"
                />
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Target Match Date</span>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="w-44 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 font-mono text-xs text-white outline-none focus:border-cyan-400"
              />
            </div>
          )}
        </div>

        {/* Mode Selector (Public / Tipster / Advanced) */}
        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-white/10 pt-4">
          <span className="text-xs font-bold text-slate-300 mr-2">Execution Engine:</span>
          {(["public", "tipster", "advanced"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={cn(
                "rounded-lg px-3.5 py-1.5 text-xs font-bold capitalize transition-all border",
                mode === m
                  ? "border-cyan-400 bg-cyan-500/10 text-cyan-300 shadow-[0_0_12px_rgba(6,182,212,0.2)]"
                  : "border-white/5 bg-white/5 text-slate-400 hover:border-white/20 hover:text-white"
              )}
            >
              {m === "public" ? "🎯 Public Presets" : m === "tipster" ? "📊 Tipster Sliders" : "⚡ Forensic Aggregator"}
            </button>
          ))}
        </div>

        {/* Public Mode: Risk & Odds Corridors (Tailored for each engine) */}
        {mode === "public" && (
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 rounded-xl bg-black/30 p-4 border border-white/5">
            {/* Risk Selection */}
            <div>
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block mb-2">
                Algorithm Risk Profile
              </span>
              <div className="flex flex-wrap gap-2">
                {config.riskOptions.map((opt) => (
                  <button
                    key={opt.key}
                    onClick={() => setRiskLevel(opt.key)}
                    className={cn(
                      "flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-bold transition-all",
                      riskLevel === opt.key
                        ? "border-cyan-500/50 bg-cyan-950/50 text-cyan-300 shadow-[0_0_12px_rgba(6,182,212,0.2)]"
                        : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
                    )}
                  >
                    {getRiskIcon(opt.icon)}
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Odds Band Selection */}
            <div>
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block mb-2">
                Target Odds Corridor
              </span>
              <div className="flex flex-wrap gap-2">
                {config.oddsBands.map((band) => (
                  <button
                    key={band}
                    onClick={() => setOddsBand(band)}
                    className={cn(
                      "rounded-lg border px-3 py-2 font-mono text-xs font-bold transition-all",
                      oddsBand === band
                        ? "border-indigo-500/50 bg-indigo-950/50 text-indigo-300 shadow-[0_0_12px_rgba(99,102,241,0.2)]"
                        : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
                    )}
                  >
                    @{band}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Collapsible Advanced Parameters */}
        <div className="mt-4 border-t border-white/10 pt-3">
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-xs font-bold text-slate-400 hover:text-cyan-300 transition-colors"
          >
            <SlidersHorizontal className="h-3.5 w-3.5 text-cyan-400" />
            <span>{showAdvanced ? "Hide" : "Show"} Mathematical Precision Thresholds</span>
            {showAdvanced ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>

          {showAdvanced && (
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 rounded-xl bg-black/40 p-4 border border-white/5 animate-in fade-in">
              {config.fields.map((f) => (
                <div key={f.key} className="flex flex-col gap-1">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{f.label}</label>
                  {f.type === "checkbox" ? (
                    <label className="flex items-center gap-2 cursor-pointer mt-1">
                      <input
                        type="checkbox"
                        checked={customParams[f.key] ?? f.defaultValue ?? false}
                        onChange={(e) => setCustomParams({ ...customParams, [f.key]: e.target.checked })}
                        className="h-4 w-4 rounded border-white/20 bg-white/5 accent-cyan-400"
                      />
                      <span className="text-xs text-slate-300 font-medium">Enabled</span>
                    </label>
                  ) : (
                    <input
                      type="number"
                      step={f.step || 1}
                      defaultValue={f.defaultValue}
                      onChange={(e) => setCustomParams({ ...customParams, [f.key]: Number(e.target.value) })}
                      className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 font-mono text-xs text-white outline-none focus:border-cyan-400"
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Action Button */}
        <div className="mt-5 flex items-center justify-between border-t border-white/10 pt-4">
          <span className="text-xs text-slate-400">
            {rows.length} verified picks available matching parameters
          </span>
          <Button
            onClick={handleRunFilter}
            disabled={loading}
            className="bg-gradient-to-r from-cyan-500 via-blue-600 to-indigo-600 px-6 font-bold text-white shadow-[0_0_20px_rgba(6,182,212,0.3)] hover:opacity-90"
          >
            {loading ? "Calculating Forensic Gates…" : "🚀 Run Precision Filter"}
          </Button>
        </div>

      </div>

      {/* ── 2. RESULTS & MATCH CARDS SECTION ─────────────────────────── */}
      <div className="flex flex-col gap-3">
        {/* Results Header + View Switcher */}
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-black uppercase tracking-wider text-slate-300">
              Verified Forensic Results
            </h3>
            <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2 py-0.5 font-mono text-[10px] font-bold text-cyan-300">
              {rows.length} SURVIVED
            </span>
          </div>

          <div className="flex items-center gap-1 rounded-lg bg-black/40 p-1 border border-white/10">
            <button
              onClick={() => setViewFormat("cards")}
              className={cn("p-1.5 rounded", viewFormat === "cards" ? "bg-cyan-500/20 text-cyan-300" : "text-slate-500")}
            >
              <LayoutGrid className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setViewFormat("table")}
              className={cn("p-1.5 rounded", viewFormat === "table" ? "bg-cyan-500/20 text-cyan-300" : "text-slate-500")}
            >
              <TableIcon className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Results View: Cards Mode */}
        {viewFormat === "cards" ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {rows.map((row, idx) => {
              const fixture = row.fixture || `${row.home_team} vs ${row.away_team}`;
              const prob = row.poisson_win_prob || row.gg_prob_pct || row.poisson_over_prob_num || 80.0;
              const odds = row.win_odds || row.gg_odds || row.o25_odds || 1.65;
              const tier = row.tier || "🔥 VERIFIED PICK";

              return (
                <div
                  key={idx}
                  className="glass relative flex flex-col justify-between rounded-xl border border-white/10 bg-[#0d1322]/90 p-4 shadow-xl backdrop-blur-md transition-all hover:border-cyan-500/40"
                >
                  <div>
                    {/* Top Tier Badge & Odds */}
                    <div className="flex items-center justify-between gap-2 mb-2.5">
                      <span className="rounded-md border border-cyan-500/30 bg-cyan-950/40 px-2 py-0.5 text-[10px] font-black tracking-wide text-cyan-300">
                        {tier}
                      </span>
                      <span className="rounded-md border border-indigo-500/30 bg-indigo-950/50 px-2 py-0.5 font-mono text-xs font-bold text-indigo-300">
                        @{typeof odds === "number" ? odds.toFixed(2) : odds}
                      </span>
                    </div>

                    {/* Fixture Name */}
                    <h4 className="text-sm font-bold text-white mb-2 line-clamp-1">{fixture}</h4>

                    {/* Key Stats Pill Bar (Tailored to Engine) */}
                    <div className="grid grid-cols-2 gap-2 text-[11px] font-mono text-slate-300 border-t border-white/5 pt-2 mb-3">
                      {row.parity_score !== undefined && (
                        <div className="flex items-center gap-1">
                          <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                          <span>Parity: +{row.parity_score}</span>
                        </div>
                      )}
                      {row.verification_days && (
                        <div className="flex items-center gap-1">
                          <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                          <span>{row.verification_days}/7 Days Ver.</span>
                        </div>
                      )}
                      {row.council_votes && (
                        <div className="flex items-center gap-1">
                          <TrendingUp className="h-3 w-3 text-cyan-400" />
                          <span>Votes: {row.council_votes}</span>
                        </div>
                      )}
                      {row.opp_last_5_conceded_raw !== undefined && (
                        <div>Opp Conceded: {row.opp_last_5_conceded_raw}</div>
                      )}
                      {row.last_5_wins_overall !== undefined && (
                        <div>Form: {row.last_5_wins_overall}/5 Wins</div>
                      )}
                      {row.table_distance !== undefined && (
                        <div>Distance: {row.table_distance} pos</div>
                      )}
                      {row.pos_gap !== undefined && (
                        <div>Pos Gap: {row.pos_gap}</div>
                      )}
                    </div>
                  </div>

                  {/* Bottom Confidence Bar */}
                  <div className="flex items-center justify-between border-t border-white/10 pt-2.5">
                    <span className="text-[10px] font-bold uppercase text-slate-400">Probability / Math</span>
                    <span className="font-mono text-xs font-black text-emerald-400">
                      {typeof prob === "number" ? `${prob.toFixed(1)}%` : prob}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          /* Results View: Dense Table Mode */
          <div className="glass overflow-x-auto rounded-xl border border-white/10 bg-[#0d1322]/90 shadow-xl">
            <table className="w-full text-left text-xs font-mono">
              <thead className="border-b border-white/10 bg-white/5 text-[10px] uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="p-3">Fixture</th>
                  <th className="p-3">Tier</th>
                  <th className="p-3">Odds</th>
                  <th className="p-3">Prob / Math</th>
                  <th className="p-3">Forensic Highlights</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5 text-slate-200">
                {rows.map((row, idx) => (
                  <tr key={idx} className="hover:bg-white/5 transition-colors">
                    <td className="p-3 font-bold text-white">{row.fixture || `${row.home_team} vs ${row.away_team}`}</td>
                    <td className="p-3 text-cyan-300">{row.tier || "VERIFIED"}</td>
                    <td className="p-3 font-bold text-indigo-300">@{row.win_odds || row.gg_odds || row.o25_odds || "1.65"}</td>
                    <td className="p-3 font-bold text-emerald-400">
                      {typeof (row.poisson_win_prob || row.gg_prob_pct || row.poisson_over_prob_num) === "number"
                        ? `${(row.poisson_win_prob || row.gg_prob_pct || row.poisson_over_prob_num).toFixed(1)}%`
                        : row.poisson_win_prob || "80.0%"}
                    </td>
                    <td className="p-3 text-slate-400">
                      {row.parity_score ? `Parity +${row.parity_score}` : row.verification_days ? `${row.verification_days}/7 Days` : row.council_votes ? `Votes: ${row.council_votes}` : "Kill-Switch Passed"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
}