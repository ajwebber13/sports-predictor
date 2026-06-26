# Alerts

How Telegram alerts fire, message types, and cron schedule.

---

## Telegram Channel

**Culture & Pulse Picks** (`@cultureandpulse` or configured via `TELEGRAM_CHANNEL` env var)

---

## Alert Types

### Morning Briefing (WNBA)
Sent at 10 AM CT on days with WNBA games. One message per component:

**Message 1 — Header + News**
```
🏀 C&P Picks — WNBA Morning Briefing
📅 [Date]
[N] game(s) today

📡 Around the W
📰 [Headline] (Source) — Read more
📰 [Headline] (Source) — Read more
```

**Message 2–N — One per game**
```
🏟 [Away] @ [Home]
🕐 [Time] CT
───────────────────
📋 [Away]: W-L | [Home]: W-L
🔥 [Away] (streak) · X days rest | [Home] (streak) · X days rest
🚑 [Team]: [Player] (Status)
⚡ [Player]: [stat] last 2G
📉 Line: [Home] +X→+Y | [Away] -X→-Y   ← if closing line captured
🔔 [Sharp signal]                         ← if ≥8 pt line movement
───────────────────
📊 Model: [Away] X% | [Home] X%
🤖 Model Pick: [Team] (X%)
🟢 EDGE PICK: [Team] ML | +X% (GREEN)   ← if edge ≥ 8%
📐 SPREAD: [Team] -X | X% cover          ← if spread edge ≥ 3 pts
🎯 TOTAL: OVER/UNDER X | X%              ← if total edge ≥ 4 pts
```

### No-Edge Games
```
🔴 No edge pick (below threshold)
📐 Projected: X-X
🎯 Total lean: UNDER X (model X, edge -X)   ← if gap ≥ 4 pts
```

### No Games Day
```
🏀 C&P Picks — WNBA Daily Slate
📅 [Date]
No WNBA games scheduled today.
```

---

## Confidence Tiers

Every edge pick shows a tier based on model probability and edge size:

| Tier | Criteria |
|------|----------|
| 🟢 GREEN | model_prob ≥ 60% AND edge ≥ 10% |
| 🟡 YELLOW | model_prob 55–59% OR edge 8–9% |
| 🔴 RED | below threshold — no pick shown |

---

## Edge Suppression

Edge picks are suppressed (shown as `⚠️ Edge suppressed`) when the picked team has **2 or more named star players** marked Out or Doubtful. Uses the `WNBA_STAR_PLAYERS` dict in `wnba_slate_digest.py`.

---

## Cron Schedule

All times in CT (UTC-5).

| Job | Schedule | What It Does |
|-----|----------|--------------|
| `wnba-morning` | 10 AM daily | WNBA slate digest + picks |
| `wnba-closing-lines` | 4 PM daily | Capture closing lines, compute movement |
| `wnba-afternoon` | 4 PM daily | WNBA afternoon picks refresh |
| `nba-morning` | 10 AM daily | NBA picks |
| `nba-afternoon` | 4 PM daily | NBA afternoon refresh |
| `ncaab-morning` | 10 AM daily | NCAAB picks |
| `ncaab-afternoon` | 4 PM daily | NCAAB afternoon refresh |
| `ncaaf-saturday` | 9 AM Saturdays | Full Saturday CFB slate |
| `ncaaf-weeknight` | 5 PM Tue–Fri | Mid-week night games |
| `nfl-sunday` | 9 AM Sundays | Full Sunday slate |
| `nfl-thursday` | 5 PM Thursdays | TNF picks |
| `nfl-monday` | 5 PM Mondays | MNF picks |
| `wnba-daily-recap` | 6:30 AM daily | Previous day results recap |
| `wnba-weekly-recap` | 9 AM Sundays | Weekly performance summary |
| `auto-results` | Midnight daily | Score results, prop outcomes, model report |
| `wnba-pregame` | Hourly | Pre-game alert check |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ODDS_API_KEY` | Yes | The Odds API key |
| `TELEGRAM_TOKEN` | Yes | Telegram bot token |
| `TELEGRAM_CHANNEL` | Yes | Channel ID or @username |

---

## Manual Triggers

```bash
# Full WNBA digest dry run
python wnba_slate_digest.py --dry-run

# Fire live alert
python render_job.py --sport wnba

# Score results manually
python auto_results.py yesterday
python auto_results.py 2026-06-25

# Capture closing lines
python capture_closing_lines.py --sport wnba --dry-run
python capture_closing_lines.py --sport wnba
```
