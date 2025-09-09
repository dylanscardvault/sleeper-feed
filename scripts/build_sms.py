#!/usr/bin/env python3
"""
Build a short, SMS-friendly league preview from data/sleeper/latest.json.

- Robust to missing fields
- Handles Sleeper matchups which come as a LIST of entries (each with matchup_id)
- Never indexes a list with a string key (fixes the TypeError you saw)
- Writes output to data/sleeper/sms.txt
"""

from __future__ import annotations
import json
import os
from collections import defaultdict
from typing import Any, Dict, List


ROOT = os.path.dirname(os.path.dirname(__file__))  # repo/scripts -> repo
DATA_DIR = os.path.join(ROOT, "data", "sleeper")
LATEST_JSON = os.path.join(DATA_DIR, "latest.json")
SMS_TXT = os.path.join(DATA_DIR, "sms.txt")


def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def to_dict(obj: Any) -> Dict[str, Any]:
    return obj if isinstance(obj, dict) else {}


def to_list(obj: Any) -> List[Any]:
    return obj if isinstance(obj, list) else []


def roster_name(roster: Dict[str, Any], users_by_id: Dict[str, Dict[str, Any]]) -> str:
    # Try team name stored on roster metadata (common in Sleeper)
    meta = to_dict(roster.get("metadata"))
    team = meta.get("team_name") or meta.get("team_name_update")
    if team:
        return str(team)

    # Fallback: owner's display name
    owner_id = roster.get("owner_id")
    owner = users_by_id.get(str(owner_id), {})
    disp = owner.get("display_name")
    if disp:
        return str(disp)

    # Last resort: roster_id label
    rid = roster.get("roster_id")
    return f"Team {rid}" if rid is not None else "Unknown Team"


def group_by_matchup_id(matchups: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for m in matchups:
        # Sleeper sends integer matchup_id, but be defensive
        mid = m.get("matchup_id")
        if mid is None:
            # If no id, shove into bucket 0 so it can still be printed
            grouped[0].append(m)
            continue
        try:
            grouped[int(mid)].append(m)
        except (TypeError, ValueError):
            grouped[0].append(m)
    return grouped


def make_name_maps(j: Dict[str, Any]) -> Dict[int, str]:
    users = to_list(j.get("users"))
    rosters = to_list(j.get("rosters"))

    users_by_id: Dict[str, Dict[str, Any]] = {str(u.get("user_id")): u for u in users}
    names_by_roster: Dict[int, str] = {}

    for r in rosters:
        rid = r.get("roster_id")
        if rid is None:
            continue
        names_by_roster[int(rid)] = roster_name(r, users_by_id)

    return names_by_roster


def format_pair(entries: List[Dict[str, Any]], names_by_roster: Dict[int, str]) -> str:
    # Expect up to 2 entries (one per roster) for a head-to-head
    left = entries[0] if len(entries) > 0 else {}
    right = entries[1] if len(entries) > 1 else {}

    lname = names_by_roster.get(int(left.get("roster_id", -1)), "TBD")
    rname = names_by_roster.get(int(right.get("roster_id", -1)), "TBD")

    # Points may not exist for upcoming week; be graceful
    lpts = left.get("points")
    rpts = right.get("points")

    if lpts is not None and rpts is not None:
        try:
            diff = float(lpts) - float(rpts)
            edge = f" (edge {lname if diff>=0 else rname} by {abs(diff):.1f})"
        except Exception:
            edge = ""
    else:
        edge = ""

    return f"{lname} vs {rname}{edge}"


def build_preview(j: Dict[str, Any]) -> str:
    league = to_dict(j.get("league"))
    league_name = league.get("name") or "Your Sleeper League"

    state = to_dict(j.get("state"))
    week = state.get("week")
    week_txt = f"Week {week}" if week else "This Week"

    names_by_roster = make_name_maps(j)

    # Matchups live at j["matchups"]["current"] as a LIST (per our fetch),
    # but be tolerant: sometimes people store it as a dict of lists.
    matchups_section = j.get("matchups", {})
    current_list: List[Dict[str, Any]] = []
    if isinstance(matchups_section, dict) and isinstance(matchups_section.get("current"), list):
        current_list = matchups_section["current"]
    elif isinstance(matchups_section, list):
        # If someone saved it directly as list
        current_list = matchups_section
    else:
        current_list = []

    pairs_by_id = group_by_matchup_id(to_list(current_list))

    # Build 3 quick headliners (or as many as exist)
    headliners: List[str] = []
    for mid in sorted(pairs_by_id.keys()):
        line = format_pair(pairs_by_id[mid], names_by_roster)
        if line not in headliners:
            headliners.append(f"• {line}")
        if len(headliners) == 3:
            break

    if not headliners:
        headliners = ["• Matchups not posted yet — check back soon."]

    # Simple SMS output
    lines = [
        f"{league_name} — {week_txt} Preview",
        "Key Matchups:",
        *headliners,
        "—",
        "Reply if you want waiver/trade targets included here."
    ]
    return "\n".join(lines)


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    j = load_json(LATEST_JSON)

    sms = build_preview(j)

    with open(SMS_TXT, "w", encoding="utf-8") as f:
        f.write(sms)

    print(f"Wrote SMS to {SMS_TXT}")
    print("---")
    print(sms)


if __name__ == "__main__":
    main()
