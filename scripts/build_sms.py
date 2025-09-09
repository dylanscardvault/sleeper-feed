# scripts/build_sms.py
from __future__ import annotations
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sleeper"
OUT  = DATA / "sms.txt"

def load_json(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default

# --- Load pulled data ---------------------------------------------------------
j = load_json(DATA / "latest.json", default={}) or {}

league = j.get("league", {}) or {}
users  = {u.get("user_id"): u for u in (j.get("users") or [])}
rosters = j.get("rosters") or []

# Sleeper team name helper (prefer team names over usernames)
def team_name_by_roster_id(rid: int | str) -> str:
    try:
        rid = int(rid)
    except Exception:
        pass
    for r in rosters:
        if r.get("roster_id") == rid:
            uid = r.get("owner_id")
            u = users.get(uid, {})
            meta = u.get("metadata") or {}
            tname = meta.get("team_name") or meta.get("team_name_update")
            if tname:
                return tname
            # fallbacks
            return u.get("display_name") or f"Roster {rid}"
    return f"Roster {rid}"

# Pair matchups by matchup_id → list of entries
def pairs(match_list):
    by = defaultdict(list)
    for m in (match_list or []):
        mid = m.get("matchup_id")
        by[mid].append(m)
    # only return real pairings (2 entries)
    result = []
    for mid, lst in by.items():
        if len(lst) == 2:
            a, b = lst
            result.append((mid, a, b))
    # stable sort by matchup_id
    result.sort(key=lambda t: (t[0] is None, t[0]))
    return result

# Friendly one-liner for a pairing
def quip(mid, a, b):
    a_name = team_name_by_roster_id(a.get("roster_id"))
    b_name = team_name_by_roster_id(b.get("roster_id"))
    a_pts  = a.get("points")
    b_pts  = b.get("points")
    if a_pts is not None and b_pts is not None:
        diff = abs(a_pts - b_pts)
        vibe = "coin-flip" if diff < 5 else ("comfortable" if diff > 25 else "tight")
        leader = a_name if a_pts > b_pts else b_name
        return f"{a_name} vs {b_name} — {leader} ahead, {vibe} (Δ {diff:.1f})."
    return f"{a_name} vs {b_name} — buckle up."

# Format trending lists (optionally map to names if players file exists)
def load_players_map():
    p = DATA / "players.json"
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
        # raw is {player_id: {first_name, last_name, position, team}}
        m = {}
        for pid, info in raw.items():
            first = info.get("first_name") or ""
            last  = info.get("last_name") or ""
            pos   = info.get("position") or ""
            tm    = info.get("team") or ""
            name = (first + " " + last).strip() or info.get("full_name") or pid
            tag = f"{name} {pos}/{tm}".strip()
            m[pid] = tag
        return m
    except Exception:
        return {}

PLAYERS = load_players_map()

def pretty_trending(arr, cap=6):
    out = []
    for item in (arr or [])[:cap]:
        pid = str(item.get("player_id"))
        cnt = item.get("count") or item.get("adds") or item.get("drops")
        label = PLAYERS.get(pid) or pid
        if cnt:
            out.append(f"{label} (+{cnt})")
        else:
            out.append(label)
    return out

# --- Build content ------------------------------------------------------------
state = j.get("state") or {}
week = state.get("week") or "?"

# Handle 'matchups' whether it’s a dict ({current:[], next:[]}) or already a list
matchups = j.get("matchups", {})
current_raw = matchups.get("current") if isinstance(matchups, dict) else matchups
next_raw    = matchups.get("next")    if isinstance(matchups, dict) else []

current_pairs = pairs(current_raw)
next_pairs    = pairs(next_raw)

adds  = pretty_trending((j.get("trending") or {}).get("add"))
drops = pretty_trending((j.get("trending") or {}).get("drop"))

headline = f"📅 Week {week} Preview + Waivers"

lines = [headline]

# Key Matchups (use current if available, otherwise next)
pm = current_pairs if current_pairs else next_pairs
if pm:
    lines.append("🔥 Key Matchups:")
    for mid, a, b in pm[:3]:
        lines.append("• " + quip(mid, a, b))

if adds:
    lines.append("🛒 Waiver Adds:")
    lines.append("• " + "; ".join(adds))

if drops:
    lines.append("📉 Trending Drops:")
    lines.append("• " + "; ".join(drops))

# Small closer
lg_name = (league.get("metadata") or {}).get("name") or league.get("name") or "Your League"
lines.append(f"— {lg_name} newsfeed. Reply with ‘more’ for deeper stats.")

text = "\n".join(lines).strip()

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(text)
print(f"Wrote {OUT}")
print()
print(text)
