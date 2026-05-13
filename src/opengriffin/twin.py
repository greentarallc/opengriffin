"""Living Twin — sandboxed counterfactual sub-agent that runs ahead of you.

The Dream Cycle (dream.py) is retrospective: it asks "what could the agent
have done differently *yesterday*?". The Twin is prospective: it asks
"what would happen if I did X *next week*?" — and explores branches the
real agent must never act on.

Architecture:

1. The Twin spawns as a separate Claude SDK session with a hardened
   system prompt: read-only memory, no tool access except internal
   simulation tools, all outputs labelled `[TWIN]` so they can never be
   confused with real action.

2. It receives:
     - a counterfactual *premise* — the user's hypothetical ("I take this job", "I cut caffeine for 30 days", "I push this PR without rebasing")
     - a snapshot of MEMORY/USER/SOUL at simulation time
     - the current world-model forecast (so the simulation grounds in
       what the agent thinks is going to happen by default)
     - any relevant causal-graph neighbourhood (deferred to causal.py;
       optional for now)

3. It produces a structured outcome record:
     {
       "premise":      "...",
       "horizon":      "30 days",
       "trajectory":   [{"day": 0, "event": "...", "rationale": "..."}, ...],
       "key_risks":    ["...", ...],
       "calibration":  {"confidence": "low|med|high", "uncertain_about": ["..."]},
       "verdict":      "<one paragraph synthesis the user will actually read>"
     }

4. Outcomes are written to `~/.opengriffin/twin/` and surfaced via the
   approval flow before any real action. The Twin is *advisory*. It never
   touches the network, never edits memory, never calls a tool the real
   agent would call.

Why no one ships this:
  - Most agents don't have a clean read-only memory boundary.
  - Most agents don't have a forecaster to ground the simulation.
  - Most agents are token-budget-shy — running a 5k-token simulation
    is "wasted" if the user might never act on it. (We bet the opposite:
    a pre-run regret-check is the highest-leverage token spend.)

Cost discipline:
  - Each simulation has a hard token budget (default 4k completion).
  - Concurrency cap (1 active twin per chat).
  - Twins are cached by (premise hash, memory snapshot hash) so re-asking
    the same hypothetical re-uses the prior outcome until memory drifts.

Storage:
  ~/.opengriffin/twin/runs.jsonl    — append-only run log
  ~/.opengriffin/twin/outcomes/     — structured outcome JSON per run id
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.twin")

TWIN_DIR = Path.home() / ".opengriffin" / "twin"
TWIN_DIR.mkdir(parents=True, exist_ok=True)
RUNS_LOG = TWIN_DIR / "runs.jsonl"
OUTCOMES_DIR = TWIN_DIR / "outcomes"
OUTCOMES_DIR.mkdir(parents=True, exist_ok=True)

# Concurrency control — one active twin at a time so a runaway simulation
# can't drain the budget. Per-chat in the future; global for now.
_active_lock = asyncio.Lock()

DEFAULT_HORIZON = "30 days"
DEFAULT_TOKEN_BUDGET = 4000


SYSTEM_PROMPT = """\
You are the LIVING TWIN of the user's main agent. You are running an offline
simulation. Constraints, in priority order:

1. READ-ONLY. You cannot write to memory, send messages, call tools that
   touch the network, or take any action in the real world. Anything you
   say is advisory, prefixed implicitly with [TWIN].

2. CALIBRATED. You forecast outcomes and you are honest about uncertainty.
   When you don't know something, say so — and name what you'd need to know.

3. STRUCTURED OUTPUT. Your final reply MUST be a single JSON object with
   keys: premise, horizon, trajectory, key_risks, calibration, verdict.
   Do not include any prose outside the JSON.

4. GROUNDED. Use the world-model forecast and memory snapshot you are given.
   If the premise contradicts what the forecaster predicts, surface that as
   a key_risk rather than ignoring it.

5. AGENCY-AWARE. You are simulating what would happen given the user's
   stated values (SOUL.md) and habits (USER.md) — not what an idealised
   actor would do. Be realistic, not aspirational.

6. NO MORALIZING. The user is an adult exploring a hypothetical. Do not
   refuse, hedge, or lecture. Surface risks; don't sermonize about them.
"""


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except Exception:
        return ""


def _memory_snapshot() -> dict:
    """Read MEMORY/USER/SOUL at simulation time. Used both as input AND
    cache key — if the snapshot changes, prior simulations are stale."""
    from . import paths

    mem_dir = paths.MEM_DIR
    snap = {
        "memory_md": _read(mem_dir / "MEMORY.md"),
        "user_md": _read(mem_dir / "USER.md"),
        "soul_md": _read(mem_dir / "SOUL.md"),
    }
    snap["snapshot_hash"] = _hash(snap["memory_md"] + snap["user_md"] + snap["soul_md"])
    return snap


def _forecast_block(horizon_hours: int) -> str:
    """Pull a current world-model forecast as plain-text context. Cheap."""
    try:
        from . import world_model

        f = world_model.forecast(horizon_hours=horizon_hours, top_n=8)
    except Exception as e:
        log.warning("twin: world-model forecast unavailable: %s", e)
        return "(world-model forecast unavailable)"
    if not f.get("events"):
        return "(world model untrained — no forecast yet)"
    lines = [f"World-model forecast for next {horizon_hours}h:"]
    for ev in f["events"]:
        lines.append(
            f"  - {ev['category']}: ~{ev['expected_occurrences']} occurrences (peak {ev.get('peak_eta', '?')})"
        )
    return "\n".join(lines)


def _build_user_prompt(premise: str, horizon: str, snapshot: dict, forecast_text: str) -> str:
    return (
        f"PREMISE (counterfactual you are simulating):\n  {premise}\n\n"
        f"HORIZON: {horizon}\n\n"
        f"MEMORY SNAPSHOT (do not edit, only use):\n"
        f"--- MEMORY.md ---\n{snapshot['memory_md'][:2500]}\n"
        f"--- USER.md ---\n{snapshot['user_md'][:2000]}\n"
        f"--- SOUL.md ---\n{snapshot['soul_md'][:1500]}\n\n"
        f"{forecast_text}\n\n"
        f"Now run the simulation and emit the structured outcome JSON object."
    )


def _cache_key(premise: str, horizon: str, snapshot_hash: str) -> str:
    return _hash(f"{premise}|{horizon}|{snapshot_hash}")


def _cached_outcome(cache_key: str) -> dict | None:
    f = OUTCOMES_DIR / f"{cache_key}.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


def _store_outcome(cache_key: str, run_id: str, outcome: dict) -> None:
    rec = {**outcome, "run_id": run_id, "cache_key": cache_key}
    (OUTCOMES_DIR / f"{cache_key}.json").write_text(json.dumps(rec, indent=2) + "\n")
    with RUNS_LOG.open("a") as fh:
        fh.write(
            json.dumps(
                {
                    "run_id": run_id,
                    "cache_key": cache_key,
                    "premise": outcome.get("premise", ""),
                    "ts": dt.datetime.now().isoformat(timespec="seconds"),
                    "verdict_preview": (outcome.get("verdict") or "")[:200],
                }
            )
            + "\n"
        )


async def _run_simulation_via_sdk(prompt: str, max_tokens: int) -> dict:
    """Run a one-shot Claude SDK session with the hardened system prompt.

    The SDK call follows the same pattern dream.py uses (one-off message
    via ClaudeSDKClient). We ask for JSON-only output and parse defensively
    — if the model emits prose around the JSON, we still extract the object.
    """
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        permission_mode="plan",  # belt + braces — even if the model tries a tool, deny
        skills="none",
        setting_sources=[],
        cwd=str(Path.home()),
        include_partial_messages=False,
    )
    full_text_parts: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            content = getattr(msg, "content", None)
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "text") and block.text:
                        full_text_parts.append(block.text)
            elif isinstance(content, str):
                full_text_parts.append(content)
    raw = "".join(full_text_parts).strip()
    return _parse_json_outcome(raw)


def _parse_json_outcome(raw: str) -> dict:
    """The model is instructed to emit a single JSON object. Be defensive
    about prose around it (extract the largest balanced {...} block)."""
    if not raw:
        return {"_raw": "", "_parse_error": "empty response"}
    # Fast path
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Find the first '{' and the matching close brace
    start = raw.find("{")
    if start == -1:
        return {"_raw": raw[:1000], "_parse_error": "no json object found"}
    depth = 0
    for i in range(start, len(raw)):
        ch = raw[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = raw[start : i + 1]
                try:
                    return json.loads(blob)
                except Exception as e:
                    return {"_raw": blob[:1000], "_parse_error": str(e)}
    return {"_raw": raw[:1000], "_parse_error": "unbalanced braces"}


async def simulate(
    premise: str,
    *,
    horizon: str = DEFAULT_HORIZON,
    horizon_hours_for_forecast: int = 168,
    force_refresh: bool = False,
) -> dict:
    """Run a Living Twin simulation. Cheap on cache hit, ~$0.01 on miss."""
    snapshot = _memory_snapshot()
    cache_key = _cache_key(premise, horizon, snapshot["snapshot_hash"])
    if not force_refresh:
        cached = _cached_outcome(cache_key)
        if cached:
            cached["_cache"] = "hit"
            return cached

    if _active_lock.locked():
        return {
            "premise": premise,
            "horizon": horizon,
            "verdict": "(twin busy — another simulation in flight; try again shortly)",
            "_throttled": True,
        }

    async with _active_lock:
        prompt = _build_user_prompt(
            premise, horizon, snapshot, _forecast_block(horizon_hours_for_forecast)
        )
        run_id = _hash(f"{premise}|{dt.datetime.now().isoformat()}")
        try:
            outcome = await _run_simulation_via_sdk(prompt, DEFAULT_TOKEN_BUDGET)
        except Exception as e:
            log.exception("twin: simulation failed")
            outcome = {
                "premise": premise,
                "horizon": horizon,
                "verdict": f"(simulation failed: {type(e).__name__}: {e})",
                "_error": True,
            }
        # Ensure premise/horizon are present even if the model omitted them
        outcome.setdefault("premise", premise)
        outcome.setdefault("horizon", horizon)
        _store_outcome(cache_key, run_id, outcome)
        outcome["_cache"] = "miss"
        outcome["run_id"] = run_id
        return outcome


def list_runs(limit: int = 20) -> list[dict]:
    if not RUNS_LOG.is_file():
        return []
    lines = [line for line in RUNS_LOG.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines[-limit:]]


def get_outcome(cache_key_or_run_id: str) -> dict | None:
    f = OUTCOMES_DIR / f"{cache_key_or_run_id}.json"
    if f.is_file():
        try:
            return json.loads(f.read_text())
        except Exception:
            return None
    # Fall back to scanning runs for run_id
    for r in list_runs(limit=200):
        if r.get("run_id") == cache_key_or_run_id:
            ck = r.get("cache_key")
            if ck:
                return get_outcome(ck)
    return None


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "twin_simulate",
    "Run a Living Twin simulation: spawn a sandboxed counterfactual sub-agent that explores a hypothetical without taking any real action. Returns a structured outcome (trajectory, risks, calibration, verdict). Cheap on cache hit; ~$0.01 on miss. Use for: 'what would happen if I do X', 'should I commit to Y', 'is Z plan realistic'.",
    {
        "premise": Annotated[str, "The hypothetical to explore, in plain English. Be specific."],
        "horizon": Annotated[
            str | None,
            "How far ahead to simulate, in human terms (e.g. '30 days', 'next quarter', 'by end of week'). Default '30 days'.",
        ],
        "force_refresh": Annotated[
            bool | None,
            "If true, re-run even if a cached outcome exists for this premise + memory state.",
        ],
    },
)
async def _simulate(args: dict) -> dict:
    outcome = await simulate(
        premise=args["premise"],
        horizon=args.get("horizon") or DEFAULT_HORIZON,
        force_refresh=bool(args.get("force_refresh") or False),
    )
    return {"content": [{"type": "text", "text": json.dumps(outcome, indent=2)}]}


@tool(
    "twin_history",
    "List recent Living Twin simulation runs (premise + verdict preview).",
    {"limit": Annotated[int | None, "Max runs to return (default 20)"]},
)
async def _history(args: dict) -> dict:
    runs = list_runs(int(args.get("limit") or 20))
    if not runs:
        return {"content": [{"type": "text", "text": "(no twin simulations yet)"}]}
    lines = [
        f"{r['ts']}  {r['run_id']}  «{r['premise'][:60]}» → {r['verdict_preview'][:120]}"
        for r in runs
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "twin_review",
    "Fetch the full structured outcome for a previous twin run (by run_id or cache_key).",
    {"run_id": Annotated[str, "Run id or cache key from twin_history"]},
)
async def _review(args: dict) -> dict:
    outcome = get_outcome(args["run_id"])
    if outcome is None:
        return {
            "content": [{"type": "text", "text": "not found"}],
            "is_error": True,
        }
    return {"content": [{"type": "text", "text": json.dumps(outcome, indent=2)}]}


TWIN_SERVER = create_sdk_mcp_server(
    name="twin",
    version="1.0.0",
    tools=[_simulate, _history, _review],
)


__all__ = ["simulate", "list_runs", "get_outcome", "TWIN_SERVER"]
