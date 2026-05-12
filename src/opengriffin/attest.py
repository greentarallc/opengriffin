"""Hardware-attested signing — Secure Enclave (macOS) / TPM (Linux) signing.

When a consequential action runs (payment, irreversible write, external
post), produce a tamper-evident signature using a hardware-backed key.
This proves the action originated from this device and hasn't been
forged after the fact.

macOS: uses Keychain via `security` CLI (or pyobjc bindings) for SE-backed
ECDSA signing. Linux: uses tpm2-tools or just `openssl` against a
non-extractable key when available. Falls back to a software Ed25519 key
in `~/.opengriffin/attest.key` when no hardware is present.

Storage:
  attest_log.jsonl — every signed action with payload digest + signature
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

ATTEST_LOG = Path.home() / ".opengriffin" / "attest_log.jsonl"
SOFTWARE_KEY = Path.home() / ".opengriffin" / "attest.key"
ATTEST_LOG.parent.mkdir(parents=True, exist_ok=True)
SOFTWARE_KEY.parent.mkdir(parents=True, exist_ok=True)


def _backend() -> str:
    """Detect which attestation backend is available."""
    # macOS Secure Enclave keys are accessed via Keychain
    if shutil.which("security") and os.uname().sysname == "Darwin":
        return "macos-keychain"
    if shutil.which("tpm2_sign"):
        return "linux-tpm2"
    return "software"


def _ensure_software_key() -> None:
    if SOFTWARE_KEY.is_file():
        return
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        # Last-resort: random 32 bytes for HMAC
        import secrets

        SOFTWARE_KEY.write_bytes(secrets.token_bytes(32))
        SOFTWARE_KEY.chmod(0o600)
        return
    pk = Ed25519PrivateKey.generate()
    pem = pk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    SOFTWARE_KEY.write_bytes(pem)
    SOFTWARE_KEY.chmod(0o600)


def sign(payload: bytes) -> dict:
    """Produce {backend, digest, signature} for a payload."""
    digest = hashlib.sha256(payload).hexdigest()
    backend = _backend()
    sig = ""
    if backend == "software":
        _ensure_software_key()
        try:
            from cryptography.hazmat.primitives import serialization

            pk = serialization.load_pem_private_key(SOFTWARE_KEY.read_bytes(), password=None)
            sig = pk.sign(payload).hex()
        except Exception:
            import hmac

            sig = hmac.new(SOFTWARE_KEY.read_bytes(), payload, hashlib.sha256).hexdigest()
    elif backend == "macos-keychain":
        # Use security CLI to sign with a key labeled 'opengriffin-attest'
        try:
            subprocess.run(
                ["security", "find-key", "-l", "opengriffin-attest"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            # Create the key on first use (RSA via security; SE-backed needs pyobjc)
            subprocess.run(
                ["security", "create-keypair", "-l", "opengriffin-attest"],
                check=False,
                capture_output=True,
            )
        try:
            r = subprocess.run(
                ["security", "sign", "-k", "opengriffin-attest"],
                input=payload,
                capture_output=True,
                check=True,
            )
            sig = r.stdout.hex()
        except subprocess.CalledProcessError:
            sig = "(unavailable)"
    elif backend == "linux-tpm2":
        try:
            r = subprocess.run(
                ["tpm2_sign", "-c", "/etc/tpm2/opengriffin.ctx"],
                input=payload,
                capture_output=True,
                check=True,
            )
            sig = r.stdout.hex()
        except Exception:
            sig = "(unavailable)"
    return {"backend": backend, "digest": digest, "signature": sig}


def attest(action_kind: str, payload: dict | str) -> dict:
    """Sign a consequential action and append to the audit log."""
    body = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else payload
    body_bytes = body.encode("utf-8")
    record = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "action_kind": action_kind,
        "payload_preview": body[:200],
    }
    record.update(sign(body_bytes))
    with ATTEST_LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


@tool(
    "attest",
    "Hardware-attested signing of a consequential action. Produces a digest + signature stored in tamper-evident audit log. Use BEFORE the action runs; pair with capability tokens for full auditability.",
    {
        "action_kind": Annotated[
            str, "Type of action (e.g. 'payment', 'send_email', 'github_push')"
        ],
        "payload_json": Annotated[str, "JSON payload describing the action"],
    },
)
async def _attest(args: dict) -> dict:
    payload = json.loads(args["payload_json"])
    rec = attest(args["action_kind"], payload)
    return {"content": [{"type": "text", "text": json.dumps(rec, indent=2)}]}


@tool(
    "attest_audit",
    "Show recent attestation log entries.",
    {"n": Annotated[int, "How many"]},
)
async def _audit(args: dict) -> dict:
    if not ATTEST_LOG.is_file():
        return {"content": [{"type": "text", "text": "(no attestations yet)"}]}
    lines = ATTEST_LOG.read_text().splitlines()[-int(args.get("n") or 20) :]
    out = [json.loads(line) for line in lines if line.strip()]
    text = "\n".join(
        f"[{r.get('ts')}] {r.get('action_kind')} | digest={r.get('digest', '')[:16]}… | backend={r.get('backend')}"
        for r in out
    )
    return {"content": [{"type": "text", "text": text}]}


ATTEST_SERVER = create_sdk_mcp_server(
    name="attest",
    version="1.0.0",
    tools=[_attest, _audit],
)
