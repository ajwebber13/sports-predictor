"""
Rolling performance alert for Culture & Pulse picks export.

Checks 7-day and 14-day ROI / win-rate by market (and by sport+market),
flags anything that crosses your thresholds, and prints a plain-text
alert summary. Meant to run against the same CSV export format you've
been pulling (pick_logo, date, sport, game, Market, Pick, Tier, odds,
edge, final_score, status).

USAGE:
    python3 rolling_alert.py path/to/export.csv

THRESHOLDS (edit these to tune sensitivity):
    ROI_ALERT_PCT       -> if rolling ROI drops below this, flag it
    WINRATE_ALERT_PCT   -> if rolling win rate drops below this, flag it
    MIN_SAMPLE          -> don't alert on windows with fewer picks than this
"""

import sys
import pandas as pd

# ---- thresholds you can tune ----
ROI_ALERT_PCT = -5.0        # flag if rolling ROI < -5%
WINRATE_ALERT_PCT = 50.0    # flag if rolling win rate < 50%
MIN_SAMPLE = 8              # need at least this many graded picks to trust the window
WINDOWS = [7, 14]           # rolling windows in days


def american_to_profit(odds, stake=100):
    odds = float(odds)
    return stake * odds / 100 if odds > 0 else stake * 100 / abs(odds)


def load_graded(csv_path):
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    graded = df[df["status"].isin(["WIN", "LOSS"])].copy()
    graded["profit"] = graded.apply(
        lambda r: american_to_profit(r["odds"]) if r["status"] == "WIN" else -100,
        axis=1,
    )
    return graded


def window_stats(g):
    n = len(g)
    if n == 0:
        return None
    wins = (g["status"] == "WIN").sum()
    win_rate = wins / n * 100
    roi = g["profit"].sum() / (n * 100) * 100
    return {"n": n, "win_rate": win_rate, "roi": roi}


def check_window(label, group_key, group_df, as_of, days):
    cutoff = as_of - pd.Timedelta(days=days - 1)
    window_df = group_df[group_df["date"] >= cutoff]
    stats = window_stats(window_df)
    if stats is None or stats["n"] < MIN_SAMPLE:
        return None, stats
    flags = []
    if stats["roi"] < ROI_ALERT_PCT:
        flags.append(f"ROI {stats['roi']:.1f}% < {ROI_ALERT_PCT}%")
    if stats["win_rate"] < WINRATE_ALERT_PCT:
        flags.append(f"win rate {stats['win_rate']:.1f}% < {WINRATE_ALERT_PCT}%")
    return flags, stats


def run(csv_path):
    graded = load_graded(csv_path)
    if graded.empty:
        print("No graded picks found (all PENDING). Nothing to check.")
        return

    as_of = graded["date"].max()
    print(f"Rolling alert check — as of {as_of.date()}\n")

    any_alert = False

    for days in WINDOWS:
        print(f"=== {days}-day window ===")

        # overall
        flags, stats = check_window("overall", None, graded, as_of, days)
        if stats:
            tag = " <-- ALERT" if flags else ""
            print(f"  OVERALL: n={stats['n']}, win_rate={stats['win_rate']:.1f}%, "
                  f"roi={stats['roi']:.1f}%{tag}")
            if flags:
                any_alert = True
                for f in flags:
                    print(f"    -> {f}")
        else:
            print(f"  OVERALL: not enough graded picks in window (min {MIN_SAMPLE})")

        # by market
        for mkt, g in graded.groupby("Market"):
            flags, stats = check_window(mkt, mkt, g, as_of, days)
            if stats is None:
                continue
            tag = " <-- ALERT" if flags else ""
            print(f"  {mkt}: n={stats['n']}, win_rate={stats['win_rate']:.1f}%, "
                  f"roi={stats['roi']:.1f}%{tag}")
            if flags:
                any_alert = True
                for f in flags:
                    print(f"    -> {f}")

        # by sport + market (only where it matters most: sport-level)
        for sport, g in graded.groupby("sport"):
            flags, stats = check_window(sport, sport, g, as_of, days)
            if stats is None:
                continue
            tag = " <-- ALERT" if flags else ""
            print(f"  sport={sport}: n={stats['n']}, win_rate={stats['win_rate']:.1f}%, "
                  f"roi={stats['roi']:.1f}%{tag}")
            if flags:
                any_alert = True
                for f in flags:
                    print(f"    -> {f}")

        print()

    if any_alert:
        print("RESULT: one or more windows breached thresholds. Consider reducing "
              "stake size on flagged markets/sports until they recover.")
    else:
        print("RESULT: no thresholds breached.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 rolling_alert.py path/to/export.csv")
        sys.exit(1)
    run(sys.argv[1])
