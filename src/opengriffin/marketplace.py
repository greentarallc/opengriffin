"""Marketplace — discover and rent specialist OpenGriffin agents.

NO backend dependency: listings live in a LOCAL file. Users curate their
own directory of specialists they trust (or peers they've discovered via
A2A handshake). For v1 launch, marketplace is just a saved-favorites list
with composable hire / ask / release semantics over A2A + wallet.

Storage:
  ~/.opengriffin/marketplace_listings.json — local listings (curated by you)
  ~/.opengriffin/marketplace_rentals.json  — open rentals

Composes:
  a2a (transport) + wallet (payment) + reputation (trust display).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

log = logging.getLogger("opengriffin.marketplace")

LISTINGS_FILE = Path.home() / ".opengriffin" / "marketplace_listings.json"
RENTALS_FILE = Path.home() / ".opengriffin" / "marketplace_rentals.json"
LISTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_listings() -> list[dict]:
    if not LISTINGS_FILE.is_file():
        return []
    try:
        return json.loads(LISTINGS_FILE.read_text()).get("listings", [])
    except Exception:
        return []


def _save_listings(items: list[dict]) -> None:
    LISTINGS_FILE.write_text(json.dumps({"listings": items}, indent=2) + "\n")


def add_listing(
    handle: str,
    role: str,
    base_url: str,
    *,
    hourly_usd: float = 0.0,
    unit_usd: float = 0.10,
    reputation_score: int = 0,
    description: str = "",
) -> dict:
    items = _load_listings()
    items = [x for x in items if x.get("handle") != handle]
    entry = {
        "handle": handle,
        "role": role,
        "base_url": base_url,
        "hourly_usd": hourly_usd,
        "unit_usd": unit_usd,
        "reputation": {"score": reputation_score},
        "description": description,
        "added_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    items.append(entry)
    _save_listings(items)
    return entry


def remove_listing(handle: str) -> bool:
    items = _load_listings()
    kept = [x for x in items if x.get("handle") != handle]
    if len(kept) == len(items):
        return False
    _save_listings(kept)
    return True


def _load() -> dict:
    if not RENTALS_FILE.is_file():
        return {"rentals": {}}
    try:
        return json.loads(RENTALS_FILE.read_text())
    except Exception:
        return {"rentals": {}}


def _save(data: dict) -> None:
    RENTALS_FILE.write_text(json.dumps(data, indent=2) + "\n")


# ----------------------------- discovery (local-only) -----------------------------


def search(
    *, role: str | None = None, max_hourly_usd: float | None = None, min_reputation: int = 0
) -> list[dict]:
    """Filter the LOCAL listings file. No network."""
    out = []
    for L in _load_listings():
        if role and L.get("role") != role:
            continue
        if max_hourly_usd is not None and float(L.get("hourly_usd", 0)) > max_hourly_usd:
            continue
        if int(L.get("reputation", {}).get("score", 0)) < min_reputation:
            continue
        out.append(L)
    return out


# ----------------------------- rental lifecycle -----------------------------


def hire(handle: str, *, session_minutes: int, max_usd: float, listing: dict | None = None) -> dict:
    """Open a rental record locally. Real payment kicks in on each ask."""
    rid = uuid.uuid4().hex[:8]
    rental = {
        "id": rid,
        "handle": handle,
        "listing": listing or {},
        "opened_at": dt.datetime.now().isoformat(timespec="seconds"),
        "expires_at": (dt.datetime.now() + dt.timedelta(minutes=session_minutes)).isoformat(
            timespec="seconds"
        ),
        "max_usd": max_usd,
        "spent_usd": 0.0,
        "asks": 0,
        "released": False,
    }
    data = _load()
    data["rentals"][rid] = rental
    _save(data)
    return rental


def get(rental_id: str) -> dict | None:
    return _load().get("rentals", {}).get(rental_id)


def release(rental_id: str) -> bool:
    data = _load()
    if rental_id not in data["rentals"]:
        return False
    data["rentals"][rental_id]["released"] = True
    data["rentals"][rental_id]["released_at"] = dt.datetime.now().isoformat(timespec="seconds")
    _save(data)
    return True


def is_active(rental: dict) -> bool:
    if rental.get("released"):
        return False
    if dt.datetime.fromisoformat(rental["expires_at"]) < dt.datetime.now():
        return False
    return not rental["spent_usd"] >= rental["max_usd"]


# ----------------------------- ask / charge -----------------------------


def ask(rental_id: str, prompt: str) -> dict:
    """Send a task to the rented agent. Charges per-call (or per-minute as
    declared in the listing). MVP: charges 'unit_usd' per ask."""
    data = _load()
    rental = data["rentals"].get(rental_id)
    if rental is None:
        return {"ok": False, "error": "rental not found"}
    if not is_active(rental):
        return {"ok": False, "error": "rental not active (released, expired, or over budget)"}

    base_url = rental.get("listing", {}).get("base_url")
    if not base_url:
        return {"ok": False, "error": "rental has no base_url"}

    # Attempt A2A delegation
    try:
        from . import a2a as a2a_module  # type: ignore
    except Exception:
        from . import a2a as a2a_module
    result = a2a_module.call_remote(
        base_url,
        prompt=prompt,
        max_amount_usd=float(rental["max_usd"]) - float(rental["spent_usd"]),
    )

    # Bill the rental
    unit = float(rental.get("listing", {}).get("unit_usd", 0.10))  # default 10c per ask
    rental["spent_usd"] = float(rental["spent_usd"]) + unit
    rental["asks"] = rental.get("asks", 0) + 1
    _save(data)

    return {
        "ok": True,
        "result": result,
        "billed_usd": unit,
        "remaining_usd": rental["max_usd"] - rental["spent_usd"],
    }


# ----------------------------- agent-callable MCP tools -----------------------------


@tool(
    "marketplace_add_listing",
    "Add a specialist agent to your local marketplace directory. No central server — this is your personal saved-specialists list.",
    {
        "handle": Annotated[str, "Specialist's public handle"],
        "role": Annotated[str, "What they specialize in"],
        "base_url": Annotated[str, "Their A2A base URL"],
        "hourly_usd": Annotated[float | None, "Hourly rate (informational)"],
        "unit_usd": Annotated[float | None, "Per-ask price (default 0.10)"],
        "description": Annotated[str | None, "Free-form description"],
    },
)
async def _add_listing(args: dict) -> dict:
    entry = add_listing(
        handle=args["handle"],
        role=args["role"],
        base_url=args["base_url"],
        hourly_usd=float(args.get("hourly_usd") or 0),
        unit_usd=float(args.get("unit_usd") or 0.10),
        description=args.get("description") or "",
    )
    return {"content": [{"type": "text", "text": json.dumps(entry, indent=2)}]}


@tool(
    "marketplace_remove_listing",
    "Remove a specialist from your local marketplace directory.",
    {"handle": Annotated[str, "Handle to remove"]},
)
async def _remove_listing(args: dict) -> dict:
    ok = remove_listing(args["handle"])
    return {
        "content": [{"type": "text", "text": "removed" if ok else "not found"}],
        "is_error": not ok,
    }


@tool(
    "marketplace_search",
    "Search your LOCAL marketplace directory for specialists. No network call.",
    {
        "role": Annotated[
            str | None, "Filter by role ('legal', 'medical', 'tax', 'research', etc.)"
        ],
        "max_hourly_usd": Annotated[float | None, "Max hourly rate"],
        "min_reputation": Annotated[int | None, "Min reputation score 0-100"],
    },
)
async def _search(args: dict) -> dict:
    listings = search(
        role=args.get("role"),
        max_hourly_usd=float(args["max_hourly_usd"])
        if args.get("max_hourly_usd") is not None
        else None,
        min_reputation=int(args.get("min_reputation") or 0),
    )
    if not listings:
        return {"content": [{"type": "text", "text": "(no listings)"}]}
    lines = [
        f"@{L['handle']} — {L.get('role', '?')} — ${L.get('hourly_usd', '?')}/h — rep {L.get('reputation', {}).get('score', '?')}"
        for L in listings
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "marketplace_hire",
    "Open a rental session with a specialist agent. Reserves a budget cap; charges accumulate per ask.",
    {
        "handle": Annotated[str, "Specialist agent handle"],
        "base_url": Annotated[str, "Their A2A base URL"],
        "session_minutes": Annotated[int, "Session duration cap (minutes)"],
        "max_usd": Annotated[float, "Hard spending cap"],
        "unit_usd": Annotated[float | None, "Per-ask price (defaults to listing or $0.10)"],
    },
)
async def _hire(args: dict) -> dict:
    listing = {"base_url": args["base_url"], "unit_usd": float(args.get("unit_usd") or 0.10)}
    rental = hire(
        args["handle"],
        session_minutes=int(args["session_minutes"]),
        max_usd=float(args["max_usd"]),
        listing=listing,
    )
    return {"content": [{"type": "text", "text": json.dumps(rental, indent=2)}]}


@tool(
    "marketplace_ask",
    "Send a task to a rented specialist. Result returned inline; bill debited from rental cap.",
    {
        "rental_id": Annotated[str, "Rental id"],
        "prompt": Annotated[str, "Task to delegate"],
    },
)
async def _ask(args: dict) -> dict:
    result = ask(args["rental_id"], args["prompt"])
    return {
        "content": [{"type": "text", "text": json.dumps(result, indent=2)[:3000]}],
        "is_error": not result.get("ok"),
    }


@tool(
    "marketplace_release",
    "End a rental early.",
    {"rental_id": Annotated[str, "Rental id"]},
)
async def _release(args: dict) -> dict:
    ok = release(args["rental_id"])
    return {
        "content": [{"type": "text", "text": "released" if ok else "not found"}],
        "is_error": not ok,
    }


@tool(
    "marketplace_rentals",
    "List active rentals.",
    {},
)
async def _list(args: dict) -> dict:
    data = _load()
    actives = [r for r in data.get("rentals", {}).values() if is_active(r)]
    if not actives:
        return {"content": [{"type": "text", "text": "(no active rentals)"}]}
    lines = [
        f"{r['id']} @{r['handle']} — ${r['spent_usd']:.2f}/${r['max_usd']:.2f} — {r['asks']} asks — until {r['expires_at']}"
        for r in actives
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


MARKETPLACE_SERVER = create_sdk_mcp_server(
    name="marketplace",
    version="1.0.0",
    tools=[_add_listing, _remove_listing, _search, _hire, _ask, _release, _list],
)
