#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, pathlib, datetime as dt

DATA_FILE = pathlib.Path("data/sleeper/latest.json")
OUT_DIR   = pathlib.Path("outputs/sms")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Load data ---------------------------------------------------------------
j = json.loads(DATA_FILE.read_text(encoding="utf-8"))

league = j.get("league", {})
league_name = league.get("name") or league.get("metadata", {}).get("name") or "Your League"

users = {u.get("user_id"): u for u in j.get("users", [])}

# Map roster_id -> Team Name (prefer custom team names; fall back to owner display)
team_map = {}
for r in j.get("rosters", []):
    rid = r.get("roster_id")
    uid = r.get("owner_id")
    tname = (
        r.get("settings", {}).get("team_name")
        or r.get("metadata", {}).get("team_name")
        or (users.get(uid, {}).get("display_name") if uid else None)
        or f"Team {rid}"
    )
    team_map[rid] = tname

# --- Helpers ----------------------------------------------------------------
def pairs(arr):
    """Convert Sleeper matchups list into [(Team A, Team B), ...]."""
    by = {}
    for m in arr or []:
        mid = m.get("matchup_id")
        if mid is None:
            continue
        by.setdefault(mid, []).append(m)

    out = []
    for mid, group in by.items():
        if len(group) == 2:
            a, b = group
            a_name = team_map.get(a.get("roster_id"), f"Team {a.get('roster_id')}")
            b_name = team_map.get(b.get("roster_id"), f"Team {b.get('roster_id')}")
            out.append((a_name, b_name))
    return out

def list_names_from_trending(items, cap=6):
    """
    Sleeper trending returns objects with at least 'player_id'.
    We don't have the players map in latest.json yet, so show the ID.
    (We can enrich with /players/nfl later if you want.)
    """
    names = []
    for it in (items or [])[:cap]:
        pid = it.get("player_id") or it.get("player") or "?"
        names.append(str(pid))
    return names

# --- Build content -----------------------------------------------------------
week = j.get("state", {}).get("week") or "?"
current_pairs = pairs(j.get("matchups", {}).get("current", []))
next_pairs    = pairs(j.get("matchups", {}).get("next", []))

adds  = list_names_from_trending(j.get("trending", {}).get("add"))
drops = list_names_from_trending(j.get("trending", {}).get("drop"))

lines = []
lines.append(f"🏈 {league_name} — Week {week} Preview")

if current_pairs:
    lines.append("Key Matchups:")
    for a, b in current_pairs[:3]:
        lines.append(f"• {a} vs {b} — coin-flip vibes.")

if next_pairs:
    lines.append("Next Week Peeks:")
    for a, b in next_pairs[:2]:
        lines.append(f"• {a} vs {b} — circle it.")

if adds:
    lines.append("Waiver Adds:")
    for n in adds:
        lines.append(f"• {n}")

if drops:
    lines.append("Trade Away Watch:")
    for n in drops[:5]:
        lines.append(f"• {n}")

lines.append("Closer: set your lineups, hydrate, and may your flexes score early. 😎")

# --- Write file --------------------------------------------------------------
out_path = OUT_DIR / f"sms_week_{week}.txt"
out_path.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {out_path}")

