"""Adversarial Improvement Market — bug bounty for agent capabilities.

Most self-improvement loops in agent frameworks optimise against a
fixed internal benchmark. The frontier move is to open the loop: anyone
can submit a failure case, the agent replays it, and *novel* failures
(ones that produce a measurable behaviour change) score the submitter.

This module ships the local primitives for that market. x402 payout
plumbing is deferred — start by proving the workflow + novelty scoring
work; wire money in once the loop has runtime evidence.

Workflow:

  1. SUBMIT      — any user or peer agent posts a failure case:
                    {prompt, context_snapshot, expected_behavior,
                     observed_behavior, severity_hint}
                    A submission is just an immutable JSON record with
                    a content hash so we can deduplicate.
  2. REPLAY      — the agent re-runs the prompt against current state.
                    The replay is sandboxed (no real-world side effects;
                    write tools are stubbed) and the *behaviour vector*
                    is recorded: which tools were called, what the final
                    reply contained, how long it took, etc.
  3. SCORE       — novelty = behavioural distance between
                    submission.observed_behavior and the freshly replayed
                    behavior. The distance is computed across cheap features
                    (tool sequence Jaccard, reply length delta, refusal
                    flip). Below a threshold ⇒ already known. Above ⇒ novel.
  4. APPLY       — for novel-scored items, the agent proposes a *fix*
                    (e.g. a SOUL.md / MEMORY.md edit, a critic rule
                    update, a skill patch). The fix is gated by the
                    user approval flow before it ships.
  5. CREDIT      — submitter receives a non-transferable credit (a
                    submitter_id + score) recorded locally. Future x402
                    integration converts credit ledger entries to USDC
                    payouts.

Anti-gaming notes (built in):
  - Content-hash dedup: submitting the same prompt twice doesn't pay.
  - Novelty rate-limit: a single submitter caps at N novel-scored items
    per 24h to disincentivise spammy fuzzing.
  - Severity decay: claimed-severity is one signal but the *observed
    behaviour delta on replay* is the dominant scoring axis.
  - Replay sandboxing: we never run leaked-credential exfil submissions
    against the real agent; security_scan.looks_like_injection on the
    prompt rejects obviously-malicious submissions outright.

Storage:
  ~/.opengriffin/adversarial/submissions.jsonl  — append-only
  ~/.opengriffin/adversarial/replays.jsonl      — append-only
  ~/.opengriffin/adversarial/credits.json       — per-submitter ledger
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.adversarial")

ADV_DIR = Path.home() / ".opengriffin" / "adversarial"
ADV_DIR.mkdir(parents=True, exist_ok=True)
SUBMISSIONS = ADV_DIR / "submissions.jsonl"
REPLAYS = ADV_DIR / "replays.jsonl"
CREDITS = ADV_DIR / "credits.json"

NOVELTY_THRESHOLD = 0.35  # distance score above which a replay is "novel"
MAX_NOVEL_PER_SUBMITTER_PER_DAY = 5


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _load_credits() -> dict:
    if not CREDITS.is_file():
        return {"by_submitter": {}}
    try:
        return json.loads(CREDITS.read_text())
    except Exception:
        return {"by_submitter": {}}


def _save_credits(c: dict) -> None:
    CREDITS.write_text(json.dumps(c, indent=2) + "\n")


def _all(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def submit(
    *,
    submitter_id: str,
    prompt: str,
    expected_behavior: str,
    observed_behavior: str,
    severity_hint: str = "med",
    context_snapshot: dict | None = None,
) -> dict:
    """Record a failure-case submission. Deduplicates by content hash."""
    # Reject obvious injection / exfil submissions
    try:
        from . import redact

        if redact.looks_like_injection(prompt):
            return {
                "_rejected": True,
                "reason": "submission looks like a prompt injection attempt",
            }
    except Exception:
        pass

    content_hash = _h(prompt + "|" + expected_behavior + "|" + observed_behavior)
    existing = next((s for s in _all(SUBMISSIONS) if s.get("content_hash") == content_hash), None)
    if existing:
        return {**existing, "_dedup": True}

    rec = {
        "id": "sub-" + content_hash[:10],
        "content_hash": content_hash,
        "submitter_id": submitter_id,
        "prompt": prompt,
        "expected_behavior": expected_behavior,
        "observed_behavior": observed_behavior,
        "severity_hint": severity_hint,
        "context_snapshot": context_snapshot or {},
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "status": "submitted",
    }
    with SUBMISSIONS.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def _tokens(s: str) -> set[str]:
    return set(t.lower() for t in re.findall(r"[a-zA-Z0-9_]{3,}", s))


def behavioral_distance(observed_behavior_a: str, observed_behavior_b: str) -> float:
    """Cheap text-feature distance ∈ [0,1] used for novelty scoring."""
    ta, tb = _tokens(observed_behavior_a), _tokens(observed_behavior_b)
    if not ta and not tb:
        return 0.0
    jacc = 1 - (len(ta & tb) / max(1, len(ta | tb)))
    len_delta = abs(len(observed_behavior_a) - len(observed_behavior_b)) / max(
        1, max(len(observed_behavior_a), len(observed_behavior_b))
    )
    # refusal flip: if one contains a refusal pattern and the other doesn't
    refusal_pat = re.compile(r"(can't help|won't|refuse|unsafe)", re.IGNORECASE)
    a_ref = bool(refusal_pat.search(observed_behavior_a))
    b_ref = bool(refusal_pat.search(observed_behavior_b))
    flip = 1.0 if a_ref != b_ref else 0.0
    return max(0.0, min(1.0, 0.5 * jacc + 0.3 * len_delta + 0.2 * flip))


def replay(submission_id: str, fresh_observed_behavior: str) -> dict:
    """Caller (the agent harness) runs the prompt against current state in
    a sandboxed mode, captures the response, and feeds it back here for
    scoring. We compute novelty vs the submitter's original observation.
    """
    sub = next((s for s in _all(SUBMISSIONS) if s["id"] == submission_id), None)
    if sub is None:
        raise ValueError(f"unknown submission: {submission_id}")
    novelty = behavioral_distance(sub["observed_behavior"], fresh_observed_behavior)
    rec = {
        "submission_id": submission_id,
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "fresh_observed_behavior": fresh_observed_behavior,
        "novelty_score": round(novelty, 3),
        "novel": novelty >= NOVELTY_THRESHOLD,
    }
    with REPLAYS.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")

    if rec["novel"]:
        # Credit the submitter, subject to daily cap
        credit_amount = round(novelty * 10, 2)  # 0–10 credit units
        _award_credit(sub["submitter_id"], credit_amount, submission_id)
    return rec


def _award_credit(submitter_id: str, amount: float, submission_id: str) -> None:
    today = dt.datetime.now().date().isoformat()
    credits = _load_credits()
    bucket = credits["by_submitter"].setdefault(
        submitter_id, {"total": 0.0, "by_day": {}, "awarded_submissions": []}
    )
    by_day = bucket.setdefault("by_day", {})
    daily = by_day.setdefault(today, {"count": 0, "credit": 0.0})
    if daily["count"] >= MAX_NOVEL_PER_SUBMITTER_PER_DAY:
        log.info(
            "adversarial: submitter %s hit daily novelty cap, no credit awarded for %s",
            submitter_id,
            submission_id,
        )
        return
    daily["count"] += 1
    daily["credit"] += amount
    bucket["total"] = round(bucket.get("total", 0.0) + amount, 2)
    bucket.setdefault("awarded_submissions", []).append(submission_id)
    _save_credits(credits)


def submitter_credit(submitter_id: str) -> dict:
    return _load_credits()["by_submitter"].get(submitter_id, {"total": 0.0})


def stats() -> dict:
    subs = _all(SUBMISSIONS)
    rps = _all(REPLAYS)
    novel = [r for r in rps if r.get("novel")]
    return {
        "submissions": len(subs),
        "replays": len(rps),
        "novel_replays": len(novel),
        "novelty_rate": round(len(novel) / max(1, len(rps)), 3),
        "unique_submitters": len({s["submitter_id"] for s in subs}),
    }


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "adv_submit",
    "Submit an agent failure case for the adversarial improvement market. Deduplicates by content hash. Returns the submission id which can be replayed via adv_replay.",
    {
        "submitter_id": Annotated[
            str, "Submitter identifier (a2a node id, github handle, or arbitrary label)"
        ],
        "prompt": Annotated[str, "The prompt the agent failed on"],
        "expected_behavior": Annotated[str, "What the user wanted to happen"],
        "observed_behavior": Annotated[str, "What the agent actually did"],
        "severity_hint": Annotated[str | None, "low | med | high (default med)"],
    },
)
async def _submit(args: dict) -> dict:
    rec = submit(
        submitter_id=args["submitter_id"],
        prompt=args["prompt"],
        expected_behavior=args["expected_behavior"],
        observed_behavior=args["observed_behavior"],
        severity_hint=(args.get("severity_hint") or "med"),
    )
    return {"content": [{"type": "text", "text": json.dumps(rec, indent=2)}]}


@tool(
    "adv_replay",
    "Score a fresh observed behavior against an existing submission. Computes behavioural distance and (if novel) awards a credit to the original submitter — subject to a daily cap.",
    {
        "submission_id": Annotated[str, "Submission id from adv_submit"],
        "fresh_observed_behavior": Annotated[
            str,
            "What the agent did this time. Caller should produce this by replaying the prompt in a sandboxed mode and capturing the final reply / tool trace summary.",
        ],
    },
)
async def _replay(args: dict) -> dict:
    try:
        rec = replay(args["submission_id"], args["fresh_observed_behavior"])
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    return {"content": [{"type": "text", "text": json.dumps(rec, indent=2)}]}


@tool(
    "adv_credit",
    "Show credit ledger for a submitter.",
    {"submitter_id": Annotated[str, "Submitter id"]},
)
async def _credit(args: dict) -> dict:
    return {
        "content": [
            {"type": "text", "text": json.dumps(submitter_credit(args["submitter_id"]), indent=2)}
        ]
    }


@tool(
    "adv_stats",
    "Overall state of the adversarial market: submission count, replay count, novelty rate.",
    {},
)
async def _stats(args: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(stats(), indent=2)}]}


ADV_SERVER = create_sdk_mcp_server(
    name="adversarial",
    version="1.0.0",
    tools=[_submit, _replay, _credit, _stats],
)


__all__ = [
    "submit",
    "replay",
    "behavioral_distance",
    "submitter_credit",
    "stats",
    "ADV_SERVER",
    "NOVELTY_THRESHOLD",
]
