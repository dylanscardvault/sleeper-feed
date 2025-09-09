#!/usr/bin/env python3
import json, pathlib, datetime as dt

p = pathlib.Path("data/sleeper/latest.json")
j = json.loads(p.read_text(encoding="utf-8"))

lg = j["league"]; users = {u["user_id"]: u for u in j["users"]}
team_map = {}
for r in j["rosters"]:
    tid = r.get("roster_id"); uid = r.get("owner_id")
    tname = r.get("settings",{}).get("team_name") or r.get("metadata",{}).get("team_name")
    team_map[tid] = tname or users.get(uid,{}).get("display_name","(unknown)")

# Try to pair current/week+1 matchups (by matchup_id)
def pairs(arr):
    by = {}
    for m in arr:
        by.setdefault(m["matchup_id"], []).append(m)
    out=[]
    for mid, two in by.items():
        if len(two)==2:
            a,b = two
            out.append((team_map.get(a["roster_id"],f"Team {a['roster_id']}"),
                        team_map.get(b["roster_id"],f"Team {b['roster_id']}")))
    return out

week = j["state"].get("week")
current = pairs(j["matchups"]["current"])
nextwk  = pairs(j["matchups"]["next"])

# Simple trending lists (top 6)
adds  = [f"{x['player'].split(':')[-1]}" if isinstance(x.get("player"),str) else x.get("player_id","?") for x in j["trending"]["add"][:6]]
drops = [f"{x['player'].split(':')[-1]}" if isinstance(x.get("player"),str) else x.get("player_id","?") for x in j["trending"]["drop"][:6]]

lines=[]
lines.append(f"🏈 {lg['metadata'].get('name','League')} — Week {week} Preview")
if current:
    lines.append("Key Matchups:")
    for a,b in current[:3]:
        lines.append(f"• {a} vs {b} — coin-flip vibes.")
if nextwk:
    lines.append("Next Week Peeks:")
    for a,b in nextwk[:2]:
        lines.append(f"• {a} vs {b} — circle it.")

if adds:
    lines.append("Waiver Adds:")
    for n in adds: lines.append(f"• {n}")
if drops:
    lines.append("Trade Away Watch:")
    for n in drops[:5]: lines.append(f"• {n}")

lines.append("Closer: set your lineups, hydrate, and may your flexes score early. 😎")
out = "\n".join(lines)

outdir = pathlib.Path("outputs/sms"); outdir.mkdir(parents=True, exist_ok=True)
fname = outdir / f"sms_week_{week}.txt"
fname.write_text(out, encoding="utf-8")
print(f"wrote {fname}")
