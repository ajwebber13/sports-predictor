def get_total_odds(event):
    """
    Pulls the MLB over/under total from the same ESPN odds block.
    "total" is the documented key, mirroring "moneyline"/"pointSpread".

    Returns {"line": float, "over_odds": int, "under_odds": int} or
    None if missing.

    FIXED (2026-07-20): confirmed live against a real in-season game —
    the "total" key IS correct (it was never a wrong-key problem the
    way the docstring worried it might be), but ESPN's line field
    comes back as a STRING with an o/u prefix baked in — "o7.5" for
    the over line, "u7.5" for the under line — not a plain number.
    float("o7.5") raises ValueError, which the bare except below was
    silently swallowing and turning into None every single time,
    regardless of whether the game had real total odds. Stripping the
    leading o/u character before the float() call fixes it. Odds
    themselves ("-110") were always plain numeric strings and never
    had this problem — only the line field does.
    """
    try:
        odds_list = event["competitions"][0].get("odds", [])
        if not odds_list:
            return None
        total = odds_list[0]["total"]
        raw_line = str(total["over"]["close"]["line"])
        line = float(raw_line.lstrip("ouOU"))
        over_odds = int(total["over"]["close"]["odds"])
        under_odds = int(total["under"]["close"]["odds"])
        return {"line": line, "over_odds": over_odds, "under_odds": under_odds}
    except (KeyError, IndexError, ValueError, TypeError):
        return None
