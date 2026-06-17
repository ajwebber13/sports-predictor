"""
hbcu_teams.py - Culture & Pulse Analytics
Master registry of HBCU teams across MEAC and SWAC conferences,
covering football, men's basketball, and women's basketball.

Team IDs confirmed against ESPN's team list endpoints.
Conference tags help with content/filtering later (e.g. MEAC-only
recaps, SWAC-only picks, Bayou Classic / Turkey Day Classic content).
"""

# ─────────────────────────────────────────────────────────────
# FOOTBALL - MEAC and SWAC (FCS level)
# ─────────────────────────────────────────────────────────────

HBCU_FOOTBALL_TEAMS = {
    # SWAC
    "Alabama A&M Bulldogs":              {"id": "2010", "conf": "SWAC"},
    "Alabama State Hornets":             {"id": "2011", "conf": "SWAC"},
    "Alcorn State Braves":               {"id": "2016", "conf": "SWAC"},
    "Arkansas-Pine Bluff Golden Lions":  {"id": "2029", "conf": "SWAC"},
    "Bethune-Cookman Wildcats":          {"id": "2065", "conf": "SWAC"},
    "Florida A&M Rattlers":              {"id": "50",   "conf": "SWAC"},
    "Grambling Tigers":                  {"id": "2755", "conf": "SWAC"},
    "Jackson State Tigers":              {"id": "2296", "conf": "SWAC"},
    "Mississippi Valley State Delta Devils": {"id": "2400", "conf": "SWAC"},
    "Prairie View A&M Panthers":         {"id": "2504", "conf": "SWAC"},
    "Southern Jaguars":                  {"id": "2582", "conf": "SWAC"},
    "Texas Southern Tigers":             {"id": "2640", "conf": "SWAC"},
    "Tennessee State Tigers":            {"id": "2634", "conf": "SWAC"},

    # MEAC
    "Delaware State Hornets":            {"id": "2169", "conf": "MEAC"},
    "Hampton Pirates":                   {"id": "2261", "conf": "MEAC"},
    "Howard Bison":                      {"id": "47",   "conf": "MEAC"},
    "Morgan State Bears":                {"id": "2415", "conf": "MEAC"},
    "Norfolk State Spartans":            {"id": "2450", "conf": "MEAC"},
    "North Carolina Central Eagles":     {"id": "2428", "conf": "MEAC"},
    "South Carolina State Bulldogs":     {"id": "2569", "conf": "MEAC"},
}


# ─────────────────────────────────────────────────────────────
# MEN'S BASKETBALL - MEAC and SWAC
# ─────────────────────────────────────────────────────────────

HBCU_MBB_TEAMS = {
    # SWAC
    "Alabama A&M Bulldogs":              {"id": "2010", "conf": "SWAC"},
    "Alabama State Hornets":             {"id": "2011", "conf": "SWAC"},
    "Alcorn State Braves":               {"id": "2016", "conf": "SWAC"},
    "Arkansas-Pine Bluff Golden Lions":  {"id": "2029", "conf": "SWAC"},
    "Bethune-Cookman Wildcats":          {"id": "2065", "conf": "SWAC"},
    "Florida A&M Rattlers":              {"id": "50",   "conf": "SWAC"},
    "Grambling Tigers":                  {"id": "2755", "conf": "SWAC"},
    "Jackson State Tigers":              {"id": "2296", "conf": "SWAC"},
    "Mississippi Valley State Delta Devils": {"id": "2400", "conf": "SWAC"},
    "Prairie View A&M Panthers":         {"id": "2504", "conf": "SWAC"},
    "Southern Jaguars":                  {"id": "2582", "conf": "SWAC"},
    "Texas Southern Tigers":             {"id": "2640", "conf": "SWAC"},
    "Tennessee State Tigers":            {"id": "2634", "conf": "SWAC"},

    # MEAC
    "Coppin State Eagles":               {"id": "2154", "conf": "MEAC"},
    "Delaware State Hornets":            {"id": "2169", "conf": "MEAC"},
    "Hampton Pirates":                   {"id": "2261", "conf": "MEAC"},
    "Howard Bison":                      {"id": "47",   "conf": "MEAC"},
    "Maryland Eastern Shore Hawks":      {"id": "2379", "conf": "MEAC"},
    "Morgan State Bears":                {"id": "2415", "conf": "MEAC"},
    "Norfolk State Spartans":            {"id": "2450", "conf": "MEAC"},
    "North Carolina Central Eagles":     {"id": "2428", "conf": "MEAC"},
    "South Carolina State Bulldogs":     {"id": "2569", "conf": "MEAC"},
}


# ─────────────────────────────────────────────────────────────
# WOMEN'S BASKETBALL - MEAC and SWAC
# Team IDs typically match men's IDs on ESPN for the same school,
# but the women's basketball sport path resolves them independently.
# Will verify and adjust during backfill if any IDs differ.
# ─────────────────────────────────────────────────────────────

HBCU_WBB_TEAMS = {
    # SWAC
    "Alabama A&M Bulldogs":              {"id": "2010", "conf": "SWAC"},
    "Alabama State Hornets":             {"id": "2011", "conf": "SWAC"},
    "Alcorn State Braves":               {"id": "2016", "conf": "SWAC"},
    "Arkansas-Pine Bluff Golden Lions":  {"id": "2029", "conf": "SWAC"},
    "Bethune-Cookman Wildcats":          {"id": "2065", "conf": "SWAC"},
    "Florida A&M Rattlers":              {"id": "50",   "conf": "SWAC"},
    "Grambling Tigers":                  {"id": "2755", "conf": "SWAC"},
    "Jackson State Tigers":              {"id": "2296", "conf": "SWAC"},
    "Mississippi Valley State Delta Devils": {"id": "2400", "conf": "SWAC"},
    "Prairie View A&M Panthers":         {"id": "2504", "conf": "SWAC"},
    "Southern Jaguars":                  {"id": "2582", "conf": "SWAC"},
    "Texas Southern Tigers":             {"id": "2640", "conf": "SWAC"},
    "Tennessee State Tigers":            {"id": "2634", "conf": "SWAC"},

    # MEAC
    "Coppin State Eagles":               {"id": "2154", "conf": "MEAC"},
    "Delaware State Hornets":            {"id": "2169", "conf": "MEAC"},
    "Hampton Pirates":                   {"id": "2261", "conf": "MEAC"},
    "Howard Bison":                      {"id": "47",   "conf": "MEAC"},
    "Maryland Eastern Shore Hawks":      {"id": "2379", "conf": "MEAC"},
    "Morgan State Bears":                {"id": "2415", "conf": "MEAC"},
    "Norfolk State Spartans":            {"id": "2450", "conf": "MEAC"},
    "North Carolina Central Eagles":     {"id": "2428", "conf": "MEAC"},
    "South Carolina State Bulldogs":     {"id": "2569", "conf": "MEAC"},
}


def get_team_registry(sport: str) -> dict:
    """Returns the team ID/conference registry for a given HBCU sport."""
    registries = {
        "hbcu_football": HBCU_FOOTBALL_TEAMS,
        "hbcu_mbb":       HBCU_MBB_TEAMS,
        "hbcu_wbb":       HBCU_WBB_TEAMS,
    }
    return registries.get(sport, {})


def get_conference(team_name: str, sport: str) -> str:
    """Returns MEAC or SWAC for a given team, or empty string if unknown."""
    registry = get_team_registry(sport)
    info     = registry.get(team_name)
    return info["conf"] if info else ""


if __name__ == "__main__":
    print(f"HBCU Football teams: {len(HBCU_FOOTBALL_TEAMS)}")
    print(f"HBCU Men's Basketball teams: {len(HBCU_MBB_TEAMS)}")
    print(f"HBCU Women's Basketball teams: {len(HBCU_WBB_TEAMS)}")
