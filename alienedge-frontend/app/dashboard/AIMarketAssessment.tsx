"use client";

import { useState } from "react";
import { ChevronDown, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface AssessmentSegment {
  text: string;
  stat?: boolean;
}

interface AggregatorAssessment {
  id: string;
  aggregator: string;
  market: string;
  segments: AssessmentSegment[];
}

/**
 * Sample analytical briefings — illustrative narrative copy, not live
 * engine output. Aggregator names mirror the real chains in main.py
 * (win_apex_aggregator, gg_forensic_aggregator, over25 killswitch stage,
 * corner_catalyst, over15_apex, apex_ud_aggregator) so the section reads
 * true to the pipeline even while the copy itself is placeholder text.
 */
const ASSESSMENTS: AggregatorAssessment[] = [
  {
    id: "win-apex",
    aggregator: "Win Apex Aggregator",
    market: "Win",
    segments: [
      { text: "The Super-Matrix detected extreme parity gaps in Serie A. The Win Apex Aggregator has locked " },
      { text: "2 fixtures", stat: true },
      { text: " with " },
      { text: ">82%", stat: true },
      { text: " Poisson probability based on severe Away GK vulnerabilities." },
    ],
  },
  {
    id: "gg-forensics",
    aggregator: "GG Forensics Audit",
    market: "GG / BTTS",
    segments: [
      { text: "Forensic cross-check flagged " },
      { text: "3 fixtures", stat: true },
      { text: " in the Bundesliga where combined H2H BTTS rate exceeds " },
      { text: "78%", stat: true },
      { text: " and both keepers carry elevated CPG liability." },
    ],
  },
  {
    id: "over25-killswitch",
    aggregator: "Over 2.5 Killswitch",
    market: "Over 2.5",
    segments: [
      { text: "Kill-switch audit rejected " },
      { text: "5 fixtures", stat: true },
      { text: " on council-vote failure, retaining " },
      { text: "4 fixtures", stat: true },
      { text: " with a combined goals-scored delta above " },
      { text: "1.8", stat: true },
      { text: " across the last 5 matches." },
    ],
  },
  {
    id: "corner-catalyst",
    aggregator: "Corner Catalyst",
    market: "Corners",
    segments: [
      { text: "Wounded-beast tactical read isolated " },
      { text: "2 fixtures", stat: true },
      { text: " where the away side sits " },
      { text: "6+ positions", stat: true },
      { text: " below its home rival, projecting a corner tier beyond " },
      { text: "11.5", stat: true },
      { text: " expected corners." },
    ],
  },
  {
    id: "over15-apex",
    aggregator: "Over 1.5 Apex",
    market: "Over 1.5",
    segments: [
      { text: "Apex aggregation confirms " },
      { text: "6 fixtures", stat: true },
      { text: " carrying a base Poisson grade above " },
      { text: "85%", stat: true },
      { text: ", each cross-verified against the unified GG/O1.5 head engine." },
    ],
  },
  {
    id: "underdog-apex",
    aggregator: "Underdog Apex Aggregator",
    market: "Underdog to Score",
    segments: [
      { text: "Handshake audit isolated " },
      { text: "1 fixture", stat: true },
      { text: " at Rank 1 where dominance gap and DNA profile agree — favorite vulnerability sits at " },
      { text: "74%", stat: true },
      { text: "." },
    ],
  },
];

const INITIAL_VISIBLE = 2;

export function AIMarketAssessment() {
  const [expanded, setExpanded] = useState(false);

  const visible = ASSESSMENTS.slice(0, INITIAL_VISIBLE);
  const rest = ASSESSMENTS.slice(INITIAL_VISIBLE);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-accent-indigo" />
          <h2 className="text-sm font-semibold text-text-primary">AI Market Assessment</h2>
        </div>
        <Badge variant="outline" className="h-4 border-accent-amber/30 px-1.5 text-[0.6rem] text-accent-amber">
          Sample Analysis
        </Badge>
      </div>

      <div className="flex flex-col gap-3">
        {visible.map((item) => (
          <AssessmentCard key={item.id} item={item} />
        ))}
      </div>

      {expanded && (
        <div className="flex flex-col gap-3 pt-3">
          {rest.map((item) => (
            <AssessmentCard key={item.id} item={item} />
          ))}
        </div>
      )}

      {rest.length > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="group mx-auto flex items-center gap-2 rounded-lg border border-accent-indigo/40 bg-accent-indigo/10 px-4 py-2 text-xs font-semibold text-accent-indigo shadow-glow transition-all duration-150 hover:border-accent-indigo/60 hover:bg-accent-indigo/20"
        >
          {expanded ? "Show Less" : "View All Market Intelligence"}
          <ChevronDown
            className={cn("h-3.5 w-3.5 transition-transform duration-300", expanded && "rotate-180")}
          />
        </button>
      )}
    </div>
  );
}

function AssessmentCard({ item }: { item: AggregatorAssessment }) {
  return (
    <div className="rounded-xl border border-border-bright bg-bg-elevated/40 p-4 shadow-panel backdrop-blur-md">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs font-bold text-text-primary">{item.aggregator}</p>
        <span className="whitespace-nowrap rounded-full border border-accent-cyan/30 bg-accent-cyan/10 px-2 py-0.5 text-2xs font-medium text-accent-cyan">
          {item.market}
        </span>
      </div>
      <p className="text-xs leading-relaxed text-text-secondary sm:text-sm">
        {item.segments.map((seg, i) =>
          seg.stat ? (
            <span key={i} className="font-mono font-semibold text-accent-cyan">
              {seg.text}
            </span>
          ) : (
            <span key={i}>{seg.text}</span>
          )
        )}
      </p>
    </div>
  );
}
