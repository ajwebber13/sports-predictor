"""
One-off correction: the Sparks @ Lynx prediction currently has a fake
-110/-110 default odds value (confirmed via verify_lynx_odds.py — not
a real captured market price). Re-logs the same pick with odds=None
so it's honestly marked "unknown" instead of quietly wrong. A None
odds value is already handled correctly everywhere downstream —
calculate_roi() already excludes picks with odds_at_pick=None from
ROI/CLV via picks_skipped_no_odds, so this doesn't break anything,
it just stops it from lying.
"""
from database import log_prediction

log_prediction({
    "game": "Los Angeles Sparks @ Minnesota Lynx",
    "bet": "Minnesota Lynx",
    "odds": None,   # was -110 — confirmed fake, both sides identical, not a real market price
    "model_prob": 77.8,
    "implied_prob": None,
    "edge": None,
    "home_record": "18-6",
    "away_record": "10-12",
    "home_rest": 3,
    "away_rest": 3,
    "home_injuries": "Juhasz (Day-To-Day)",
    "away_injuries": "Brink (Out), Plum (Out)",
}, sport="wnba")
# NOTE: log_prediction() prints its own real status ("Logged prediction: ..."
# on success, "Prediction log error: ..." on failure) — no separate success
# message here, since printing one unconditionally would just repeat the
# exact mistake that made the earlier NoneType crash look like a success.
