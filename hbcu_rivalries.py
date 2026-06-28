"""
hbcu_rivalries.py — Culture & Pulse Analytics
===============================================
HBCU rivalry records, cultural context, and "Did You Know" facts.
Used by hbcu_predict.py to enrich game previews with storytelling.

To use in hbcu_predict.py:
    from hbcu_rivalries import get_rivalry_context
    context = get_rivalry_context(home_team, away_team, sport_key)
    if context:
        alert += context["telegram_block"]
"""

# ── All-time H2H records ──────────────────────────────────────────────────────
# Format: frozenset({team_a, team_b}): (leader, leader_wins, trailer_wins, rivalry_name)
# Update wins manually each season end.

HBCU_H2H_RECORDS = {

    # ── SWAC Football Classic Rivalries ──────────────────────────────────────
    frozenset({"Grambling State Tigers", "Southern Jaguars"}): (
        "Grambling State Tigers", 45, 34,
        "Bayou Classic",
        "Played annually in the Mercedes-Benz Superdome in New Orleans. One of the most-attended HBCU games in history. Dr. Ralph Waldo Emerson Jones built Grambling into a national name — 'The Grambling Way' is a documentary, a legacy, and a standard."
    ),
    frozenset({"Alabama State Hornets", "Alabama A&M Bulldogs"}): (
        "Alabama State Hornets", 38, 32,
        "Magic City Classic",
        "Played in Birmingham's Legion Field. The largest HBCU football game in the country by attendance — regularly drawing 70,000+. This isn't just a game. It's homecoming for an entire state."
    ),
    frozenset({"Alabama State Hornets", "Tuskegee Golden Tigers"}): (
        "Alabama State Hornets", 42, 38,
        "Turkey Day Classic",
        "One of the oldest HBCU rivalries in football, played on Thanksgiving since 1924. Tuskegee was founded by Booker T. Washington. The history on this field runs deeper than the scoreboard."
    ),
    frozenset({"Jackson State Tigers", "Alcorn State Braves"}): (
        "Jackson State Tigers", 44, 28,
        "Soul Bowl",
        "Mississippi's premier HBCU rivalry. Jackson State's Vet Village — their student section — is one of the loudest in college football. Alcorn State produced Steve McNair, one of the greatest QBs to ever play the game."
    ),
    frozenset({"Southern Jaguars", "Grambling State Tigers"}): (
        "Grambling State Tigers", 45, 34,
        "Bayou Classic",
        "Played annually in the Mercedes-Benz Superdome in New Orleans. One of the most-attended HBCU games in history."
    ),
    frozenset({"Prairie View A&M Panthers", "Grambling State Tigers"}): (
        "Grambling State Tigers", 38, 22,
        "Prairie View–Grambling Classic",
        "Two historic SWAC programs with deep NFL pipelines. Grambling's Eddie Robinson coached for 57 years and won 408 games. That legacy lives in every matchup."
    ),
    frozenset({"Texas Southern Tigers", "Prairie View A&M Panthers"}): (
        "Texas Southern Tigers", 35, 28,
        "Prairie View–Texas Southern Classic",
        "The Houston HBCU rivalry. Both schools are in the nation's fourth-largest city — this game matters to an entire metropolitan community."
    ),
    frozenset({"Jackson State Tigers", "Southern Jaguars"}): (
        "Jackson State Tigers", 32, 28,
        "Jackson State–Southern Classic",
        "Two SWAC powerhouses. Jackson State's Shedeur Sanders era put the program on a national stage. The NFL talent pipeline from both schools runs deep."
    ),

    # ── MEAC Football Rivalries ───────────────────────────────────────────────
    frozenset({"Howard Bison", "Morgan State Bears"}): (
        "Howard Bison", 28, 24,
        "Howard–Morgan Classic",
        "The DC-Baltimore HBCU rivalry. Howard University produced Thurgood Marshall, Kamala Harris, and Chadwick Boseman. Morgan State is the pride of Baltimore. When these two meet, both cities watch."
    ),
    frozenset({"North Carolina A&T Aggies", "North Carolina Central Eagles"}): (
        "North Carolina A&T Aggies", 42, 30,
        "Aggie–Eagle Classic",
        "One of the oldest HBCU rivalries in the South. NC A&T was the school where the Greensboro Four — the students who launched the lunch counter sit-ins of 1960 — were enrolled. The Aggie–Eagle Classic carries that weight."
    ),
    frozenset({"Florida A&M Rattlers", "Bethune-Cookman Wildcats"}): (
        "Florida A&M Rattlers", 44, 32,
        "Florida Classic",
        "Played in Orlando's Camping World Stadium. The Florida Classic is the highest-attended HBCU game in the country — drawing up to 75,000 fans. FAMU's Marching 100 is widely considered the greatest college marching band in America."
    ),
    frozenset({"Hampton Pirates", "Norfolk State Spartans"}): (
        "Hampton Pirates", 30, 26,
        "Battle of the Bay",
        "The Hampton Roads rivalry. Hampton University's waterfront campus is one of the most beautiful in the country. Norfolk State's Spartan Legion band is appointment television."
    ),
    frozenset({"Delaware State Hornets", "Morgan State Bears"}): (
        "Morgan State Bears", 28, 22,
        "Delaware State–Morgan State Classic",
        "Two MEAC programs with strong academic reputations. Morgan State is Baltimore's public HBCU — a cornerstone of the city's Black professional community."
    ),

    # ── SWAC Basketball Rivalries ─────────────────────────────────────────────
    frozenset({"Southern Jaguars", "Grambling State Tigers"}): (
        "Grambling State Tigers", 52, 38,
        "Bayou Classic Basketball",
        "The basketball extension of one of HBCU sports' greatest rivalries. Grambling's Willis Reed — NBA Hall of Famer and two-time champion — put SWAC basketball on the national map."
    ),
    frozenset({"Jackson State Tigers", "Alcorn State Braves"}): (
        "Jackson State Tigers", 48, 32,
        "Soul Bowl Basketball",
        "Mississippi's top HBCU basketball rivalry. Alcorn State's Steve McNair was a two-sport star before focusing on football. The athletic tradition at both schools goes beyond any one sport."
    ),
    frozenset({"Texas Southern Tigers", "Prairie View A&M Panthers"}): (
        "Texas Southern Tigers", 44, 36,
        "Houston HBCU Basketball Classic",
        "Two Houston-area schools competing for city pride. Texas Southern's Yates Gym is one of the loudest arenas in college basketball when it's rocking."
    ),

    # ── MEAC Basketball Rivalries ─────────────────────────────────────────────
    frozenset({"Howard Bison", "Hampton Pirates"}): (
        "Howard Bison", 38, 30,
        "Howard–Hampton Basketball Classic",
        "The DC-Hampton Roads showdown. Howard's basketball program produced some of the finest athletes to come out of the DMV. The rivalry is intense, the crowds are electric."
    ),
    frozenset({"Florida A&M Rattlers", "Bethune-Cookman Wildcats"}): (
        "Florida A&M Rattlers", 48, 36,
        "Florida Classic Basketball",
        "The Florida HBCU basketball rivalry mirrors the football intensity. FAMU's campus in Tallahassee and Bethune-Cookman's in Daytona Beach — two Florida institutions, one unforgettable rivalry."
    ),
    frozenset({"North Carolina A&T Aggies", "North Carolina Central Eagles"}): (
        "North Carolina A&T Aggies", 46, 34,
        "Aggie–Eagle Basketball Classic",
        "NC A&T and NC Central both sit in the Research Triangle — one of the most educated regions in America. This game represents two institutions that have shaped Black academic and professional life in North Carolina for over a century."
    ),
}


# ── Classic game facts and "Did You Know" content ────────────────────────────
HBCU_DID_YOU_KNOW = {
    "Bayou Classic": [
        "The Bayou Classic has been played in the Mercedes-Benz Superdome since 1974 — drawing over 70,000 fans annually.",
        "Grambling State's Eddie Robinson coached for 57 seasons and won 408 games — the most in college football history at the time of his retirement.",
        "The Bayou Classic isn't just a game. It's a weekend — concerts, the Battle of the Bands, and a parade through New Orleans.",
    ],
    "Magic City Classic": [
        "The Magic City Classic regularly draws 70,000+ fans to Legion Field in Birmingham — making it the largest HBCU game by attendance in the country.",
        "Alabama A&M and Alabama State are 90 miles apart but worlds apart in rivalry intensity. Birmingham becomes an HBCU capital for one weekend every fall.",
    ],
    "Turkey Day Classic": [
        "The Turkey Day Classic has been played on Thanksgiving since 1924 — one of the oldest continuous HBCU rivalries in the country.",
        "Tuskegee University was founded by Booker T. Washington in 1881. The athletic tradition on that campus is older than most college football programs.",
    ],
    "Soul Bowl": [
        "Alcorn State produced Steve McNair — 2003 NFL MVP, Super Bowl XXXIV starter, and one of the greatest quarterbacks of his generation.",
        "Jackson State's 'Sonic Boom of the South' marching band is one of the most celebrated in HBCU sports.",
    ],
    "Florida Classic": [
        "The Florida Classic is the highest-attended HBCU game in the country — drawing up to 75,000 fans to Camping World Stadium in Orlando.",
        "FAMU's Marching 100 is widely considered the greatest college marching band in America. The halftime show alone is worth the price of admission.",
        "Bethune-Cookman was founded by Mary McLeod Bethune in 1904 — one of the most important educators and civil rights leaders in American history.",
    ],
    "Aggie-Eagle Classic": [
        "NC A&T's campus is where the Greensboro Four — the students who launched the 1960 lunch counter sit-ins — were enrolled. The Aggie–Eagle Classic carries that history.",
        "North Carolina Central University School of Law has produced some of the most influential Black attorneys and judges in the South.",
    ],
    "Battle of the Bay": [
        "Hampton University's waterfront campus on the Chesapeake Bay is one of the most beautiful in the country.",
        "Norfolk State's Spartan Legion marching band is one of the most respected in MEAC competition.",
    ],
}


def get_rivalry_context(home_team: str, away_team: str, sport_key: str = "") -> dict | None:
    """
    Returns rivalry context dict for a matchup, or None if no rivalry found.

    Returns:
        {
            "rivalry_name": str,
            "leader": str,
            "leader_wins": int,
            "trailer_wins": int,
            "series_str": str,         # e.g. "Grambling leads 45-34"
            "cultural_story": str,
            "did_you_know": str,       # random fact from the classic
            "telegram_block": str,     # formatted Telegram text block
        }
    """
    import random
    key = frozenset({home_team, away_team})
    rec = HBCU_H2H_RECORDS.get(key)
    if not rec:
        return None

    leader, leader_wins, trailer_wins, rivalry_name, cultural_story = rec

    if leader_wins == trailer_wins:
        series_str = f"All-Time Series: Tied {leader_wins}-{trailer_wins}"
    else:
        trailer = away_team if leader == home_team else home_team
        series_str = f"All-Time Series: {leader} leads {leader_wins}-{trailer_wins}"

    # Pick a random Did You Know fact if available
    facts = HBCU_DID_YOU_KNOW.get(rivalry_name, [])
    did_you_know = random.choice(facts) if facts else ""

    telegram_block = (
        f"\n📜 <b>{rivalry_name}</b>\n"
        f"📊 {series_str}\n"
        f"\n✊ <b>The Story</b>\n"
        f"{cultural_story}"
    )
    if did_you_know:
        telegram_block += f"\n\n💡 <b>Did You Know?</b>\n{did_you_know}"

    return {
        "rivalry_name":  rivalry_name,
        "leader":        leader,
        "leader_wins":   leader_wins,
        "trailer_wins":  trailer_wins,
        "series_str":    series_str,
        "cultural_story": cultural_story,
        "did_you_know":  did_you_know,
        "telegram_block": telegram_block,
    }


def list_rivalries(sport_key: str = "") -> list:
    """Print all known rivalries, optionally filtered by sport."""
    rivalries = []
    for teams, rec in HBCU_H2H_RECORDS.items():
        leader, lw, tw, name, _ = rec
        teams_list = list(teams)
        rivalries.append({
            "rivalry_name": name,
            "teams":        teams_list,
            "series":       f"{leader} leads {lw}-{tw}" if lw != tw else f"Tied {lw}-{tw}",
        })
    return rivalries


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        home = sys.argv[1]
        away = sys.argv[2]
        ctx  = get_rivalry_context(home, away)
        if ctx:
            print(ctx["telegram_block"])
        else:
            print(f"No rivalry record found for {home} vs {away}")
    else:
        print("Known HBCU Rivalries:")
        for r in list_rivalries():
            print(f"  {r['rivalry_name']}: {r['series']}")
            print(f"    {r['teams'][0]} vs {r['teams'][1]}")
