#!/usr/bin/env python3
"""
Builds an SMS-friendly league preview/recap from Sleeper pull.
Input:  data/sleeper/latest.json   (written by sleeper-feed.yml)
Output: data/sleeper/sms.txt
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any, Tuple

DATA_DIR = Path("data/sleeper")
LATEST = DATA_DIR / "latest.json"
SMS_OUT = DATA_DIR / "sms.txt"


def load_latest() -> Dict[str, Any]:
    with open(LATEST, "r") as f:
        return json.load(f)


def safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def build_team_maps(j: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[int, str]]:
    """
    Returns:
      user_id -> team display name
      roster_id -> team display name
    """
    users = j.get("users", []) or []
    rosters = j.get("rosters", []) or []

    # user_id -> nice name (prefer team_name if league shows team names)
    user_to_name: Dict[str, str] = {}
    for u in users:
        meta = (u.get("metadata") or {})
        team_name = meta.get("team_name") or meta.get("team_name_update")  # sometimes it’s stored here
        display = team_name or u.get("display_name") or u.get("username") or str(u.get("user_id") or "")
        user_to_name[str(u.get("user_id"))] = display

    # roster_id -> nice name (by owner_id -> name)
    roster_to_name: Dict[int, str] = {}
    for r in rosters:
        rid = int(r.get("roster_id"))
        owner = str(r.get("owner_id"))
        roster_to_name[rid] = user_to_name.get(owner, f"Roster {rid}")

    return user_to_name, roster_to_name


def group_by_matchup_id(matchups: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """
    Turn a flat list of matchup rows into pairs (or groups) by matchup_id.
    """
    groups: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for m in matchups or []:
        mid = m.get("matchup_id")
        if mid is None:
            # If Sleeper returns 0/None in off weeks, bucket them separately by roster_id
            mid = 10_000_000 + int(m.get("roster_id", 0))
        groups[int(mid)].append(m)
    # Sort for stability
    return [groups[k] for k in sorted(groups.keys())]


def format_pair(pair: List[Dict[str, Any]], roster_to_name: Dict[int, str]) -> str:
    """
    Build a 1-liner for a matchup group.
    """
    if not pair:
        return "TBD vs TBD"

    # Each item has: roster_id, points (recap), or projections in-season in some contexts
    names = [roster_to_name.get(int(p.get("roster_id")), f"Roster {p.get('roster_id')}") for p in pair]
    # Ensure exactly two names for a tidy line
    if len(names) == 1:
        names.append("TBD")

    # Pull points if present (recap week)
    pts = [safe_float(p.get("points")) for p in pair]
    if any(p > 0 for p in pts):
        # Show score ordering: TeamA 123.4 — TeamB 118.7
        left = f"{names[0]} {pts[0]:.1f}"
        right = f"{names[1]} {pts[1]:.1f}" if len(pts) > 1 else names[1]
        return f"{left} — {right}"
    else:
        # Preview style without points
        return f"{names[0]} vs {names[1]}"


def find_awards(recap_pairs: List[List[Dict[str, Any]]], roster_to_name: Dict[int, str]) -> Dict[str, str]:
    """
    Compute top scorer, closest game, blowout from recap pairs.
    """
    if not recap_pairs:
        return {}

    def pair_points(pair):
        pts = [safe_float(x.get("points")) for x in pair]
        return pts if len(pts) == 2 else (pts + [0.0])[:2]

    top_team = ""
    top_pts = -1.0
    closest_line = ""
    closest_diff = 10**9
    blowout_line = ""
    blowout_diff = -1.0

    for pair in recap_pairs:
        pts = pair_points(pair)
        names = [roster_to_name.get(int(x.get("roster_id")), f"Roster {x.get('roster_id')}") for x in pair]
        if len(names) == 1:
            names.append("TBD")

        # top scorer (team with max points)
        for n, p in zip(names, pts):
            if p > top_pts:
                top_pts = p
                top_team = n

        # diffs
        if len(pts) == 2:
            diff = abs(pts[0] - pts[1])
            line = f"{names[0]} {pts[0]:.1f} — {names[1]} {pts[1]:.1f} (Δ {diff:.1f})"
            if diff < closest_diff:
                closest_diff = diff
                closest_line = line
            if diff > blowout_diff:
                blowout_diff = diff
                blowout_line = line

    out = {}
    if top_team:
        out["Top Scorer"] = f"{top_team} ({top_pts:.1f})"
    if closest_line:
        out["Closest Game"] = closest_line
    if blowout_line:
        out["Blowout"] = blowout_line
    return out


def standings_snapshot(rosters: List[Dict[str, Any]], roster_to_name: Dict[int, str]) -> List[str]:
    lines = []
    # Sleeper stores wins/losses in roster.settings
    table = []
    for r in rosters or []:
        s = r.get("settings") or {}
        wins = int(s.get("wins", 0))
        losses = int(s.get("losses", 0))
        ties = int(s.get("ties", 0))
        fpts = safe_float(s.get("fpts", 0)) + safe_float(s.get("fpts_decimal", 0)) / 100.0
        name = roster_to_name.get(int(r.get("roster_id")), f"Roster {r.get('roster_id')}")
        table.append((wins, -fpts, name, wins, losses, ties, fpts))
    # Sort: wins desc, points for desc as tiebreaker
    table.sort(key=lambda x: (x[0], -x[6]), reverse=True)
    for _, __, name, w, l, t, pf in table[:5]:  # keep SMS tight (top 5)
        rec = f"{w}-{l}" + (f"-{t}" if t else "")
        lines.append(f"{name} {rec} (PF {pf:.1f})")
    return lines


def build_sms(j: Dict[str, Any]) -> str:
    _, roster_to_name = build_team_maps(j)

    # Matchups structure is object with lists: recap/current/next
    msets = j.get("matchups", {}) or {}
    recap_pairs = group_by_matchup_id(msets.get("recap") or [])
    current_pairs = group_by_matchup_id(msets.get("current") or [])
    next_pairs = group_by_matchup_id(msets.get("next") or [])

    # Compose sections (SMS-friendly)
    out: List[str] = []
    league = j.get("league", {}) or {}
    lname = league.get("name") or "Your League"
    out.append(f"🏈 {lname}: Weekly Preview")
    out.append("")

    # Key Matchups (prefer current, else next)
    use_pairs = current_pairs if current_pairs else next_pairs
    if use_pairs:
        out.append("Key Matchups:")
        for pair in use_pairs[:3]:
            out.append(f"• {format_pair(pair, roster_to_name)}")
        out.append("")

    # Recap highlights (if we have them)
    if recap_pairs:
        awards = find_awards(recap_pairs, roster_to_name)
        if awards:
            out.append("Last Week:")
            if "Top Scorer" in awards:
                out.append(f"• Top Scorer: {awards['Top Scorer']}")
            if "Closest Game" in awards:
                out.append(f"• Closest: {awards['Closest Game']}")
            if "Blowout" in awards:
                out.append(f"• Blowout: {awards['Blowout']}")
            out.append("")

    # Standings snapshot (top 5)
    snap = standings_snapshot(j.get("rosters") or [], roster_to_name)
    if snap:
        out.append("Standings (Top 5):")
        for line in snap:
            out.append(f"• {line}")
        out.append("")

    out.append("Good luck 🍀 — set those lineups!")
    return "\n".join(out).strip()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    j = load_latest()
    sms = build_sms(j)
    SMS_OUT.write_text(sms, encoding="utf-8")
    print(f"Wrote {SMS_OUT} ({len(sms)} chars)")


if __name__ == "__main__":
    main()
