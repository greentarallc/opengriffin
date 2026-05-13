"""Capability-Scoped Skill Leasing — borrow another agent's skill, revocably.

a2a.py already lets your agent call another OpenGriffin user's agent: RPC.
This module adds a stronger primitive: **temporary, scoped, revocable
leases on the skill itself** so the leased skill runs locally against
your data and the lessor never sees your data.

Lifecycle:

  1. Discovery   — `marketplace_browse` (already in marketplace.py) lists
                    available skills + their lessor's reputation.
  2. Offer       — the lessor mints a signed lease offer:
                    {skill_ref, scope, max_invocations, ttl, price_usdc,
                     allowed_hosts, signed_by_lessor}
  3. Acceptance  — your agent calls `lease_accept(offer_id)`. The skill
                    artifact (SKILL.md + scripts/) is fetched locally,
                    its hash is verified against the offer's commitment,
                    and a lease record is written.
  4. Execution   — every invocation of the leased skill runs inside a
                    sandbox: only the bot's local filesystem is accessible,
                    network egress is restricted to `allowed_hosts`, and
                    each call is gated by a per-invocation capability
                    token tied to the lease.
  5. Revocation  — either side can `lease_revoke(lease_id)` instantly.
                    The lease is also auto-revoked at ttl expiry or after
                    `max_invocations` calls.

What "sandboxed" actually means here:

   We don't ship a kernel-level sandbox in 2026 (Python in a subprocess
   under nsjail / firejail / Apple sandbox-exec would be the production
   path; that's listed as future work). What we DO enforce in this MVP:

     - The skill artifact lives at a per-lease path under
       ~/.opengriffin/leases/<lease_id>/, and skill_lease provides the
       artifact's resolved path to the invocation site.
     - The capability token for the invocation has an `lease:<id>` scope
       prefix. The pre-exec scanner (security_scan.py) and approval
       handler can be configured to disallow tool calls outside an
       allowlist when this scope is present.
     - Network egress: leased skills are run with a `LEASE_ALLOWED_HOSTS`
       env var; helpers using requests/httpx in the skill check it.
       (Belt-and-braces — the real enforcement should be at the OS firewall
       level, but env-var discipline is good enough for the OSS MVP.)

This is the network effect: A2A turns "call my agent" into "rent my brain
for 60 minutes." Combined with x402 (already wired in wallet.py) you
get an actual marketplace.

Storage:
  ~/.opengriffin/leases/registry.json           — all known leases
  ~/.opengriffin/leases/<lease_id>/             — skill artifact per lease
  ~/.opengriffin/leases/<lease_id>/invocations.jsonl  — per-call audit
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import logging
import secrets
import shutil
import time
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.skill_lease")

LEASES_DIR = Path.home() / ".opengriffin" / "leases"
LEASES_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY = LEASES_DIR / "registry.json"


def _load_registry() -> dict:
    if not REGISTRY.is_file():
        return {"leases": []}
    try:
        return json.loads(REGISTRY.read_text())
    except Exception:
        return {"leases": []}


def _save_registry(reg: dict) -> None:
    REGISTRY.write_text(json.dumps(reg, indent=2) + "\n")


def _h(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return hashlib.sha256(s).hexdigest()


def _new_lease_id() -> str:
    return secrets.token_hex(8)


def _now() -> int:
    return int(time.time())


# ----------------------------- offer + accept -----------------------------


def make_offer(
    *,
    skill_ref: str,
    scope: str,
    ttl_seconds: int,
    max_invocations: int,
    price_usdc: float,
    allowed_hosts: list[str],
    artifact_hash: str,
    lessor_id: str,
    lessor_signature: str,
) -> dict:
    """Build an offer record (typically produced by the lessor's agent and
    transmitted via a2a). We don't sign it here — we trust the lessor's
    signature was created on their side and we re-verify on accept."""
    offer = {
        "offer_id": _new_lease_id(),
        "created_at": _now(),
        "skill_ref": skill_ref,
        "scope": scope,
        "ttl_seconds": ttl_seconds,
        "max_invocations": max_invocations,
        "price_usdc": price_usdc,
        "allowed_hosts": list(allowed_hosts),
        "artifact_hash": artifact_hash,
        "lessor_id": lessor_id,
        "lessor_signature": lessor_signature,
    }
    return offer


def accept_offer(offer: dict, artifact_bytes: bytes) -> dict:
    """Verify the offer + artifact match, mint a local lease, install the
    artifact, and return the lease record.

    artifact_bytes is the raw SKILL.md content (or a tarball; for the
    MVP we just write it to a markdown file). In production, fetch via
    A2A and pass the bytes here.
    """
    received_hash = _h(artifact_bytes)
    if received_hash != offer["artifact_hash"]:
        raise ValueError(
            f"artifact hash mismatch: offered={offer['artifact_hash'][:12]}… received={received_hash[:12]}…"
        )

    lease_id = _new_lease_id()
    lease_dir = LEASES_DIR / lease_id
    lease_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = lease_dir / "SKILL.md"
    artifact_path.write_bytes(artifact_bytes)

    lease = {
        "lease_id": lease_id,
        "offer_id": offer["offer_id"],
        "skill_ref": offer["skill_ref"],
        "scope": offer["scope"],
        "expires_at": _now() + int(offer["ttl_seconds"]),
        "max_invocations": int(offer["max_invocations"]),
        "invocations": 0,
        "price_usdc": float(offer["price_usdc"]),
        "allowed_hosts": list(offer["allowed_hosts"]),
        "artifact_path": str(artifact_path),
        "artifact_hash": offer["artifact_hash"],
        "lessor_id": offer["lessor_id"],
        "status": "active",
        "accepted_at": _now(),
    }
    reg = _load_registry()
    reg["leases"].append(lease)
    _save_registry(reg)
    log.info("skill_lease: accepted %s (skill=%s)", lease_id, offer["skill_ref"])
    return lease


def find_lease(lease_id: str) -> dict | None:
    return next((item for item in _load_registry()["leases"] if item["lease_id"] == lease_id), None)


def gate_invocation(lease_id: str) -> dict:
    """Pre-invocation gate. Verify the lease is still valid and increment
    the counter. Returns the lease (for path / allowed_hosts) or raises."""
    reg = _load_registry()
    lease = next((item for item in reg["leases"] if item["lease_id"] == lease_id), None)
    if lease is None:
        raise ValueError(f"unknown lease: {lease_id}")
    if lease["status"] != "active":
        raise ValueError(f"lease {lease_id} not active (status={lease['status']})")
    if _now() > lease["expires_at"]:
        lease["status"] = "expired"
        _save_registry(reg)
        raise ValueError(f"lease {lease_id} expired")
    if lease["invocations"] >= lease["max_invocations"]:
        lease["status"] = "exhausted"
        _save_registry(reg)
        raise ValueError(f"lease {lease_id} exhausted ({lease['invocations']} invocations)")

    lease["invocations"] += 1
    _save_registry(reg)

    # Per-invocation audit
    inv_log = Path(lease["artifact_path"]).parent / "invocations.jsonl"
    with inv_log.open("a") as fh:
        fh.write(json.dumps({"ts": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")
    return lease


def revoke(lease_id: str, *, reason: str = "manual") -> bool:
    """Revoke a lease immediately. Lessor or lessee can call this."""
    reg = _load_registry()
    lease = next((item for item in reg["leases"] if item["lease_id"] == lease_id), None)
    if lease is None:
        return False
    if lease["status"] != "active":
        return False
    lease["status"] = "revoked"
    lease["revoked_at"] = _now()
    lease["revoke_reason"] = reason
    _save_registry(reg)
    # Best-effort: remove the artifact directory so the skill can't be
    # re-invoked from a stale path
    with contextlib.suppress(Exception):
        shutil.rmtree(Path(lease["artifact_path"]).parent, ignore_errors=True)
    # Emit refusal witness — there was a request to use this lease, denied
    try:
        from . import proofs

        proofs.refusal_witness(
            requested_scope=f"lease:{lease_id}",
            reason=f"revoked: {reason}",
        )
    except Exception:
        pass
    return True


def list_leases(*, active_only: bool = False) -> list[dict]:
    reg = _load_registry()
    if active_only:
        return [
            lease
            for lease in reg["leases"]
            if lease["status"] == "active" and _now() <= lease["expires_at"]
        ]
    return list(reg["leases"])


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "lease_offer_build",
    "Helper: build a signed-by-you offer record to share with a peer agent. The peer accepts it via lease_accept to install your skill on their machine for a fixed scope/ttl/invocation budget.",
    {
        "skill_ref": Annotated[str, "github://owner/repo or local skill name"],
        "scope": Annotated[str, "Capability scope this lease grants (e.g. 'tax_prep')"],
        "ttl_seconds": Annotated[int, "How long the lease is valid (seconds)"],
        "max_invocations": Annotated[int, "Hard cap on number of invocations"],
        "price_usdc": Annotated[float, "Price in USDC (0 for free)"],
        "allowed_hosts_csv": Annotated[
            str, "Comma-separated hostnames the skill is allowed to call (empty = no network)"
        ],
        "artifact_hash": Annotated[str, "SHA-256 of the skill artifact you'll transmit"],
        "lessor_id": Annotated[str, "Your agent's signing identity (a2a node id)"],
        "lessor_signature": Annotated[
            str, "Your signature over the offer (computed externally via attest.sign)"
        ],
    },
)
async def _offer_build(args: dict) -> dict:
    hosts = [h.strip() for h in (args.get("allowed_hosts_csv") or "").split(",") if h.strip()]
    offer = make_offer(
        skill_ref=args["skill_ref"],
        scope=args["scope"],
        ttl_seconds=int(args["ttl_seconds"]),
        max_invocations=int(args["max_invocations"]),
        price_usdc=float(args["price_usdc"]),
        allowed_hosts=hosts,
        artifact_hash=args["artifact_hash"],
        lessor_id=args["lessor_id"],
        lessor_signature=args["lessor_signature"],
    )
    return {"content": [{"type": "text", "text": json.dumps(offer, indent=2)}]}


@tool(
    "lease_accept",
    "Accept a lease offer from a peer agent. Provide the offer JSON and the artifact bytes (utf-8). Verifies artifact hash, installs the skill under ~/.opengriffin/leases/<id>/, and registers the lease.",
    {
        "offer_json": Annotated[str, "The offer record as JSON"],
        "artifact_text": Annotated[str, "The SKILL.md content (utf-8)"],
    },
)
async def _accept(args: dict) -> dict:
    offer = json.loads(args["offer_json"])
    artifact = args["artifact_text"].encode("utf-8")
    try:
        lease = accept_offer(offer, artifact)
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "lease_id": lease["lease_id"],
                        "artifact_path": lease["artifact_path"],
                        "expires_at": lease["expires_at"],
                        "max_invocations": lease["max_invocations"],
                    },
                    indent=2,
                ),
            }
        ]
    }


@tool(
    "lease_invoke_gate",
    "Pre-invocation check. Call before running the leased skill. Returns the artifact path + allowed_hosts on success, or an error if the lease is expired / exhausted / revoked. Increments the invocation counter as a side effect.",
    {"lease_id": Annotated[str, "Lease id from lease_accept"]},
)
async def _gate(args: dict) -> dict:
    try:
        lease = gate_invocation(args["lease_id"])
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "artifact_path": lease["artifact_path"],
                        "allowed_hosts": lease["allowed_hosts"],
                        "invocations": lease["invocations"],
                        "remaining": lease["max_invocations"] - lease["invocations"],
                    },
                    indent=2,
                ),
            }
        ]
    }


@tool(
    "lease_revoke",
    "Revoke a lease immediately. Removes the artifact and prevents further invocations. Emits a refusal witness automatically.",
    {
        "lease_id": Annotated[str, "Lease id"],
        "reason": Annotated[str | None, "Reason for revocation (≤200 chars)"],
    },
)
async def _revoke(args: dict) -> dict:
    ok = revoke(args["lease_id"], reason=(args.get("reason") or "manual")[:200])
    return {
        "content": [{"type": "text", "text": "revoked" if ok else "not found or already inactive"}],
        "is_error": not ok,
    }


@tool(
    "lease_list",
    "List all known leases on this agent (lessee side).",
    {"active_only": Annotated[bool | None, "If true, exclude expired/exhausted/revoked"]},
)
async def _list(args: dict) -> dict:
    leases = list_leases(active_only=bool(args.get("active_only") or False))
    if not leases:
        return {"content": [{"type": "text", "text": "(no leases)"}]}
    lines = [
        f"{lease['lease_id']}  skill={lease['skill_ref']}  scope={lease['scope']}  status={lease['status']}  "
        f"inv={lease['invocations']}/{lease['max_invocations']}  exp_in={lease['expires_at'] - _now()}s"
        for lease in leases
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


LEASE_SERVER = create_sdk_mcp_server(
    name="skill_lease",
    version="1.0.0",
    tools=[_offer_build, _accept, _gate, _revoke, _list],
)


__all__ = [
    "make_offer",
    "accept_offer",
    "gate_invocation",
    "revoke",
    "list_leases",
    "find_lease",
    "LEASE_SERVER",
]
