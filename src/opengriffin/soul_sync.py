"""Soul Sync — extract a writing-voice profile from past chats and apply it.

MVP version: builds a "voice card" from user-authored snippets in past
sessions. No LoRA training in this OSS release — that's a paid-tier
cloud feature when demand justifies the Lambda Labs spend.

The voice card is a structured markdown profile (sentence length, tone,
recurring phrases, anti-patterns) that gets injected into the system
prompt when 'draft as me' mode is active.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import statistics
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

PROJECT_DIR = Path.home() / ".claude" / "projects" / "-Users-macmini"
VOICE_CARD = Path.home() / ".opengriffin" / "memories" / "VOICE.md"


def _user_authored_snippets(limit: int = 200) -> list[str]:
    """Pull recent user messages from Claude Code's session JSONL store."""
    if not PROJECT_DIR.is_dir():
        return []
    out: list[str] = []
    for f in sorted(PROJECT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                msg = json.loads(line)
                if msg.get("role") != "user":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    out.append(content)
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            out.append(c.get("text", ""))
                if len(out) >= limit:
                    return out
        except Exception:
            continue
    return out


def analyze(samples: list[str]) -> dict:
    """Compute voice statistics across samples."""
    if not samples:
        return {}
    sents = []
    for s in samples:
        sents.extend(re.split(r"(?<=[.!?])\s+", s.strip()))
    sents = [s for s in sents if 2 <= len(s.split()) <= 80]
    if not sents:
        return {}
    lengths = [len(s.split()) for s in sents]

    # Count contractions, em-dashes, profanity, hedges
    n = len(samples)
    joined = "\n".join(samples).lower()
    em_dashes = joined.count(" — ") + joined.count("—")
    contractions = len(re.findall(r"\b\w+'(?:s|ll|d|ve|re|m|t)\b", joined))
    hedges = sum(joined.count(h) for h in ["maybe", "perhaps", "i think", "sort of", "kind of"])
    questions = joined.count("?")
    first_person = len(re.findall(r"\bi\b", joined))

    # Top recurring 2-grams
    words = re.findall(r"\w+", joined)
    bigrams = list(zip(words, words[1:], strict=False))
    from collections import Counter

    top = [b for b, c in Counter(bigrams).most_common(15) if c >= 3]

    return {
        "samples": len(samples),
        "sentences": len(sents),
        "avg_sentence_len": round(statistics.mean(lengths), 1),
        "stddev_sentence_len": round(statistics.pstdev(lengths), 1),
        "em_dash_rate_per_sample": round(em_dashes / n, 2),
        "contraction_rate_per_sample": round(contractions / n, 2),
        "hedge_rate_per_sample": round(hedges / n, 2),
        "first_person_rate_per_sample": round(first_person / n, 2),
        "question_rate_per_sample": round(questions / n, 2),
        "frequent_phrases": [" ".join(b) for b in top[:10]],
    }


def build_voice_card(stats: dict) -> str:
    """Render a markdown voice card for system-prompt injection."""
    if not stats:
        return "# Voice card (insufficient data)\n"
    return f"""# Voice card — {dt.date.today().isoformat()}

Built from {stats["samples"]} samples across recent sessions.

**Sentence length**: {stats["avg_sentence_len"]} ± {stats["stddev_sentence_len"]} words.
**Em-dash usage**: {stats["em_dash_rate_per_sample"]}/sample.
**Contractions**: {stats["contraction_rate_per_sample"]}/sample.
**Hedges** (maybe/perhaps/I think): {stats["hedge_rate_per_sample"]}/sample. {"Low — direct voice." if stats["hedge_rate_per_sample"] < 0.5 else "Moderate."}
**First-person 'I'**: {stats["first_person_rate_per_sample"]}/sample.
**Question marks**: {stats["question_rate_per_sample"]}/sample.

**Recurring phrases**:
{chr(10).join("- " + p for p in stats["frequent_phrases"])}

When asked to "draft as me" or write in this voice:
- Match sentence length distribution.
- Use contractions at the rate shown.
- Avoid hedges unless they were used in the original.
- Prefer phrases above when natural; never force them.
"""


def refresh_voice_card() -> str:
    samples = _user_authored_snippets(limit=200)
    stats = analyze(samples)
    card = build_voice_card(stats)
    VOICE_CARD.parent.mkdir(parents=True, exist_ok=True)
    VOICE_CARD.write_text(card)
    return card


@tool(
    "voice_card_refresh",
    "Re-analyze recent user messages to update the writing-voice card. Run periodically (or before drafting a long-form piece in the user's voice).",
    {},
)
async def _refresh(args: dict) -> dict:
    card = refresh_voice_card()
    return {"content": [{"type": "text", "text": card}]}


@tool(
    "voice_card_show",
    "Show the current voice card.",
    {},
)
async def _show(args: dict) -> dict:
    if not VOICE_CARD.is_file():
        return {"content": [{"type": "text", "text": "(no voice card; run voice_card_refresh)"}]}
    return {"content": [{"type": "text", "text": VOICE_CARD.read_text()}]}


SOUL_SYNC_SERVER = create_sdk_mcp_server(
    name="soul_sync",
    version="1.0.0",
    tools=[_refresh, _show],
)
