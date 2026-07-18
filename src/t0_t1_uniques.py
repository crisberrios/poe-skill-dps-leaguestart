"""
t0_t1_uniques.py — Hardcoded T0 and T1 unique item sets for character filtering.

T0 uniques: chase items, world-drop only, enormous value (100+ divines at league peak).
T1 uniques: very rare boss drops, high value but more accessible than T0 (20+ divines).

These lists are deliberately conservative — only items that are genuinely rare/expensive
enough to distort the build meta. Common meta uniques are NOT included; they'll be
filtered by the time-based divine cap instead (3 divines × league_day).

All name matching is case-insensitive. process.py normalizes before lookup.
"""

# Tier 0 — true chase items, world-drop only, enormous value
T0_UNIQUES: set[str] = {
    "Mageblood",
    "Headhunter",
    "Replica Headhunter",
    "Mirror of Kalandra",
    "Kalandra's Touch",
    "Original Scripture",
    "Hinekora's Lock",
    "Progenesis",
    "Nimis",
    "Oriath's End",
    "The Squire",
    "Original Sin",
    "Voices",
    "That Which Was Taken",
    "One With Nothing",
}

# Tier 1 — very rare boss drops, high value but not chase-tier
T1_UNIQUES: set[str] = {
    "The Adorned",
    "Forbidden Shako",
    "Ashes of the Stars",
    "Crystallised Omniscience",
    "Replica Farrul's Fur",
    "Atziri's Reflection",
    "Voidforge",
    "Voltaxic Rift",
    "Sublime Vision",
    "Rational Doctrine",
    "Balance of Terror",
    "Replica Bated Breath",
}

ALL_EXCLUDED_UNIQUES: set[str] = T0_UNIQUES | T1_UNIQUES