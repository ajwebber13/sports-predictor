"""
espn_winprob.py
================
Pulls ESPN win probability for WNBA, NBA, and NCAAB games.
Used as a sanity check against internal model projections.

Endpoints:
  WNBA  : site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard
  NBA   : site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
  NCAAB : site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard

No API key required.
"""

import requests
from typing import Optional

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

DIVERGENCE_THRESHOLD = 15.0  # raised from 10 — WNBA pre-game ESPN model is less reliable
MIN_GAMES_THRESHOLD  = 10    # flag teams with fewer games as low confidence

ESPN_URLS = {
    "WNBA":  "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "NBA":   "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "NCAAB": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":  "application/json",
    "Referer": "https://www.espn.com/",
}


# ─────────────────────────────────────────────────────────────
# FETCH ESPN WIN PROBABILITIES
# ─────────────────────────────────────────────────────────────

def get_espn_win_probs(league: str) -> dict:
    """
    Fetch ESPN win probabilities for all games in today's scoreboard.
    Returns a dict keyed by normalized matchup string:
      "{away_team} @ {home_team}" -> {"home_prob": float, "away_prob": float}

    Returns empty dict if ESPN is unreachable or no games found.

    ESPN stores win probability in two places depending on game status:
      - Pre-game: competitions[0].odds[0].homeTeamOdds.winPercentage
      - Live:     competitions[0].situation.lastPlay.probability.homeWinPercentage
                  OR competitions[0].predictor.homeTeam.gameProjection
    """
    league = league.upper()
    url    = ESPN_URLS.get(league)

    if not url:
        print(f"  [ESPN] Unknown league: {league}")
        return {}

    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception as e:
        print(f"  [ESPN] {league} fetch failed: {e}")
        return {}

    result = {}

    for event in events:
        try:
            comp        = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            home        = next((t for t in competitors if t["homeAway"] == "home"), None)
            away        = next((t for t in competitors if t["homeAway"] == "away"), None)

            if not home or not away:
                continue

            home_name = home["team"]["displayName"]
            away_name = away["team"]["displayName"]
            key       = f"{away_name} @ {home_name}"

            home_prob = _extract_win_prob(comp, home_name, away_name)
            if home_prob is None:
                continue

            result[key] = {
                "home_team": home_name,
                "away_team": away_name,
                "home_prob": round(home_prob, 1),
                "away_prob": round(100 - home_prob, 1),
            }
        except Exception:
            continue

    if not result:
        print(f"  [ESPN] No win probability data found for {league}")

    return result


def _extract_win_prob(comp: dict, home_name: str, away_name: str) -> Optional[float]:
    """
    Try all known ESPN win prob locations. Returns home win % (0-100) or None.

    Priority:
      1. predictor.homeTeam.gameProjection       (pre-game %)
      2. odds[0].homeTeamOdds.winPercentage      (pre-game odds-based %)
      3. situation.lastPlay.probability...        (live)
      4. competitors[home].statistics winProbability
    """
    # 1. Predictor block (most reliable pre-game)
    predictor = comp.get("predictor", {})
    if predictor:
        home_proj = predictor.get("homeTeam", {}).get("gameProjection")
        if home_proj is not None:
            val = float(home_proj)
            return val if val <= 100 else val / 100 * 100

    # 2. Odds block win percentage
    odds_list = comp.get("odds", [])
    if odds_list:
        odds    = odds_list[0]
        home_wp = odds.get("homeTeamOdds", {}).get("winPercentage")
        if home_wp is not None:
            val = float(home_wp)
            return val if val <= 1.0 else val  # handle 0-1 vs 0-100

    # 3. Live game situation
    situation  = comp.get("situation", {})
    last_play  = situation.get("lastPlay", {})
    prob       = last_play.get("probability", {})
    home_live  = prob.get("homeWinPercentage")
    if home_live is not None:
        val = float(home_live)
        return val * 100 if val <= 1.0 else val

    # 4. Competitor statistics
    for c in comp.get("competitors", []):
        if c.get("homeAway") == "home":
            for stat in c.get("statistics", []):
                if "win" in stat.get("name", "").lower() and "prob" in stat.get("name", "").lower():
                    val = float(stat.get("value", 0))
                    return val * 100 if val <= 1.0 else val

    return None


# ─────────────────────────────────────────────────────────────
# SANITY CHECK
# ─────────────────────────────────────────────────────────────

def check_divergence(
    model_home_prob: float,
    espn_home_prob:  float,
    threshold:       float = DIVERGENCE_THRESHOLD,
) -> dict:
    """
    Compare model win prob vs ESPN win prob for home team.

    Returns:
      {
        "diverged":  bool,
        "gap":       float,   # absolute difference in percentage points
        "direction": str,     # "model_higher" or "espn_higher"
        "flag":      str | None,  # "DIVERGENCE" if flagged, else None
      }
    """
    gap       = abs(model_home_prob - espn_home_prob)
    direction = "model_higher" if model_home_prob > espn_home_prob else "espn_higher"
    diverged  = gap > threshold

    return {
        "diverged":  diverged,
        "gap":       round(gap, 1),
        "direction": direction,
        "flag":      "DIVERGENCE" if diverged else None,
    }


# ─────────────────────────────────────────────────────────────
# CONFIDENCE FILTER
# ─────────────────────────────────────────────────────────────

def get_confidence_flag(wins: int, losses: int, min_games: int = MIN_GAMES_THRESHOLD) -> str:
    """
    Flag teams with insufficient game history.
    Returns "LOW_CONFIDENCE" if games played is below threshold.
    Returns "STANDARD" otherwise.
    """
    games_played = wins + losses
    if games_played < min_games:
        return "LOW_CONFIDENCE"
    return "STANDARD"


def should_suppress_pick(confidence_flag: str, divergence_flag: Optional[str]) -> bool:
    """
    Returns True if the pick should be suppressed from publishing.
    Suppress when: low confidence team OR significant ESPN divergence.
    """
    return confidence_flag == "LOW_CONFIDENCE" or divergence_flag == "DIVERGENCE"


# ─────────────────────────────────────────────────────────────
# COMBINED VALIDATION
# ─────────────────────────────────────────────────────────────

def validate_pick(
    league:           str,
    home_team:        str,
    away_team:        str,
    model_home_prob:  float,
    home_wins:        int = None,
    home_losses:      int = None,
    away_wins:        int = None,
    away_losses:      int = None,
) -> dict:
    """
    Full validation pipeline for a single game pick.

    1. Fetches ESPN win prob for the matchup
    2. Runs divergence check vs model
    3. Runs confidence filter on both teams
    4. Returns a validation result dict

    Returns:
      {
        "espn_home_prob":   float | None,
        "divergence":       dict | None,
        "home_confidence":  str,
        "away_confidence":  str,
        "suppress":         bool,
        "suppress_reason":  str | None,
      }
    """
    matchup_key = f"{away_team} @ {home_team}"

    # Auto-fetch live records if not passed in
    if home_wins is None or away_wins is None:
        try:
            from live_records import get_live_records, get_record
            records     = get_live_records(league)
            home_wins, home_losses = get_record(home_team, league, records)
            away_wins, away_losses = get_record(away_team, league, records)
        except Exception as e:
            print(f"  [Records] Auto-fetch failed: {e} — skipping confidence filter")
            home_wins = home_losses = away_wins = away_losses = 15

    # Confidence flags
    home_conf = get_confidence_flag(home_wins, home_losses)
    away_conf = get_confidence_flag(away_wins, away_losses)

    # ESPN win prob lookup
    espn_probs  = get_espn_win_probs(league)
    espn_game   = espn_probs.get(matchup_key)
    espn_home_wp = espn_game["home_prob"] if espn_game else None

    # Divergence check
    divergence = None
    if espn_home_wp is not None:
        divergence = check_divergence(model_home_prob, espn_home_wp)

    # Suppress logic
    suppress        = False
    suppress_reason = None

    if home_conf == "LOW_CONFIDENCE":
        suppress        = True
        suppress_reason = f"{home_team} has fewer than {MIN_GAMES_THRESHOLD} games played"
    elif away_conf == "LOW_CONFIDENCE":
        suppress        = True
        suppress_reason = f"{away_team} has fewer than {MIN_GAMES_THRESHOLD} games played"
    elif divergence and divergence["diverged"]:
        suppress        = True
        suppress_reason = (
            f"Model ({model_home_prob}%) vs ESPN ({espn_home_wp}%) "
            f"diverge by {divergence['gap']} pts — exceeds {DIVERGENCE_THRESHOLD} pt threshold"
        )

    return {
        "espn_home_prob":  espn_home_wp,
        "divergence":      divergence,
        "home_confidence": home_conf,
        "away_confidence": away_conf,
        "suppress":        suppress,
        "suppress_reason": suppress_reason,
    }


# ─────────────────────────────────────────────────────────────
# DIAGNOSTIC
# ─────────────────────────────────────────────────────────────

def print_validation_result(result: dict, home_team: str, away_team: str):
    """Print a human-readable validation summary."""
    print(f"\n  📊 Validation: {away_team} @ {home_team}")
    print(f"  Home confidence : {result['home_confidence']}")
    print(f"  Away confidence : {result['away_confidence']}")
    if result["espn_home_prob"] is not None:
        d = result["divergence"]
        print(f"  ESPN home prob  : {result['espn_home_prob']}%")
        print(f"  Divergence      : {d['gap']} pts ({d['direction']})")
    else:
        print(f"  ESPN home prob  : Not available")
    if result["suppress"]:
        print(f"  ⚠ SUPPRESSED   : {result['suppress_reason']}")
    else:
        print(f"  ✅ CLEAR TO POST")


if __name__ == "__main__":
    # Quick test
    for league in ["WNBA", "NBA", "NCAAB"]:
        probs = get_espn_win_probs(league)
        print(f"\n{league} — {len(probs)} games with win prob data")
        for matchup, data in list(probs.items())[:3]:
            print(f"  {matchup}: Home {data['home_prob']}% | Away {data['away_prob']}%")