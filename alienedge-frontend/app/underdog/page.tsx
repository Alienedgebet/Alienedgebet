"use client";

import { useMemo } from "react";
import { Swords } from "lucide-react";
import {
  underdogApi,
  type UnderdogApexPick,
  type UnderdogMasterPick,
  type UnderdogBasePick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_UD_APEX, MOCK_UD_AUDIT, MOCK_UD_BASE } from "@/lib/mock-chains";

const apexColumns: PredictionColumn<UnderdogApexPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.Fixture}</span>,
  },
  { key: "rank", header: "Rank", render: (r) => <TierBadge tier={r.Rank} /> },
  {
    key: "prob",
    header: "Monte UD %",
    render: (r) => <ProbCell value={r.Monte_UD_Prob} showBar={false} />,
  },
  { key: "engine", header: "Engine", render: (r) => r.Engine },
  { key: "handshake", header: "Handshake", render: (r) => r.Handshake },
  { key: "dna", header: "DNA", render: (r) => r.DNA },
  { key: "rule", header: "Rule", render: (r) => r.Rule },
  { key: "vuln", header: "Fav Vulnerability", render: (r) => r.Fav_Vuln },
  { key: "sh_gg", header: "SH GG Label", render: (r) => r.SH_GG_Label },
];

const auditColumns: PredictionColumn<UnderdogMasterPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "underdog", header: "Underdog", render: (r) => r.underdog_team },
  {
    key: "audit_prob",
    header: "Audit Real Prob",
    render: (r) => <ProbCell value={r.Audit_Real_Prob} showBar={false} />,
  },
  {
    key: "dog_score",
    header: "Dog Score Prob",
    render: (r) => <ProbCell value={r.Dog_Score_Prob} showBar={false} />,
  },
  { key: "fav_spear", header: "Fav Spear Power", render: (r) => r.Fav_Spear_Power },
  { key: "dominance", header: "Dominance Gap", align: "right", render: (r) => r.Dominance_Gap },
  { key: "verdict", header: "Audit Verdict", render: (r) => <TierBadge tier={r.Audit_Verdict} /> },
  {
    key: "flags",
    header: "Flags",
    render: (r) => (
      <div className="flex flex-wrap gap-1 text-2xs">
        {r.dog_is_hot && <span className="text-accent-amber">Hot</span>}
        {r.dog_due_goal && <span className="text-accent-cyan">Due</span>}
      </div>
    ),
  },
];

const baseColumns: PredictionColumn<UnderdogBasePick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "league", header: "League", render: (r) => r.league },
  { key: "underdog", header: "Underdog", render: (r) => r.underdog_team },
  {
    key: "score_prob",
    header: "Dog Score Prob",
    render: (r) => <ProbCell value={r.dog_score_prob} showBar={false} />,
  },
  { key: "odds", header: "Dog Odds", align: "right", render: (r) => r.dog_odds.toFixed(2) },
  { key: "parity", header: "Parity Gap", align: "right", render: (r) => r.parity_gap },
  { key: "att", header: "Dog Att Strength", align: "right", render: (r) => r.dog_att_strength },
  { key: "def", header: "Fav Def Weakness", align: "right", render: (r) => r.fav_def_weakness },
  {
    key: "flags",
    header: "Flags",
    render: (r) => (
      <div className="flex flex-wrap gap-1 text-2xs">
        {r.dog_is_hot && <span className="text-accent-amber">Hot</span>}
        {r.dog_due_goal && <span className="text-accent-cyan">Due</span>}
        {r.both_no_draw_3 && <span className="text-accent-green">No-Draw-3</span>}
      </div>
    ),
  },
];

export default function UnderdogPage() {
  const { date } = useSelectedDate();

  // 1. Apex (Verify -> Rest)
  const apexColumnsWithVerify = useMemo(
    () => [createVerifyColumn<UnderdogApexPick>(), ...apexColumns],
    []
  );

  // 2. Audit (Verify -> Rest)
  const auditColumnsWithVerify = useMemo(
    () => [createVerifyColumn<UnderdogMasterPick>(), ...auditColumns],
    []
  );

  // 3. Base (Verify -> Rest)
  const baseColumnsWithVerify = useMemo(
    () => [createVerifyColumn<UnderdogBasePick>(), ...baseColumns],
    []
  );

  return (
    <div
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-red/30 bg-accent-red/10 shadow-[0_0_12px_rgba(244,63,94,0.2)]">
            <Swords className="h-4 w-4 text-accent-red" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Underdog to Score Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Full 3-stage U2S engine — Apex picks, master audit &amp; foundation base
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. STAGE 1: Underdog Apex ────────────────────────────────── */}
      <div>
        <ChainStage
          title="Underdog Apex — Final Aggregator"
          description="Elite output"
          fetcher={() => underdogApi.getApex(date)}
          deps={[date]}
          columns={apexColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No apex picks for this date."
          fallbackData={MOCK_UD_APEX}
        />
      </div>

      {/* ── 4. STAGE 2: Underdog Master Audit ────────────────────────── */}
      <div>
        <ChainStage
          title="Underdog Master Audit"
          description="Audit layer"
          fetcher={() => underdogApi.getAudit(date)}
          deps={[date]}
          columns={auditColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No audit picks for this date."
          fallbackData={MOCK_UD_AUDIT}
        />
      </div>

      {/* ── 5. STAGE 3: Underdog Base Engine ─────────────────────────── */}
      <div>
        <ChainStage
          title="Underdog Base Engine"
          description="Foundation base"
          fetcher={() => underdogApi.getBase(date)}
          deps={[date]}
          columns={baseColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No base picks for this date."
          fallbackData={MOCK_UD_BASE}
        />
      </div>
    </div>
  );
}
