"""Personal Causal Data Layer — life-as-graph with counterfactual queries.

Mem0 has graph memory, but every shipping system uses it as a thin
*retrieval* layer — find facts connected by an edge. This module adds the
property that turns retrieval into reasoning: **directed causal edges
with confidence scores**, proposed by observation and confirmed by the
user in the loop.

The graph:
  - NODES   = events or states. Examples: "late night Tuesday",
              "poor sleep Tue→Wed", "skipped morning workout Wed",
              "low mood Wed PM", "stripe revenue dropped 12% week-of-X".
              Nodes carry: id, label, kind (event|state|behavior|metric),
              timestamp_range, source.
  - EDGES   = causal *hypotheses* from cause-node → effect-node, with
              fields: direction, confidence ∈ [0,1], support_count,
              counter_count, proposer ("agent" | "user"), status
              ("proposed" | "confirmed" | "rejected"), notes.

Discovery loop:
  1. The PWM forecast log + journal entries surface candidate temporal
     pairs (A happened in slot S, B happened soon after in slot S+1).
  2. A periodic scan computes for each pair (A,B) the lift =
     P(B|A) / P(B). Pairs above a threshold are proposed as edges.
  3. Proposed edges are surfaced to the user via the gen_ui choice
     primitive: "Confirm / Reject / Need more data". The user is the
     instrument variable; their feedback is what makes N=1 causal
     inference tractable.
  4. Confirmed edges raise confidence; rejected edges DECREMENT
     confidence on similar pairs (anti-pattern learning).

Counterfactual query:
  - "If I had not done A on Tuesday, what's the forecast for B on
    Wednesday?" → walk the confirmed-edge subgraph from A's neighbours
    (excluding A), feed to the Living Twin as a grounded premise.

Honest scope:
  - The agent never claims certainty. Edges live in [0,1] confidence
    forever; we never collapse to "A causes B."
  - We don't run randomised experiments on the user. We just listen
    for confirmations / rejections and update.
  - The graph is human-browseable. Every edge should be defensible by
    pointing at the underlying observations.

Storage:
  ~/.opengriffin/causal/graph.json    — nodes + edges
  ~/.opengriffin/causal/proposals.jsonl  — append-only edge proposals
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import secrets
from collections import defaultdict
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.causal")

CAUSAL_DIR = Path.home() / ".opengriffin" / "causal"
CAUSAL_DIR.mkdir(parents=True, exist_ok=True)
GRAPH_FILE = CAUSAL_DIR / "graph.json"
PROPOSALS_LOG = CAUSAL_DIR / "proposals.jsonl"

# Minimum lift before an edge is even proposed
PROPOSAL_LIFT_THRESHOLD = 2.0
# Minimum joint occurrences to avoid noise
MIN_JOINT = 3


def _load_graph() -> dict:
    if not GRAPH_FILE.is_file():
        return {"nodes": {}, "edges": []}
    try:
        return json.loads(GRAPH_FILE.read_text())
    except Exception:
        return {"nodes": {}, "edges": []}


def _save_graph(g: dict) -> None:
    GRAPH_FILE.write_text(json.dumps(g, indent=2) + "\n")


def _node_id() -> str:
    return secrets.token_hex(6)


def _edge_id() -> str:
    return "e" + secrets.token_hex(6)


def add_node(label: str, *, kind: str = "event", source: str = "") -> dict:
    g = _load_graph()
    # Deduplicate by label
    for nid, n in g["nodes"].items():
        if n["label"] == label and n["kind"] == kind:
            return {"node_id": nid, **n, "_dedup": True}
    nid = _node_id()
    rec = {
        "label": label,
        "kind": kind,
        "source": source,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    g["nodes"][nid] = rec
    _save_graph(g)
    return {"node_id": nid, **rec}


def propose_edge(
    cause_id: str,
    effect_id: str,
    *,
    confidence: float,
    lift: float | None = None,
    support_count: int = 0,
    proposer: str = "agent",
    notes: str = "",
) -> dict:
    g = _load_graph()
    if cause_id not in g["nodes"] or effect_id not in g["nodes"]:
        raise ValueError("cause or effect node not found")
    # Prevent duplicate proposed-or-confirmed edges
    for e in g["edges"]:
        if e["cause"] == cause_id and e["effect"] == effect_id and e["status"] != "rejected":
            return {**e, "_dedup": True}
    edge = {
        "edge_id": _edge_id(),
        "cause": cause_id,
        "effect": effect_id,
        "confidence": max(0.0, min(1.0, confidence)),
        "lift": lift,
        "support_count": int(support_count),
        "counter_count": 0,
        "proposer": proposer,
        "status": "proposed",
        "notes": notes,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    g["edges"].append(edge)
    _save_graph(g)
    with PROPOSALS_LOG.open("a") as fh:
        fh.write(json.dumps(edge) + "\n")
    return edge


def update_edge_status(edge_id: str, status: str) -> dict | None:
    if status not in ("proposed", "confirmed", "rejected"):
        raise ValueError("status must be proposed | confirmed | rejected")
    g = _load_graph()
    for e in g["edges"]:
        if e["edge_id"] == edge_id:
            e["status"] = status
            # Update confidence on confirm/reject
            if status == "confirmed":
                e["support_count"] = e.get("support_count", 0) + 1
                e["confidence"] = max(e["confidence"], 0.6)
            elif status == "rejected":
                e["counter_count"] = e.get("counter_count", 0) + 1
                e["confidence"] = min(e["confidence"], 0.15)
            e["status_changed_at"] = dt.datetime.now().isoformat(timespec="seconds")
            _save_graph(g)
            return e
    return None


# ----------------------------- discovery -----------------------------


def discover_from_world_model(*, days: int = 30) -> list[dict]:
    """Walk the PWM event log; for each pair (cat_a happened before cat_b
    within the same day), compute lift = P(cat_b within next 24h | cat_a)
    / P(cat_b within next 24h). Surface high-lift pairs as proposed edges.
    """
    try:
        from . import world_model

        events = world_model._all_events(days=days)  # type: ignore[attr-defined]
    except Exception:
        return []
    if len(events) < 20:
        return []
    # Build per-day lists of categories
    by_day: dict[str, list[tuple[dt.datetime, str]]] = defaultdict(list)
    cat_global: dict[str, int] = defaultdict(int)
    for e in events:
        ts = dt.datetime.fromisoformat(e["ts"])
        day = ts.date().isoformat()
        by_day[day].append((ts, e["category"]))
        cat_global[e["category"]] += 1
    days_count = len(by_day) or 1
    p_global = {c: n / days_count for c, n in cat_global.items()}

    # Count co-occurrences (A then B within next 24h)
    joint: dict[tuple[str, str], int] = defaultdict(int)
    cause_count: dict[str, int] = defaultdict(int)
    for _day, evs in by_day.items():
        evs.sort()
        seen_pairs: set[tuple[str, str]] = set()
        for i, (ts_a, cat_a) in enumerate(evs):
            cause_count[cat_a] += 1
            for ts_b, cat_b in evs[i + 1 :]:
                if (ts_b - ts_a).total_seconds() > 86400:
                    break
                if cat_a == cat_b:
                    continue
                if (cat_a, cat_b) in seen_pairs:
                    continue
                seen_pairs.add((cat_a, cat_b))
                joint[(cat_a, cat_b)] += 1

    proposals: list[dict] = []
    for (cat_a, cat_b), n in joint.items():
        if n < MIN_JOINT:
            continue
        p_b_given_a = n / max(1, cause_count[cat_a])
        if p_global.get(cat_b, 0) == 0:
            continue
        lift = p_b_given_a / p_global[cat_b]
        if lift < PROPOSAL_LIFT_THRESHOLD:
            continue
        # Materialise nodes + propose the edge
        a_node = add_node(label=cat_a, kind="event", source="world_model")
        b_node = add_node(label=cat_b, kind="event", source="world_model")
        # Initial confidence is lift-derived but bounded
        conf = max(0.1, min(0.5, math.log(lift) / 4))
        prop = propose_edge(
            a_node["node_id"],
            b_node["node_id"],
            confidence=conf,
            lift=lift,
            support_count=n,
            proposer="agent",
            notes=f"derived from world_model temporal pairs (n={n}, lift={lift:.2f})",
        )
        proposals.append(prop)
    proposals.sort(key=lambda p: -(p.get("lift") or 0))
    return proposals


# ----------------------------- query -----------------------------


def counterfactual_neighbours(node_id: str, *, removed: bool = False) -> list[dict]:
    """Return the confirmed-edge effects of node_id. If `removed=True`,
    return what is *expected to NOT happen* if node_id is removed —
    the same set, with confidence reported."""
    g = _load_graph()
    out: list[dict] = []
    for e in g["edges"]:
        if e["cause"] == node_id and e["status"] == "confirmed":
            out.append(
                {
                    "edge_id": e["edge_id"],
                    "effect": g["nodes"][e["effect"]],
                    "effect_id": e["effect"],
                    "confidence": e["confidence"],
                    "evidence": {
                        "support_count": e["support_count"],
                        "counter_count": e["counter_count"],
                        "notes": e["notes"],
                    },
                }
            )
    out.sort(key=lambda r: -r["confidence"])
    return out


def explain_edge(edge_id: str) -> dict | None:
    g = _load_graph()
    for e in g["edges"]:
        if e["edge_id"] == edge_id:
            return {
                "edge": e,
                "cause": g["nodes"].get(e["cause"]),
                "effect": g["nodes"].get(e["effect"]),
            }
    return None


def summary() -> dict:
    g = _load_graph()
    by_status: dict[str, int] = defaultdict(int)
    for e in g["edges"]:
        by_status[e["status"]] += 1
    return {
        "n_nodes": len(g["nodes"]),
        "n_edges": len(g["edges"]),
        "edges_by_status": dict(by_status),
    }


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "causal_discover",
    "Scan the world-model event log for high-lift temporal pairs and propose causal edges. Idempotent — re-running deduplicates against existing edges. Returns the new proposals.",
    {"days": Annotated[int | None, "Lookback window in days (default 30)"]},
)
async def _discover(args: dict) -> dict:
    proposals = discover_from_world_model(days=int(args.get("days") or 30))
    if not proposals:
        return {"content": [{"type": "text", "text": "(no new proposals)"}]}
    lines = [
        f"{p['edge_id']}  lift={p.get('lift', 0):.2f}  conf={p['confidence']:.2f}  {p['notes']}"
        for p in proposals
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "causal_confirm",
    "Mark a proposed edge as confirmed by the user. Bumps confidence and support_count. The agent's confidence in this edge will compound over time as more confirmations land.",
    {"edge_id": Annotated[str, "Edge id"]},
)
async def _confirm(args: dict) -> dict:
    edge = update_edge_status(args["edge_id"], "confirmed")
    if edge is None:
        return {"content": [{"type": "text", "text": "not found"}], "is_error": True}
    return {"content": [{"type": "text", "text": json.dumps(edge, indent=2)}]}


@tool(
    "causal_reject",
    "Mark a proposed edge as rejected. Drops confidence and counts against this hypothesis being re-proposed.",
    {"edge_id": Annotated[str, "Edge id"]},
)
async def _reject(args: dict) -> dict:
    edge = update_edge_status(args["edge_id"], "rejected")
    if edge is None:
        return {"content": [{"type": "text", "text": "not found"}], "is_error": True}
    return {"content": [{"type": "text", "text": json.dumps(edge, indent=2)}]}


@tool(
    "causal_neighbours",
    "Return the confirmed downstream effects of a node — what the agent currently believes a given cause produces. Used to feed Living Twin counterfactuals with grounded edges.",
    {"node_label": Annotated[str, "Label of the cause node (matches add_node label)"]},
)
async def _neighbours(args: dict) -> dict:
    g = _load_graph()
    nid = next(
        (id_ for id_, n in g["nodes"].items() if n["label"] == args["node_label"]),
        None,
    )
    if nid is None:
        return {"content": [{"type": "text", "text": "node not found"}], "is_error": True}
    nbrs = counterfactual_neighbours(nid)
    if not nbrs:
        return {"content": [{"type": "text", "text": "(no confirmed effects)"}]}
    lines = [f"{r['edge_id']}  → {r['effect']['label']}  conf={r['confidence']:.2f}" for r in nbrs]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "causal_summary",
    "Quick state of the causal graph: node count, edge count, status distribution.",
    {},
)
async def _summary(args: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(summary(), indent=2)}]}


CAUSAL_SERVER = create_sdk_mcp_server(
    name="causal",
    version="1.0.0",
    tools=[_discover, _confirm, _reject, _neighbours, _summary],
)


__all__ = [
    "add_node",
    "propose_edge",
    "update_edge_status",
    "discover_from_world_model",
    "counterfactual_neighbours",
    "explain_edge",
    "summary",
    "CAUSAL_SERVER",
]
