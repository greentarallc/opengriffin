"""Agent Reputation Ledger — public, opt-in, signed JSON-LD profile.

Each OpenGriffin instance can publish a public reputation page at
opengriffin.com/u/<handle> (or self-hosted at any domain) that includes:
  - completed task count (from kanban + cron history)
  - approval rate (from approvals.py outcomes)
  - specialties (top categories from skill usage)
  - public skills authored (skills with author=user.handle)
  - signature (Ed25519 over the canonical JSON)

Used for A2A discovery — agent X can vet agent Y before delegating.

Stored at:
  ~/.opengriffin/reputation.json    — local source-of-truth
  reputation.signed.json          — signed payload published to your domain
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

REP_FILE = Path.home() / ".opengriffin" / "reputation.json"
REP_SIGNED = Path.home() / ".opengriffin" / "reputation.signed.json"
KANBAN = Path.home() / ".opengriffin" / "kanban.json"
USAGE = Path.home() / ".opengriffin" / "usage.jsonl"
SKILLS_DIR = Path.home() / ".claude" / "skills"


def _kanban_stats() -> dict:
    if not KANBAN.is_file():
        return {"completed": 0, "blocked": 0}
    try:
        data = json.loads(KANBAN.read_text())
    except Exception:
        return {"completed": 0, "blocked": 0}
    counts = {"completed": 0, "blocked": 0, "doing": 0}
    for t in data.get("tasks", []):
        s = t.get("status")
        if s in counts:
            counts[s] += 1
    return counts


def _usage_stats() -> dict:
    if not USAGE.is_file():
        return {"sessions": 0, "total_cost_usd": 0}
    sessions = set()
    total_cost = 0.0
    for line in USAGE.read_text().splitlines():
        try:
            e = json.loads(line)
            if e.get("session_id"):
                sessions.add(e["session_id"])
            total_cost += float(e.get("cost_usd") or 0)
        except Exception:
            continue
    return {"sessions": len(sessions), "total_cost_usd": round(total_cost, 4)}


def _user_authored_skills(handle: str) -> list[str]:
    if not SKILLS_DIR.is_dir():
        return []
    out = []
    for d in SKILLS_DIR.iterdir():
        sk = d / "SKILL.md"
        if sk.is_file():
            text = sk.read_text(errors="replace")[:500]
            if f"author: {handle}" in text or f"author: '{handle}'" in text:
                out.append(d.name)
    return sorted(out)


def build_profile(handle: str, *, public: bool = True) -> dict:
    """Compute the canonical reputation profile.

    No backend dependency: the @context is just a JSON-LD identifier
    (informational, not a URL the verifier must fetch). The `url` is
    where YOU choose to host the public profile JSON — set
    OPENGRIFFIN_REPUTATION_BASE_URL env var to override or leave empty
    to skip publishing.
    """
    base = os.environ.get("OPENGRIFFIN_REPUTATION_BASE_URL", "").rstrip("/")
    public_url = f"{base}/{handle}" if (public and base) else ""
    profile = {
        "@context": "urn:opengriffin:reputation-v1",
        "@type": "AgentReputation",
        "handle": handle,
        "url": public_url,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "kanban": _kanban_stats(),
        "usage": _usage_stats(),
        "authored_skills": _user_authored_skills(handle),
        "specialties": [],  # filled from skill_strategy.usage_counts top categories
        "version": "0.1",
    }
    return profile


def sign_profile(profile: dict) -> dict:
    """Sign with an Ed25519 key if available; otherwise produce an unsigned payload."""
    payload = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        return {"profile": profile, "signature": None, "warning": "cryptography not installed"}
    key_path = os.environ.get("OPENGRIFFIN_SIGNING_KEY") or str(
        Path.home() / ".opengriffin" / "signing.key"
    )
    if not Path(key_path).is_file():
        return {"profile": profile, "signature": None, "warning": "no signing key at " + key_path}
    pk = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
    sig = pk.sign(payload).hex()
    return {"profile": profile, "signature": sig, "algorithm": "ed25519"}


def write_signed(handle: str) -> dict:
    profile = build_profile(handle)
    REP_FILE.write_text(json.dumps(profile, indent=2))
    signed = sign_profile(profile)
    REP_SIGNED.write_text(json.dumps(signed, indent=2))
    return signed


@tool(
    "reputation_publish",
    "Generate (and optionally sign) the agent's public reputation profile. Writes to ~/.opengriffin/reputation.signed.json — upload to your domain at the path schema requires.",
    {"handle": Annotated[str, "Your public handle (e.g. 'alice')"]},
)
async def _publish(args: dict) -> dict:
    signed = write_signed(args["handle"])
    return {"content": [{"type": "text", "text": json.dumps(signed, indent=2)[:3000]}]}


@tool(
    "reputation_show",
    "Show the latest computed reputation profile (without re-signing).",
    {"handle": Annotated[str, "Public handle"]},
)
async def _show(args: dict) -> dict:
    profile = build_profile(args["handle"])
    return {"content": [{"type": "text", "text": json.dumps(profile, indent=2)}]}


REPUTATION_SERVER = create_sdk_mcp_server(
    name="reputation",
    version="1.0.0",
    tools=[_publish, _show],
)
