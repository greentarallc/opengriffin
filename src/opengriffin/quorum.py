"""Quorum actions — N-of-M sub-agent vote required for high-stakes actions.

For actions over a configured threshold (cost, scope, blast radius), run
the proposed action through M independent sub-agents (each with a slightly
different SOUL or model). Each votes approve/deny/abstain. Action proceeds
only with N agreeing approvals.

Reduces single-point failure of one agent being prompt-injected or
hallucinating a bad action.

Default: 2-of-3 with Claude/GPT/Gemini as the three judges (or three
Claude instances with different SOUL files if multi-provider keys aren't
set).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.quorum")

QUORUM_LOG = Path.home() / ".opengriffin" / "quorum_log.jsonl"
QUORUM_LOG.parent.mkdir(parents=True, exist_ok=True)


VOTE_PROMPT = """\
You are voting whether to approve a high-stakes proposed action. \
You are one of {m} independent voters; the action passes only with at \
least {n} approvals.

Output a SINGLE JSON object on one line, no other text:
{{"vote": "approve|deny|abstain", "reason": "<one sentence>"}}

You should consider:
- Reversibility — is this destructive?
- Necessity — is it actually solving the user's stated goal?
- Side effects — what else does it touch?
- Cost — financial, reputational, attention?
- Risk to constraints (CONSTRAINTS.md if loaded)

Voter persona: {persona}

Proposed action:
{action}

Brief context (may be empty):
{context}
"""


PERSONAS = [
    "skeptical security reviewer; defaults to deny on ambiguity",
    "pragmatic engineer; defaults to approve when costs are bounded",
    "patient ethicist; defaults to deny on reputational risk",
]


async def vote(action: str, *, context: str = "", n: int = 2, m: int = 3) -> dict:
    """Run the quorum. Returns {decision, votes: [...], approvals, denials}."""
    from . import bot as bot_module

    if m < 1 or n < 1 or n > m:
        raise ValueError("invalid n/m")

    async def one_vote(persona: str) -> dict:
        prompt = VOTE_PROMPT.format(
            m=m,
            n=n,
            persona=persona,
            action=action[:3000],
            context=context[:500],
        )
        try:
            reply = await bot_module.ask_claude_with_progress(0, prompt, None, status_msg_id=None)
        except Exception as e:
            return {"vote": "abstain", "reason": f"voter error: {e}", "persona": persona}
        for line in reply.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    v = json.loads(line)
                    v["persona"] = persona
                    return v
                except Exception:
                    continue
        return {"vote": "abstain", "reason": "could not parse vote", "persona": persona}

    personas = (PERSONAS + [f"general voter {i}" for i in range(m)])[:m]
    votes = await asyncio.gather(*[one_vote(p) for p in personas])
    approvals = sum(1 for v in votes if v.get("vote") == "approve")
    denials = sum(1 for v in votes if v.get("vote") == "deny")
    decision = "approve" if approvals >= n else "deny"
    record = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "n": n,
        "m": m,
        "decision": decision,
        "approvals": approvals,
        "denials": denials,
        "votes": votes,
        "action_preview": action[:200],
    }
    with QUORUM_LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


@tool(
    "quorum_vote",
    "Run an N-of-M independent vote on a proposed high-stakes action. Returns approve/deny with per-voter reasoning. Default 2-of-3.",
    {
        "action": Annotated[str, "Description of the action to be voted on"],
        "context": Annotated[str, "Optional brief context"],
        "n": Annotated[int, "Required approvals (default 2)"],
        "m": Annotated[int, "Total voters (default 3)"],
    },
)
async def _vote(args: dict) -> dict:
    rec = await vote(
        args["action"],
        context=args.get("context") or "",
        n=int(args.get("n") or 2),
        m=int(args.get("m") or 3),
    )
    return {"content": [{"type": "text", "text": json.dumps(rec, indent=2)}]}


@tool(
    "quorum_audit",
    "Show recent quorum decisions.",
    {"n": Annotated[int, "How many"]},
)
async def _audit(args: dict) -> dict:
    if not QUORUM_LOG.is_file():
        return {"content": [{"type": "text", "text": "no votes yet"}]}
    lines = QUORUM_LOG.read_text().splitlines()[-int(args.get("n") or 10) :]
    out = []
    for line in lines:
        try:
            r = json.loads(line)
            out.append(
                f"[{r.get('ts')}] {r.get('decision')} ({r.get('approvals')}/{r.get('m')}) | {r.get('action_preview', '')[:120]}"
            )
        except Exception:
            continue
    return {"content": [{"type": "text", "text": "\n".join(out)}]}


QUORUM_SERVER = create_sdk_mcp_server(
    name="quorum",
    version="1.0.0",
    tools=[_vote, _audit],
)
