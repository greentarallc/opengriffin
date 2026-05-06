"""Echo Memory — autobiographical memory with time-aware decay.

Hierarchical summarization across four tiers:
  vivid   — last 7 days, full session transcripts available
  recent  — 8–30 days, day-summary granularity
  fading  — 31–365 days, week-summary granularity
  ancient — >365 days, month-summary granularity (oldest entries decay further)

Storage: memories/echo/{tier}/{YYYY-MM[-DD]}.md (markdown summaries).
Retrieval: substring + recency-weighted scoring; LLM consolidator
re-summarizes lower tiers into higher ones nightly.

Memory Receipts: every claim the agent makes can be backed by a citation
token like [echo:vivid/2026-05-04:abc123] which tracks back to a session
and turn.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any, Optional

from claude_agent_sdk import create_sdk_mcp_server, tool

ECHO_ROOT = Path.home() / ".opengriffin" / "memories" / "echo"
TIERS = ("vivid", "recent", "fading", "ancient")
TIER_BOUNDS = {  # max age in days; entries older slide to next tier
    "vivid":   7,
    "recent":  30,
    "fading":  365,
    "ancient": 10_000,
}


# ----------------------------- storage -----------------------------


def _tier_dir(tier: str) -> Path:
    p = ECHO_ROOT / tier
    p.mkdir(parents=True, exist_ok=True)
    return p


def _date_key(d: dt.date | dt.datetime, granularity: str = "day") -> str:
    if isinstance(d, dt.datetime):
        d = d.date()
    if granularity == "day":
        return d.isoformat()
    if granularity == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if granularity == "month":
        return d.strftime("%Y-%m")
    raise ValueError(granularity)


def write(tier: str, entry: str, *, key: Optional[str] = None) -> str:
    """Append/replace an entry in `tier`. Returns the citation token."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    if key is None:
        gran = {"vivid": "day", "recent": "day", "fading": "week", "ancient": "month"}[tier]
        key = _date_key(dt.date.today(), gran)
    path = _tier_dir(tier) / f"{key}.md"
    digest = hashlib.sha256(entry.encode("utf-8")).hexdigest()[:8]
    block = f"\n<!-- {digest} {dt.datetime.now().isoformat(timespec='seconds')} -->\n{entry.strip()}\n"
    if path.is_file():
        path.write_text(path.read_text() + block)
    else:
        path.write_text(f"# {tier}/{key}\n{block}")
    return f"[echo:{tier}/{key}:{digest}]"


def read_tier(tier: str, *, limit: int = 50) -> list[dict]:
    """Return all entries in a tier, most recent first."""
    out = []
    files = sorted(_tier_dir(tier).glob("*.md"), reverse=True)[:limit]
    for f in files:
        out.append({
            "tier": tier,
            "key": f.stem,
            "path": str(f),
            "content": f.read_text(),
            "mtime": dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
        })
    return out


# ----------------------------- retrieval -----------------------------


def search(query: str, *, max_per_tier: int = 5) -> list[dict]:
    """Substring match across all tiers, weighted by recency.

    Returns entries with a citation token + score so the agent can render
    Memory Receipts inline (e.g. "your anniversary is May 12 [echo:recent/2026-04-22:7f3a]").
    """
    needle = query.lower()
    if not needle.strip():
        return []
    today = dt.date.today()
    weights = {"vivid": 4.0, "recent": 2.0, "fading": 1.0, "ancient": 0.4}
    hits = []
    for tier in TIERS:
        per_tier = []
        for f in _tier_dir(tier).glob("*.md"):
            text = f.read_text()
            low = text.lower()
            if needle in low:
                # Score: tier weight × recency
                try:
                    fdate = dt.date.fromisoformat(f.stem.split("-W")[0][:10])
                    age = max((today - fdate).days, 1)
                except Exception:
                    age = 30
                score = weights[tier] * (1 / age ** 0.5)
                # Find the entry block containing the match
                idx = low.find(needle)
                start = max(0, idx - 200)
                snippet = text[start:start + 400].replace("\n", " ").strip()
                # Try to find the receipt digest preceding the snippet
                m = re.search(r"<!--\s*([0-9a-f]{8})", text[:idx][::-1].split("-->")[-1::-1][0]) if "<!--" in text[:idx] else None
                # Simpler: regex backwards
                preceding = text[:idx]
                last_marker = re.findall(r"<!--\s*([0-9a-f]{8})", preceding)
                digest = last_marker[-1] if last_marker else "?"
                per_tier.append({
                    "tier": tier,
                    "key": f.stem,
                    "score": round(score, 3),
                    "snippet": snippet,
                    "receipt": f"[echo:{tier}/{f.stem}:{digest}]",
                })
        per_tier.sort(key=lambda x: -x["score"])
        hits.extend(per_tier[:max_per_tier])
    hits.sort(key=lambda x: -x["score"])
    return hits


# ----------------------------- consolidation (nightly) -----------------------------


async def consolidate_nightly() -> dict:
    """Roll up older entries from a lower tier into a higher tier.

    vivid   → recent  : files older than 7 days
    recent  → fading  : files older than 30 days  (consolidate by week)
    fading  → ancient : files older than 365 days (consolidate by month)

    Uses the bot's own ask_claude to summarize, so it inherits the user's
    preferences (terseness from SOUL.md, etc.).
    """
    from . import bot as bot_module  # noqa
    today = dt.date.today()
    moved = {"vivid_to_recent": 0, "recent_to_fading": 0, "fading_to_ancient": 0}

    # vivid → recent: just move the files (already day-granular)
    for f in _tier_dir("vivid").glob("*.md"):
        try:
            d = dt.date.fromisoformat(f.stem)
        except Exception:
            continue
        if (today - d).days > TIER_BOUNDS["vivid"]:
            new_path = _tier_dir("recent") / f.name
            f.rename(new_path)
            moved["vivid_to_recent"] += 1

    # recent → fading: group recent files by ISO week, ask LLM to summarize
    recent_to_consolidate: dict[str, list[Path]] = {}
    for f in _tier_dir("recent").glob("*.md"):
        try:
            d = dt.date.fromisoformat(f.stem)
        except Exception:
            continue
        if (today - d).days > TIER_BOUNDS["recent"]:
            wk = _date_key(d, "week")
            recent_to_consolidate.setdefault(wk, []).append(f)
    for wk, files in recent_to_consolidate.items():
        joined = "\n\n".join(f.read_text() for f in files)
        prompt = (
            f"Consolidate these {len(files)} day-summaries from week {wk} into a "
            "single ~200-word week summary preserving the most durable facts and "
            "decisions. Drop minutiae. Plain prose.\n\n" + joined
        )
        try:
            summary = await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
            write("fading", summary, key=wk)
            for f in files:
                f.unlink()
            moved["recent_to_fading"] += len(files)
        except Exception:
            pass

    # fading → ancient: group by month
    fading_to_consolidate: dict[str, list[Path]] = {}
    for f in _tier_dir("fading").glob("*.md"):
        # Files are like 2026-W18; convert to month
        m = re.match(r"(\d{4})-W(\d{2})", f.stem)
        if not m:
            continue
        try:
            iso_year = int(m.group(1))
            iso_week = int(m.group(2))
            d = dt.date.fromisocalendar(iso_year, iso_week, 1)
        except Exception:
            continue
        if (today - d).days > TIER_BOUNDS["fading"]:
            mo = _date_key(d, "month")
            fading_to_consolidate.setdefault(mo, []).append(f)
    for mo, files in fading_to_consolidate.items():
        joined = "\n\n".join(f.read_text() for f in files)
        prompt = (
            f"Consolidate these {len(files)} week-summaries from {mo} into a "
            "single ~120-word month summary. Keep only what would matter a year "
            "from now.\n\n" + joined
        )
        try:
            summary = await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
            write("ancient", summary, key=mo)
            for f in files:
                f.unlink()
            moved["fading_to_ancient"] += len(files)
        except Exception:
            pass

    return moved


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "echo_remember",
    "Persist a durable autobiographical fact in echo memory's vivid tier. Use for new user preferences, life events, ongoing projects, or important decisions that will matter days/weeks/months later. Returns a citation receipt the agent can quote inline.",
    {"content": Annotated[str, "Concise factual statement"]},
)
async def _remember(args: dict) -> dict:
    receipt = write("vivid", args["content"])
    return {"content": [{"type": "text", "text": f"saved {receipt}"}]}


@tool(
    "echo_recall",
    "Search autobiographical memory across all time tiers. Returns hits with citation receipts the agent should QUOTE INLINE when stating recalled facts (e.g. 'your anniversary is May 12 [echo:recent/2026-04-22:7f3a]').",
    {"query": Annotated[str, "Substring to search for"]},
)
async def _recall(args: dict) -> dict:
    hits = search(args["query"])
    if not hits:
        return {"content": [{"type": "text", "text": "(no matches)"}]}
    lines = [f"{h['receipt']} ({h['tier']}, score {h['score']}): {h['snippet'][:200]}" for h in hits[:8]]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


ECHO_SERVER = create_sdk_mcp_server(
    name="echo_memory",
    version="1.0.0",
    tools=[_remember, _recall],
)
