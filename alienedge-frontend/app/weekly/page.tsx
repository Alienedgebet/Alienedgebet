"use client";

import { Filter, Layers, Target, ShieldCheck, Zap } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { filterApi } from "@/lib/api";
import { FilterTab } from "./FilterTab";
import { GG_FILTER_CONFIG, WIN_FILTER_CONFIG, OVER25_FILTER_CONFIG } from "./filter-config";

export default function WeeklyPage() {
  return (
    <div className="flex flex-col gap-6 p-4 md:p-8 max-w-7xl mx-auto w-full">
      
      {/* ── TOP BANNER ────────────────────────────────────────────── */}
      <div className="glass relative overflow-hidden rounded-2xl border border-cyan-500/20 bg-gradient-to-r from-[#071322] via-[#0c1f36] to-[#071322] p-5 shadow-[0_0_30px_rgba(6,182,212,0.1)]">
        <div className="flex items-center gap-3.5">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 shadow-[0_0_15px_rgba(6,182,212,0.4)]">
            <Filter className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-black uppercase tracking-wider text-white flex items-center gap-2">
              Weekly Forensic Aggregators
            </h1>
            <p className="text-xs text-cyan-200/70">
              Institutional precision filters across 7-day cross-verification, parity score gates (Safe ≥ 15), and AI council votes.
            </p>
          </div>
        </div>
      </div>

      {/* ── TABS NAVIGATION ───────────────────────────────────────── */}
      <Tabs defaultValue="gg" className="w-full">
        <TabsList className="grid grid-cols-2 md:grid-cols-4 gap-2 bg-[#090e1a]/80 p-1.5 rounded-xl border border-white/10 h-auto">
          <TabsTrigger
            value="gg"
            className="flex items-center gap-2 py-2.5 text-xs font-bold data-[state=active]:bg-gradient-to-r data-[state=active]:from-cyan-500 data-[state=active]:to-blue-600 data-[state=active]:text-white rounded-lg transition-all"
          >
            <Target className="h-3.5 w-3.5" />
            GG Precision (Parity ≤ 4)
          </TabsTrigger>

          <TabsTrigger
            value="over25"
            className="flex items-center gap-2 py-2.5 text-xs font-bold data-[state=active]:bg-gradient-to-r data-[state=active]:from-cyan-500 data-[state=active]:to-blue-600 data-[state=active]:text-white rounded-lg transition-all"
          >
            <Layers className="h-3.5 w-3.5" />
            Over 2.5 Stage 3
          </TabsTrigger>

          <TabsTrigger
            value="win"
            className="flex items-center gap-2 py-2.5 text-xs font-bold data-[state=active]:bg-gradient-to-r data-[state=active]:from-cyan-500 data-[state=active]:to-blue-600 data-[state=active]:text-white rounded-lg transition-all"
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            Win Poisson (Safe ≥ 15)
          </TabsTrigger>

          <TabsTrigger
            value="win_precision"
            className="flex items-center gap-2 py-2.5 text-xs font-bold data-[state=active]:bg-gradient-to-r data-[state=active]:from-cyan-500 data-[state=active]:to-blue-600 data-[state=active]:text-white rounded-lg transition-all"
          >
            <Zap className="h-3.5 w-3.5" />
            Win Cross-Check
          </TabsTrigger>
        </TabsList>

        {/* ── TAB 1: GG FILTER ────────────────────────────────────── */}
        <TabsContent value="gg" className="mt-6">
          <FilterTab
            config={GG_FILTER_CONFIG}
            fetchSingle={(date, params) => filterApi.getGGFilter(date, params)}
            fetchWeekly={(params) => filterApi.getGGWeekly(params)}
          />
        </TabsContent>

        {/* ── TAB 2: OVER 2.5 FILTER ──────────────────────────────── */}
        <TabsContent value="over25" className="mt-6">
          <FilterTab
            config={OVER25_FILTER_CONFIG}
            fetchSingle={(date, params) => filterApi.getOver25Filter(date, params)}
            fetchWeekly={(params) => filterApi.getOver25Weekly(params)}
          />
        </TabsContent>

        {/* ── TAB 3: WIN FILTER ───────────────────────────────────── */}
        <TabsContent value="win" className="mt-6">
          <FilterTab
            config={WIN_FILTER_CONFIG}
            fetchSingle={(date, params) => filterApi.getWinFilter(date, params)}
            fetchWeekly={(params) => filterApi.getWinWeekly(params)}
          />
        </TabsContent>

        {/* ── TAB 4: WIN PRECISION CROSS-CHECK ────────────────────── */}
        <TabsContent value="win_precision" className="mt-6">
          <FilterTab
            config={WIN_FILTER_CONFIG}
            fetchSingle={(date) => filterApi.getWinPrecision(date)}
            fetchWeekly={(params) => filterApi.getWinPrecisionWeekly(params as any)}
          />
        </TabsContent>
      </Tabs>

    </div>
  );
}