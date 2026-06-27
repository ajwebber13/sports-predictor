"""
wnba_news_feed.py — Culture & Pulse Analytics
===============================================
Pulls WNBA news headlines from multiple RSS sources.
Filters stories by team name and returns relevant
headlines per game for the daily slate digest.

Sources (all free, no API key needed):
  - Google News WNBA RSS
  - CBS Sports WNBA RSS
  - Just Women Sports RSS
  - Boardroom RSS (sports/culture angle)
  - ESPN RSS

Used by wnba_slate_digest.py to add the morning briefing layer.

Usage (standalone):
  python wnba_news_feed.py              # print all WNBA headlines
  python wnba_news_feed.py "Indiana Fever"  # filter by team
"""

import sys
import time
import feedparser
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────────────────────
# RSS FEED SOURCES
# Priority order — best WNBA coverage first
# ─────────────────────────────────────────────────────────────

RSS_FEEDS = [
    {
        "name":     "Google News",
        "url":      "https://news.google.com/rss/search?q=WNBA&hl=en-US&gl=US&ceid=US:en",
        "priority": 1,
    },
    {
        "name":     "CBS Sports",
        "url":      "https://www.cbssports.com/rss/headlines/wnba/",
        "priority": 1,
    },
    {
        "name":     "Just Women Sports",
        "url":      "https://justwomenssports.com/feed/",
        "priority": 2,
    },
    {
        "name":     "Boardroom",
        "url":      "https://boardroom.tv/feed/",
        "priority": 2,
    },
    {
        "name":     "ESPN",
        "url":      "https://www.espn.com/espn/rss/wnba/news",
        "priority": 1,
    },
    {
        "name":     "Yahoo Sports",
        "url":      "https://sports.yahoo.com/wnba/rss.xml",
        "priority": 1,
    },
]

# ─────────────────────────────────────────────────────────────
# TEAM NAME ALIASES
# Maps full team name to keywords used in headlines
# ─────────────────────────────────────────────────────────────

TEAM_KEYWORDS = {
    "Las Vegas Aces":          ["Las Vegas Aces", "Aces", "A'ja Wilson", "Jackie Young", "Chennedy Carter"],
    "New York Liberty":        ["New York Liberty", "Liberty", "Breanna Stewart", "Sabrina Ionescu", "Jonquel Jones", "Satou Sabally"],
    "Seattle Storm":           ["Seattle Storm", "Storm", "Jewell Loyd"],
    "Minnesota Lynx":          ["Minnesota Lynx", "Lynx", "Napheesa Collier", "Kayla McBride"],
    "Connecticut Sun":         ["Connecticut Sun", "Sun", "Brittney Griner", "Leila Lacan"],
    "Indiana Fever":           ["Indiana Fever", "Fever", "Caitlin Clark", "Aliyah Boston", "NaLyssa Smith", "Kelsey Mitchell"],
    "Chicago Sky":             ["Chicago Sky", "Sky", "Kamilla Cardoso", "Skylar Diggins", "Natasha Cloud"],
    "Atlanta Dream":           ["Atlanta Dream", "Dream", "Rhyne Howard", "Allisha Gray", "Angel Reese", "Te-Hina Paopao"],
    "Phoenix Mercury":         ["Phoenix Mercury", "Mercury", "Alyssa Thomas", "DeWanna Bonner", "Kahleah Copper", "Natasha Mack"],
    "Los Angeles Sparks":      ["Los Angeles Sparks", "Sparks", "Dearica Hamby", "Kelsey Plum", "Nneka Ogwumike", "Kate Martin"],
    "Washington Mystics":      ["Washington Mystics", "Mystics", "Shakira Austin", "Lauren Betts"],
    "Dallas Wings":            ["Dallas Wings", "Wings", "Arike Ogunbowale", "Paige Bueckers", "Azzi Fudd"],
    "Golden State Valkyries":  ["Golden State Valkyries", "Valkyries", "Tiffany Hayes", "Kayla Thornton"],
    "Toronto Tempo":           ["Toronto Tempo", "Tempo", "Marina Mabrey", "Kiki Rice"],
    "Portland Fire":           ["Portland Fire", "Fire", "Carla Leite"],
}

# General WNBA keywords — stories that apply to the whole slate
WNBA_GENERAL_KEYWORDS = ["WNBA", "W league", "women's basketball"]

# How many hours back to look for stories
NEWS_LOOKBACK_HOURS = 36

# Max headlines per team per game
MAX_HEADLINES_PER_TEAM = 1

# Max headlines for general WNBA news in header
MAX_GENERAL_HEADLINES = 3

# ─────────────────────────────────────────────────────────────
# NOISE FILTER
# Headlines containing these phrases get skipped
# Catches: live stream guides, watch-party links, TV listings,
#          betting odds roundups, DFS lineup filler
# ─────────────────────────────────────────────────────────────

NOISE_PHRASES = [
    "how to watch",
    "how to live stream",
    "free live stream",
    "live stream today",
    "watch live",
    "where to watch",
    "tv channel",
    "start time and stream",
    "streaming guide",
    "all you need to know",
    "dfs picks",
    "dfs lineup",
    "best prop bet",
    "prop bets",
    "prediction, picks",
    "picks & odds",
    "picks and odds",
    "wnba picks today",
    "spread, wnba",
    "odds, game preview",
    "best bets",
    "prizepicks",
    "rotowire",
    "vs. prediction",
    "vs prediction",
    "prediction, odds",
    "odds, best",
    "best wnba prop",
    "draftkings network",
    "prediction, pick for",
    "prediction, spread",
    "gameday discussion",
    "picks for saturday",
    "picks for sunday",
    "picks for monday",
    "picks for tuesday",
    "picks for wednesday",
    "picks for thursday",
    "picks for friday",
]


# ─────────────────────────────────────────────────────────────
# FETCH ALL HEADLINES
# ─────────────────────────────────────────────────────────────

def fetch_all_headlines() -> list:
    """
    Pull headlines from all RSS sources.
    Returns deduplicated list of story dicts.
    """
    all_stories = []
    seen_titles = set()
    cutoff      = datetime.now(timezone.utc) - timedelta(hours=NEWS_LOOKBACK_HOURS)

    for feed_cfg in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            for entry in feed.entries:
                title   = entry.get("title", "").strip()
                link    = entry.get("link", "")
                summary = entry.get("summary", "")

                if not title:
                    continue

                # Deduplicate by title similarity (first 60 chars)
                title_key = title[:60].lower()
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)

                # Skip noise: live stream guides, odds roundups, DFS filler
                title_lower = title.lower()
                if any(phrase in title_lower for phrase in NOISE_PHRASES):
                    continue

                # Parse publish date
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except:
                        pass

                # Skip if too old
                if published and published < cutoff:
                    continue

                all_stories.append({
                    "title":     title,
                    "link":      link,
                    "summary":   summary,
                    "source":    feed_cfg["name"],
                    "priority":  feed_cfg["priority"],
                    "published": published,
                })

        except Exception as e:
            print(f"  [News] Feed error ({feed_cfg['name']}): {e}")
            continue

    # Sort: priority first, then newest
    all_stories.sort(key=lambda x: (x["priority"], -(x["published"].timestamp() if x["published"] else 0)))

    print(f"  [News] Fetched {len(all_stories)} total headlines across {len(RSS_FEEDS)} sources")
    return all_stories


# ─────────────────────────────────────────────────────────────
# FILTER BY TEAM
# ─────────────────────────────────────────────────────────────

def filter_stories_for_team(team_name: str, stories: list) -> list:
    """
    Return stories mentioning this team or its star players.
    """
    keywords = TEAM_KEYWORDS.get(team_name, [team_name])
    matches  = []

    for story in stories:
        text = f"{story['title']} {story['summary']}".lower()
        for kw in keywords:
            if kw.lower() in text:
                matches.append(story)
                break

    return matches[:MAX_HEADLINES_PER_TEAM]


# Terms that indicate non-WNBA content slipping through
NON_WNBA_NOISE = [
    "nba", "nfl", "mlb", "nhl", "knicks", "lakers", "celtics",
    "warriors", "bulls nba", "heat nba", "nets nba",
]

def filter_general_wnba_stories(stories: list, used_titles: set) -> list:
    """
    Return general WNBA stories not already used in team sections.
    Must explicitly mention WNBA and must not be about other leagues.
    """
    matches = []
    for story in stories:
        if story["title"] in used_titles:
            continue
        text  = f"{story['title']} {story['summary']}".lower()
        title = story["title"].lower()

        # Must contain a WNBA keyword
        if not any(kw.lower() in text for kw in WNBA_GENERAL_KEYWORDS):
            continue

        # Must not be primarily about another league
        if any(noise in title for noise in NON_WNBA_NOISE):
            continue

        matches.append(story)

    return matches[:MAX_GENERAL_HEADLINES]


# ─────────────────────────────────────────────────────────────
# FORMAT HEADLINE
# ─────────────────────────────────────────────────────────────

def format_headline(story: dict) -> str:
    """Format a single story for Telegram with clickable Read more link."""
    title  = story["title"]
    source = story["source"]
    link   = story.get("link", "")

    # Trim long titles
    if len(title) > 90:
        title = title[:87] + "..."

    # Google News redirect URLs don't render as clickable in Telegram
    if "news.google.com" in link:
        return f"📰 {title} <i>({source})</i>"

    if link:
        return f'📰 {title} <i>({source})</i> — <a href="{link}">Read more</a>'

    return f"📰 {title} <i>({source})</i>"


# ─────────────────────────────────────────────────────────────
# MAIN INTERFACE — called by wnba_slate_digest.py
# ─────────────────────────────────────────────────────────────

def get_game_news(home_team: str, away_team: str, all_stories: list) -> list:
    """
    Returns formatted headline lines for a specific matchup.
    Rules:
    1. Story title must mention a keyword for one of THIS game's teams
    2. Story title must NOT mention a keyword for a team NOT in this game
    """
    home_keywords = [k.lower() for k in TEAM_KEYWORDS.get(home_team, [home_team])]
    away_keywords = [k.lower() for k in TEAM_KEYWORDS.get(away_team, [away_team])]
    game_keywords = set(home_keywords + away_keywords)

    # All keywords for teams NOT in this game
    other_keywords = set(
        k.lower()
        for team, kws in TEAM_KEYWORDS.items()
        if team not in [home_team, away_team]
        for k in kws
        if len(k) > 6
    )

    home_stories = filter_stories_for_team(home_team, all_stories)
    away_stories = filter_stories_for_team(away_team, all_stories)

    lines = []
    used  = set()

    for story in away_stories + home_stories:
        if len(lines) >= MAX_HEADLINES_PER_TEAM * 2:
            break
        if story["title"] in used:
            continue

        title_lower = story["title"].lower()

        # Rule 1: must mention this game's teams in the title
        if not any(kw in title_lower for kw in game_keywords):
            continue

        # Rule 2: must NOT mention a team from a different game in the title
        other_hits = [kw for kw in other_keywords if kw in title_lower]
        if other_hits:
            print(f"  [EXCLUDED] '{story['title'][:60]}' — other team kw: {other_hits}")
            continue

        lines.append(format_headline(story))
        used.add(story["title"])

    return lines


def get_general_news(all_stories: list, used_titles: set) -> list:
    """
    Returns general WNBA headlines for the digest header.
    """
    general = filter_general_wnba_stories(all_stories, used_titles)
    return [format_headline(s) for s in general]


# ─────────────────────────────────────────────────────────────
# STANDALONE RUNNER
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    team_filter = sys.argv[1] if len(sys.argv) > 1 else None

    print("\n🏀 WNBA Morning Briefing — Culture & Pulse Analytics")
    print(f"📅 {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
    print("━" * 50)

    stories = fetch_all_headlines()

    if team_filter:
        print(f"\nHeadlines for: {team_filter}")
        matches = filter_stories_for_team(team_filter, stories)
        if matches:
            for s in matches:
                print(f"  {format_headline(s)}")
        else:
            print("  No recent stories found.")
    else:
        print(f"\nAll WNBA headlines ({len(stories)} total):\n")
        for s in stories[:20]:
            print(f"  [{s['source']}] {s['title']}")