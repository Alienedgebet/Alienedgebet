"use client";

import { Swords } from "lucide-react";
import {
  underdogApi,
  type UnderdogApexPick,
  type UnderdogMasterPick,
  type UnderdogBasePick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
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
  { key: "odds", header: "Dog Odds", align: "right", render: (r) => r.dog_odds.toFixed(2) },
  {
    key: "score_prob",
    header: "Dog Score Prob",
    render: (r) => <ProbCell value={r.dog_score_prob} showBar={false} />,
  },
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

  return (
    <div
      className="flex flex-col gap-4 p-6"
    >
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-red/15">
          <Swords className="h-5 w-5 text-accent-red" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Underdog to Score Intelligence</h1>
          <p className="text-xs text-text-secondary">
            Full engine chain, every stage visible — apex aggregation up top, the master audit
            layer, and the foundation base underneath it.
          </p>
        </div>
      </div>

      <div>
        <ChainStage
          title="Underdog Apex — Final Aggregator"
          description="Elite output"
          fetcher={() => underdogApi.getApex(date)}
          deps={[date]}
          columns={apexColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No apex picks for this date."
          fallbackData={MOCK_UD_APEX}
        />
      </div>

      <div>
        <ChainStage
          title="Underdog Master Audit"
          description="Audit layer"
          fetcher={() => underdogApi.getAudit(date)}
          deps={[date]}
          columns={auditColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No audit picks for this date."
          fallbackData={MOCK_UD_AUDIT}
        />
      </div>

      <div>
        <ChainStage
          title="Underdog Base Engine"
          description="Foundation base"
          fetcher={() => underdogApi.getBase(date)}
          deps={[date]}
          columns={baseColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No base picks for this date."
          fallbackData={MOCK_UD_BASE}
        />
      </div>
    </div>
  );
}
