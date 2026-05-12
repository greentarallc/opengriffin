"""Predictive memory — agent learns user patterns and pre-computes likely needs.

Daily job: scan recent sessions for time-of-day patterns ("user asks about
NVDA every weekday morning at 8:30"). Build a small model of:
  - Recurring queries by time-of-day / day-of-week
  - Routine after-event followups ("if X happens, user usually asks Y")

Then pre-runs likely-asked things 5-10 minutes before the predicted time
and caches results in `predictions/`. When the user actually asks, the
cached answer is returned instantly.

This is the "I noticed you check NVDA every morning — here it is" feature.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.predictive")

PRED_DIR = Path.home() / ".opengriffin" / "predictions"
PRED_DIR.mkdir(parents=True, exist_ok=True)
PATTERNS_FILE = PRED_DIR / "patterns.json"

PROJECTS = Path.home() / ".claude" / "projects" / "-Users-macmini"


def _load_patterns() -> dict:
    if not PATTERNS_FILE.is_file():
        return {"patterns": []}
    try:
        return json.loads(PATTERNS_FILE.read_text())
    except Exception:
        return {"patterns": []}


def _save_patterns(data: dict) -> None:
    PATTERNS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _user_messages_with_time(days: int = 30) -> list[tuple[dt.datetime, str]]:
    """Pull (timestamp, user_message) tuples from recent sessions."""
    out = []
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    if not PROJECTS.is_dir():
        return out
    for f in PROJECTS.glob("*.jsonl"):
        try:
            mtime = dt.datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                continue
            for line in f.read_text().splitlines():
                msg = json.loads(line)
                if msg.get("role") != "user":
                    continue
                content = msg.get("content")
                text = (
                    content
                    if isinstance(content, str)
                    else (
                        next(
                            (
                                c.get("text", "")
                                for c in content
                                if isinstance(c, dict) and c.get("type") == "text"
                            ),
                            "",
                        )
                        if isinstance(content, list)
                        else ""
                    )
                )
                if text:
                    out.append((mtime, text[:300]))
        except Exception:
            continue
    return out


def detect_patterns() -> list[dict]:
    """Find recurring query topics by hour-of-day/day-of-week."""
    msgs = _user_messages_with_time(days=30)
    if not msgs:
        return []

    # Bucket by (weekday, hour, normalized topic)
    bucket: dict[tuple[int, int, str], int] = defaultdict(int)
    for ts, text in msgs:
        topic = _normalize_topic(text)
        if not topic:
            continue
        key = (ts.weekday(), ts.hour, topic)
        bucket[key] += 1

    # A pattern is significant if it appears 3+ times at the same weekday+hour
    patterns = []
    for (weekday, hour, topic), n in bucket.items():
        if n >= 3:
            patterns.append(
                {
                    "weekday": weekday,  # 0=Monday
                    "hour": hour,
                    "topic": topic,
                    "occurrences": n,
                    "confidence": min(1.0, n / 10),
                    "detected_at": dt.datetime.now().isoformat(timespec="seconds"),
                }
            )
    patterns.sort(key=lambda p: -p["confidence"])
    _save_patterns({"patterns": patterns})
    return patterns


_NOISE = {
    "the",
    "a",
    "an",
    "is",
    "to",
    "i",
    "you",
    "me",
    "my",
    "of",
    "and",
    "in",
    "on",
    "for",
    "with",
}


def _normalize_topic(text: str) -> str:
    """Compress a message into a 'topic' for grouping (top noun-ish 3-grams)."""
    words = [w.lower() for w in re.findall(r"[a-zA-Z]{3,}", text) if w.lower() not in _NOISE]
    if len(words) < 2:
        return ""
    # Take the first 3 distinct words as the topic key
    seen, chosen = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            chosen.append(w)
        if len(chosen) >= 3:
            break
    return " ".join(chosen)


async def precompute_due() -> dict:
    """Run every 5 minutes. For any pattern that fires within the next 15
    minutes, pre-compute the answer and cache it."""
    from . import bot as bot_module

    now = dt.datetime.now()
    upcoming = []
    for p in _load_patterns().get("patterns", []):
        if p["weekday"] != now.weekday():
            continue
        # Hours until next occurrence today
        if p["hour"] - now.hour in (0, 1) and p["confidence"] >= 0.3:
            upcoming.append(p)

    cached = 0
    for p in upcoming:
        cache_key = f"{p['weekday']}_{p['hour']}_{re.sub(r'[^a-z]', '_', p['topic'])}.md"
        cache_path = PRED_DIR / cache_key
        if (
            cache_path.is_file()
            and (now - dt.datetime.fromtimestamp(cache_path.stat().st_mtime)).total_seconds() < 3600
        ):
            continue  # already fresh
        prompt = (
            f"Pre-compute a brief answer the user is likely to ask about: {p['topic']}. Be concise."
        )
        try:
            answer = await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
            cache_path.write_text(answer)
            cached += 1
        except Exception as e:
            log.warning("pre-compute failed: %s", e)

    return {"upcoming": len(upcoming), "cached": cached}


def lookup_cached(text: str) -> str | None:
    """When user sends a message, check if we pre-computed something close to it."""
    topic = _normalize_topic(text)
    if not topic:
        return None
    for p in _load_patterns().get("patterns", []):
        if p["topic"] == topic:
            cache_key = f"{p['weekday']}_{p['hour']}_{re.sub(r'[^a-z]', '_', p['topic'])}.md"
            cache_path = PRED_DIR / cache_key
            if cache_path.is_file():
                age = (
                    dt.datetime.now() - dt.datetime.fromtimestamp(cache_path.stat().st_mtime)
                ).total_seconds()
                if age < 7200:  # 2h freshness
                    return cache_path.read_text()
    return None


@tool(
    "predictive_detect",
    "Re-scan recent sessions to detect recurring query patterns by time-of-day. Updates patterns.json.",
    {},
)
async def _detect(args: dict) -> dict:
    patterns = detect_patterns()
    return {
        "content": [
            {
                "type": "text",
                "text": f"detected {len(patterns)} patterns:\n"
                + "\n".join(
                    f"  weekday={p['weekday']} hour={p['hour']} {p['topic']} (×{p['occurrences']}, conf {p['confidence']:.2f})"
                    for p in patterns[:10]
                ),
            }
        ]
    }


@tool(
    "predictive_run",
    "Pre-compute answers for any patterns that fire in the next hour.",
    {},
)
async def _run(args: dict) -> dict:
    result = await precompute_due()
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


PREDICTIVE_SERVER = create_sdk_mcp_server(
    name="predictive",
    version="1.0.0",
    tools=[_detect, _run],
)
