"""
factor_correlation_check.py — Culture & Pulse Analytics

Breaks the margin projection down into its individual components
(base runs/rate, pitcher/matchup factor, weather, situational, injury,
line movement, h2h, matchup — whatever keys prediction_factors.py logs
for a given sport) and checks which ones actually correlate with real
game margins vs which are just noise.

For each factor, computes diff = home_factor_value - away_factor_value
(the same way it contributes to the final projected margin) and
correlates that diff against the real final margin (home_score -
away_score) across graded games. A factor with near-zero correlation
isn't adding predictive signal — it's adding noise (or, at best,
capturing something real but small enough to be swamped by everything
else).

Works for any sport already logged via save_prediction_factors() —
discovers factor keys dynamically from the data rather than hardcoding
per-sport field names.

USAGE:
    python3 factor_correlation_check.py --sport mlb
    python3 factor_correlation_check.py --sport wnba
"""

import json
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn


def fetch_factor_rows(sport: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT pf.home_factors, pf.away_factors, r.home_score, r.away_score
        FROM prediction_factors pf
        JOIN results r
          ON r.sport = pf.sport
         AND r.home_team = pf.home_team
         AND r.away_team = pf.away_team
         AND r.date = substr(pf.game_id, 1, 10)
        WHERE pf.sport = ?
          AND r.home_score IS NOT NULL
          AND r.away_score IS NOT NULL
    """, (sport,))
    rows = c.fetchall()
    conn.close()

    out = []
    for r in rows:
        try:
            home_f = r["home_factors"] if isinstance(r["home_factors"], dict) else json.loads(r["home_factors"])
            away_f = r["away_factors"] if isinstance(r["away_factors"], dict) else json.loads(r["away_factors"])
        except (TypeError, json.JSONDecodeError):
            continue
        actual_margin = float(r["home_score"]) - float(r["away_score"])
        out.append({"home_factors": home_f, "away_factors": away_f, "actual_margin": actual_margin})
    return out


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def analyze(rows, sport_label):
    print(f"\n{'='*60}")
    print(f"  Factor Correlation Check — {sport_label}")
    print(f"  {len(rows)} graded games with matched factor data")
    print(f"{'='*60}\n")

    if len(rows) < 5:
        print("  Not enough matched rows to say anything meaningful.\n")
        return

    # Discover all numeric keys present in home_factors across rows
    all_keys = set()
    for r in rows:
        for k, v in r["home_factors"].items():
            if isinstance(v, (int, float)):
                all_keys.add(k)

    results = []
    for key in sorted(all_keys):
        diffs = []
        margins = []
        for r in rows:
            hv = r["home_factors"].get(key)
            av = r["away_factors"].get(key)
            if hv is None or av is None:
                continue
            if not isinstance(hv, (int, float)) or not isinstance(av, (int, float)):
                continue
            diffs.append(hv - av)
            margins.append(r["actual_margin"])
        if len(diffs) < 5:
            continue
        corr = _pearson(diffs, margins)
        results.append({"factor": key, "n": len(diffs), "corr": corr})

    results.sort(key=lambda x: abs(x["corr"]) if x["corr"] is not None else 0, reverse=True)

    print(f"  {'Factor':<22} {'N':<6} {'Corr (diff vs actual margin)':<30}")
    for r in results:
        corr_str = f"{r['corr']:.3f}" if r["corr"] is not None else "N/A"
        flag = ""
        if r["corr"] is not None:
            if abs(r["corr"]) >= 0.3:
                flag = "  <- real signal"
            elif abs(r["corr"]) < 0.05:
                flag = "  <- near zero, likely noise"
        print(f"  {r['factor']:<22} {r['n']:<6} {corr_str:<30}{flag}")

    print(f"\n  Reference: overall projected margin correlation with actual margin")
    print(f"  was measured separately in margin_calibration_check.py.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True)
    args = parser.parse_args()

    rows = fetch_factor_rows(args.sport.lower())
    analyze(rows, args.sport.upper())
