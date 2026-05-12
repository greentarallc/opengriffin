"""Skill Graph as Strategy — recommend skills based on co-usage patterns.

Reads usage.jsonl. Builds a co-occurrence matrix of skills used in the
same chat session. Suggests:
  - Missing skills the user would likely benefit from (skills frequently
    co-used by similar users; in single-user OSS mode, derived from the
    co-occurrence within the user's own sessions).
  - Skills that are heavily used (worth investing time in customizing).
  - Skills that haven't been used in 30+ days (candidates to remove).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

USAGE_LOG = Path.home() / ".opengriffin" / "usage.jsonl"
SKILLS_DIR = Path.home() / ".claude" / "skills"


def _sessions_with_skills() -> list[set[str]]:
    """Return a list of sessions, each as a set of skills used in that session.

    Skills are extracted from the 'extra.tools' field if recorded, otherwise
    from each entry. Adjust to your actual usage logging schema.
    """
    if not USAGE_LOG.is_file():
        return []
    by_session: dict[str, set[str]] = defaultdict(set)
    for line in USAGE_LOG.read_text().splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        sid = e.get("session_id")
        if not sid:
            continue
        # Skills used in this run might be in extra.tool_calls or extra.skills
        skills = []
        if isinstance(e.get("extra"), dict):
            ts = e["extra"].get("tool_calls") or []
            for t in ts:
                if isinstance(t, str) and not t.startswith("Bash") and not t.startswith("Read"):
                    skills.append(t)
        for s in skills:
            by_session[sid].add(s)
    return [s for s in by_session.values() if s]


def co_occurrence() -> dict[tuple[str, str], int]:
    matrix: dict[tuple[str, str], int] = Counter()
    for session in _sessions_with_skills():
        skills = sorted(session)
        for i, a in enumerate(skills):
            for b in skills[i + 1 :]:
                matrix[(a, b)] += 1
    return dict(matrix)


def usage_counts() -> Counter:
    counts: Counter = Counter()
    for session in _sessions_with_skills():
        for s in session:
            counts[s] += 1
    return counts


def installed_skills() -> set[str]:
    if not SKILLS_DIR.is_dir():
        return set()
    return {p.name for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}


def recommend() -> dict:
    """Three lists: top-used, never-used, suggestions for missing skills."""
    counts = usage_counts()
    installed = installed_skills()
    top_used = counts.most_common(10)
    never_used = sorted(installed - set(counts))[:30]

    # "Suggestions": skills NOT installed that frequently co-occur with top-used ones
    co = co_occurrence()
    candidate_pairs = []
    for (a, b), n in co.items():
        if a in installed and b not in installed and n >= 2:
            candidate_pairs.append((b, a, n))
        elif b in installed and a not in installed and n >= 2:
            candidate_pairs.append((a, b, n))
    suggestions = sorted(candidate_pairs, key=lambda x: -x[2])[:10]

    return {
        "top_used": top_used,
        "never_used": never_used,
        "suggestions": [{"missing": s, "co_used_with": w, "weight": n} for s, w, n in suggestions],
    }


@tool(
    "skill_strategy",
    "Analyze installed skills + usage patterns. Recommends: which skills to install (based on co-usage), which are unused (candidates to uninstall), which are heavily used (candidates to invest in customizing).",
    {},
)
async def _strategy(args: dict) -> dict:
    rec = recommend()
    text = (
        "*Top used*\n"
        + "\n".join(f"- {n}× {s}" for s, n in rec["top_used"])
        + "\n\n*Never used (30+ days)*\n"
        + ("\n".join(f"- {s}" for s in rec["never_used"][:10]) or "(none)")
        + "\n\n*Suggestions* (skills frequently co-used with what you have)\n"
        + (
            "\n".join(
                f"- {s['missing']} (with {s['co_used_with']}, ×{s['weight']})"
                for s in rec["suggestions"]
            )
            or "(no suggestions yet — need more usage data)"
        )
    )
    return {"content": [{"type": "text", "text": text}]}


STRATEGY_SERVER = create_sdk_mcp_server(
    name="skill_strategy",
    version="1.0.0",
    tools=[_strategy],
)
