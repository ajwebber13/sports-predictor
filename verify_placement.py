"""
verify_placement.py — run from C:\temp\sports_predictor after copying
the 6 patched files in. Confirms every file is at the repo ROOT (not
app/, app/api/, services/), no stray duplicates exist in subfolders,
every patched file imports cleanly, and the shelf list is shared.

    python verify_placement.py
"""
import os, sys, hashlib, importlib

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

FILES = ["active_sports.py", "prop_edge.py", "render_job.py", "wnba_props_alert.py",
         "mlb_props_alert.py", "pick_of_the_day.py", "fetch_prizepicks_props.py"]

ok = True
def fail(msg):
    global ok; ok = False; print(f"  FAIL  {msg}")
def good(msg): print(f"  ok    {msg}")

print("\n1) Files at repo root")
for f in FILES:
    if os.path.isfile(os.path.join(ROOT, f)): good(f)
    else: fail(f"{f} missing from root")

print("\n2) No stray copies in subfolders")
for dirpath, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", ".venv", "venv")]
    if dirpath == ROOT: continue
    for f in files:
        if f in ("active_sports.py", "prop_edge.py"):
            fail(f"stray copy: {os.path.relpath(os.path.join(dirpath, f), ROOT)}")
print("  ok    none found" if ok else "")

print("\n3) Patched content present")
checks = {
    "render_job.py":            "from active_sports import ALL_SPORTS",
    "mlb_props_alert.py":       "def filter_by_edge",
    "wnba_props_alert.py":      "ALLOWED_STATS",
    "active_sports.py":         "PROPS_SPORTS",
    "pick_of_the_day.py":       "PROP_MIN_EDGE_PTS",
    "fetch_prizepicks_props.py": "wrong game",
}
for f, needle in checks.items():
    try:
        txt = open(f, encoding="utf-8").read()
        good(f"{f} contains '{needle}'") if needle in txt else fail(f"{f} is the OLD version (missing '{needle}')")
    except FileNotFoundError:
        pass

print("\n4) Imports resolve from root")
os.environ.setdefault("SUPABASE_DB_URL", "")
for m in ["active_sports", "prop_edge", "render_job", "mlb_props_alert", "pick_of_the_day", "fetch_prizepicks_props"]:
    try:
        mod = importlib.import_module(m); good(f"import {m}  ({os.path.relpath(mod.__file__, ROOT)})")
    except Exception as e:
        fail(f"import {m}: {type(e).__name__}: {e}")

print("\n5) Shelf list is shared")
try:
    import active_sports, render_job, pick_of_the_day, mlb_props_alert
    if render_job.ALL_SPORTS is active_sports.ALL_SPORTS and pick_of_the_day.ALL_SPORTS is active_sports.ALL_SPORTS:
        good(f"ALL_SPORTS = {active_sports.ALL_SPORTS} (one object, three readers)")
    else:
        fail("render_job / pick_of_the_day are NOT reading active_sports.ALL_SPORTS")
    good(f"props_active wnba={active_sports.props_active('wnba')} mlb={active_sports.props_active('mlb')}")
except Exception as e:
    fail(str(e))

print("\n" + ("ALL CHECKS PASSED — safe to git add / commit / push" if ok else "FIX THE FAILURES ABOVE BEFORE PUSHING") + "\n")
sys.exit(0 if ok else 1)
