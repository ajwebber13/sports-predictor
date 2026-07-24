"""
discord_alerts.py — Culture & Pulse Analytics
=================================================
Shared Discord-sending layer, replacing the Telegram bot API across
every alert script. One function every other file imports, instead of
each duplicating its own requests.post() call — same principle as
database.py's get_conn() being the single shared connection point.

Discord webhooks are simpler than Telegram's bot API: no bot token +
chat_id pair, just a webhook URL per channel. Create one at:
  Discord channel -> Settings -> Integrations -> Webhooks -> New Webhook

Formatting differs from Telegram's HTML (parse_mode="HTML"):
  Telegram          Discord
  <b>text</b>   ->  **text**
  <i>text</i>   ->  *text*
No direct Discord equivalent for underline/strikethrough beyond
markdown's own __underline__/~~strikethrough~~, not used here since
Telegram messages didn't use them either.

Discord message length limit is 2000 characters for plain content
(same limit Telegram effectively didn't hit in practice for these
alerts, but Discord's is stricter about enforcing it — messages over
the limit are REJECTED outright, not truncated). Long messages
(recaps, multi-pick digests) are automatically split into multiple
sends rather than failing.

Usage:
    from discord_alerts import send_discord_message, html_to_discord_markdown

    send_discord_message(html_to_discord_markdown(my_html_formatted_text), webhook_url=SOME_WEBHOOK)
"""

import os
import re
import time
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DISCORD_MAX_LENGTH = 2000

# Maps sport -> its dedicated Discord webhook env var. Matches the
# env vars already set in GitHub Actions / Render (2026-07-24).
SPORT_WEBHOOK_ENV = {
    "wnba":  "DISCORD_WEBHOOK_WNBA",
    "mlb":   "DISCORD_WEBHOOK_MLB",
    "nfl":   "DISCORD_WEBHOOK_NFL",
    "cfb":   "DISCORD_WEBHOOK_CFB",
    "ncaab": "DISCORD_WEBHOOK_NCAAB",
}


def get_webhook_for_sport(sport: str) -> str:
    """Returns the Discord webhook URL for a sport's dedicated channel,
    or "" if no channel exists yet for that sport (caller falls back
    to DISCORD_WEBHOOK_GAME_PICKS in that case). NBA has no dedicated
    channel yet — falls back too, which is fine since NBA is out of
    season."""
    if not sport:
        return ""
    env_var = SPORT_WEBHOOK_ENV.get(sport.lower())
    return os.getenv(env_var, "") if env_var else ""


def html_to_discord_markdown(text: str) -> str:
    """Converts the small HTML subset every alert file actually used
    (<b>, <i>, &amp;) into Discord markdown. Not a general HTML
    parser — deliberately narrow, matching exactly what these alert
    templates ever emit, so it's easy to verify correct rather than
    a general-purpose (and harder to trust) HTML-to-markdown library."""
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text, flags=re.DOTALL)
    text = text.replace("&amp;", "&")
    return text


def _split_for_discord(text: str, max_length: int = DISCORD_MAX_LENGTH) -> list:
    """Splits a long message into chunks under Discord's hard 2000-char
    limit, breaking on blank lines (paragraph boundaries) where
    possible so a single pick/section doesn't get cut mid-sentence.
    Falls back to a hard split only if a single paragraph itself
    exceeds the limit (shouldn't happen with these alert formats, but
    doesn't silently drop content if it does)."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_length:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(paragraph) <= max_length:
                current = paragraph
            else:
                # Single paragraph itself too long — hard split as a last resort.
                for i in range(0, len(paragraph), max_length):
                    chunks.append(paragraph[i:i + max_length])
                current = ""
    if current:
        chunks.append(current)
    return chunks


def send_discord_message(content: str, webhook_url: str = None) -> bool:
    """Sends content to Discord via webhook, auto-splitting if over the
    2000-char limit. Returns True only if every chunk sent successfully
    — a partial send (some chunks landed, one failed) still returns
    False so callers know not to trust the message as fully delivered.

    webhook_url defaults to DISCORD_WEBHOOK_URL from the environment if
    not passed explicitly — lets each alert file target a different
    channel by passing its own webhook, while sharing this one function."""
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        print("ERROR: no Discord webhook URL provided (pass webhook_url= or set DISCORD_WEBHOOK_URL).")
        return False

    chunks = _split_for_discord(content)
    all_ok = True
    for i, chunk in enumerate(chunks):
        try:
            r = requests.post(url, json={"content": chunk}, timeout=10)
            if r.status_code in (200, 204):
                print(f"Sent successfully" + (f" (part {i+1}/{len(chunks)})" if len(chunks) > 1 else ""))
            else:
                print(f"Failed: {r.status_code} {r.text}")
                all_ok = False
        except Exception as e:
            print(f"Discord send error: {e}")
            all_ok = False
        if len(chunks) > 1:
            time.sleep(1)  # avoid Discord's per-webhook rate limit on rapid multi-part sends
    return all_ok