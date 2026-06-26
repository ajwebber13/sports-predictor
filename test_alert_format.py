"""
test_alert_format.py — Culture & Pulse Analytics
Sends a sample alert to Telegram showing the full new format including props.

Usage:
    python test_alert_format.py
"""

import os
import sys
import time
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"


def send(text: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHANNEL, "text": text, "parse_mode": "HTML"}
    r       = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        print("  ✅ Sent")
    else:
        print(f"  ❌ Failed: {r.status_code} — {r.text}")


if not TELEGRAM_TOKEN:
    print("❌ TELEGRAM_TOKEN not set.")
    sys.exit(1)


# ── Message 1: Header + News ──
msg1 = """🏀 <b>C&amp;P Picks — WNBA Morning Briefing</b>
📅 June 27, 2026
<b>3 game(s) today</b>

📡 <b>Around the W</b>
📰 Mercury's Thomas suspended for shot on Clark <i>(ESPN)</i> — <a href="https://www.espn.com/wnba">Read more</a>
📰 Gabby Williams — perfect fit for the Valkyries <i>(ESPN)</i> — <a href="https://www.espn.com/wnba">Read more</a>
📰 Marina Mabrey ties A'ja Wilson franchise record <i>(Yahoo Sports)</i> — <a href="https://sports.yahoo.com">Read more</a>"""

# ── Message 2: Game with GREEN edge + spread + totals + line movement + props ──
msg2 = """🏟 <b>Washington Mystics @ Connecticut Sun</b>
🕐 6:30 PM CT
───────────────────
📋 Washington Mystics: 8-8 | Connecticut Sun: 3-15
🔥 Washington Mystics (L1) · 2 days rest | Connecticut Sun (W1) · 4 days rest
🚑 Connecticut Sun: Hailey Van Lith (Out), Saniya Rivers (Out), Aneesah Morrow (Out)
⚡ Shakira Austin: 12.0 RPG last 2G
⚡ Brittney Griner: 3.0 BPG last 2G
🎯 <b>Prop Picks</b>
  ✅ Shakira Austin o2.5 AST — 66.7%
  ⚠️ Michaela Onyenwere o9.5 PTS — 62.5%
  ⚠️ Kiki Iriafen o8.5 REB — 57.1%
  ⚠️ Shakira Austin o7.5 REB — 55.6%
📉 Line: Connecticut -155→-175 | Washington +130→+148
🔔 Connecticut ML moved -20 pts — possible sharp action
───────────────────
📊 Model: Washington Mystics 41.1% | Connecticut Sun 58.9%
🤖 <b>Model Pick: Connecticut Sun (58.9%)</b>
🟡 <b>EDGE PICK: Connecticut Sun ML | +16.5% (YELLOW)</b>
📐 <b>SPREAD: Sun -5.5 | 64% cover</b> (model margin +8.2 vs posted -5.5)
🎯 <b>TOTAL: UNDER 167.5 | 61%</b> (model projects 161.0, edge -6.5)

<i>Culture &amp; Pulse Analytics | For entertainment only.</i>"""

# ── Message 3: Game with props + no edge ──
msg3 = """🏟 <b>Portland Fire @ Chicago Sky</b>
🕐 6:30 PM CT
───────────────────
📋 Portland Fire: 8-10 | Chicago Sky: 5-12
🔥 Portland Fire (L1) · 2 days rest | Chicago Sky (W1) · 2 days rest
🚑 Chicago Sky: Courtney Vandersloot (Out), DiJonai Carrington (Out), Rickea Jackson (Out)
⚡ Kamilla Cardoso: 11.0 RPG last 2G
🎯 <b>Prop Picks</b>
  ✅ Natasha Cloud o3.5 REB — 70.0%
  ⚠️ Kamilla Cardoso o2.5 AST — 60.0%
  ⚠️ Skylar Diggins o14.5 PTS — 55.6%
───────────────────
📊 Model: Portland Fire 40.1% | Chicago Sky 59.9%
🤖 <b>Model Pick: Chicago Sky (59.9%)</b>
🔴 No edge pick (below threshold)
📐 Projected: 84.5-80.9
🎯 Total lean: UNDER 162.5 (model 155.8, edge -6.7)

<i>Culture &amp; Pulse Analytics | For entertainment only.</i>"""

# ── Message 4: GREEN edge + props ──
msg4 = """🏟 <b>Atlanta Dream @ Golden State Valkyries</b>
🕐 9:00 PM CT
───────────────────
📋 Atlanta Dream: 12-5 | Golden State Valkyries: 11-7
🔥 Atlanta Dream (L1) · 2 days rest | Golden State Valkyries (W1) · 2 days rest
🚑 Atlanta Dream: Aaliyah Nye (Out), Brionna Jones (Out)
🚑 Golden State Valkyries: Iliana Rupert (Out)
⚡ Angel Reese: 10.5 RPG last 2G
───────────────────
📊 Model: Atlanta Dream 38.6% | Golden State Valkyries 61.4%
🤖 <b>Model Pick: Golden State Valkyries (61.4%)</b>
🟢 <b>EDGE PICK: Golden State Valkyries ML | +10.3% (GREEN)</b>
📐 <b>SPREAD: Valkyries -5.5 | 64% cover</b> (model margin +8.2 vs posted -5.5)
🎯 <b>TOTAL: UNDER 167.5 | 61%</b> (model projects 161.0, edge -6.5)

<i>Culture &amp; Pulse Analytics | For entertainment only.</i>"""


print("\nSending test alert format to Telegram...\n")

messages = [
    ("Header + News", msg1),
    ("YELLOW Edge + Props + Spread + Totals + Line Movement", msg2),
    ("No Edge + Props + Projected Score", msg3),
    ("GREEN Edge + Spread + Totals", msg4),
]

for label, msg in messages:
    print(f"  Sending: {label}")
    send(msg)
    time.sleep(1)

print("\nDone. Check @cultureandpulsepicks.\n")
