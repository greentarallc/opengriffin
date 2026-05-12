"""Agentic Wallet — x402 client + per-skill spending caps + Telegram approval.

x402 (Coinbase, May 2025) extends HTTP 402 Payment Required for agentic
checkouts. When a service responds with 402 + payment instructions, the
agent prepares a signed payment, pings the user via Telegram for approval
(unless under the trust cap), and retries.

This MVP implements the client side. Real wallet signing is delegated to
an external signer (env: WALLET_SIGNER_URL) so we never hold private keys.
Per-skill and per-day spending caps are enforced.

Env:
  WALLET_SIGNER_URL          — your signer service URL (returns signed payment header)
  WALLET_DAILY_USD_CAP       — global cap (default $10)
  WALLET_AUTO_APPROVE_USD    — auto-approve below this amount (default $1)
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Annotated

import requests
from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.wallet")

WALLET_FILE = Path.home() / ".opengriffin" / "wallet.json"
WALLET_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    if not WALLET_FILE.is_file():
        return {"caps": {}, "spend": {}}
    try:
        return json.loads(WALLET_FILE.read_text())
    except Exception:
        return {"caps": {}, "spend": {}}


def _save(data: dict) -> None:
    WALLET_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _today() -> str:
    return dt.date.today().isoformat()


def daily_spent_usd() -> float:
    data = _load()
    return float(data.get("spend", {}).get(_today(), 0))


def can_spend(amount_usd: float, *, skill: str | None = None) -> tuple[bool, str]:
    daily_cap = float(os.environ.get("WALLET_DAILY_USD_CAP", "10"))
    if daily_spent_usd() + amount_usd > daily_cap:
        return False, f"would exceed daily cap (${daily_cap:.2f})"
    if skill:
        per_skill_cap = _load().get("caps", {}).get(skill)
        if per_skill_cap and daily_spent_usd() + amount_usd > per_skill_cap:
            return False, f"would exceed cap for skill {skill}"
    return True, "ok"


async def approve_via_telegram(amount_usd: float, vendor: str, item: str) -> bool:
    """Ask the user via Telegram inline buttons to approve a payment."""
    # Reuse the approvals.py infra
    from botctx import CTX

    from . import approvals

    if CTX.bot is None or not CTX.home_chat_id:
        return False
    auto = float(os.environ.get("WALLET_AUTO_APPROVE_USD", "1"))
    if amount_usd <= auto:
        return True
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    import uuid as _uuid

    req_id = _uuid.uuid4().hex[:8]
    approvals.STATE.pending[req_id] = fut
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"💳 Pay ${amount_usd:.2f}", callback_data=f"appr:once:{req_id}"
                ),
                InlineKeyboardButton("❌ Deny", callback_data=f"appr:deny:{req_id}"),
            ]
        ]
    )
    await CTX.bot.send_message(
        chat_id=CTX.home_chat_id,
        text=f"💳 *Wallet payment*\nVendor: {vendor}\nItem: {item}\nAmount: *${amount_usd:.2f}*\n\n_Auto-deny in 60s._",
        reply_markup=kb,
        parse_mode="Markdown",
    )
    try:
        decision = await asyncio.wait_for(fut, timeout=60)
    except TimeoutError:
        return False
    finally:
        approvals.STATE.pending.pop(req_id, None)
    return decision == "allow"


def record_spend(amount_usd: float, vendor: str, item: str) -> None:
    data = _load()
    today = _today()
    data["spend"][today] = float(data.get("spend", {}).get(today, 0)) + amount_usd
    data.setdefault("history", []).append(
        {
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "amount_usd": amount_usd,
            "vendor": vendor,
            "item": item,
        }
    )
    _save(data)


# ----------------------------- x402 client -----------------------------


async def fetch_with_x402(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    skill: str | None = None,
    max_amount_usd: float = 5,
) -> dict:
    """GET/POST a URL. If it returns 402, prepare payment, ask the user, retry.

    Returns: {ok, status, body, payment: {amount_usd, vendor, paid: bool}}
    """
    r = requests.request(method, url, json=body, timeout=30)
    if r.status_code != 402:
        return {"ok": True, "status": r.status_code, "body": r.text[:5000], "payment": None}

    # Parse x402 challenge (spec evolving; expect payment-required headers / JSON body)
    try:
        challenge = r.json()
    except Exception:
        return {"ok": False, "status": 402, "body": r.text[:2000], "payment": None}

    amount = float(challenge.get("amount_usd") or challenge.get("price") or 0)
    vendor = challenge.get("vendor") or url.split("/")[2]
    item = challenge.get("item") or url

    if amount > max_amount_usd:
        return {
            "ok": False,
            "status": 402,
            "body": "exceeds max_amount_usd",
            "payment": {"amount_usd": amount, "paid": False},
        }
    cs_ok, cs_msg = can_spend(amount, skill=skill)
    if not cs_ok:
        return {
            "ok": False,
            "status": 402,
            "body": cs_msg,
            "payment": {"amount_usd": amount, "paid": False},
        }

    if not await approve_via_telegram(amount, vendor, item):
        return {
            "ok": False,
            "status": 402,
            "body": "user denied",
            "payment": {"amount_usd": amount, "paid": False},
        }

    # Sign payment via external signer
    signer = os.environ.get("WALLET_SIGNER_URL")
    if not signer:
        return {
            "ok": False,
            "status": 402,
            "body": "WALLET_SIGNER_URL not set; cannot sign",
            "payment": {"amount_usd": amount, "paid": False},
        }
    sign_resp = requests.post(signer, json={"challenge": challenge}, timeout=20)
    sign_resp.raise_for_status()
    payment_header = sign_resp.json().get("payment_header")
    if not payment_header:
        return {
            "ok": False,
            "status": 402,
            "body": "signer returned no header",
            "payment": {"amount_usd": amount, "paid": False},
        }

    # Retry with payment header
    r2 = requests.request(method, url, json=body, headers={"X-Payment": payment_header}, timeout=30)
    if 200 <= r2.status_code < 300:
        record_spend(amount, vendor, item)
        return {
            "ok": True,
            "status": r2.status_code,
            "body": r2.text[:5000],
            "payment": {"amount_usd": amount, "paid": True, "vendor": vendor},
        }
    return {
        "ok": False,
        "status": r2.status_code,
        "body": r2.text[:2000],
        "payment": {"amount_usd": amount, "paid": False},
    }


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "wallet_pay_url",
    "Fetch a URL that may require x402 payment. Asks the user via Telegram for approval if the amount is over WALLET_AUTO_APPROVE_USD ($1 default). Enforces daily and per-skill caps.",
    {
        "url": Annotated[str, "URL to fetch"],
        "max_amount_usd": Annotated[float | None, "Cap for THIS call"],
        "skill": Annotated[str | None, "Skill name for per-skill spend tracking"],
    },
)
async def _pay(args: dict) -> dict:
    result = await fetch_with_x402(
        args["url"],
        max_amount_usd=float(args.get("max_amount_usd") or 5),
        skill=args.get("skill"),
    )
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)[:3000]}]}


@tool(
    "wallet_status",
    "Show today's spending and configured caps.",
    {},
)
async def _status(args: dict) -> dict:
    data = _load()
    cap = float(os.environ.get("WALLET_DAILY_USD_CAP", "10"))
    spent = daily_spent_usd()
    text = f"Today: ${spent:.2f} / ${cap:.2f}\nPer-skill caps: {data.get('caps') or 'none'}"
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "wallet_set_skill_cap",
    "Set a per-skill daily spending cap (USD).",
    {
        "skill": Annotated[str, "Skill name"],
        "cap_usd": Annotated[float, "Cap amount"],
    },
)
async def _setcap(args: dict) -> dict:
    data = _load()
    data.setdefault("caps", {})[args["skill"]] = float(args["cap_usd"])
    _save(data)
    return {
        "content": [
            {"type": "text", "text": f"cap set: {args['skill']} = ${args['cap_usd']:.2f}/day"}
        ]
    }


WALLET_SERVER = create_sdk_mcp_server(
    name="wallet",
    version="1.0.0",
    tools=[_pay, _status, _setcap],
)
