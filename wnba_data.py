def get_wnba_events() -> list:
    """Fetch today's WNBA games from ESPN."""
    import pytz
    ct = pytz.timezone("America/Chicago")
    today = datetime.now(ct).strftime("%Y%m%d")

    data = _get(f"{BASE}/scoreboard", params={"dates": today})
    if not data:
        return []

    events = []
    for event in data.get("events", []):
        # Only grab games not yet played
        status_name = event.get("status", {}).get("type", {}).get("name", "")
        if status_name not in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS"):
            continue

        competitions = event.get("competitions", [{}])
        if not competitions:
            continue
        comp = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), "")
        away_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), "")
        game_time = event.get("date", "")

        if home_team and away_team:
            events.append({
                "home_team": home_team,
                "away_team": away_team,
                "game_time": game_time,
                "event_id":  event.get("id", ""),
            })

    return events