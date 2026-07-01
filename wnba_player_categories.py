"""
wnba_player_categories.py — Culture & Pulse Analytics
=======================================================
Maps each tracked WNBA player to their primary stat category
(scorer / rebounder / playmaker), based on 2026 season averages.

Used by prop_hit_rates.py to downgrade confidence on "off-role" props —
e.g. a PTS prop on a player whose primary value is rebounding or
playmaking is inherently more volatile than a PTS prop on a true scorer.

Player names must match the exact spelling used in wnba_game_log
(same convention as WNBA_STAR_PLAYERS in wnba_slate_digest.py).

Data snapshot: June 30, 2026 (10-16 GP sample per player). Revisit
mid-season and after the All-Star break — roles and minutes shift.
"""

WNBA_PLAYER_CATEGORY = {
    # Las Vegas Aces
    "A'ja Wilson":       {"team": "Las Vegas Aces", "categories": ["scorer", "rebounder"]},
    "Chelsea Gray":       {"team": "Las Vegas Aces", "categories": ["playmaker"]},
    "Jackie Young":       {"team": "Las Vegas Aces", "categories": ["scorer", "playmaker"]},

    # Los Angeles Sparks
    "Kelsey Plum":        {"team": "Los Angeles Sparks", "categories": ["scorer", "playmaker"]},
    "Nneka Ogwumike":     {"team": "Los Angeles Sparks", "categories": ["rebounder"]},

    # Toronto Tempo
    "Brittney Sykes":     {"team": "Toronto Tempo", "categories": ["scorer"]},
    "Marina Mabrey":      {"team": "Toronto Tempo", "categories": ["scorer", "playmaker"]},

    # Indiana Fever
    "Caitlin Clark":      {"team": "Indiana Fever", "categories": ["scorer", "playmaker"]},
    "Aliyah Boston":      {"team": "Indiana Fever", "categories": ["rebounder"]},
    "Kelsey Mitchell":    {"team": "Indiana Fever", "categories": ["scorer"]},

    # New York Liberty
    "Breanna Stewart":    {"team": "New York Liberty", "categories": ["scorer", "rebounder"]},
    "Jonquel Jones":      {"team": "New York Liberty", "categories": ["rebounder"]},

    # Atlanta Dream
    "Allisha Gray":       {"team": "Atlanta Dream", "categories": ["scorer"]},
    "Angel Reese":        {"team": "Atlanta Dream", "categories": ["rebounder"]},
    "Rhyne Howard":       {"team": "Atlanta Dream", "categories": ["scorer", "playmaker"]},

    # Dallas Wings
    "Paige Bueckers":     {"team": "Dallas Wings", "categories": ["scorer", "playmaker"]},
    "Arike Ogunbowale":   {"team": "Dallas Wings", "categories": ["scorer"]},
    "Azzi Fudd":          {"team": "Dallas Wings", "categories": ["scorer"]},

    # Phoenix Mercury
    "Kahleah Copper":     {"team": "Phoenix Mercury", "categories": ["scorer"]},
    "Alyssa Thomas":      {"team": "Phoenix Mercury", "categories": ["rebounder", "playmaker"]},

    # Minnesota Lynx
    "Olivia Miles":       {"team": "Minnesota Lynx", "categories": ["scorer", "playmaker"]},
    "Kayla McBride":      {"team": "Minnesota Lynx", "categories": ["scorer"]},

    # Washington Mystics
    "Sonia Citron":       {"team": "Washington Mystics", "categories": ["scorer"]},
    "Shakira Austin":     {"team": "Washington Mystics", "categories": ["rebounder"]},

    # Golden State Valkyries
    "Veronica Burton":    {"team": "Golden State Valkyries", "categories": ["playmaker"]},

    # Chicago Sky
    "Skylar Diggins":     {"team": "Chicago Sky", "categories": ["scorer", "playmaker"]},
    "Kamilla Cardoso":    {"team": "Chicago Sky", "categories": ["rebounder"]},  # unverified REB — confirm before relying on it

    # Seattle Storm
    "Natisha Hiedeman":   {"team": "Seattle Storm", "categories": ["scorer", "playmaker"]},

    # Connecticut Sun
    # (no scorer/playmaker with reliable sample yet — small sample size league-wide for CON)

    # Portland Fire (expansion team — thin sample, revisit after more games)
    "Bridget Carleton":   {"team": "Portland Fire", "categories": ["scorer"]},
}


def get_categories(player_name: str) -> list:
    """Return this player's primary stat categories, or [] if untracked."""
    return WNBA_PLAYER_CATEGORY.get(player_name, {}).get("categories", [])


def is_off_role(player_name: str, stat: str) -> bool:
    """
    True if this stat isn't one of the player's primary categories.
    stat: "pts", "reb", or "ast" (maps to scorer/rebounder/playmaker)
    Untracked players return False (no penalty — insufficient info either way).
    """
    stat_to_category = {"pts": "scorer", "reb": "rebounder", "ast": "playmaker"}
    target = stat_to_category.get(stat)
    if not target:
        return False
    categories = get_categories(player_name)
    if not categories:
        return False
    return target not in categories
