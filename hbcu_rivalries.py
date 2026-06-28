"""
hbcu_rivalries.py — Culture & Pulse Analytics
===============================================
HBCU rivalry records, classic game context, and cultural storytelling.
Used by hbcu_predict.py to enrich game previews.

Usage:
    from hbcu_rivalries import get_rivalry_context
    ctx = get_rivalry_context(home_team, away_team, sport_key)
    if ctx:
        print(ctx["telegram_block"])

    # List all known rivalries
    python hbcu_rivalries.py
    # Look up a specific matchup
    python hbcu_rivalries.py "Jackson State Tigers" "Alabama A&M Bulldogs" hbcu_football
"""

# ── Football H2H records ──────────────────────────────────────────────────────
# Format: frozenset({team_a, team_b}):
#   (leader, leader_wins, trailer_wins, classic_name, cultural_story)

HBCU_H2H_FOOTBALL = {

    # ══════════════════════════════════════════════════════
    # SWAC FOOTBALL — SIGNATURE CLASSICS
    # ══════════════════════════════════════════════════════

    frozenset({"Grambling State Tigers", "Southern Jaguars"}): (
        "Grambling State Tigers", 45, 34,
        "Bayou Classic",
        "Played annually in the Mercedes-Benz Superdome in New Orleans since 1974. The first game drew 76,000 fans. Eddie Robinson coached Grambling for 57 seasons and won 408 games — the most in college football history at the time of his retirement. The Bayou Classic is not just a game. It is a weekend — Battle of the Bands, concerts, a parade through New Orleans, and two of the most storied programs in HBCU history."
    ),

    frozenset({"Alabama State Hornets", "Alabama A&M Bulldogs"}): (
        "Alabama State Hornets", 38, 32,
        "Magic City Classic",
        "Played in Birmingham's Legion Field — the largest HBCU football game in the country by attendance, regularly drawing 70,000+. Birmingham becomes an HBCU capital for one weekend every fall. This game represents two institutions separated by 90 miles but united by a rivalry that defines Alabama's Black college sports culture."
    ),

    frozenset({"Alabama State Hornets", "Tuskegee Golden Tigers"}): (
        "Alabama State Hornets", 42, 38,
        "Turkey Day Classic",
        "One of the oldest HBCU rivalries in the country, played on Thanksgiving since 1924. Tuskegee University was founded by Booker T. Washington in 1881. The history on this field runs deeper than any scoreboard. The Turkey Day Classic predates the NFL's Thanksgiving games and has outlasted many of them in cultural significance."
    ),

    frozenset({"Jackson State Tigers", "Alcorn State Braves"}): (
        "Jackson State Tigers", 44, 28,
        "Soul Bowl",
        "Mississippi's premier HBCU rivalry. Jackson State's Vet Village student section is one of the loudest in college football. Alcorn State produced Steve McNair — 2003 NFL MVP, Super Bowl XXXIV starter — one of the greatest quarterbacks to ever play the game. Jackson State's Shedeur Sanders era put the program on a national stage. The Soul Bowl has always been bigger than Mississippi."
    ),

    frozenset({"Jackson State Tigers", "Alabama A&M Bulldogs"}): (
        "Jackson State Tigers", 32, 18,
        "Gulf Coast Challenge",
        "Played at Ladd-Peebles Stadium in Mobile, Alabama — a city with deep roots in Black college sports history. The Gulf Coast Challenge is the ultimate HBCU experience: three days of culture, competition, and community. Concerts, a parade, a college and career fair, HBCU Fest, and then the game. Mobile has hosted HBCU football since 2016 and has turned this classic into a regional economic engine. Jackson State and Alabama A&M have a long track record of delivering electric games."
    ),

    frozenset({"Alabama State Hornets", "Mississippi Valley State Delta Devils"}): (
        "Alabama State Hornets", 22, 14,
        "Port City Classic",
        "Played at Ladd-Peebles Stadium in Mobile, Alabama. The Port City Classic is Mobile's HBCU cultural celebration — complete with a Mardi Gras-style parade, HBCU Summit, and tailgating experience. Mobile has deep roots in Black college sports history, and the Port City Classic is the city's signature HBCU event."
    ),

    frozenset({"Prairie View A&M Panthers", "Grambling State Tigers"}): (
        "Grambling State Tigers", 38, 22,
        "Prairie View–Grambling Classic",
        "Two of SWAC's most historic programs. Grambling's Eddie Robinson built the blueprint for HBCU football as a cultural event. Prairie View A&M holds the record for the longest losing streak in college football history — 80 games from 1989 to 1998 — and then won a national championship. The comeback story is part of the legacy."
    ),

    frozenset({"Texas Southern Tigers", "Prairie View A&M Panthers"}): (
        "Texas Southern Tigers", 35, 28,
        "Houston HBCU Classic",
        "The Houston HBCU rivalry. Both schools are in the nation's fourth-largest city — this game matters to an entire metropolitan community. Texas Southern's campus sits in Houston's historic Third Ward, one of the most culturally significant Black neighborhoods in America."
    ),

    frozenset({"Jackson State Tigers", "Southern Jaguars"}): (
        "Jackson State Tigers", 32, 28,
        "Jackson State–Southern Classic",
        "Two SWAC powerhouses. Jackson State's Shedeur Sanders era brought national attention to HBCU football in a way not seen since Eddie Robinson's Grambling dynasty. Southern's Jaguar Nation is one of the most passionate fan bases in college football. This matchup draws fans from across the South."
    ),

    frozenset({"Southern Jaguars", "Texas Southern Tigers"}): (
        "Southern Jaguars", 30, 22,
        "Southern Heritage Classic",
        "Played in Memphis, Tennessee — the Southern Heritage Classic brings SWAC football to the Mid-South. Memphis has a deep connection to Black culture and history, and the Southern Heritage Classic fits naturally into that tradition. One of the newer major HBCU classics but growing in attendance and cultural impact every year."
    ),

    frozenset({"Grambling State Tigers", "Texas Southern Tigers"}): (
        "Grambling State Tigers", 28, 20,
        "Grambling–Texas Southern Classic",
        "Grambling State's legacy stretches from Louisiana to the NFL. Over 200 Grambling players have made it to the pros. Texas Southern produced NFL players and civil rights history — the school's law school is one of the most respected HBCU professional programs in the country."
    ),

    # ══════════════════════════════════════════════════════
    # MEAC FOOTBALL — SIGNATURE CLASSICS
    # ══════════════════════════════════════════════════════

    frozenset({"Florida A&M Rattlers", "Bethune-Cookman Wildcats"}): (
        "Florida A&M Rattlers", 44, 32,
        "Florida Classic",
        "Played at Camping World Stadium in Orlando — the Florida Classic is the highest-attended HBCU game in the country, drawing up to 75,000 fans. FAMU's Marching 100 is widely considered the greatest college marching band in America. Bethune-Cookman was founded by Mary McLeod Bethune in 1904, one of the most important educators and civil rights leaders in American history. The Florida Classic is HBCU football at its absolute peak."
    ),

    frozenset({"North Carolina A&T Aggies", "North Carolina Central Eagles"}): (
        "North Carolina A&T Aggies", 42, 30,
        "Aggie–Eagle Classic",
        "NC A&T's campus is where the Greensboro Four — the students who launched the 1960 lunch counter sit-ins — were enrolled. That history lives in every Aggie–Eagle Classic. North Carolina Central's law school has produced some of the most influential Black attorneys and judges in the South. Two institutions that have shaped Black academic and professional life in North Carolina for over a century."
    ),

    frozenset({"Howard Bison", "Hampton Pirates"}): (
        "Howard Bison", 30, 26,
        "Battle of the Real HU",
        "DC vs Hampton Roads. Howard University is the most prominent HBCU in America — producing Thurgood Marshall, Kamala Harris, Chadwick Boseman, Toni Morrison, and countless others. Hampton University's waterfront campus is one of the most beautiful in the country. When these two meet at Audi Field in Washington DC, both cities show up."
    ),

    frozenset({"Howard Bison", "Morgan State Bears"}): (
        "Howard Bison", 28, 24,
        "Howard–Morgan Classic",
        "The DC-Baltimore HBCU rivalry. Howard produced Thurgood Marshall — the first Black Supreme Court Justice. Morgan State is the pride of Baltimore and one of the most respected research HBCUs in the country. This rivalry connects two of the most important cities on the East Coast."
    ),

    frozenset({"Hampton Pirates", "Norfolk State Spartans"}): (
        "Hampton Pirates", 30, 26,
        "Battle of the Bay",
        "The Hampton Roads rivalry. Hampton University's waterfront campus and Norfolk State's urban Spartan Nation represent two different faces of the same community. Norfolk State's Spartan Legion marching band is appointment television. The Battle of the Bay fills the stands with two fan bases that never need an excuse to show out."
    ),

    frozenset({"South Carolina State Bulldogs", "Florida A&M Rattlers"}): (
        "Florida A&M Rattlers", 26, 24,
        "Palmetto Capital City Classic",
        "South Carolina State and Florida A&M represent two of the most storied MEAC programs. SC State produced NFL Hall of Famers and has one of the most passionate fan bases in Black college football. FAMU's Marching 100 turns every game into a show. When these two meet, the bands alone are worth the trip."
    ),

    frozenset({"Morgan State Bears", "North Carolina A&T Aggies"}): (
        "North Carolina A&T Aggies", 24, 20,
        "Morgan State–NC A&T Classic",
        "Two of MEAC's most competitive programs. Morgan State is Baltimore's public HBCU — a cornerstone of the city's Black professional community. NC A&T is the largest HBCU in the country. This matchup represents two institutions with national footprints and deeply loyal alumni bases."
    ),

    frozenset({"Tennessee State Tigers", "Florida A&M Rattlers"}): (
        "Florida A&M Rattlers", 18, 16,
        "Tennessee State–FAMU Classic",
        "Tennessee State University in Nashville — home of the John A. Merritt Classic — is one of HBCU football's most historic programs. Coach John Merritt won three national championships and built TSU into a national powerhouse in the 1960s and 70s. FAMU brings the Marching 100. Nashville vs Tallahassee — two HBCU capitals collide."
    ),

    frozenset({"Tuskegee Golden Tigers", "Fort Valley State Wildcats"}): (
        "Tuskegee Golden Tigers", 28, 18,
        "Port City Classic",
        "Played at Ladd-Peebles Stadium in Mobile, Alabama. The Port City Classic rotates opponents and in 2026 features Tuskegee vs Fort Valley State — two SIAC powerhouses bringing their rivalry to the Gulf Coast. Mobile's Mardi Gras-style parade, HBCU Summit, and tailgating experience surround the game."
    ),

    # ══════════════════════════════════════════════════════
    # CHAMPIONSHIP GAMES
    # ══════════════════════════════════════════════════════

    frozenset({"MEAC Champion", "SWAC Champion"}): (
        "SWAC Champion", 7, 4,
        "Celebration Bowl",
        "The HBCU national championship game, played in Atlanta's Mercedes-Benz Stadium. The Celebration Bowl pits the MEAC champion against the SWAC champion — the biggest game in Black college football. Atlanta's Black community turns out in force. The halftime show featuring both conference bands is one of the greatest spectacles in all of college sports."
    ),
}


# ── Basketball H2H records ────────────────────────────────────────────────────
HBCU_H2H_BASKETBALL = {

    frozenset({"Howard Bison", "Hampton Pirates"}): (
        "Howard Bison", 38, 30,
        "Howard–Hampton Basketball Classic",
        "The DC-Hampton Roads basketball showdown. Howard's basketball program has produced some of the finest athletes from the DMV. The rivalry is intense, the crowds are electric, and the trash talk between DC and Hampton Roads fans is legendary."
    ),

    frozenset({"Florida A&M Rattlers", "Bethune-Cookman Wildcats"}): (
        "Florida A&M Rattlers", 48, 36,
        "Florida Classic Basketball",
        "The Florida HBCU basketball rivalry mirrors the football intensity. FAMU's campus in Tallahassee and Bethune-Cookman's in Daytona Beach — two Florida institutions separated by 250 miles but united by one of the fiercest rivalries in MEAC basketball."
    ),

    frozenset({"North Carolina A&T Aggies", "North Carolina Central Eagles"}): (
        "North Carolina A&T Aggies", 46, 34,
        "Aggie–Eagle Basketball Classic",
        "NC A&T and NC Central both sit in the Research Triangle — one of the most educated regions in America. This game represents two institutions that have shaped Black academic and professional life in North Carolina for over a century. The basketball version carries the same intensity as the football classic."
    ),

    frozenset({"Southern Jaguars", "Grambling State Tigers"}): (
        "Grambling State Tigers", 52, 38,
        "Bayou Classic Basketball",
        "The basketball chapter of one of HBCU sports' greatest rivalries. Grambling's Willis Reed — NBA Hall of Famer and two-time champion with the New York Knicks — put SWAC basketball on the national map. The Bayou Classic energy translates from football to hardwood without missing a beat."
    ),

    frozenset({"Jackson State Tigers", "Alcorn State Braves"}): (
        "Jackson State Tigers", 48, 32,
        "Soul Bowl Basketball",
        "Mississippi's top HBCU basketball rivalry. Alcorn State's Steve McNair was a two-sport star before focusing on football — the athletic tradition at both schools goes beyond any one sport. The Soul Bowl basketball edition carries the same stakes and passion as the football version."
    ),

    frozenset({"Texas Southern Tigers", "Prairie View A&M Panthers"}): (
        "Texas Southern Tigers", 44, 36,
        "Houston HBCU Basketball Classic",
        "Two Houston-area schools competing for city pride. Texas Southern's H&PE Arena is one of the loudest arenas in SWAC basketball when it's rocking. Prairie View A&M's comeback story — from an 80-game losing streak to a national championship — is one of the greatest in all of college sports."
    ),

    frozenset({"Jackson State Tigers", "Southern Jaguars"}): (
        "Jackson State Tigers", 44, 36,
        "SWAC Basketball Rivalry",
        "Two of SWAC's most competitive basketball programs. Jackson State and Southern have met in the SWAC Tournament multiple times — the stakes are always high and the atmosphere is always electric."
    ),

    frozenset({"Alabama State Hornets", "Alabama A&M Bulldogs"}): (
        "Alabama State Hornets", 42, 34,
        "Magic City Classic Basketball",
        "The basketball version of Alabama's biggest HBCU rivalry. Alabama State and Alabama A&M bring the same Magic City energy from Legion Field to the hardwood. Both programs have deep NBA alumni histories and passionate fan bases."
    ),

    frozenset({"Morgan State Bears", "Howard Bison"}): (
        "Howard Bison", 36, 28,
        "Howard–Morgan Basketball Classic",
        "The DC-Baltimore basketball rivalry. Howard and Morgan State represent two of the most important HBCU communities on the East Coast — connected by Amtrak, divided by basketball. The intensity in the stands matches anything in college basketball."
    ),

    frozenset({"Hampton Pirates", "Norfolk State Spartans"}): (
        "Hampton Pirates", 34, 28,
        "Battle of the Bay Basketball",
        "Hampton Roads' premier HBCU basketball rivalry. Hampton and Norfolk State are separated by a bridge-tunnel but united by one of the most intense rivalries in MEAC basketball. The Spartan Legion and Hampton's student section make this one of the loudest environments in the conference."
    ),
}


# ── Did You Know facts ────────────────────────────────────────────────────────
HBCU_DID_YOU_KNOW = {
    "Bayou Classic": [
        "The very first Bayou Classic in 1974 drew 76,000 fans — more than most NFL games that season.",
        "Eddie Robinson coached Grambling for 57 seasons (1941–1997) and won 408 games — the most in college football history at the time of his retirement.",
        "The Bayou Classic Battle of the Bands is so popular it has its own separate ticket event. Some fans come just for the bands.",
        "Grambling has sent over 200 players to the NFL — more than most Power Five programs.",
    ],
    "Magic City Classic": [
        "The Magic City Classic regularly draws 70,000+ fans to Legion Field in Birmingham — the largest HBCU game by attendance in the country.",
        "Birmingham's Legion Field was once called 'the football capital of the South.' The Magic City Classic is why.",
        "Alabama A&M and Alabama State are 90 miles apart but worlds apart in rivalry intensity. The game has been played since 1924.",
    ],
    "Magic City Classic Basketball": [
        "Alabama State and Alabama A&M have combined to produce multiple NBA players — the talent pipeline from Alabama's HBCUs is real.",
        "The Magic City Classic basketball rivalry carries the same weight as the football version — two schools, one city, zero mercy.",
    ],
    "Turkey Day Classic": [
        "The Turkey Day Classic has been played on Thanksgiving since 1924 — one of the oldest continuous HBCU rivalries in the country.",
        "Tuskegee University was founded by Booker T. Washington in 1881 on a former plantation in Alabama. The school's agricultural and engineering programs changed Black America.",
        "The Turkey Day Classic predates the NFL's Thanksgiving games and has outlasted many traditions in college football.",
    ],
    "Soul Bowl": [
        "Alcorn State produced Steve McNair — 2003 NFL MVP, Super Bowl XXXIV starter, and one of the greatest quarterbacks of his generation.",
        "Jackson State's 'Sonic Boom of the South' marching band is considered one of the greatest in HBCU history.",
        "Deion Sanders coached Jackson State from 2020 to 2022, bringing national media attention to HBCU football in a way not seen in decades.",
    ],
    "Soul Bowl Basketball": [
        "Alcorn State's Steve McNair was a two-sport star in college before becoming one of the greatest quarterbacks in NFL history.",
        "Jackson State's basketball program has been a SWAC contender for decades — the Soul Bowl intensity carries from football to hardwood.",
    ],
    "Gulf Coast Challenge": [
        "The Gulf Coast Challenge is played at Ladd-Peebles Stadium in Mobile, Alabama — a city with deep roots in Black college football dating back to 2016.",
        "Mobile's Gulf Coast Challenge spans three days: concerts, a parade, a college and career fair, HBCU Fest, and then the game.",
        "Jackson State vs Alabama A&M at the Gulf Coast Challenge is one of the most anticipated SWAC matchups of the regular season.",
        "The Mobile Sports Authority has hosted 11 HBCU games since bringing Black college football back to the city in 2016.",
    ],
    "Port City Classic": [
        "The Port City Classic features a Mardi Gras-style parade through Mobile — the city that invented Mardi Gras in America.",
        "Mobile, Alabama has hosted HBCU football since 2016 and continues to grow as a destination for Black college sports events.",
    ],
    "Florida Classic": [
        "The Florida Classic is the highest-attended HBCU game in the country — drawing up to 75,000 fans to Camping World Stadium in Orlando.",
        "FAMU's Marching 100 is widely considered the greatest college marching band in America. The halftime show alone is worth the price of admission.",
        "Bethune-Cookman was founded by Mary McLeod Bethune in 1904 — one of the most important educators and civil rights leaders in American history.",
        "The Florida Classic has been played since 1978. It is the Super Bowl of HBCU football in Florida.",
    ],
    "Florida Classic Basketball": [
        "FAMU and Bethune-Cookman have met over 80 times in basketball — one of the most-played rivalries in MEAC history.",
        "Mary McLeod Bethune founded Bethune-Cookman in 1904 with $1.50 and a dream. The school now has over 3,500 students.",
    ],
    "Aggie–Eagle Classic": [
        "NC A&T's campus is where the Greensboro Four — the students who launched the 1960 lunch counter sit-ins — were enrolled.",
        "North Carolina A&T is the largest HBCU in the country with over 15,000 students.",
        "NC Central's law school has produced some of the most influential Black attorneys and judges in the American South.",
    ],
    "Aggie–Eagle Basketball Classic": [
        "NC A&T is the largest HBCU in America. Their basketball program has been one of the most competitive in the MEAC for decades.",
        "NC Central's law school produced some of the most influential Black attorneys in the South — the academic tradition bleeds into the athletic rivalry.",
    ],
    "Battle of the Real HU": [
        "Howard University has produced Thurgood Marshall, Kamala Harris, Chadwick Boseman, Toni Morrison, and Phylicia Rashad — among thousands of others.",
        "The 'Real HU' nickname reflects a longstanding friendly debate between Howard and Hampton fans about which school is the 'real' HU.",
        "The 2026 Battle of the Real HU is played at Audi Field in Washington DC — bringing the rivalry to the nation's capital.",
    ],
    "Howard–Hampton Basketball Classic": [
        "Howard University's basketball program has sent players to the NBA and produced some of the finest athletes from the DMV.",
        "The rivalry between Howard and Hampton spans football, basketball, and a decades-long debate about which school is the 'Real HU.'",
    ],
    "Howard–Morgan Classic": [
        "Howard produced Thurgood Marshall — the first Black Supreme Court Justice and one of the greatest legal minds in American history.",
        "Morgan State University is one of the most respected research HBCUs in the country — a Carnegie Research Institution.",
    ],
    "Howard–Morgan Basketball Classic": [
        "Howard and Morgan State represent two of the most important Black academic communities on the East Coast.",
        "The DC-Baltimore corridor has one of the highest concentrations of HBCU alumni in the country — and this rivalry reflects that pride.",
    ],
    "Battle of the Bay": [
        "Hampton University's waterfront campus on the Chesapeake Bay is one of the most beautiful in the country.",
        "Norfolk State's Spartan Legion marching band is one of the most respected in MEAC competition.",
        "The Hampton Roads metro area has one of the highest concentrations of HBCU alumni on the East Coast.",
    ],
    "Battle of the Bay Basketball": [
        "Hampton and Norfolk State are separated by a bridge-tunnel but united by one of MEAC basketball's most intense rivalries.",
        "Norfolk State's 2012 NCAA Tournament upset of Missouri as a 15-seed remains one of the greatest upsets in March Madness history.",
    ],
    "Celebration Bowl": [
        "The Celebration Bowl is the HBCU national championship game — played annually in Atlanta's Mercedes-Benz Stadium.",
        "The halftime show at the Celebration Bowl featuring both conference bands is one of the greatest spectacles in all of college sports.",
        "The SWAC leads the all-time Celebration Bowl series — a testament to the conference's dominance in HBCU football since 2015.",
    ],
    "Palmetto Capital City Classic": [
        "South Carolina State has produced more NFL players per capita than almost any other HBCU program.",
        "FAMU's Marching 100 has performed at six presidential inaugurations — more than any other college band.",
    ],
    "Southern Heritage Classic": [
        "The Southern Heritage Classic brings SWAC football to Memphis — a city with deep roots in Black music, culture, and civil rights history.",
        "Memphis is home to Beale Street, the birthplace of the Blues, and the National Civil Rights Museum at the Lorraine Motel.",
    ],
    "Bayou Classic Basketball": [
        "Grambling's Willis Reed won two NBA championships with the New York Knicks and was named Finals MVP both times.",
        "The Bayou Classic basketball edition carries the same energy as the football version — two of the most passionate fan bases in SWAC competing on hardwood.",
    ],
    "Houston HBCU Classic": [
        "Texas Southern's campus sits in Houston's Third Ward — one of the most culturally significant Black neighborhoods in America.",
        "Prairie View A&M went 80 games without a win from 1989 to 1998 and then won a national championship. That comeback is one of the greatest stories in college football.",
    ],
    "Houston HBCU Basketball Classic": [
        "Texas Southern's H&PE Arena is one of the loudest arenas in SWAC basketball when it's rocking.",
        "Prairie View A&M's comeback story — from the longest losing streak in college football to a national championship — defines HBCU resilience.",
    ],
    "Tennessee State–FAMU Classic": [
        "Tennessee State University's John Merritt era (1963–1983) produced over 100 NFL players — one of the greatest runs in HBCU football history.",
        "FAMU's Marching 100 has performed at six presidential inaugurations. When they travel, the whole city notices.",
    ],
    "SWAC Basketball Rivalry": [
        "The SWAC Tournament is one of the most electric events in HBCU sports — and Jackson State vs Southern is always a marquee matchup.",
        "Jackson State's basketball program has been building toward consistent SWAC contention — Southern's Jaguar Nation makes every road game a battle.",
    ],
}

# ── Sport key routing ─────────────────────────────────────────────────────────
BASKETBALL_SPORT_KEYS = {"hbcu_mbb", "hbcu_wbb", "mbb", "wbb", "basketball"}
FOOTBALL_SPORT_KEYS   = {"hbcu_football", "football"}


def get_rivalry_context(home_team: str, away_team: str, sport_key: str = "") -> dict | None:
    """
    Returns rivalry context for a matchup, or None if not found.
    Uses sport_key to route to the correct H2H table.

    Returns dict with:
        rivalry_name, leader, leader_wins, trailer_wins,
        series_str, cultural_story, did_you_know, telegram_block
    """
    import random
    key = frozenset({home_team, away_team})

    # Route to correct table based on sport_key
    if sport_key.lower() in BASKETBALL_SPORT_KEYS:
        rec = HBCU_H2H_BASKETBALL.get(key)
    elif sport_key.lower() in FOOTBALL_SPORT_KEYS:
        rec = HBCU_H2H_FOOTBALL.get(key)
    else:
        # No sport specified — check football first, then basketball
        rec = HBCU_H2H_FOOTBALL.get(key) or HBCU_H2H_BASKETBALL.get(key)

    if not rec:
        return None

    leader, leader_wins, trailer_wins, rivalry_name, cultural_story = rec

    if leader_wins == trailer_wins:
        series_str = f"All-Time Series: Tied {leader_wins}-{trailer_wins}"
    else:
        series_str = f"All-Time Series: {leader} leads {leader_wins}-{trailer_wins}"

    facts        = HBCU_DID_YOU_KNOW.get(rivalry_name, [])
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
        "rivalry_name":   rivalry_name,
        "leader":         leader,
        "leader_wins":    leader_wins,
        "trailer_wins":   trailer_wins,
        "series_str":     series_str,
        "cultural_story": cultural_story,
        "did_you_know":   did_you_know,
        "telegram_block": telegram_block,
    }


def list_rivalries(sport: str = "all") -> list:
    """Returns known rivalries. sport: 'football', 'basketball', or 'all'."""
    rivalries = []
    tables = []
    if sport in ("football", "all"):
        tables.append(("Football", HBCU_H2H_FOOTBALL))
    if sport in ("basketball", "all"):
        tables.append(("Basketball", HBCU_H2H_BASKETBALL))

    for sport_label, table in tables:
        for teams, rec in table.items():
            leader, lw, tw, name, _ = rec
            teams_list = list(teams)
            rivalries.append({
                "sport":        sport_label,
                "rivalry_name": name,
                "teams":        teams_list,
                "series":       f"{leader} leads {lw}-{tw}" if lw != tw else f"Tied {lw}-{tw}",
            })
    return sorted(rivalries, key=lambda x: (x["sport"], x["rivalry_name"]))


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        home       = sys.argv[1]
        away       = sys.argv[2]
        sport_key  = sys.argv[3] if len(sys.argv) >= 4 else ""
        ctx = get_rivalry_context(home, away, sport_key)
        if ctx:
            print(ctx["telegram_block"])
        else:
            print(f"No rivalry record found for {home} vs {away}")
    else:
        print("Known HBCU Rivalries & Classics:\n")
        for r in list_rivalries():
            print(f"  [{r['sport']}] {r['rivalry_name']}")
            print(f"    {r['teams'][0]} vs {r['teams'][1]}")
            print(f"    {r['series']}\n")