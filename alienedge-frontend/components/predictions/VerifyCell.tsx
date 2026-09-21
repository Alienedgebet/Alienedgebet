"use client";

import { Check, X } from "lucide-react";

export interface VerificationData {
  status: "SCHEDULED" | "LIVE" | "FINISHED";
  score?: string;
  minute?: number | string | null;
  verdict: "PENDING" | "IN_PLAY" | "WON" | "LOST";
  badge_text: string;
  note?: string;
  h_corners?: number;
  a_corners?: number;
  total_corners?: number;
  h_sot?: number;
  a_sot?: number;
  total_sot?: number;
}

export function VerifyCell({ data }: { data?: VerificationData }) {
  if (!data || data.status === "SCHEDULED" || data.verdict === "PENDING") {
    return (
      <div className="flex items-center justify-center font-mono text-xs text-slate-500">
        <span title={data?.note || "Awaiting Kickoff"}>—</span>
      </div>
    );
  }

  // Corners rows expose the per-team split; SOT rows expose theirs. Prefer
  // whichever split this row actually carries so the cell reads e.g.
  // "5+4=9" instead of a bare FT score.
  const splitScore =
    data.h_corners !== undefined && data.a_corners !== undefined
      ? `${data.h_corners}+${data.a_corners}=${data.total_corners}`
      : data.h_sot !== undefined && data.a_sot !== undefined
        ? `${data.h_sot}+${data.a_sot}=${data.total_sot}`
        : data.score;

  // 1. LIVE IN-PLAY STATE
  if (data.status === "LIVE" || data.verdict === "IN_PLAY") {
    return (
      <div
        className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-950/40 px-2 py-0.5 font-mono text-2xs font-bold text-amber-300 shadow-[0_0_10px_rgba(245,158,11,0.15)] animate-pulse"
        title={data.note || "Live in play"}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-ping" />
        <span>{data.score || "0-0"}</span>
        {data.minute && <span className="text-[10px] text-amber-400/80">{data.minute}&apos;</span>}
      </div>
    );
  }

  // 2. FINISHED: WON STATE
  if (data.verdict === "WON") {
    const displayScore = data.h_corners !== undefined && data.a_corners !== undefined
      ? `${data.h_corners}+${data.a_corners}=${data.total_corners}`
      : data.score;
    return (
      <div
        className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-950/50 px-2 py-0.5 font-mono text-xs font-bold text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.2)]"
        title={data.note}
      >
        <Check className="h-3 w-3 text-emerald-400 stroke-[3]" />
        <span>{displayScore}</span>
      </div>
    );
  }

  // 3. FINISHED: LOST STATE
  const displayScore = data.h_corners !== undefined && data.a_corners !== undefined
    ? `${data.h_corners}+${data.a_corners}=${data.total_corners}`
    : data.score;
  return (
    <div
      className="inline-flex items-center gap-1 rounded-md border border-rose-500/40 bg-rose-950/50 px-2 py-0.5 font-mono text-xs font-bold text-rose-300 shadow-[0_0_12px_rgba(244,63,94,0.2)]"
      title={data.note}
    >
      <X className="h-3 w-3 text-rose-400 stroke-[3]" />
      <span>{displayScore}</span>
    </div>
  );
}
