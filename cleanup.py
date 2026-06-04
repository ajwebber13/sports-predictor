"""
cleanup.py
===========
One-time cleanup script for sports-predictor repository.
Run from C:\temp\sports_predictor:
  python cleanup.py

What it does:
  1. Checks which "investigate" files are actually imported anywhere
  2. Moves redundant files to an _archive folder (not deleted — safe)
  3. Prints a summary of what was moved and what to do next
"""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ARCHIVE = ROOT / "_archive"
ARCHIVE.mkdir(exist_ok=True)

moved   = []
skipped = []
kept    = []


def archive(filepath: str, reason: str):
    src = ROOT / filepath
    if not src.exists():
        skipped.append(f"NOT FOUND: {filepath}")
        return
    dst = ARCHIVE / src.name
    # If destination already exists, add suffix
    if dst.exists():
        dst = ARCHIVE / (src.stem + "_dup" + src.suffix)
    shutil.move(str(src), str(dst))
    moved.append(f"  ARCHIVED: {filepath} → _archive/{dst.name}  ({reason})")


def check_imports(filename: str) -> list:
    """Check which files import a given module name."""
    module = Path(filename).stem
    results = []
    for py_file in ROOT.rglob("*.py"):
        if py_file.name == Path(filename).name:
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if f"import {module}" in content or f"from {module}" in content:
                results.append(str(py_file.relative_to(ROOT)))
        except:
            pass
    return results


print("=" * 60)
print("Culture & Pulse Sports Predictor — Cleanup Script")
print("=" * 60)
print()


# ─────────────────────────────────────────────────────────────
# STEP 1: INVESTIGATE UNKNOWN FILES
# ─────────────────────────────────────────────────────────────

print("STEP 1: Investigating unknown files...")
print()

investigate = [
    "cfbd_api.py",
    "espn_api.py",
    "data_pipeline.py",
    "model/features/base.py",
    "model/inference/predictor.py",
    "model/inference/simulator.py",
    "app/schemas/game.py",
    "app/schemas/prediction.py",
    "app/dependencies.py",
]

for f in investigate:
    importers = check_imports(f)
    status = "USED BY: " + ", ".join(importers) if importers else "NOT IMPORTED ANYWHERE"
    print(f"  {f}")
    print(f"    → {status}")
print()


# ─────────────────────────────────────────────────────────────
# STEP 2: ARCHIVE REDUNDANT ROOT-LEVEL DUPLICATES
# ─────────────────────────────────────────────────────────────

print("STEP 2: Archiving redundant files...")
print()

# One-time utility scripts — not needed after running
archive("add_teams.py",          "one-time utility script")
archive("fix_wnba_ids.py",       "one-time utility script")
archive("write_profiles.py",     "one-time utility script")
archive("sample_teams.py",       "one-time utility script")

# Duplicate data files — proper versions are in data/
archive("wnba_data_fixed.py",    "replaced by wnba_data.py")
archive("debug_cfbd.py",         "debug script, not needed")
archive("archive_predictor_basic.py", "already archived")

# Root-level duplicates — proper versions are in subdirectories
archive("routes_edges.py",       "duplicate of app/api/routes_edges.py")
archive("routes_wnba.py",        "duplicate of app/api/routes_wnba.py")
archive("nfl_profiles.py",       "duplicate of data/nfl_profiles.py")
archive("team_profiles.py",      "duplicate of data/team_profiles.py")
archive("wnba_profiles.py",      "duplicate of data/wnba_profiles.py")
archive("model_connector.py",    "duplicate of services/model_connector.py")
archive("odds_parser.py",        "duplicate of services/odds_parser.py")
archive("edge_calculator.py",    "duplicate of services/edge_calculator.py")

# Duplicate display files — replaced by dashboard/app.py
archive("display.py",            "replaced by dashboard/app.py")
archive("enhanced_display.py",   "replaced by dashboard/app.py")

# Duplicate runners — keep auto_predict.py
archive("runner_auto_predictions.py", "duplicate runner")
archive("run_predictions.py",    "duplicate runner")
archive("run.py",                "duplicate runner")

# Duplicate predictor — keep enhanced_predictor.py
archive("predictor_core.py",     "merged into enhanced_predictor.py")

print()


# ─────────────────────────────────────────────────────────────
# STEP 3: ARCHIVE UNKNOWN FILES IF NOT IMPORTED
# ─────────────────────────────────────────────────────────────

print("STEP 3: Archiving unused unknown files...")
print()

unknown_not_imported = []
for f in investigate:
    importers = check_imports(f)
    if not importers:
        unknown_not_imported.append(f)

for f in unknown_not_imported:
    archive(f, "not imported anywhere — archiving safely")

# Archive whole model/ folder if nothing imports it
model_used = any(check_imports(f) for f in [
    "model/features/base.py",
    "model/inference/predictor.py",
    "model/inference/simulator.py",
])
if not model_used:
    model_dir = ROOT / "model"
    if model_dir.exists():
        dst = ARCHIVE / "model"
        shutil.move(str(model_dir), str(dst))
        moved.append("  ARCHIVED: model/ → _archive/model/  (not imported anywhere)")

print()


# ─────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────

print("=" * 60)
print("CLEANUP SUMMARY")
print("=" * 60)
print()

print(f"Files archived: {len(moved)}")
for m in moved:
    print(m)

print()
if skipped:
    print(f"Files not found (already clean): {len(skipped)}")
    for s in skipped:
        print(f"  {s}")

print()
print("All archived files are in: _archive/")
print("Nothing was permanently deleted.")
print("To restore any file: copy it back from _archive/")
print()

# Count remaining files
remaining = list(ROOT.rglob("*.py"))
remaining = [f for f in remaining if "_archive" not in str(f)]
print(f"Remaining Python files: {len(remaining)}")
print()
print("NEXT STEPS:")
print("  1. Review _archive/ folder — confirm nothing important was moved")
print("  2. Run: git add .")
print("  3. Run: git commit -m 'Cleanup - archive redundant files'")
print("  4. Run: git push")
print("  5. Trigger Render redeploy")
