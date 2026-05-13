"""Verifiable Refusal Proofs + Provable Forgetting — the inverse-safety frontier.

zk_proofs.py already gives us a Merkle-rooted, hash-chained log: prove that
a specific *positive* action existed. The forward-safety primitive.

This module adds the *inverse*: prove that a specific *negative* event
happened — a refusal occurred, a memory was erased, a fact never entered a
prompt context. The shape that regulated industries actually need.

Three primitive proof kinds, each emitting a signed witness that is also
appended to the audit log so the existence of the witness is itself
verifiable:

1. REFUSAL WITNESS
   - emitted whenever a tool call or capability check returns deny
   - records: requested_scope, denied_at, deny_reason, requester_session
   - signed by the bot's hardware-attested identity (attest.py) when
     available, else by the HMAC capability-secret as fallback
   - lets the user — or an external auditor — later prove "the agent did
     not perform action X at time T" without revealing what else happened

2. ERASURE RECEIPT
   - emitted by memory_remove() when a user invokes forget-X
   - records: removed_fact_hash (NOT the fact itself, to preserve privacy
     of WHAT was forgotten), index_invalidated_at, predecessor_root,
     successor_root
   - cryptographically commits that the Merkle leaf for the fact's
     storage was invalidated; the user retains the privilege to reveal
     the original fact later if they want to prove what was erased

3. NON-DISCLOSURE PROOF
   - emitted at end-of-session for any session that explicitly opted into
     redaction
   - records: session_id, redacted_fact_hashes[], context_prefix_hash
   - commits that none of the listed fact-hashes appeared in any prompt
     context for the session — verifiable by replaying the prompt-build
     pipeline against the same memory snapshot and confirming the
     fact-hashes are absent from the recomputed context-prefix-hash

Honest scope of this module:
  - Witnesses are signed, append-only, and Merkle-anchored. That's enough
    for tamper evidence + selective disclosure.
  - The non-disclosure proof is *commit-and-reveal* style: we commit to a
    hash now; verification means later rebuilding the prompt and checking
    the commitment holds. It's not a zk-SNARK and doesn't try to be.
  - Hardware attestation is best-effort. If attest.py can sign, we use it;
    otherwise we fall back to HMAC. Both produce valid (per-installation)
    witnesses; only the hardware-signed ones cross-verify against a
    public attestation root.

Storage:
  ~/.opengriffin/proofs/witnesses.jsonl   — append-only signed witness log
  ~/.opengriffin/proofs/witness_secret    — HMAC fallback key
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import secrets
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.proofs")

PROOFS_DIR = Path.home() / ".opengriffin" / "proofs"
PROOFS_DIR.mkdir(parents=True, exist_ok=True)
WITNESSES = PROOFS_DIR / "witnesses.jsonl"
HMAC_SECRET = PROOFS_DIR / "witness_secret"


REFUSAL = "refusal"
ERASURE = "erasure"
NON_DISCLOSURE = "non_disclosure"


def _hmac_key() -> bytes:
    if not HMAC_SECRET.is_file():
        HMAC_SECRET.write_bytes(secrets.token_bytes(32))
        HMAC_SECRET.chmod(0o600)
    return HMAC_SECRET.read_bytes()


def _h(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return hashlib.sha256(s).hexdigest()


def _canonical(rec: dict) -> str:
    """Canonical bytes for signing/verification. Strip everything added
    AFTER the signature is computed (algorithm tag + zk anchor) so signing
    and verification produce the same input."""
    skip = {"signature", "signature_algorithm", "zk_leaf", "zk_index"}
    body = {k: v for k, v in rec.items() if k not in skip}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _sign(rec: dict) -> tuple[str, str]:
    """Sign the canonical form with HMAC over a local secret.

    Design note: a previous version tried attest.sign() for hardware-rooted
    Ed25519 signatures, but Ed25519 is randomized (signatures contain a
    fresh nonce) and attest.py doesn't yet expose a verify() that takes a
    public key, so "re-sign and compare" is not a valid verification path.
    Until attest.py grows a real verify(), we stick with HMAC — which is
    the right primitive for the use case anyway: a witness emitted by
    *this* agent installation, verifiable by *this* installation. The
    hardware-rooted path is listed as future work; when it lands, this
    function gets a new branch and signature_algorithm becomes "hardware".
    """
    canon = _canonical(rec)
    return ("hmac", hmac.new(_hmac_key(), canon.encode(), hashlib.sha256).hexdigest())


def _verify_signature(rec: dict) -> bool:
    alg = rec.get("signature_algorithm")
    sig = rec.get("signature")
    if not sig or alg != "hmac":
        return False
    canon = _canonical(rec)
    expected = hmac.new(_hmac_key(), canon.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _zk_anchor(rec: dict) -> dict | None:
    """Anchor the witness in the Merkle audit log. The audit log already
    chains hashes — by appending the witness there, we get tamper evidence
    for the witness itself for free.

    Returns the audit entry, or None if zk_proofs is unavailable.
    """
    try:
        from . import zk_proofs

        entry = zk_proofs.append(f"proof:{rec['kind']}", rec)
        return entry
    except Exception as e:
        log.warning("proofs: failed to anchor in zk audit log: %s", e)
        return None


def _emit(kind: str, body: dict) -> dict:
    """Build a witness record, sign it, anchor it, append it."""
    rec = {
        "kind": kind,
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "body": body,
    }
    alg, sig = _sign(rec)
    rec["signature_algorithm"] = alg
    rec["signature"] = sig
    anchor = _zk_anchor(rec)
    if anchor is not None:
        rec["zk_leaf"] = anchor.get("leaf")
        rec["zk_index"] = anchor.get("index")
    with WITNESSES.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


# ----------------------------- public API -----------------------------


def refusal_witness(
    *,
    requested_scope: str,
    reason: str,
    requester_session: str | None = None,
    requester_tool: str | None = None,
) -> dict:
    """Emit a signed witness that the agent denied a specific request."""
    body = {
        "requested_scope": requested_scope,
        "reason": reason,
        "requester_session": requester_session,
        "requester_tool": requester_tool,
    }
    return _emit(REFUSAL, body)


def erasure_receipt(
    *,
    fact_hash: str,
    predecessor_root: str | None = None,
    successor_root: str | None = None,
    note: str = "",
) -> dict:
    """Emit a signed witness that a specific fact (by hash, not content)
    was removed from memory.

    Take the hash of the fact BEFORE removal — that gives the user the
    privilege to later reveal the original fact and prove that's what
    was removed. We do NOT store the plaintext.
    """
    body = {
        "fact_hash": fact_hash,
        "predecessor_root": predecessor_root,
        "successor_root": successor_root,
        "note": note,
    }
    return _emit(ERASURE, body)


def non_disclosure_proof(
    *,
    session_id: str,
    redacted_fact_hashes: list[str],
    context_prefix_hash: str,
) -> dict:
    """Commit that the listed fact hashes did not appear in the session's
    prompt context. Verifiable later by recomputing the prefix hash
    against the same memory snapshot."""
    body = {
        "session_id": session_id,
        "redacted_fact_hashes": redacted_fact_hashes,
        "context_prefix_hash": context_prefix_hash,
    }
    return _emit(NON_DISCLOSURE, body)


def fact_hash(plaintext: str) -> str:
    """Canonical hash function for facts. Use the same one on the verifier side."""
    return _h(plaintext.strip().lower())


def _all_witnesses(kind: str | None = None) -> list[dict]:
    if not WITNESSES.is_file():
        return []
    out: list[dict] = []
    for line in WITNESSES.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if kind is None or rec.get("kind") == kind:
                out.append(rec)
        except Exception:
            continue
    return out


def verify_witness(rec: dict) -> dict:
    """Verifier-side check. Returns a structured result."""
    sig_ok = _verify_signature(rec)
    anchor_ok = None
    if "zk_leaf" in rec and "zk_index" in rec:
        try:
            from . import zk_proofs

            proof = zk_proofs.inclusion_proof(int(rec["zk_index"]))
            anchor_ok = proof["leaf"] == rec["zk_leaf"] and zk_proofs.verify_proof(
                proof["leaf"], proof["path"], proof["root"]
            )
        except Exception as e:
            log.warning("verify_witness: anchor check failed: %s", e)
            anchor_ok = False
    return {
        "signature_valid": sig_ok,
        "merkle_anchor_valid": anchor_ok,
        "kind": rec.get("kind"),
        "ts": rec.get("ts"),
        "signature_algorithm": rec.get("signature_algorithm"),
    }


def verify_non_disclosure(
    rec: dict,
    *,
    rebuilt_context_prefix_hash: str,
) -> dict:
    """Caller rebuilds the prompt context for the session and supplies its
    hash. We confirm: (a) signature is valid, (b) the redacted fact hashes
    are absent from the rebuilt context (caller must check this against
    their own context, since we don't see plaintext), (c) the prefix hash
    matches what was committed."""
    base = verify_witness(rec)
    body = rec.get("body", {})
    base["context_prefix_hash_matches"] = (
        body.get("context_prefix_hash") == rebuilt_context_prefix_hash
    )
    return base


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "proof_refusal_emit",
    "Emit a signed witness that the agent refused a specific action. Called automatically by approvals.py + capabilities.py on every deny, but also exposed so external systems (e.g. a critic that vetoed something) can record refusals.",
    {
        "requested_scope": Annotated[str, "What was refused (tool / scope / capability)"],
        "reason": Annotated[str, "Why it was refused"],
        "requester_session": Annotated[str | None, "Session that requested the action"],
        "requester_tool": Annotated[str | None, "The tool name involved, if applicable"],
    },
)
async def _refusal_emit(args: dict) -> dict:
    rec = refusal_witness(
        requested_scope=args["requested_scope"],
        reason=args["reason"],
        requester_session=args.get("requester_session"),
        requester_tool=args.get("requester_tool"),
    )
    return {
        "content": [
            {
                "type": "text",
                "text": f"emitted refusal witness #{rec.get('zk_index')}  alg={rec['signature_algorithm']}\n"
                f"signature: {rec['signature'][:32]}…",
            }
        ]
    }


@tool(
    "proof_erasure_emit",
    "Emit a signed erasure receipt for a fact that was removed from memory. Pass the SHA-256 of the fact (use proof_fact_hash to compute), NEVER the plaintext.",
    {
        "fact_hash": Annotated[
            str, "SHA-256 hash of the erased fact. Use proof_fact_hash to compute from plaintext."
        ],
        "predecessor_root": Annotated[str | None, "Merkle root before erasure (zk_commit_root)"],
        "successor_root": Annotated[str | None, "Merkle root after erasure"],
        "note": Annotated[str | None, "Optional note (≤200 chars)"],
    },
)
async def _erasure_emit(args: dict) -> dict:
    rec = erasure_receipt(
        fact_hash=args["fact_hash"],
        predecessor_root=args.get("predecessor_root"),
        successor_root=args.get("successor_root"),
        note=(args.get("note") or "")[:200],
    )
    return {
        "content": [
            {
                "type": "text",
                "text": f"emitted erasure receipt #{rec.get('zk_index')}\nfact_hash: {rec['body']['fact_hash']}\nsig: {rec['signature'][:32]}…",
            }
        ]
    }


@tool(
    "proof_non_disclosure_emit",
    "Commit that a set of fact-hashes did not appear in a session's prompt context. Provide the session id, the fact-hashes redacted, and the SHA-256 of the actual prompt-context-prefix used.",
    {
        "session_id": Annotated[str, "Session identifier"],
        "redacted_fact_hashes_json": Annotated[
            str, "JSON array of SHA-256 hashes that were redacted"
        ],
        "context_prefix_hash": Annotated[
            str, "SHA-256 of the actual prompt-prefix used in the session"
        ],
    },
)
async def _nd_emit(args: dict) -> dict:
    hashes = json.loads(args["redacted_fact_hashes_json"])
    rec = non_disclosure_proof(
        session_id=args["session_id"],
        redacted_fact_hashes=list(hashes),
        context_prefix_hash=args["context_prefix_hash"],
    )
    return {
        "content": [
            {
                "type": "text",
                "text": f"emitted non-disclosure proof #{rec.get('zk_index')}\nsession: {args['session_id']}\nredacted: {len(hashes)} facts",
            }
        ]
    }


@tool(
    "proof_fact_hash",
    "Compute the canonical SHA-256 of a fact for use with erasure receipts / non-disclosure proofs. The hash is over the lowercased, stripped plaintext.",
    {"plaintext": Annotated[str, "The fact to hash"]},
)
async def _fact_hash(args: dict) -> dict:
    return {"content": [{"type": "text", "text": fact_hash(args["plaintext"])}]}


@tool(
    "proof_verify",
    "Verify a single witness record by JSON. Checks signature + Merkle anchor.",
    {"witness_json": Annotated[str, "The witness record as JSON"]},
)
async def _verify(args: dict) -> dict:
    rec = json.loads(args["witness_json"])
    result = verify_witness(rec)
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "proof_list",
    "List recent witnesses, optionally filtered by kind (refusal | erasure | non_disclosure).",
    {
        "kind": Annotated[str | None, "Filter by kind"],
        "limit": Annotated[int | None, "Max records (default 20)"],
    },
)
async def _list(args: dict) -> dict:
    recs = _all_witnesses(kind=args.get("kind"))[-int(args.get("limit") or 20) :]
    if not recs:
        return {"content": [{"type": "text", "text": "(no witnesses)"}]}
    lines = []
    for r in recs:
        lines.append(
            f"{r['ts']}  {r['kind']:<14}  #{r.get('zk_index', '?')}  alg={r['signature_algorithm']}"
        )
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


PROOFS_SERVER = create_sdk_mcp_server(
    name="proofs",
    version="1.0.0",
    tools=[_refusal_emit, _erasure_emit, _nd_emit, _fact_hash, _verify, _list],
)


__all__ = [
    "refusal_witness",
    "erasure_receipt",
    "non_disclosure_proof",
    "fact_hash",
    "verify_witness",
    "verify_non_disclosure",
    "PROOFS_SERVER",
    "REFUSAL",
    "ERASURE",
    "NON_DISCLOSURE",
]
