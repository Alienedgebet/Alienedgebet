"""
CONVERGENCE — do INDEPENDENT sources point the same way?

WHY THIS EXISTS
---------------
The live chain asks "what do my own codes say about each other?" (Code 3 picks vs
Code 4 chemistry). That is a self-consistency check between two views of ONE
live feed: it can show the system is coherent, but it cannot surface anything
the feed did not already contain.

This asks a different question: do sources that CANNOT be wrong in the same way
agree? A lineup verdict and a season-form profile come from different engines,
different data and different windows. When both point the same way, that is not
one fact counted twice.

THE INDEPENDENCE RULE, AND ITS LIMIT
------------------------------------
    Code 4  (live lineups + 400-day history)   -> ONE source
    DNA v2  (season statistics, prematch)      -> ONE source
    market  (bookmaker price)                   -> ONE source

Code 4's OWN outputs are NOT independent of each other. A BLESSING verdict and
a "favourite goalkeeper is a liability" verdict both come out of the same
key-monument over the same window. When both fire they are one measurement
observed twice, so counting them as two agreeing sources would manufacture
confidence that was never earned. They are folded into a single Code 4 vote
here, and `source_count` counts genuinely distinct sources.

WHY A VOTE, NOT A MARGIN
------------------------
On an underdog every difference is worth something — a 0.1 edge on a longshot is
still an edge. But DNA factor margins are frequently 0.1 or 0.2 apart on
computed indices, which is rounding noise rather than an observed gap. Gating on
a raw margin would either fire on noise or miss real leans.

So the DNA signal is a VOTE across its factors rather than a single number: a
lean carried by several factors beats one carried by a single 0.1 margin,
without either being discarded merely for being small.

WHAT THIS DOES NOT CLAIM
------------------------
No convergence rule here has been backtested. The live backtest
(tools/live_signal_backtest.py) measures the individual signals and finds they
tie with guessing across 183 internationals. Convergence of signals that
individually show nothing is not thereby evidence. This module therefore
reports WHICH sources agreed and how strongly, and names the outcome
CONFIRMED — two independent sources licensing — rather than PREDICTED.
"""
import json
import os
def _dna_lean(dna_entry, market, side):
    """
    How many of DNA's factors favour `side` on this market.

    Returns (lean, votes_for, votes_against, total). A factor reporting
    winner "neutral" is excluded from BOTH counts rather than counted either
    way — the engine declining to pick a winner is not evidence for the team it
    declined.
    """
    markets = (dna_entry or {}).get("markets") or {}
    factors = (markets.get(market) or {}).get("factors") or []
    other = _opposite[side]
    back = against = total = 0
    for f in factors:
        if not isinstance(f, dict):
            continue
        winner = str(f.get("winner") or "").lower()
        if winner not in (side, other):
            continue
        total += 1
        if winner == side:
            back += 1
        else:
            against += 1
    if not total or back / total < DNA_MAJORITY_RATIO:
        return "neutral", back, against, total
    return side, back, against, total


def _code4_vote(home, away, target):
    """
    Code 4's view on `target`, as ONE vote.

    Its own outputs are not independent: the verdict and the goalkeeper call
    both come from the same key-monument over the same window. The strongest
    single signal is used rather than the sum, so two correlated reads cannot
    masquerade as corroboration.
    """
    me = home if target == "home" else away
    them = away if target == "home" else home
    verdict = str((me or {}).get("verdict") or "").upper()
    if verdict == "BLESSING":
        return target, (f"{me.get('team_name')} verdict BLESSING "
                        f"(net {me.get('net_impact')}) — those who left were "
                        f"worse than the ones now starting")
    opp_gk = str((them or {}).get("gk_verdict") or "").upper()
    if opp_gk == "DANGER":
        return target, (f"{them.get('team_name')} goalkeeper flagged DANGER "
                        f"({str(them.get('gk_note') or '')[:80]})")
    return "neutral", f"Code 4 verdict {verdict or 'n/a'} on {me.get('team_name')}"


def _market_view(fixture_id, market, target):
    """
    The book's view, from the odds stage 1 already persists.

    Returns (lean, implied_for_target, detail). The market is the strongest
    single source available, so it is reported SEPARATELY from the vote count
    rather than added to it: a price is not another voice in the room, it is
    the price of the room.
    """
    prematch = _load(PREMATCH_FILE, {})
    # The audit is a DICT keyed by fixture_id, not a list. Iterating it directly
    # yields the KEY STRINGS, so the lookup found nothing and reported "no
    # prematch odds" on every fixture that plainly had them. A shape assumption
    # that cannot match is a silent zero, again.
    if isinstance(prematch, dict):
        entry = prematch.get(str(fixture_id))
        if entry is None:
            entry = next((r for r in prematch.values()
                          if isinstance(r, dict)
                          and str(r.get("fixture_id")) == str(fixture_id)), None)
    elif isinstance(prematch, list):
        entry = next((r for r in prematch if isinstance(r, dict)
                      and str(r.get("fixture_id")) == str(fixture_id)), None)
    else:
        entry = None
    if entry is None:
        return "neutral", None, "no prematch odds for this fixture"

    other = _opposite[target]
    keys = {"win": ("odds_home_win", "odds_away_win"),
            "over25": ("odds_o25", None),
            "unders": (None, None)}.get(market, (None, None))
    mine, theirs = keys
    if not mine:
        return "neutral", None, f"no odds published for the {market} market"

    try:
        my_odds, their_odds = float(entry.get(mine)), float(entry.get(theirs))
    except (TypeError, ValueError):
        return "neutral", None, "odds unreadable for this market"
    if my_odds <= 1.0:
        return "neutral", None, f"implied price {my_odds} is not usable"

    p_mine = 1.0 / my_odds
    p_theirs = (1.0 / their_odds) if (their_odds and their_odds > 1.0) else 0.0
    total = p_mine + p_theirs
    implied = p_mine / total if total else 0.0
    if implied < MIN_MEANINGFUL_IMPLIED:
        return "neutral", round(implied * 100, 1), (
            f"{target} priced at {my_odds} — a longshot price, not a market "
            f"view worth weighing")

    lean = target if my_odds < their_odds else other
    return lean, round(implied * 100, 1), (
        f"{target} {my_odds} vs {other} {their_odds} — book implies "
        f"{implied * 100:.0f}% for {target}")


def converge(fixture_id, market="win", target="away"):
    """
    Do INDEPENDENT sources favour `target` on this fixture and market?

    Returns the votes, the sources that agreed, and a label. `label` is
    CONFIRMED only when two or more genuinely distinct sources point the same
    way; with one it is a SIGNAL, which is what a single live reading honestly
    is. The market is a third source the caller may join — it is never counted
    here, because this module does not read odds.
    """
    danger = _load(DANGER_FILE, [])
    entry = next((r for r in danger if isinstance(r, dict)
                  and str(r.get("fixture_id")) == str(fixture_id)), None)
    if entry is None:
        return {"fixture_id": fixture_id, "error": "not on the danger audit"}

    home, away = entry.get("home_team"), entry.get("away_team")
    dna_all = _load(DNA_FILE, {})
    dna_entry = (dna_all.get(str(fixture_id))
                 if isinstance(dna_all, dict) else None)

    votes = []
    # `_code4_vote` returns the SIDE it favours (or "neutral"), not the word
    # "favours". Returning a literal here would never equal `target`, and the
    # Code 4 vote would silently drop out of every count.
    c4_lean, c4_why = _code4_vote(home, away, target)
    votes.append({"source": "code4", "leans": c4_lean, "detail": c4_why})

    if dna_entry:
        lean, back, against, total = _dna_lean(dna_entry, market, target)
        votes.append({
            "source": "dna_v2", "leans": lean,
            "detail": (f"{back} of {total} factors favour {target} "
                       f"(needs {int(DNA_MAJORITY_RATIO * 100)}%)"
                       if total else "no usable factors for this market"),
            "votes_for": back, "votes_against": against, "total": total,
        })
    else:
        votes.append({"source": "dna_v2", "leans": "neutral",
                      "detail": "no DNA profile for this fixture"})

    sources = [v["source"] for v in votes if v["leans"] == target]
    n = len(sources)

    # The market is reported alongside, never folded into the count. It is the
    # price of the room, not another voice in it — and the useful case is
    # precisely when it DISAGREES with the live read, because that is the only
    # scenario where the live feed is saying something the book has not already
    # priced in.
    m_lean, m_implied, m_detail = _market_view(fixture_id, market, target)
    market_agrees = (m_lean == target)
    live_says_yes = n >= 1
    disagrees = bool(live_says_yes and m_lean != "neutral"
                     and not market_agrees)

    if n >= 2:
        label = "CONFIRMED"
        headline = f"{n} independent sources favour {target} on {market}"
    elif n == 1:
        label = "SIGNAL"
        headline = f"only 1 source favours {target} on {market} — not confirmed"
    else:
        label = "NONE"
        headline = f"no source favours {target} on {market}"

    if disagrees:
        headline += (f". The MARKET DISAGREES ({m_detail}) — the live read is "
                      f"pointing somewhere the book has not priced, which is "
                      f"the case worth acting on")

    return {"fixture_id": fixture_id, "fixture": entry.get("fixture"),
            "market_name": market, "target": target, "label": label,
            "headline": headline, "sources_agreeing": sources,
            "source_count": n, "votes": votes,
            # `market` is the BOOK's view; `market_name` is which market is
            # being read. Two keys, not one — naming both the same thing would
            # have the view silently overwrite the market it describes.
            "market": {"leans": m_lean,
                       "implied_pct_for_target": m_implied,
                       "agrees_with_live": market_agrees,
                       "disagrees_with_live": disagrees,
                       "detail": m_detail}}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

DANGER_FILE = os.path.join(DATA_DIR, "danger_audit.json")
DNA_FILE = os.path.join(DATA_DIR, "dna_v2_market_factors.json")
PREMATCH_FILE = os.path.join(DATA_DIR, "prematch_team_audit.json")

# A DNA lean needs a MAJORITY of the factors, not a single winner.
DNA_MAJORITY_RATIO = 0.6
_opposite = {"home": "away", "away": "home"}

# Implied probabilities below this are not a real market view — they are a
# longshot price the book has to quote to offer the market at all. Treating
# 29.0 as "97% confident in the away side" would let the market confirm
# anything on a mismatch fixture.
MIN_MEANINGFUL_IMPLIED = 0.05


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return default