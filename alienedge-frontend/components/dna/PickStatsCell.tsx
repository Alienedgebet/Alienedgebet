"use client";

/**
 * PickStatsCell — the SportyBet-style history card, opened on demand.
 *
 * WHAT THIS IS
 * ------------
 * A small "DNA" cell that sits right after Verify on a pick row. Clicking it
 * opens the SAME read-only history panel the DNA detail page shows at the top:
 * both teams' last five results, and the head-to-head record.
 *
 * WHY A CLICK INSTEAD OF AN INLINE CARD
 * -------------------------------------
 * That panel is roughly ten match results plus a full H2H block. A pick page can
 * show twenty or more fixtures. Rendering it inline for every row produces an
 * unusable page, so it is loaded per row, on demand.
 *
 * DATA, AND WHY NOTHING NEW IS COMPUTED
 * --------------------------------------
 *   form -> dna_profiles[team].form_rows, already delivered by the page's one
 *           existing useDnaV2(date) call
 *   H2H  -> /api/dna/v2/h2h/{date}/{fixtureId}, fetched ONLY on click and only
 *           because it is per-fixture. The server caches per team-pair.
 *
 * Both are pure history. This component starts no engine work, changes no pick,
 * and contributes nothing to any score — the same contract SportyMatchOverview
 * holds on the DNA page.
 */

import { useState } from "react";
import { BarChart3 } from "lucide-react";
import SportyMatchOverview from "@/components/dna/SportyMatchOverview";
import type { SportyH2HMeeting } from "@/components/dna/SportyMatchOverview";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  DnaV2H2HResponse,
  DnaV2Profile,
  DnaV2Response,
} from "@/lib/api";
import type { PredictionColumn } from "@/components/predictions";

function normalize(v: string): string {
  return v.trim().toLowerCase().replace(/\s+/g, " ");
}

/**
 * Split a pick's "Home vs Away" fixture string into its two team names.
 *
 * Every market in this app writes its fixture the same way ("New York City vs
 * New England", "Sokol Saratov vs Leningradets"), including on rows that carry
 * no fixture id. That makes the name the universal fallback for resolving a
 * team when an id is absent — which is why form data still renders on SOT,
 * FHVI, SHVI and the Over 1.5 psychology block, none of which publish an id.
 *
 * Returns nulls rather than guessing when the string does not have the expected
 * shape, so an unparseable fixture yields a disabled button instead of a card
 * showing the wrong two teams.
 */
export function splitFixtureTeams(fixture: string | null | undefined): {
  home: string | null;
  away: string | null;
} {
  if (!fixture) return { home: null, away: null };
  const parts = fixture.split(/\s+vs\.?\s+/);
  if (parts.length < 2) return { home: null, away: null };
  return {
    home: parts[0].trim() || null,
    away: parts.slice(1).join(" vs ").trim() || null,
  };
}

/** Find a team profile by id first, then by name (rows without an id). */
function findProfile(
  dna: DnaV2Response | null | undefined,
  teamId: string | number | null | undefined,
  teamName: string | null | undefined
): DnaV2Profile | undefined {
  const profiles = dna?.dna_profiles;
  if (!profiles) return undefined;
  if (teamId != null) {
    const byId = profiles[String(teamId)];
    if (byId) return byId;
  }
  if (!teamName) return undefined;
  const target = normalize(teamName);
  return Object.values(profiles).find(
    (p) => normalize(p.team_name ?? "") === target
  );
}

export function PickStatsButton({
  dna,
  date,
  fixtureId,
  homeId,
  awayId,
  homeTeam,
  awayTeam,
}: {
  dna: DnaV2Response | null | undefined;
  date: string;
  fixtureId?: string | number | null;
  homeId?: string | number | null;
  awayId?: string | number | null;
  homeTeam?: string | null;
  awayTeam?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [h2h, setH2h] = useState<DnaV2H2HResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const homeProfile = findProfile(dna, homeId, homeTeam);
  const awayProfile = findProfile(dna, awayId, awayTeam);
  const hasForm = Boolean(
    homeProfile?.form_rows?.length || awayProfile?.form_rows?.length
  );
  const hasH2H = (h2h?.meetings?.length ?? 0) > 0;

  // Disabled rather than silently empty: a cell that opens to nothing reads as a
  // broken button, and "we hold no history for this team" is worth knowing
  // before clicking, not after.
  const disabled = !hasForm && !hasH2H && !loading;

  async function handleClick() {
    setOpen(true);
    // H2H needs the fixture id and is per-fixture, so it loads on demand only.
    if (h2h || loading || fixtureId == null) return;
    setLoading(true);
    try {
      const { dnaV2Api } = await import("@/lib/api");
      const res = await dnaV2Api.getH2H(date, String(fixtureId));
      setH2h(res.data ?? null);
    } catch {
      setH2h({
        date,
        fixture_id: String(fixtureId),
        home_team: homeTeam ?? null,
        away_team: awayTeam ?? null,
        home_id: homeId != null ? String(homeId) : null,
        away_id: awayId != null ? String(awayId) : null,
        meetings: [],
        error: "provider_unreachable",
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled}
        className="inline-flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5 font-mono text-2xs uppercase tracking-wider text-text-muted transition-colors hover:border-accent-cyan/40 hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40"
        aria-label={`Match history for ${homeTeam ?? "home"} vs ${awayTeam ?? "away"}`}
      >
        <BarChart3 className="h-3 w-3" aria-hidden="true" />
        DNA
      </button>

      <Dialog open={open} onOpenChange={(o) => !o && setOpen(false)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {homeTeam ?? "Home"} vs {awayTeam ?? "Away"}
            </DialogTitle>
            <DialogDescription className="text-text-secondary">
              Match history only — last five results and head-to-head. Nothing
              in this panel feeds into the pick.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[75vh] overflow-y-auto">
            <SportyMatchOverview
              homeTeam={homeTeam ?? undefined}
              awayTeam={awayTeam ?? undefined}
              homeId={homeId != null ? String(homeId) : null}
              awayId={awayId != null ? String(awayId) : null}
              homeForm={homeProfile?.form_rows}
              awayForm={awayProfile?.form_rows}
              h2hMeetings={
                fixtureId == null || loading
                  ? null
                  : ((h2h?.meetings ?? null) as SportyH2HMeeting[] | null)
              }
              h2hError={
                fixtureId == null
                  ? "unresolved_teams"
                  : loading
                    ? undefined
                    : (h2h?.error ?? null)
              }
            />
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

export interface PickStatsOptions<T> {
  /**
   * useDnaV2() yields `DnaV2Response | null`, so null is accepted here rather
   * than forced into undefined at every call site.
   */
  dna: DnaV2Response | null | undefined;
  date: string;
  getFixtureId: (row: T) => string | number | null | undefined;
  getHomeTeam: (row: T) => string | null | undefined;
  getAwayTeam: (row: T) => string | null | undefined;
  getHomeId?: (row: T) => string | number | null | undefined;
  getAwayId?: (row: T) => string | number | null | undefined;
}

/**
 * Builds the "DNA" column for a pick table.
 *
 * THE COLUMN IS NAMED "DNA", NOT "Stats". The badge-based pages (WIN, GG, DRAW,
 * UNDERS, OVER 2.5, OVER 1.5) already label this slot DNA, and a page whose
 * same slot read "Stats" is the exact inconsistency this removes. What differs
 * between the two is only HOW it resolves — by market factor count where the
 * DNA engine has a factor set for that market, and by opening the team's real
 * history where it does not. The label is the same either way.
 *
 * Call it where the Verify column is built and insert the result straight after
 * it, so the button lands in the same place on every page.
 */
export function createPickStatsColumn<T>(
  opts: PickStatsOptions<T>
): PredictionColumn<T> {
  return {
    key: "dna_v2",
    header: "DNA",
    render: (r) => (
      <PickStatsButton
        dna={opts.dna}
        date={opts.date}
        fixtureId={opts.getFixtureId(r)}
        homeId={opts.getHomeId?.(r)}
        awayId={opts.getAwayId?.(r)}
        homeTeam={opts.getHomeTeam(r)}
        awayTeam={opts.getAwayTeam(r)}
      />
    ),
  };
}