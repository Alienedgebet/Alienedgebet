"""
o15_rules_report.py — Phase 1 verdict on the 13 Over 1.5 rules.

Reads the leak-free feature table from o15_rules_probe.py and reports, for
each rule, three things that the previous investigation conflated:

  1. AVAILABILITY — could the rule even be evaluated? (both sides had the
     underlying stat on all 5 history matches). A rule that cannot fire
     because the data is missing is a DATA problem.
  2. FIRE RATE — how often it fires once available.
  3. VALUE — hit rate when it fires vs when it does not, with a bootstrap
     CI on the difference. A rule that fires constantly at the base rate
     carries no information, however confident it looks.

Rules are then bucketed into KEEP / RETUNE / DROP on evidence, and the
whole thing is reported with the sample-size caveat that 20 days of
settled matches cannot resolve small differences.
"""
import pickle
import sys

import numpy as np
import pandas as pd

FEAT = "/tmp/o15_rule_features.pkl"

RULES = {
    "r01_both_possession_veto": ("VETO  Both Possession", "poss"),
    "r02_both_defensive_veto": ("VETO  Both Defensive", "tkl+itr+sot"),
    "r03_holy_grail": ("BOOST Holy Grail", "atk+gj+HT"),
    "r04_both_attacking": ("BOOST Both Attacking", "atk"),
    "r05_both_glass_jaw": ("BOOST Both Glass Jaw", "goals"),
    "r06_both_ht_active": ("BOOST Both HT Active", "HT"),
    "r07_early_kill": ("BOOST Early Kill", "HT"),
    "r08_mixed_high_sot": ("BOOST Mixed/High SOT", "sot"),
    "r09_attacker_vs_glass_jaw": ("BOOST Atk vs Glass Jaw", "atk+gj"),
    "r10_crossing": ("BOOST Crossing", "crosses"),
    "r11_both_clinical": ("BOOST Both Clinical", "sot+bcc"),
    "r12_no_clean_sheets": ("BOOST No Clean Sheets", "goals"),
    "r13_high_recent_goals": ("BOOST High Recent Goals", "goals"),
    "p14_btts_ud_high": ("PSYCH BTTS/UD Spear", "catalogue"),
    "p15_wounded_fav": ("PSYCH Wounded Fav", "goals"),
}

# which availability columns gate each rule
AVAIL = {
    "r01_both_possession_veto": None,
    "r02_both_defensive_veto": ["h_sot", "a_sot"],
    "r03_holy_grail": ["h_ht", "a_ht", "h_gl", "a_gl"],
    "r04_both_attacking": ["h_sot", "a_sot"],
    "r05_both_glass_jaw": ["h_gl", "a_gl"],
    "r06_both_ht_active": ["h_ht", "a_ht"],
    "r07_early_kill": ["h_ht", "a_ht"],
    "r08_mixed_high_sot": ["h_sot", "a_sot"],
    "r09_attacker_vs_glass_jaw": ["h_gl", "a_gl"],
    "r10_crossing": ["h_cr", "a_cr"],
    "r11_both_clinical": ["h_sot", "a_sot"],
    "r12_no_clean_sheets": ["h_gl", "a_gl"],
    "r13_high_recent_goals": ["h_gl", "a_gl"],
    "p14_btts_ud_high": None,
    "p15_wounded_fav": ["h_gl", "a_gl"],
}


def boot(a, b, reps=2000, seed=0):
    rng = np.random.default_rng(seed)
    a = np.asarray(a, float); b = np.asarray(b, float)
    if len(a) < 5 or len(b) < 5:
        return (np.nan, np.nan)
    d = np.array([rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean()
                  for _ in range(reps)])
    return (float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)))


def main():
    D = pickle.load(open(FEAT, "rb"))
    n = len(D)
    base = D.hit.mean()
    print("=" * 100)
    print("OVER 1.5 — PHASE 1: WHAT ARE THE 13 RULES ACTUALLY WORTH?")
    print("=" * 100)
    print(f"settled targets      {n}")
    print(f"dates                {D.date.nunique()}  ({D.date.min()} -> {D.date.max()})")
    print(f"Over 1.5 base rate   {base:.4f}")
    print()

    # ── data availability, independent of any rule ──
    print("─" * 100)
    print("A. DATA AVAILABILITY  (can the rule be evaluated at all?)")
    print("─" * 100)
    print(f"{'underlying data':<22}{'both sides available':<24}{'missing':<10}{'note'}")
    for lbl, cols in [("HT goals", ["h_ht", "a_ht"]),
                      ("Shots On Target", ["h_sot", "a_sot"]),
                      ("Total Crosses", ["h_cr", "a_cr"]),
                      ("Goals (FT)", ["h_gl", "a_gl"]),
                      ("W/L outcome", ["h_wo", "a_wo"])]:
        ok = int((D[cols[0]] & D[cols[1]]).sum())
        print(f"{lbl:<22}{f'{ok}/{n}  ({ok/n:.1%})':<24}{n-ok:<10}")
    print()

    # ── per-rule verdict ──
    print("─" * 100)
    print("B. PER-RULE VERDICT")
    print("─" * 100)
    hdr = (f"{'rule':<30}{'avail':>8}{'fired':>8}{'fire%':>8}"
           f"{'hit|fired':>11}{'hit|off':>10}{'delta':>9}  {'95% CI':>18}  verdict")
    print(hdr)
    print("-" * len(hdr))

    verdicts = {}
    for r, (label, need) in RULES.items():
        cols = AVAIL.get(r)
        if cols:
            mask = D[cols[0]] & D[cols[1]]
        else:
            mask = pd.Series(True, index=D.index)
        avail = int(mask.sum())
        fired = D[r] & mask
        off = (~D[r]) & mask
        nf, no = int(fired.sum()), int(off.sum())
        if nf < 15 or no < 15:
            v = "INSUFFICIENT n"
            hf = ho = d = np.nan
            lo = hi = np.nan
        else:
            hf = D.hit[fired].mean(); ho = D.hit[off].mean(); d = hf - ho
            lo, hi = boot(D.hit[fired].values, D.hit[off].values)
            if lo > 0:
                v = "KEEP (helps)"
            elif hi < 0:
                v = "HARMFUL (inverted)"
            elif abs(d) < 0.03:
                v = "NULL (noise)"
            else:
                v = "WEAK"
        verdicts[r] = dict(avail=avail, fired=nf, hit_fired=hf, hit_off=ho,
                           delta=d, lo=lo, hi=hi, verdict=v, need=need)
        cis = f"[{lo:+.3f},{hi:+.3f}]" if lo == lo else "n/a"
        print(f"{label:<30}{avail:>8}{nf:>8}{nf/avail if avail else 0:>8.1%}"
              f"{hf if hf==hf else float('nan'):>11.4f}{ho if ho==ho else float('nan'):>10.4f}"
              f"{d if d==d else float('nan'):>+9.4f}  {cis:>18}  {v}")

    # ── bucket summary ──
    print()
    print("─" * 100)
    print("C. BUCKETS")
    print("─" * 100)
    buckets = {"KEEP (helps)": [], "WEAK": [], "NULL (noise)": [],
               "HARMFUL (inverted)": [], "INSUFFICIENT n": []}
    for r, x in verdicts.items():
        buckets[x["verdict"]].append(RULES[r][0])
    for k, v in buckets.items():
        if v:
            print(f"{k:<20} ({len(v)})  {', '.join(v)}")
    print()

    # ── honest limits ──
    print("─" * 100)
    print("D. WHAT THIS CAN AND CANNOT SETTLE")
    print("─" * 100)
    se = float(np.sqrt(base * (1 - base) / n))
    print(f"base-rate standard error on {n} rows: ±{1.96*se:.4f} (95%)")
    cov20 = int(n * 0.2)
    se20 = float(np.sqrt(base * (1 - base) / max(cov20, 1)))
    print(f"at 20% coverage ({cov20} rows):        ±{1.96*se20:.4f} (95%)")
    print("A rule whose true effect is smaller than that band cannot be separated from zero here.")
    print(f"Bootstrap CIs above are computed per rule on the rows where that rule was")
    print(f"evaluable, so they are wider still. Treat 'WEAK' as a candidate to retest on")
    print(f"fresh data, not as a decision.")

    out = "/tmp/o15_rule_verdicts.pkl"
    pickle.dump(verdicts, open(out, "wb"))
    print(f"\nverdicts -> {out}")


if __name__ == "__main__":
    main()
