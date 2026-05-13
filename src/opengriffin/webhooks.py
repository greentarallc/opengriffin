"""HMAC-validated webhooks gateway.

Listens on WEBHOOK_PORT (default 8645). For each route configured in
webhooks.json, validates an X-Hub-Signature-256 (or X-Signature-256) HMAC
against the per-route secret, then either:
  - delivery mode: sends the rendered template to a Telegram chat (no LLM)
  - agent mode: feeds the rendered prompt to Claude as a one-shot, delivers result

Config format (webhooks.json):
{
  "routes": [
    {
      "path": "github",
      "secret_env": "GITHUB_WEBHOOK_SECRET",
      "deliver_to": "YOUR_TELEGRAM_CHAT_ID",
      "mode": "deliver",
      "template": "GitHub: {{ headers['X-GitHub-Event'] }} on {{ body['repository']['full_name'] }}"
    }
  ]
}
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from aiohttp import web

from .botctx import CTX

log = logging.getLogger("opengriffin.webhooks")

CONFIG_FILE = Path(__file__).resolve().parent / "webhooks.json"
DEFAULT_PORT = int(os.environ.get("WEBHOOK_PORT", "8645"))


def _load() -> dict:
    if not CONFIG_FILE.exists():
        return {"routes": []}
    return json.loads(CONFIG_FILE.read_text())


def _verify(secret: str, body: bytes, signature_header: str) -> bool:
    if not signature_header:
        return False
    sig = signature_header.replace("sha256=", "").strip()
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, mac)


_TEMPLATE_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")


def _render(template: str, ctx: dict[str, Any]) -> str:
    """Tiny dot-notation template renderer. Supports {{ headers['X'] }} and {{ body.repo.full_name }}."""

    def lookup(expr: str) -> str:
        try:
            # Allow Python-style indexing in a sandboxed eval.
            return str(eval(expr, {"__builtins__": {}}, ctx))
        except Exception:
            return f"<missing:{expr}>"

    return _TEMPLATE_RE.sub(lambda m: lookup(m.group(1)), template)


async def _handle(request: web.Request) -> web.Response:
    cfg = _load()
    path = request.match_info.get("path", "")
    route = next((r for r in cfg["routes"] if r["path"] == path), None)
    if route is None:
        return web.json_response({"error": "no such route"}, status=404)

    body = await request.read()

    secret_env = route.get("secret_env")
    if secret_env:
        secret = os.environ.get(secret_env)
        if not secret:
            return web.json_response({"error": f"server missing {secret_env}"}, status=500)
        sig = (
            request.headers.get("X-Hub-Signature-256")
            or request.headers.get("X-Signature-256")
            or request.headers.get("X-Signature")
            or ""
        )
        if not _verify(secret, body, sig):
            return web.json_response({"error": "bad signature"}, status=403)

    try:
        body_json = json.loads(body) if body else {}
    except Exception:
        body_json = {"_raw": body.decode("utf-8", errors="replace")}

    ctx = {
        "headers": dict(request.headers),
        "body": body_json,
        "query": dict(request.query),
    }

    rendered = _render(route.get("template", "(no template)"), ctx)
    deliver_to = route["deliver_to"]
    if deliver_to == "home":
        deliver_to = CTX.home_chat_id or ""

    mode = route.get("mode", "deliver")
    if mode == "deliver":
        if CTX.bot:
            try:
                await CTX.bot.send_message(chat_id=deliver_to, text=rendered)
            except Exception as e:
                log.exception("webhook deliver failed")
                return web.json_response({"error": str(e)}, status=500)
    elif mode == "agent":
        # Schedule an agent run; respond fast so the sender doesn't time out.
        import asyncio

        from . import cron as cron_module

        async def _run():
            job = cron_module.Job(
                id=f"webhook-{path}",
                name=f"webhook:{path}",
                schedule="manual",
                deliver_to=str(deliver_to),
                prompt=rendered,
                enabled=True,
            )
            await cron_module.run_job(job, CTX.bot)

        asyncio.create_task(_run())
    else:
        return web.json_response({"error": f"unknown mode: {mode}"}, status=400)

    return web.json_response({"ok": True, "rendered_chars": len(rendered)})


async def start_server(port: int = DEFAULT_PORT) -> web.AppRunner:
    app = web.Application()
    app.router.add_post("/hooks/{path}", _handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port, reuse_address=True, reuse_port=True)
    await site.start()
    log.info("webhooks listening on http://127.0.0.1:%d/hooks/<route>", port)
    return runner
