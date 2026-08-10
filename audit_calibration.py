"""
audit_calibration.py — Confidence Calibration Audit (Phase 2, Step A)

Purpose: measure sample size per confidence bucket, per sport, before
deciding HOW (or whether) to fit a real calibration curve. Fitting
Platt/isotonic scaling on a bucket with 6 games teaches the model
its own noise, not real miscalibration — this script exists to catch
that before it happens, not after.

Does NOT fit anything. Read-only report. Recommendation logic is a
simple, transparent rule (not a black box): a bucket needs a minimum
sample size before its actual_win_rate is trustworthy enough to
correct against. 20 is a reasonable floor for a rough signal, 30+ for
anything resembling real curve-fitting — both are conservative
statistical rules of thumb, not tuned to make the data look better.

Usage:
    python audit_calibration.py                    # season, all sports
    python audit_calibration.py --season            # explicit, same as above
    python audit_calibration.py --range 2026-06-01 2026-07-15
"""

import argparse
from performance_tracker import calculate_confidence_buckets

MIN_ROUGH_SIGNAL = 20   # below this, don't trust the number at all
MIN_CURVE_FIT     = 30  # below this, don't fit a real curve on it — widen or pool instead

SPORTS = ["wnba", "mlb", "cfb", "nfl"]


def audit(date_range=None):
    print("="*70)
    print("CONFIDENCE CALIBRATION AUDIT")
    print("="*70)
    print("Not fitting anything — this only measures whether you HAVE enough")
    print("data to fit anything trustworthy. Read before touching calibration.\n")

    overall_thin_buckets = []
    sport_fit_ready = {}

    # Per-sport breakdown — this is the number that actually matters,
    # since WNBA/MLB have far more graded history than CFB/NFL right
    # now, and pooling everything together hides that.
    for sport in SPORTS:
        buckets = calculate_confidence_buckets(date_range=date_range, sport=sport)
        if not buckets:
            print(f"{sport.upper():<6} — no graded picks with model_prob on record")
            continue

        print(f"{sport.upper()}")
        for b in buckets:
            n = b["total"]
            if n < MIN_ROUGH_SIGNAL:
                flag = "  ⚠️  TOO THIN — do not trust this number at all"
                overall_thin_buckets.append((sport, b["bucket"], n))
            elif n < MIN_CURVE_FIT:
                flag = "  ⚠️  rough signal only — do not fit a curve on this alone"
                overall_thin_buckets.append((sport, b["bucket"], n))
            else:
                flag = "  ✓ enough for real signal"
            print(f"  {b['bucket']:<8} {b['wins']:>3}-{b['losses']:<3} "
                  f"({b['actual_win_rate']:>5.1f}% actual, n={n:<4}){flag}")
        ready_buckets = sum(1 for bucket in buckets if bucket["total"] >= MIN_CURVE_FIT)
        sport_fit_ready[sport] = (ready_buckets / len(buckets)) >= 0.80
        print()


    # Pooled across all sports — the ONLY view where curve-fitting is
    # remotely viable right now, if any.
    print("ALL SPORTS POOLED")
    pooled = calculate_confidence_buckets(date_range=date_range, sport=None)
    if not pooled:
        print("  no graded picks with model_prob on record\n")
    else:
        for b in pooled:
            n = b["total"]
            if n < MIN_ROUGH_SIGNAL:
                flag = "  ⚠️  TOO THIN"
            elif n < MIN_CURVE_FIT:
                flag = "  ⚠️  rough signal only"
            else:
                flag = "  ✓ enough for real signal"
            print(f"  {b['bucket']:<8} {b['wins']:>3}-{b['losses']:<3} "
                  f"({b['actual_win_rate']:>5.1f}% actual, n={n:<4}){flag}")
        print()

    # Verdict
    print("="*70)
    print("VERDICT")
    print("="*70)
    pooled_fit_ready = pooled and all(b["total"] >= MIN_CURVE_FIT for b in pooled)
    per_sport_fit_ready = bool(sport_fit_ready) and all(sport_fit_ready.values())

    if per_sport_fit_ready:
        print("Every sport has enough data per bucket. Fitting a per-sport")
        print("calibration curve (isotonic regression) is statistically justified.")
    elif pooled_fit_ready:
        print("Per-sport buckets are too thin to fit individually, but the POOLED")
        print("(all-sports) buckets have enough data. Recommendation: fit ONE")
        print("calibration curve across all sports for now, not per-sport curves.")
        print("Revisit per-sport once each sport accumulates more graded history.")
    else:
        print("Not enough data anywhere to responsibly fit a calibration curve yet")
        print("— pooled or per-sport. Fitting now would be learning noise, not signal.")
        print()
        print("Recommended alternative: WIDEN buckets instead of fitting a curve.")
        print("E.g. collapse 80-84/85-89/90+ into a single '80%+' bucket and see")
        print("if THAT has enough samples to trust. A coarser, honest number beats")
        print("a precise, overfit one.")

    if overall_thin_buckets:
        print(f"\n{len(overall_thin_buckets)} thin bucket(s) flagged above — do not")
        print("cite these individually until they accumulate more games.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", nargs=2, metavar=("START", "END"),
                         help="Date range YYYY-MM-DD YYYY-MM-DD. Default: full season (no filter).")
    args = parser.parse_args()

    date_range = tuple(args.range) if args.range else None
    audit(date_range=date_range)
