"""ZK-style action proofs — Merkle-tree audit log + selective reveal.

Honest about scope: this is NOT zkSNARKs. Real ZK is heavy and overkill
for this use case. What we implement:

  1. Append every consequential action as a leaf in a hash-chained,
     Merkle-rooted log.
  2. Periodically publish the current Merkle root (commitment) somewhere
     immutable (text file you push to a public repo, signed tweet, etc).
  3. To prove an action existed without revealing other actions, produce
     a Merkle inclusion proof for that single leaf. Verifiers reconstruct
     the root from {leaf, proof_path} and check it matches the committed
     root.

This gives you:
  - Tamper evidence: any change to old entries breaks the chain.
  - Selective disclosure: reveal one action without exposing others.
  - Public auditability: commit to root publicly, prove inclusion later.

What it does NOT give you:
  - Hiding the *existence* of actions (count is leaked).
  - Privacy of action contents until you reveal them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

LOG = Path.home() / ".opengriffin" / "zk_audit.jsonl"
ROOTS = Path.home() / ".opengriffin" / "zk_roots.jsonl"
LOG.parent.mkdir(parents=True, exist_ok=True)


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _leaf_hash(payload: str) -> str:
    return _h(b"leaf:" + payload.encode("utf-8"))


def _internal_hash(left: str, right: str) -> str:
    return _h(b"internal:" + left.encode() + b"|" + right.encode())


def append(action_kind: str, payload: dict | str) -> dict:
    """Append a leaf. Returns {index, leaf_hash, prev_root}."""
    body = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else payload
    prev_root = _current_root()
    leaf_input = json.dumps(
        {
            "action_kind": action_kind,
            "payload": body,
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "prev_root": prev_root,
        },
        sort_keys=True,
    )
    leaf = _leaf_hash(leaf_input)
    entry = {
        "index": _next_index(),
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "action_kind": action_kind,
        "payload": body[:2000],
        "leaf": leaf,
        "prev_root": prev_root,
    }
    with LOG.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def _all_entries() -> list[dict]:
    if not LOG.is_file():
        return []
    out = []
    for line in LOG.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _next_index() -> int:
    return len(_all_entries())


def _merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return _h(b"empty")
    layer = list(leaves)
    while len(layer) > 1:
        nxt = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else layer[i]  # duplicate last if odd
            nxt.append(_internal_hash(left, right))
        layer = nxt
    return layer[0]


def _current_root() -> str:
    leaves = [e["leaf"] for e in _all_entries()]
    return _merkle_root(leaves)


def commit_root() -> dict:
    """Snapshot the current root. Print/share this — it's the public commitment."""
    root = _current_root()
    n = len(_all_entries())
    rec = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "root": root,
        "leaf_count": n,
    }
    with ROOTS.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def inclusion_proof(index: int) -> dict:
    """Generate a Merkle inclusion proof for leaf at `index`.

    Returns {leaf, leaf_index, path: [{sibling, side}], root}.
    A verifier can reconstruct the root from leaf + path.
    """
    entries = _all_entries()
    if not (0 <= index < len(entries)):
        raise ValueError(f"index {index} out of range")
    leaves = [e["leaf"] for e in entries]
    target = leaves[index]
    path: list[dict] = []
    layer = leaves[:]
    idx = index
    while len(layer) > 1:
        nxt = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else layer[i]
            nxt.append(_internal_hash(left, right))
        # Record sibling for this layer
        sibling_idx = idx + 1 if idx % 2 == 0 else idx - 1
        if sibling_idx >= len(layer):
            sibling_idx = idx  # duplicated odd
        path.append(
            {
                "sibling": layer[sibling_idx],
                "side": "right" if idx % 2 == 0 else "left",
            }
        )
        idx = idx // 2
        layer = nxt
    return {
        "leaf": target,
        "leaf_index": index,
        "path": path,
        "root": _merkle_root(leaves),
        "entry_preview": json.dumps(entries[index])[:400],
    }


def verify_proof(leaf: str, path: list[dict], expected_root: str) -> bool:
    """Verifier-side: reconstruct root from leaf + path; compare to expected."""
    computed = leaf
    for step in path:
        sib = step["sibling"]
        if step["side"] == "right":
            computed = _internal_hash(computed, sib)
        else:
            computed = _internal_hash(sib, computed)
    return computed == expected_root


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "zk_append",
    "Append an action to the Merkle-rooted audit log. Returns the new leaf hash + previous root.",
    {
        "action_kind": Annotated[str, "Type of action"],
        "payload_json": Annotated[str, "JSON payload"],
    },
)
async def _append(args: dict) -> dict:
    payload = json.loads(args["payload_json"])
    entry = append(args["action_kind"], payload)
    return {"content": [{"type": "text", "text": json.dumps(entry, indent=2)}]}


@tool(
    "zk_commit_root",
    "Snapshot the current Merkle root for public commitment. Share this hash anywhere immutable to lock the audit log state.",
    {},
)
async def _commit(args: dict) -> dict:
    rec = commit_root()
    return {
        "content": [
            {
                "type": "text",
                "text": f"COMMIT root: {rec['root']}\nleaves: {rec['leaf_count']}\nat: {rec['ts']}\n\nPublish this root publicly to enable later proof verification.",
            }
        ]
    }


@tool(
    "zk_proof",
    "Generate a Merkle inclusion proof for a single leaf. Reveal this + the leaf data to prove the action was logged WITHOUT revealing any other entries.",
    {"index": Annotated[int, "Leaf index in the log"]},
)
async def _proof(args: dict) -> dict:
    try:
        proof = inclusion_proof(int(args["index"]))
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    return {"content": [{"type": "text", "text": json.dumps(proof, indent=2)}]}


@tool(
    "zk_verify",
    "Verify a Merkle inclusion proof (you'd typically run this on the verifier side, not as the agent).",
    {
        "leaf": Annotated[str, "Leaf hash"],
        "path_json": Annotated[str, "JSON-encoded proof path"],
        "expected_root": Annotated[str, "Root to check against"],
    },
)
async def _verify(args: dict) -> dict:
    path = json.loads(args["path_json"])
    ok = verify_proof(args["leaf"], path, args["expected_root"])
    return {"content": [{"type": "text", "text": "VALID" if ok else "INVALID"}], "is_error": not ok}


ZK_SERVER = create_sdk_mcp_server(
    name="zk_proofs",
    version="1.0.0",
    tools=[_append, _commit, _proof, _verify],
)
