# ─────────────────────────────────────────────────────────────
# PASTE THIS into telegram_alerts.py
# REPLACE the existing format_alert() function with this one
# ─────────────────────────────────────────────────────────────

def format_alert(bet: dict, sport: str, game_time: str, context: dict = None) -> str:
    emoji      = sport_emoji(sport)
    label      = sport_label(sport)
    game       = bet.get("game", "")
    bet_label  = bet.get("bet", "")
    odds       = bet.get("odds")
    edge_pct   = round(bet.get("edge", 0) * 100, 1)
    model_prob = bet.get("model_prob", 0)
    implied    = bet.get("implied_prob", 0)
    projected  = bet.get("projected")

    parts       = game.split(" @ ")
    away_team   = parts[0] if len(parts) == 2 else ""
    home_team   = parts[1] if len(parts) == 2 else ""
    bet_on_home = home_team in bet_label
    home_prob   = model_prob if bet_on_home else round(100 - model_prob, 1)
    away_prob   = round(100 - model_prob, 1) if bet_on_home else model_prob

    odds_str  = f" ({fmt_odds(odds)})" if odds else ""
    proj_line = f"\n📊 <b>Projected:</b> {projected}" if projected else ""

    # ── CONTEXT LINES (injuries, records, rest) ──
    context_lines = ""
    if context:
        injuries = context.get("injuries", {})
        records  = context.get("records", {})
        rest     = context.get("rest", {})

        # Injuries — show for both teams if any
        inj_parts = []
        for team in [away_team, home_team]:
            team_inj = injuries.get(team, [])
            if team_inj:
                inj_parts.append(", ".join(team_inj[:3]))  # cap at 3 per team
        if inj_parts:
            context_lines += f"\n🏥 <b>Injuries:</b> {' | '.join(inj_parts)}"

        # Records
        away_rec = records.get(away_team, "N/A")
        home_rec = records.get(home_team, "N/A")
        context_lines += f"\n📋 <b>Records:</b> {away_team} {away_rec} | {home_team} {home_rec}"

        # Rest days
        away_rest = rest.get(away_team)
        home_rest = rest.get(home_team)
        if away_rest is not None and home_rest is not None:
            context_lines += f"\n😴 <b>Rest:</b> {away_team} {away_rest}d | {home_team} {home_rest}d"

    return (
        f"{emoji} <b>{label} — PICK ALERT</b>\n\n"
        f"<b>{game}</b>\n"
        f"🕐 {game_time}\n\n"
        f"✅ <b>Pick:</b> {bet_label}{odds_str}\n"
        f"📈 <b>Edge:</b> +{edge_pct}% — {edge_label(edge_pct)}\n"
        f"{proj_line}"
        f"{context_lines}\n\n"
        f"<b>WIN PROBABILITY</b>\n"
        f"{away_team}: {away_prob}%\n"
        f"{home_team}: {home_prob}%\n"
        f"Market: {implied}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Culture &amp; Pulse Analytics</i>\n"
        f"<i>For entertainment only. Bet responsibly.</i>"
    )
