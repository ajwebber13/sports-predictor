"""
verify_fix.py — one-off check, not part of the pipeline
Run: python verify_fix.py

Calls the real get_hit_rate() against your actual cp_analytics.db —
same function fetch_prizepicks_props.py calls every morning — to prove
the off-role downgrade is live in your code right now, without needing
to wait for the next game day.
"""
from prop_hit_rates import get_hit_rate

print("Chelsea Gray — PTS 11.5 (off-role: she's tagged playmaker, not scorer)")
r = get_hit_rate("Chelsea Gray", "pts", 11.5)
print(f"  hit rate: {r['overall']['hit_rate']}%  ({r['overall']['games']} games)")
print(f"  tier: {r['confidence_tier']}")
print()

print("Chelsea Gray — AST 6.5 (on-role: this IS her category)")
r = get_hit_rate("Chelsea Gray", "ast", 6.5)
print(f"  hit rate: {r['overall']['hit_rate']}%  ({r['overall']['games']} games)")
print(f"  tier: {r['confidence_tier']}")
print()

print("A'ja Wilson — PRA 34.5 (combo stat, on-role: tagged scorer+rebounder)")
r = get_hit_rate("A'ja Wilson", "pra", 34.5)
print(f"  hit rate: {r['overall']['hit_rate']}%  ({r['overall']['games']} games)")
print(f"  tier: {r['confidence_tier']}")
