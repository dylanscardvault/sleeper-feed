#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Builds an SMS-friendly league preview/waiver/trade note from Sleeper public data
fetched into data/sleeper/latest.json by the sleeper-feed workflow.

This script is intentionally defensive about JSON shapes so it won't crash if
Sleeper returns slightly different structures (e.g., dict vs list).
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "sleeper"
LATEST_JSON = DATA_DIR / "latest.json"
OUT_SMS = DATA_DIR / "sms.txt"

def load_latest() -> dict:
    if not LATEST_JSON.exists():
        raise SystemExit(f"Missing {LATEST_JSON} — run the pull job first.")
    with LATEST_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)

def is_listlike(x) -> bool:
    return isinstance(x, (list, tuple))

def as_list(x):
    if x is None:
        return []
    return list(x) if is_listlike(x) else [x]

def safe_matchup_chunks(j: dict):
    """
    Returns (current_raw, next_raw) as lists of matchup records.
    Accepts:
      - j["matchups"] as dict with keys "current"/"next"
      - j["matchups"] as already-a-list (we treat as current)
      - anything else -> empty lists
    """
    matchups = j.get("matchups")
    if isinstance(matchups, dict):
        current_raw = as_list(matchups.get("current"))
        next_raw = as_list(matchups.get("next"))
    elif is_listlike(matchups):
        current_raw = list(matchups)
        next_raw = []
    else:
        current_raw, next_raw = [], []
    # Flatten any nested single-element lists Sleeper can sometimes return
    def flatten(xs):
        out = []
        for x in xs:
            if is_listlike(x):
                out.extend(x)
            else:
                out.append(x)
        return out
    return flatten(current_raw), flatten(next_raw)

def pair_by_matchup_id(rows: list[dict]) -> list[tuple[dict, dict]]:
    """Group matchup rows into (teamA, teamB) pairs by matchup_id."""
    by = defaultdict(list)
    for m in rows:
        # Some rows may lack matchup_id; bucket them by a rolling key
        key = m.get("matchup_id")
        by[str(key)].append(m)
    pairs = []
    for _, bucket in by.items():
        if len(bucket) >= 2:
            pairs.append((bucket[0], bucket[1]))
        elif len(bucket) == 1:
            # If only one side present, pair with None (still printable)
            pairs.append((bucket[0], {}))
    return pairs

def roster_owner_maps(users, rosters):
    # Map user_id -> display team name if available (use metadata name)
    user_name = {}
    for u in as_list(users):
        # Prefer team name if Sleeper exposes it under display_name; else username
        nm = (u.get("metadata", {}) or {}).get("team_name") \
             or u.get("display_name") \
             or u.get("username") \
             or f"user_{u.get('user_id','?')}"
        user_name[u.get("user_id")] = nm

    # Map roster_id -> user display name (or “Team X” fallback)
    rid_to_user = {}
    for r in as_list(rosters):
        rid = r.get("roster_id")
        uid = r.get("owner_id")
        nm = user_name.get(uid) or f"Team {rid}"
        rid_to_user[rid] = nm
    return rid_to_user

def nice_team(rid, rid_to_user):
    return rid_to_user.get(rid, f"Team {rid or '?'}")

def build_matchup_lines(pairs, rid_to_user):
    lines = []
    for a, b in pairs:
        an = nice_team(a.get("roster_id"), rid_to_user)
        bn = nice_team(b.get("roster_id"), rid_to_user) if b else "TBD"
        # If projected or points exist, show a tiny blurb
        ap = a.get("points") or a.get("starters_points") or 0
        bp = b.get("points") or b.get("starters_points") or 0
        # Keep SMS short
        if ap or bp:
            lines.append(f"{an} vs {bn} — {ap:.1f}-{bp:.1f}")
        else:
            lines.append(f"{an} vs {bn}")
    return lines[:3]  # cap at 3 bullets for SMS

def trending_blurbs(j: dict, rid_to_user: dict):
    # Build owned set by player_id (from each roster's players list)
    owned = set()
    for r in as_list(j.get("rosters")):
        for pid in as_list(r.get("players")):
            owned.add(str(pid))

    adds = as_list(j.get("trending", {}).get("add"))
    drops = as_list(j.get("trending", {}).get("drop"))

    # Simple readable fields (Sleeper trending items often include player_id & count)
    def label(x):
        # Try name/pos/team if sleeper expanded; otherwise show player_id
        nm = x.get("player_name") or x.get("name") or x.get("full_name") or x.get("first_name")
        if nm:
            pos = x.get("position") or x.get("pos")
            tm = x.get("team") or x.get("pro_team")
            core = nm
            if pos: core += f" {pos}"
            if tm:  core += f" ({tm})"
            return core
        return f"Player {x.get('player_id','?')}"

    # Waiver Adds: unowned trending adds
    waiver_adds = []
    for x in adds:
        pid = str(x.get("player_id"))
        if pid and pid not in owned:
            waiver_adds.append(label(x))
    waiver_adds = waiver_adds[:6] if waiver_adds else []

    # Trade For: highly added but already owned by someone
    trade_for = []
    for x in adds:
        pid = str(x.get("player_id"))
        if pid and pid in owned:
            trade_for.append(label(x))
    trade_for = trade_for[:5]

    # Trade Away: heavily dropped
    drop_counts = Counter([str(x.get("player_id")) for x in drops if x.get("player_id")])
    trade_away = [label(x) for x in drops if drop_counts.get(str(x.get("player_id"))) and label(x)]
    # De-dup while preserving order
    seen = set()
    ta_unique = []
    for t in trade_away:
        if t not in seen:
            seen.add(t)
            ta_unique.append(t)
    trade_away = ta_unique[:5]

    return waiver_adds, trade_for, trade_away

def build_sms(j: dict) -> str:
    # Headline
    league = j.get("league", {}) or {}
    lg_name = league.get("name") or league.get("metadata", {}).get("name") or "League"
    state = j.get("state", {}) or {}
    week = state.get("week")
    fetched_at = j.get("fetched_at")
    ts = datetime.fromtimestamp(fetched_at, tz=timezone.utc).astimezone().strftime("%b %d, %I:%M %p")

    users = as_list(j.get("users"))
    rosters = as_list(j.get("rosters"))
    rid_to_user = roster_owner_maps(users, rosters)

    current_raw, next_raw = safe_matchup_chunks(j)
    cur_pairs = pair_by_matchup_id(current_raw)
    nxt_pairs = pair_by_matchup_id(next_raw)

    waiver_adds, trade_for, trade_away = trending_blurbs(j, rid_to_user)

    lines = []
    lines.append(f"{lg_name} — Week {week} Preview 🔮")
    lines.append(f"(auto-pulled {ts})")
    lines.append("")
    # Key Matchups
    if cur_pairs or nxt_pairs:
        lines.append("Key Matchups:")
        ml = build_matchup_lines(cur_pairs or nxt_pairs, rid_to_user)
        for m in ml:
            lines.append(f"• {m}")
        lines.append("")

    # Waiver Adds
    if waiver_adds:
        lines.append("Waiver Adds:")
        for w in waiver_adds:
            lines.append(f"• {w}")
        lines.append("")

    # Trade targets
    if trade_for:
        lines.append("Trade For (buy):")
        for t in trade_for:
            lines.append(f"• {t}")
    if trade_away:
        lines.append("Trade Away (sell):")
        for t in trade_away:
            lines.append(f"• {t}")
    if trade_for or trade_away:
        lines.append("")

    # Closer
    lines.append("Good luck. Set lineups, win friends, fleece responsibly 🧀.")

    return "\n".join(lines).strip() + "\n"

def main():
    j = load_latest()
    OUT_SMS.parent.mkdir(parents=True, exist_ok=True)
    sms = build_sms(j)
    OUT_SMS.write_text(sms, encoding="utf-8")
    print(f"Wrote {OUT_SMS.relative_to(ROOT)} ({len(sms)} chars)")

if __name__ == "__main__":
    main()
