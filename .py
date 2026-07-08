warning: in the working copy of 'telegram_alerts.py', LF will be replaced by CRLF the next time Git touches it
[1mdiff --git a/telegram_alerts.py b/telegram_alerts.py[m
[1mindex 3793a9a..562e2eb 100644[m
[1m--- a/telegram_alerts.py[m
[1m+++ b/telegram_alerts.py[m
[36m@@ -40,13 +40,9 @@[m [mESPN_SCHEDULE_ENDPOINTS = {[m
     "ncaab": "basketball/mens-college-basketball",[m
     "ncaaw": "basketball/womens-college-basketball",[m
     "wnba":  "basketball/wnba",[m
[32m+[m[32m    "mlb":   "baseball/mlb",[m
 }[m
 [m
[31m-[m
[31m-# ─────────────────────────────────────────────────────────────[m
[31m-# SEASON GATES[m
[31m-# ─────────────────────────────────────────────────────────────[m
[31m-[m
 SEASON_WINDOWS = {[m
     "nfl":   (9, 2),[m
     "ncaaf": (8, 1),[m
[36m@@ -54,6 +50,7 @@[m [mSEASON_WINDOWS = {[m
     "ncaaw": (11, 4),[m
     "wnba":  (5, 10),[m
     "nba":   (10, 5),[m
[32m+[m[32m    "mlb":   (3, 10),   # spring training through World Series[m
 }[m
 [m
 def is_in_season(sport: str) -> bool:[m
[36m@@ -146,9 +143,8 @@[m [mdef send_message(text: str):[m
     else:[m
         print(f"Failed: {r.status_code} {r.text}")[m
 [m
[31m-[m
 def sport_emoji(sport: str) -> str:[m
[31m-    return "🏈" if sport in ["ncaaf", "nfl"] else "🏀"[m
[32m+[m[32m    return "🏈" if sport in ["ncaaf", "nfl"] else "⚾" if sport == "mlb" else "🏀"[m
 [m
 [m
 def sport_label(sport: str) -> str:[m
[36m@@ -159,6 +155,7 @@[m [mdef sport_label(sport: str) -> str:[m
         "ncaaw": "College Basketball (Women)",[m
         "wnba":  "WNBA",[m
         "nba":   "NBA",[m
[32m+[m[32m        "mlb":   "MLB",[m
     }[m
     return labels.get(sport, sport.upper())[m
 [m
[36m@@ -359,6 +356,7 @@[m [mdef get_edges_url(sport: str, simulations: int) -> str:[m
         "ncaaw": f"{API_BASE}/ncaaw/edges",[m
         "wnba":  f"{API_BASE}/wnba/edges",[m
         "nba":   f"{API_BASE}/nba/edges",[m
[32m+[m[32m        "mlb":   f"{API_BASE}/mlb/edges",[m
     }[m
     url = endpoints.get(sport)[m
     if not url:[m
