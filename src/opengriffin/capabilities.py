"""Capability tokens — signed, scoped, expiring permissions for tools.

Pattern: every consequential tool call requires a capability token. A token
declares:
  scope    — which tool(s) it grants ("Bash", "Bash:git*", "wallet:pay")
  cap_usd  — optional spend cap
  expires  — UNIX timestamp; tokens are short-lived
  signature — HMAC-SHA256 over canonical JSON, key = ~/.opengriffin/cap_secret

Tokens are minted by the user (via /capability_mint or the dashboard) and
embedded in agent state. The agent presents them when calling tools.

This is finer-grained than the existing approval flow: instead of one
session-wide grant, tokens can be issued per-task with hard caps.

Storage:
  ~/.opengriffin/capabilities.json  — issued tokens
  ~/.opengriffin/cap_secret       — HMAC secret (32 random bytes)
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

CAPS_FILE = Path.home() / ".opengriffin" / "capabilities.json"
SECRET_PATH = Path.home() / ".opengriffin" / "cap_secret"
SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)


def _secret() -> bytes:
    if not SECRET_PATH.is_file():
        SECRET_PATH.write_bytes(secrets.token_bytes(32))
        SECRET_PATH.chmod(0o600)
    return SECRET_PATH.read_bytes()


def _load() -> dict:
    if not CAPS_FILE.is_file():
        return {"tokens": []}
    try:
        return json.loads(CAPS_FILE.read_text())
    except Exception:
        return {"tokens": []}


def _save(data: dict) -> None:
    CAPS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _canonical(token: dict) -> str:
    """Canonical JSON for signing — sorted keys, no spaces, signature stripped."""
    body = {k: v for k, v in token.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _sign(token: dict) -> str:
    return hmac.new(_secret(), _canonical(token).encode(), hashlib.sha256).hexdigest()


def mint(
    scope: str, *, ttl_seconds: int = 3600, cap_usd: float | None = None, note: str = ""
) -> dict:
    """Issue a new capability token."""
    token = {
        "id": secrets.token_hex(8),
        "scope": scope,
        "cap_usd": cap_usd,
        "issued_at": int(time.time()),
        "expires_at": int(time.time()) + ttl_seconds,
        "note": note,
        "consumed_usd": 0.0,
        "uses": 0,
    }
    token["signature"] = _sign(token)
    data = _load()
    data["tokens"].append(token)
    _save(data)
    return token


def verify(token_id: str) -> dict | None:
    """Return the token if valid (signature OK + not expired), else None."""
    data = _load()
    tok = next((t for t in data["tokens"] if t.get("id") == token_id), None)
    if tok is None:
        return None
    expected_sig = _sign(tok)
    if not hmac.compare_digest(expected_sig, tok.get("signature", "")):
        return None
    if tok.get("expires_at", 0) < time.time():
        return None
    return tok


def covers(tok: dict, requested_scope: str) -> bool:
    """Token scope can be exact match or fnmatch pattern (e.g. 'Bash:git*')."""
    scope = tok.get("scope", "")
    return (
        scope == requested_scope
        or fnmatch.fnmatch(requested_scope, scope)
        or fnmatch.fnmatch(scope, requested_scope)
    )


def consume(token_id: str, *, amount_usd: float = 0.0) -> bool:
    """Record a use of the token. Returns False if cap is exceeded."""
    data = _load()
    tok = next((t for t in data["tokens"] if t.get("id") == token_id), None)
    if tok is None:
        return False
    tok["consumed_usd"] = float(tok.get("consumed_usd", 0)) + amount_usd
    tok["uses"] = tok.get("uses", 0) + 1
    if tok.get("cap_usd") is not None and tok["consumed_usd"] > tok["cap_usd"]:
        return False
    # Re-sign with updated counters? We don't (signature covers issued state only;
    # consumption is local-only telemetry).
    _save(data)
    return True


def revoke(token_id: str) -> bool:
    data = _load()
    before = len(data["tokens"])
    data["tokens"] = [t for t in data["tokens"] if t.get("id") != token_id]
    if len(data["tokens"]) == before:
        return False
    _save(data)
    return True


def list_active() -> list[dict]:
    now = time.time()
    return [t for t in _load()["tokens"] if t.get("expires_at", 0) >= now]


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "capability_mint",
    "Mint a new short-lived capability token granting a specific tool scope. Returns token id which the agent presents on subsequent gated tool calls.",
    {
        "scope": Annotated[
            str,
            "Tool scope: e.g. 'Bash', 'Bash:git*', 'wallet:pay', 'WebFetch:https://api.X.com/*'",
        ],
        "ttl_seconds": Annotated[int | None, "TTL in seconds (default 3600 = 1h)"],
        "cap_usd": Annotated[float | None, "Optional dollar cap (e.g. for wallet scopes)"],
        "note": Annotated[str | None, "Why this token was minted"],
    },
)
async def _mint(args: dict) -> dict:
    tok = mint(
        scope=args["scope"],
        ttl_seconds=int(args.get("ttl_seconds") or 3600),
        cap_usd=float(args["cap_usd"]) if args.get("cap_usd") is not None else None,
        note=args.get("note") or "",
    )
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"id": tok["id"], "scope": tok["scope"], "expires_at": tok["expires_at"]},
                    indent=2,
                ),
            }
        ]
    }


@tool(
    "capability_verify",
    "Check whether a capability token is valid for a requested scope. Returns the token details or null.",
    {
        "token_id": Annotated[str, "Token id"],
        "requested_scope": Annotated[str, "Scope being requested"],
    },
)
async def _verify(args: dict) -> dict:
    tok = verify(args["token_id"])
    if tok is None:
        return {
            "content": [{"type": "text", "text": "INVALID: token missing/expired/bad signature"}],
            "is_error": True,
        }
    if not covers(tok, args["requested_scope"]):
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"INVALID: token scope '{tok['scope']}' doesn't cover '{args['requested_scope']}'",
                }
            ],
            "is_error": True,
        }
    return {
        "content": [
            {
                "type": "text",
                "text": "VALID: "
                + json.dumps({k: v for k, v in tok.items() if k != "signature"}, indent=2),
            }
        ]
    }


@tool(
    "capability_list",
    "List all currently-active (unexpired) capability tokens.",
    {},
)
async def _list(args: dict) -> dict:
    items = list_active()
    if not items:
        return {"content": [{"type": "text", "text": "(no active tokens)"}]}
    lines = [
        f"{t['id']} scope={t['scope']} ttl={int(t['expires_at'] - time.time())}s uses={t.get('uses', 0)} cap={t.get('cap_usd')}"
        for t in items
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "capability_revoke",
    "Revoke a capability token immediately.",
    {"token_id": Annotated[str, "Token id"]},
)
async def _revoke(args: dict) -> dict:
    ok = revoke(args["token_id"])
    return {
        "content": [{"type": "text", "text": "revoked" if ok else "not found"}],
        "is_error": not ok,
    }


CAPABILITIES_SERVER = create_sdk_mcp_server(
    name="capabilities",
    version="1.0.0",
    tools=[_mint, _verify, _list, _revoke],
)
